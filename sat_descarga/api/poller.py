"""
Poller en background de solicitudes WS — multi-empresa.

Un hilo daemon que cada `POLL_INTERVAL_S` recorre TODAS las empresas del
catálogo (no solo la activa):

1. Marca como "vencida" toda solicitud pendiente con más de 72 h (el SLA del
   SAT) para que nada quede "abierto" para siempre.
2. Verifica contra el SAT las solicitudes que siguen pendientes usando la
   e.firma DE CADA EMPRESA — construye su propia FIEL desde el catálogo, sin
   tocar la sesión interactiva del agente (`state._session`).
3. Cuando una solicitud queda lista (3), descarga sus paquetes a la carpeta
   convencional, la registra en el historial y la marca "descargada". También
   retoma solicitudes que quedaron en "3" sin descargarse (p. ej. la app se
   cerró antes de bajar los ZIPs).

Con esto el usuario puede lanzar solicitudes en varias empresas, cambiar de
empresa o de pantalla, y todo se resuelve solo en background; la UI solo lee
el catálogo (y el watcher del renderer notifica éxitos/fallas por empresa).

Notas de diseño:
- El keychain solo se toca cuando una empresa tiene trabajo pendiente (cargar
  su e.firma requiere la contraseña de `keyring`); una pasada sin pendientes
  no toca keyring. Ver memoria sobre keyring en builds sin firma.
- La FIEL de cada empresa se cachea por (cer_path, key_path) para no golpear
  el keychain en cada pasada; si falla la carga se recuerda el fallo y no se
  reintenta hasta que cambien los paths (re-alta de la e.firma).
- Dedup de descargas contra el endpoint /descargar vía
  `state._iniciar_descarga_ws` (candado en memoria del proceso).
- Kill switch: variable de entorno SAT_DM_SIN_POLLER=1 (útil en tests/debug).
- Sesión única (F1.1, `api/sesion_unica.py`): si otra instalación reclamó la
  cuenta (escritorio, modo exigir), se PAUSA lo que arranca trabajo nuevo: los
  reenvíos de contabilidad electrónica (abren el portal con la e.firma) y la
  sincronización periódica. Se reanuda solo en la primera pasada después de
  "Continuar aquí". Lo que NO se pausa: terminar las solicitudes del Web
  Service que ya se hicieron (verificar y bajar sus paquetes). El SAT las
  resuelve en un máximo de 72 h y limita las solicitudes idénticas por rango
  (5002 «agotadas de por vida»); pausarlas puede perderlas sin remedio, y
  terminarlas no da uso de la app a nadie: solo deja en esta computadora los
  XML que se pidieron cuando tenía la sesión. Las solicitudes viven en el
  catálogo local, así que la otra instalación no puede terminarlas.
"""

import logging
import os
from datetime import datetime
import threading
from typing import Optional

import requests

from ..core.errores import ErrorEsperado
from ..core.fiel import FIEL
from ..webservice.auth import obtener_token
from ..webservice.descarga import descargar_todos
from ..webservice.verificacion import consultar_solicitud, ESTADO_TERMINADA
from .state import (
    _iniciar_descarga_ws,
    _registrar_descarga,
    _salida_descarga_ws,
    _terminar_descarga_ws,
)
from .uso import rango, tipo_de_solicitud, track

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 60          # entre pasadas completas
ARRANQUE_DELAY_S = 20         # deja arrancar el agente antes de la 1.ª pasada

_stop = threading.Event()
_thread: Optional[threading.Thread] = None

# rfc → (cer_path, key_path, FIEL | None). None = la carga falló; no se
# reintenta hasta que los paths cambien (evita martillar el keychain).
_fiel_cache: dict = {}


def iniciar_poller() -> None:
    """Arranca el hilo del poller (idempotente). No bloquea el startup."""
    global _thread
    if os.environ.get("SAT_DM_SIN_POLLER") == "1":
        logger.info("[poller] Deshabilitado por SAT_DM_SIN_POLLER=1")
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ws-poller", daemon=True)
    _thread.start()
    logger.info("[poller] Poller de solicitudes WS iniciado (cada %ds)", POLL_INTERVAL_S)


def detener_poller() -> None:
    _stop.set()


def _loop() -> None:
    if _stop.wait(ARRANQUE_DELAY_S):
        return
    pasadas = 0
    sync_pendiente = False
    while not _stop.is_set():
        try:
            _una_pasada()
        except Exception:  # noqa: BLE001 — el poller nunca debe morir
            logger.exception("[poller] Falló la pasada; se reintenta en la siguiente")
        # Sync del catálogo de empresas y de las tareas al arrancar y luego
        # cada ~30 min: converge cambios hechos en la otra instalación
        # (desktop ⇄ online) aunque el usuario no toque nada. Best-effort,
        # cada uno en su propio hilo. Pausado si otra instalación reclamó la
        # cuenta: queda pendiente y corre en la primera pasada al reanudar.
        if pasadas % 30 == 0:
            sync_pendiente = True
        if sync_pendiente and not _sesion_cerrada():
            sync_pendiente = False
            try:
                from .sync_empresas import sincronizar_async
                from .sync_tareas import sincronizar_async as sincronizar_tareas

                sincronizar_async("poller")
                sincronizar_tareas("poller")
            except Exception:  # noqa: BLE001
                pass
        pasadas += 1
        if _stop.wait(POLL_INTERVAL_S):
            return


def _una_pasada() -> None:
    """Recorre todas las empresas no archivadas y resuelve sus solicitudes."""
    from ..cli import config_store

    for emp in config_store.list_empresas():
        if _stop.is_set():
            return
        if emp.get("archived_at"):
            continue
        rfc = emp["rfc"]
        try:
            # Lo ya solicitado al Web Service se termina siempre (ver docstring).
            _procesar_empresa(rfc, emp)
            if not _sesion_cerrada():
                _reanudar_envios_ce(rfc, emp)
        except (requests.RequestException, ErrorEsperado) as e:
            # SAT caído/lento (timeouts, SSL, su «Error no controlado»): condición
            # transitoria esperada — la siguiente pasada reintenta. Warning para
            # que cada tormenta del SAT no genere eventos de Sentry.
            logger.warning("[poller] SAT no disponible procesando %s: %s", rfc, e)
        except Exception:  # noqa: BLE001 — una empresa con problemas no frena a las demás
            logger.exception("[poller] Error procesando %s", rfc)


def _sesion_cerrada() -> bool:
    """True si otra instalación reclamó la cuenta (sesión única, F1.1).
    Cualquier falla = False: la sesión única nunca frena al poller por error."""
    try:
        from .sesion_unica import cerrada

        return cerrada()
    except Exception:  # noqa: BLE001
        return False


def _procesar_empresa(rfc: str, emp: dict) -> None:
    from ..cli import config_store

    # 1) Vencimiento local: cierra lo que el SAT dejó colgado más de 72 h.
    for v in config_store.marcar_solicitudes_vencidas(rfc):
        logger.warning(
            "[poller] %s: solicitud %s marcada como vencida (creada %s)",
            rfc, v.get("id_solicitud"), v.get("timestamp"),
        )

    pendientes = config_store.get_solicitudes_pendientes(rfc)
    # 2) Solicitudes "Lista" que nadie descargó (p. ej. la app se cerró antes).
    listas = [s for s in config_store.list_solicitudes(rfc) if s.get("estado") == "3"]
    if not pendientes and not listas:
        return

    if "fiel" not in emp.get("metodos", []):
        # Solo la e.firma puede verificar/descargar por WS. (Una empresa
        # solo-CIEC no debería tener solicitudes WS, pero por si acaso.)
        return

    fiel = _fiel_de(rfc)
    if fiel is None:
        return

    token = obtener_token(fiel)

    for sol in pendientes:
        if _stop.is_set():
            return
        id_sol = sol["id_solicitud"]
        try:
            estado = consultar_solicitud(token, fiel.rfc, id_sol, fiel)
        except Exception as e:  # noqa: BLE001 — red/SSL del SAT: reintenta luego
            logger.warning("[poller] %s: no se pudo verificar %s: %s", rfc, id_sol, e)
            continue
        if not estado.cod_estado:
            continue
        estado_catalogo = "vencida" if estado.cod_estado == "6" else estado.cod_estado
        config_store.update_solicitud(
            rfc, id_sol, estado_catalogo,
            package_ids=estado.package_ids or None,
            mensaje=estado.mensaje,
            numero_cfdis=estado.numero_cfdis,
        )
        logger.info("[poller] %s: %s → estado %s", rfc, id_sol, estado_catalogo)
        if estado.cod_estado == ESTADO_TERMINADA:
            listas.append(config_store.get_solicitud(rfc, id_sol) or dict(sol))

    for sol in listas:
        if _stop.is_set():
            return
        _descargar_lista(rfc, fiel, sol)


def _descargar_lista(rfc: str, fiel: FIEL, sol: dict) -> None:
    """Baja los paquetes de una solicitud en estado 3 y la marca descargada."""
    from ..cli import config_store

    id_sol = sol["id_solicitud"]
    if not _iniciar_descarga_ws(id_sol):
        return  # el endpoint /descargar ya la está bajando
    try:
        token = obtener_token(fiel)  # token fresco: dura ~5 min
        package_ids = sol.get("package_ids") or []
        numero_cfdis = sol.get("numero_cfdis")
        if not package_ids:
            estado = consultar_solicitud(token, fiel.rfc, id_sol, fiel)
            package_ids = estado.package_ids
            numero_cfdis = estado.numero_cfdis
        if not package_ids:
            # Lista pero sin paquetes = sin CFDIs en el periodo.
            config_store.update_solicitud(
                rfc, id_sol, "descargada",
                mensaje="Sin CFDIs para el periodo.", numero_cfdis=numero_cfdis or 0,
            )
            track("descarga_completada", canal="web_service", credencial="efirma",
                  tipo=tipo_de_solicitud(sol), tamano="0", segundo_plano=True)
            return
        salida = _salida_descarga_ws(rfc, id_sol)
        descargar_todos(
            token=token,
            rfc_solicitante=fiel.rfc,
            package_ids=package_ids,
            directorio_salida=salida,
            fiel=fiel,
            extraer=True,
        )
        _registrar_descarga(
            rfc, "ws", "cfdi",
            descripcion=f"Descarga WS · solicitud {id_sol[:8]}… (automática)",
            ruta=salida, total=numero_cfdis,
        )
        config_store.update_solicitud(
            rfc, id_sol, "descargada", package_ids=package_ids,
        )
        track("descarga_completada", canal="web_service", credencial="efirma",
              tipo=tipo_de_solicitud(sol), tamano=rango(numero_cfdis), segundo_plano=True)
        logger.info("[poller] %s: solicitud %s descargada en %s", rfc, id_sol, salida)
    except Exception as e:  # noqa: BLE001 — reintenta en la siguiente pasada (sigue en 3)
        logger.warning("[poller] %s: descarga de %s falló: %s", rfc, id_sol, e)
    finally:
        _terminar_descarga_ws(id_sol)


def _fiel_de(rfc: str) -> Optional[FIEL]:
    """FIEL de la empresa, cacheada por paths. Devuelve None si no se puede
    cargar (e.firma incompleta, contraseña mala, cert ilegible) — se recuerda
    el fallo para no golpear el keychain en cada pasada."""
    from ..cli import config_store

    try:
        emp = config_store.get_empresa(rfc)  # incluye password del keychain
    except Exception as e:  # noqa: BLE001
        logger.warning("[poller] %s: no se pudo leer la empresa: %s", rfc, e)
        return None

    cer, key, pwd = emp.get("cer_path"), emp.get("key_path"), emp.get("password")
    if not (cer and key and pwd):
        return None

    cached = _fiel_cache.get(rfc)
    if cached is not None and cached[0] == cer and cached[1] == key:
        return cached[2]

    try:
        fiel = FIEL(cer, key, pwd)
    except Exception as e:  # noqa: BLE001
        logger.warning("[poller] %s: no se pudo cargar la e.firma: %s", rfc, e)
        fiel = None
    _fiel_cache[rfc] = (cer, key, fiel)
    return fiel


# ---------------------------------------------------------------------------
# Envíos CE pendientes (cola de reintento diferido)
# ---------------------------------------------------------------------------

# El SAT se pone lento o entra en mantenimiento sin aviso; los envíos que
# agotaron reintentos quedan en ~/.sat-descarga/envios/{RFC}.json y aquí se
# retoman solos. Enfriamiento para no martillar un portal caído.
ENVIOS_ENFRIAMIENTO_S = 30 * 60

# candado propio: la reanudación abre un Chromium; nunca dos a la vez, ni
# encimarse con un job interactivo de la UI
_envio_en_curso = threading.Lock()


def _reanudar_envios_ce(rfc: str, emp: dict) -> None:
    if os.environ.get("SAT_DM_SIN_REANUDAR_ENVIOS") == "1":
        return
    from ..cli import config_store

    pendientes = [e for e in config_store.get_envios_pendientes(rfc)
                  if e.get("tramite") == "ce"]
    if not pendientes:
        return

    # enfriamiento: reintentar solo si el último intento fue hace ≥30 min
    ahora = datetime.now()
    def _frio(e):
        ui = e.get("ultimo_intento")
        if not ui:
            return True
        try:
            return (ahora - datetime.fromisoformat(ui)).total_seconds() \
                >= ENVIOS_ENFRIAMIENTO_S
        except ValueError:
            return True
    if not any(_frio(e) for e in pendientes):
        return

    # no encimarse con un job interactivo (comparten Playwright/CPU) ni
    # correr dos reanudaciones a la vez
    from . import jobs
    if jobs.registry.hay_activo():
        logger.info("[poller] %s: envíos CE pendientes, pero hay un job "
                    "activo; se intenta en la siguiente pasada.", rfc)
        return
    if not _envio_en_curso.acquire(blocking=False):
        return
    try:
        fiel_info = emp if emp.get("cer_path") and emp.get("password") else None
        if not fiel_info:
            logger.info("[poller] %s: envíos CE pendientes pero sin e.firma "
                        "completa en el catálogo.", rfc)
            return
        logger.info("[poller] %s: reanudando %d envío(s) CE pendiente(s)...",
                    rfc, len(pendientes))
        from ..cli.config_store import get_descargas_dir
        from ..core import paths
        from ..portal.reanudar_envios import reanudar_envios_ce

        base = get_descargas_dir()
        resumen = reanudar_envios_ce(
            rfc, emp["cer_path"], emp["key_path"], emp["password"],
            headless=True,
            destino_de=lambda f: paths.dir_ce(f["rfc"], f["anio"],
                                              salida_base=base),
        )
        logger.info("[poller] %s: envíos CE — completados=%d, "
                    "aún pendientes=%d", rfc,
                    len(resumen["completados"]), len(resumen["aun_pendientes"]))
    finally:
        _envio_en_curso.release()

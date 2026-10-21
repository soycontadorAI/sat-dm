"""
Estado de sesión y helpers compartidos entre los routers del agente local.

Vive aquí todo lo que usa MÁS de un router (`api/routers/*`):
- `_session` — sesión FIEL en memoria (un usuario a la vez en el agente local).
- `_get_fiel` / `_renovar_token` / `_limpiar_session` — manejo de la e-firma en sesión.
- `_cargar_fiel_empresa` / `_autocargar_empresa_default` — carga de la e.firma desde
  el catálogo de empresas (forman una unidad con `_limpiar_session`, por eso viven
  juntas aquí aunque la autocarga solo la invoque el router de webservice).
- `_descargas_base` — carpeta base de descargas configurada.
- `_registrar_descarga` — registro best-effort en el historial.
- `SolicitudRequest` — único modelo Pydantic compartido entre routers
  (lo usan `/solicitar` en webservice y `/metadata` en utilidades); los demás
  modelos viven en el router de su dominio.

NOTA: server.py re-exporta `_session` y `_limpiar_session` para compatibilidad
con los tests (monkeypatchean/limpian vía `server._limpiar_session()`).
"""

import logging
import os
import threading
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from ..core.fiel import FIEL
from ..webservice.auth import obtener_token
from ..core.config import TIPO_CFDI, TIPO_EMITIDO

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Estado de sesión (en memoria — un usuario a la vez en el agente local)
# ---------------------------------------------------------------------------

_session: dict = {
    "fiel": None,        # Objeto FIEL cargado
    "rfc": None,         # RFC extraído del certificado
    "cer_path": None,    # Path al .cer
    "key_path": None,    # Path al .key
    "password": None,    # Contraseña de la llave (en memoria, no en disco)
    "es_temp": False,    # True si cer/key son temporales (borrar al limpiar);
                         # False si apuntan a una empresa guardada (NO borrar).
}


def _get_fiel() -> FIEL:
    if _session["fiel"] is None:
        raise HTTPException(
            status_code=401,
            detail=(
                "No hay e-firma cargada. "
                "Llama primero a POST /auth/cargar-fiel con tu .cer y .key"
            ),
        )
    return _session["fiel"]


def _renovar_token() -> str:
    """Obtiene un token fresco del SAT."""
    fiel = _get_fiel()
    token = obtener_token(fiel)
    return token


def _limpiar_session():
    """Limpia el estado de sesión. Solo borra los .cer/.key si eran temporales
    (no toca los de una empresa guardada en ./efirma/)."""
    if _session.get("es_temp"):
        for path_key in ("cer_path", "key_path"):
            path = _session.get(path_key)
            if path:
                try:
                    os.unlink(path)
                except Exception:
                    pass
    _session.update({
        "fiel": None,
        "rfc": None,
        "cer_path": None,
        "key_path": None,
        "password": None,
        "es_temp": False,
    })


def _cargar_fiel_empresa(empresa: dict) -> bool:
    """
    Carga la e.firma de una empresa del catálogo en `_session`.

    `empresa` es el dict de `config_store.get_empresa` (con cer_path/key_path/password).
    Devuelve True si cargó la e.firma; False si la empresa no tiene método FIEL.
    Lanza ValueError si la e.firma está incompleta o no se pudo abrir (cert/llave/contraseña).
    """
    if "fiel" not in empresa.get("metodos", []):
        return False
    cer, key, pwd = empresa.get("cer_path"), empresa.get("key_path"), empresa.get("password")
    if not (cer and key and pwd):
        raise ValueError("La empresa no tiene e.firma completa.")
    fiel = FIEL(cer, key, pwd)  # nota: carga aunque el cert esté vencido (la UI avisa)
    _limpiar_session()
    _session.update({
        "fiel": fiel, "rfc": fiel.rfc, "cer_path": cer,
        "key_path": key, "password": pwd, "es_temp": False,
    })
    # Si la empresa quedó con el RFC como nombre (la extracción del nombre falló
    # al darla de alta, p. ej. cert con Ñ), recupéralo ahora que la FIEL está
    # cargada y tenemos legal_name. Se corrige solo, sin borrar y re-agregar.
    try:
        nombre = fiel.legal_name
        if nombre:
            from ..cli import config_store
            config_store.actualizar_nombre_si_placeholder(fiel.rfc, nombre)
    except Exception as e:  # noqa: BLE001
        logger.debug("No se pudo actualizar el nombre de %s: %s", fiel.rfc, e)
    return True


def _autocargar_empresa_default() -> None:
    """Carga al arranque la e.firma de la empresa predeterminada (si tiene FIEL).

    Se llama desde el lifespan del agente. Tolerante a fallos: si la empresa no
    tiene e.firma, o el cert/llave no se pueden abrir, solo se registra y se sigue
    (la UI permite cargarla a mano)."""
    if _session["fiel"] is not None:
        return
    try:
        from ..cli import config_store
        rfc = config_store.get_default()
        if not rfc:
            return
        if _cargar_fiel_empresa(config_store.get_empresa(rfc)):
            logger.info("e.firma de la empresa activa (%s) cargada al arranque.", rfc)
    except Exception as e:  # noqa: BLE001
        logger.warning("No se pudo autocargar la e.firma de la empresa activa: %s", e)


# ---------------------------------------------------------------------------
# Helpers compartidos (paths de descargas + historial)
# ---------------------------------------------------------------------------


def _descargas_base() -> str:
    """Carpeta base de descargas configurada (default ~/Documents/TodoConta)."""
    from ..cli import config_store
    return config_store.get_descargas_dir()


def direcciones_de(tipo_comprobante: Optional[str]) -> list[str]:
    """Direcciones (E/R) que descarga un `tipo_comprobante` de la API. Misma
    regla que el portal (`portal/cfdi.py::_normalizar_tipos`, que no se importa
    aquí porque arrastra Playwright): E/EMITIDOS, R/RECIBIDOS y cualquier otra
    cosa ("RE", "AMBOS", vacío) son las dos."""
    t = (tipo_comprobante or "").strip().upper()
    if t in ("E", "EMITIDOS"):
        return ["E"]
    if t in ("R", "RECIBIDOS"):
        return ["R"]
    return ["E", "R"]


def _marcar_calendario(rfc, rango, direcciones) -> None:
    """Marca como provisional el rango descargado en el cuadro de control.
    El calendario vive en el índice (`procesador.db`): con el indexado automático
    apagado (`SAT_DM_SIN_INDEXADO=1`) tampoco se toca. Best-effort: nunca lanza."""
    try:
        from ..procesador import calendario
        from ..procesador.indexar import automatico_activo

        if not automatico_activo():
            return

        desde, hasta = rango
        for d in direcciones:
            calendario.marcar(rfc, desde, hasta, d, "provisional")
    except Exception:  # noqa: BLE001 - el calendario tampoco rompe la descarga
        logger.warning("No se pudo marcar el calendario", exc_info=True)


def _registrar_descarga(rfc, canal, tipo, descripcion="", ruta="", total=None,
                        rango: Optional[tuple[date, date]] = None,
                        direcciones: Optional[Iterable[str]] = None,
                        paquetes: Optional[list] = None):
    """Registra una descarga completada en el historial y, si son CFDIs, los
    indexa al procesador en segundo plano. Con `rango` y `direcciones` marca
    además esos días como provisionales en el cuadro de control (solo quien
    llama sabe si la descarga quedó completa). Con `paquetes` (los del Web Service)
    se indexan solo las carpetas de esos paquetes, en un solo trabajo: `ruta` puede
    ser una carpeta compartida con otras descargas (la del rango pedido); el
    historial sigue con `ruta`. Best-effort: nunca lanza."""
    try:
        from ..cli import config_store
        config_store.registrar_descarga(
            rfc, canal, tipo, descripcion=descripcion, ruta=ruta, total=total,
        )
    except Exception:  # noqa: BLE001 - el historial no debe romper una descarga
        logger.warning("No se pudo registrar la descarga en el historial", exc_info=True)
    if tipo == "cfdi":
        try:
            from ..procesador.indexar import indexar_descarga
            from ..webservice.descarga import carpeta_paquete

            if paquetes is None:
                indexar_descarga(rfc, ruta, canal)
            else:
                # Solo las extraídas; sin ninguna (bajó sin extraer) el trabajo no lee
                # nada y solo pone al día el cuadro de control, como cualquier indexado.
                carpetas = [str(c) for c in (carpeta_paquete(Path(ruta), pid) for pid in paquetes)
                            if c.is_dir()]
                indexar_descarga(rfc, ruta, canal, carpetas=carpetas)
        except Exception:  # noqa: BLE001 - el índice tampoco
            logger.warning("No se pudo indexar la descarga", exc_info=True)
        if rango and direcciones:
            _marcar_calendario(rfc, rango, list(direcciones))


def _salida_descarga_ws(rfc: str, id_solicitud: str) -> str:
    """Calcula la carpeta de salida para la descarga WS siguiendo la convención
    CIEC (`{base}/cfdi/{RFC}/{emitidos|recibidos}/{desde}_a_{hasta}/`), recuperando
    del catálogo lo que el usuario solicitó. Si el registro no existe o le falta
    info, cae al directorio base por RFC (compatible hacia atrás). La usan el
    endpoint /descargar y el poller en background."""
    from ..cli import config_store
    from ..core import paths
    from datetime import date as _date

    base = _descargas_base()
    try:
        sol = config_store.get_solicitud(rfc, id_solicitud) or {}
    except Exception:  # noqa: BLE001
        sol = {}
    if sol.get("uuids"):
        # Por folio: sin rango de fechas; su propia carpeta para no reindexar
        # toda la empresa al terminar.
        return str(paths.dir_folios(rfc, id_solicitud, salida_base=base))
    tipo = sol.get("tipo_comprobante")
    fi, ff = sol.get("fecha_inicio"), sol.get("fecha_fin")
    rango = sol.get("carpeta_rango")
    if isinstance(rango, (list, tuple)) and len(rango) == 2:
        # Parte de una petición que se sirvió en parte de la base
        # (/solicitar/desde-base): baja a la carpeta del rango que pidió el
        # usuario, junto con lo servido.
        fi, ff = rango
    if tipo in ("E", "R") and fi and ff:
        try:
            desde, hasta = _date.fromisoformat(fi), _date.fromisoformat(ff)
            if es_metadata(sol):
                return str(paths.dir_metadata(rfc, tipo, desde, hasta, salida_base=base))
            return str(paths.dir_cfdi(rfc, tipo, desde, hasta, salida_base=base))
        except ValueError:
            pass  # fechas malformadas → fallback
    return str(paths.dir_cfdi_base(rfc, salida_base=base))


def es_metadata(sol: Optional[dict]) -> bool:
    """¿La solicitud del catálogo es de Metadata? (`config_store.es_metadata`)."""
    from ..cli import config_store

    return config_store.es_metadata(sol)


# ---------------------------------------------------------------------------
# Descargas WS en curso — dedup entre el endpoint /descargar y el poller en
# background: ambos pueden ver la misma solicitud "Lista" al mismo tiempo y
# sin este candado bajarían los mismos ZIPs dos veces.
# ---------------------------------------------------------------------------

_descargas_ws_en_curso: set = set()
_descargas_ws_lock = threading.Lock()


def _iniciar_descarga_ws(id_solicitud: str) -> bool:
    """Reserva la descarga de una solicitud. False si ya está en curso."""
    with _descargas_ws_lock:
        if id_solicitud in _descargas_ws_en_curso:
            return False
        _descargas_ws_en_curso.add(id_solicitud)
        return True


def _terminar_descarga_ws(id_solicitud: str) -> None:
    with _descargas_ws_lock:
        _descargas_ws_en_curso.discard(id_solicitud)


# ---------------------------------------------------------------------------
# Modelos compartidos entre routers
# ---------------------------------------------------------------------------


class SolicitudRequest(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    tipo_solicitud: str = TIPO_CFDI       # "CFDI" o "Metadata"
    tipo_comprobante: str = TIPO_EMITIDO  # "E" o "R"
    rfc_emisor: Optional[str] = None
    rfc_receptor: Optional[str] = None

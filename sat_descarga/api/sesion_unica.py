"""
Una sesión activa a la vez (F1.1 del plan de la app v3, en todoconta-apps
`docs/operacion/plan-app-v3.md`).

Regla: GANA LA SESIÓN MÁS RECIENTE. Una cuenta (persona) tiene TodoConta abierta
en una sola instalación a la vez (esta computadora con la app de escritorio, o
un navegador con la web; cuentan igual). Al abrir la app o iniciar sesión, la
instalación reclama la cuenta y las demás se cierran. No hay vencimiento por
inactividad: la sesión sigue mientras el token sea válido, salvo que otra
instalación la reclame en medio. La MCP, la API y Abacus no pasan por aquí.

Quién hace qué:
- La UI reclama al abrir (montar con sesión), al iniciar sesión y con
  "Continuar aquí" (`POST /auth/sesion/reclamar`), y late al volver a la
  ventana (`POST /auth/sesion/latido`).
- En ESCRITORIO este módulo es la instalación: id estable en el directorio de
  datos del agente (`~/.sat-descarga/instalacion.json`), etiqueta "macOS ·
  nombre-del-equipo", y un hilo que late cada 60 s mientras el agente corre.
  Guarda el estado (`cerrada`) para la UI y para pausar el trabajo en segundo
  plano (`poller.py`). También lo actualiza la licencia (header
  `X-TodoConta-Instalacion` → campo `sesion`).
- En la WEB (modo hosted) la instalación es cada navegador (id en su
  localStorage): el contenedor es compartido por todos los navegadores de la
  cuenta, así que aquí solo se reenvía al servicio con el Bearer y NO se guarda
  estado ni se pausa nada.

Nunca cierra sin respuesta del servicio: sin internet, con el servicio viejo
(404) o con un error, la app sigue abierta (mismo criterio que la licencia).

Números (el servidor manda `heartbeat_segundos` y se respeta, con tope):
`LATIDO_S` = 60, `ARRANQUE_DELAY_S` = 30, `LATIDO_MIN_S` = 15, `LATIDO_MAX_S` = 600.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import socket
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..core.config import es_modo_hosted

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

LATIDO_S = 60            # default si el servidor no dice otra cosa
LATIDO_MIN_S = 15        # tope inferior al valor del servidor
LATIDO_MAX_S = 600       # tope superior
ARRANQUE_DELAY_S = 30    # el hilo espera a que la UI reclame primero al abrir

RUTA_RECLAMAR = "/api/desktop/sesion/reclamar"
RUTA_LATIDO = "/api/desktop/sesion/latido"
HEADER_INSTALACION = "X-TodoConta-Instalacion"

ARCHIVO_INSTALACION = "instalacion.json"
_INSTALACION_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# ---------------------------------------------------------------------------
# Estado (solo escritorio)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_estado: dict[str, Any] = {
    "cerrada": False,       # otra instalación reclamó la cuenta (modo exigir)
    "modo": None,           # 'apagado' | 'observar' | 'exigir' | None (sin datos)
    "otra": None,           # {etiqueta, tipo, desde}
    "sin_conexion": False,  # la última llamada no llegó al servicio
    "verificada_en": None,  # epoch de la última respuesta válida del servicio
    "heartbeat_segundos": LATIDO_S,
}
_ultima_interaccion: Optional[float] = None
_instalacion_cache: Optional[str] = None

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


def es_valida(instalacion_id: Any) -> bool:
    return isinstance(instalacion_id, str) and bool(_INSTALACION_RE.match(instalacion_id))


# ---------------------------------------------------------------------------
# Identidad de esta instalación (escritorio)
# ---------------------------------------------------------------------------


def _ruta_instalacion() -> Path:
    from ..cli import config_store

    return config_store.CONFIG_DIR / ARCHIVO_INSTALACION


def instalacion_id() -> str:
    """Id estable de esta instalación: se genera una vez y vive en el directorio
    de datos del agente. Si el archivo falta o está dañado se genera otro (la
    cuenta verá una "computadora nueva", nada más)."""
    global _instalacion_cache
    with _lock:
        if _instalacion_cache:
            return _instalacion_cache
        ruta = _ruta_instalacion()
        try:
            data = json.loads(ruta.read_text(encoding="utf-8"))
            if es_valida(data.get("id")):
                _instalacion_cache = data["id"]
                return _instalacion_cache
        except (OSError, ValueError, AttributeError):
            pass
        nuevo = str(uuid.uuid4())
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = ruta.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(
                    {"id": nuevo, "creada_en": datetime.now(timezone.utc).isoformat()},
                    indent=2,
                ),
                encoding="utf-8",
            )
            tmp.replace(ruta)
        except OSError as e:  # disco de solo lectura: vale para esta corrida
            logger.warning("[sesion] no se pudo guardar el id de instalación: %s", e)
        _instalacion_cache = nuevo
        return nuevo


_SO = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}


def etiqueta_local() -> str:
    """"macOS · MacBook-de-Ana": sistema + nombre del equipo (sin dominio)."""
    so = _SO.get(platform.system(), platform.system() or "Computadora")
    try:
        equipo = socket.gethostname().split(".")[0].strip()
    except OSError:
        equipo = ""
    return f"{so} · {equipo}"[:120] if equipo else so


def _version_app() -> Optional[str]:
    # El shell Electron pasa la versión de la app como SENTRY_RELEASE.
    v = os.environ.get("SENTRY_RELEASE", "").strip()
    if v:
        return v[:40]
    try:
        from importlib.metadata import version

        return version("sat-descarga-masiva")[:40]
    except Exception:  # noqa: BLE001
        return None


def header_instalacion() -> dict[str, str]:
    """Header para GET /api/desktop/license (solo escritorio)."""
    if es_modo_hosted():
        return {}
    return {HEADER_INSTALACION: instalacion_id()}


# ---------------------------------------------------------------------------
# Interacción del usuario (para medir uso simultáneo en modo observar)
# ---------------------------------------------------------------------------


def registrar_interaccion(hace_s: Optional[float]) -> None:
    """La UI reporta cuántos segundos lleva sin tocarse (teclado o ratón)."""
    global _ultima_interaccion
    if hace_s is None or hace_s < 0:
        return
    momento = time.time() - float(hace_s)
    with _lock:
        if _ultima_interaccion is None or momento > _ultima_interaccion:
            _ultima_interaccion = momento


def _interaccion_hace_s() -> Optional[int]:
    with _lock:
        if _ultima_interaccion is None:
            return None
        return max(0, int(time.time() - _ultima_interaccion))


# ---------------------------------------------------------------------------
# Llamadas al servicio
# ---------------------------------------------------------------------------


def _llamar(ruta: str, body: dict) -> dict:
    """POST al servicio con el Bearer de la sesión (refresca si venció).
    Devuelve la respuesta si es válida, o un marcador:
    `_sin_conexion` (red caída), `_sin_sesion` (401) o `_sin_servicio`
    (servicio sin el endpoint, 5xx, cuerpo raro). Nunca lanza."""
    from . import license_client as lc

    try:
        status, data = lc.proxy_desktop("POST", ruta, json_body=body)
    except lc.ServicioNoDisponible:
        return {"_sin_conexion": True}
    except Exception as e:  # noqa: BLE001 — la sesión única nunca rompe al agente
        logger.warning("[sesion] %s falló: %s", ruta, e)
        return {"_sin_servicio": True}
    if status == 200 and isinstance(data, dict) and isinstance(data.get("activa"), bool):
        return data
    if status == 401:
        return {"_sin_sesion": True}
    if status not in (404,):
        logger.info("[sesion] %s respondió %s", ruta, status)
    return {"_sin_servicio": True}


def _otra(valor: Any) -> Optional[dict]:
    if not isinstance(valor, dict):
        return None
    return {
        "etiqueta": valor.get("etiqueta") if isinstance(valor.get("etiqueta"), str) else None,
        "tipo": "web" if valor.get("tipo") == "web" else "desktop",
        "desde": valor.get("desde") if isinstance(valor.get("desde"), str) else None,
    }


def _intervalo_de(resp: dict) -> int:
    hb = resp.get("heartbeat_segundos")
    if isinstance(hb, bool) or not isinstance(hb, (int, float)):
        return LATIDO_S
    return int(min(max(hb, LATIDO_MIN_S), LATIDO_MAX_S))


def _estado_de(resp: dict, previo: dict) -> dict:
    """Estado nuevo a partir de la respuesta. Sin respuesta del servicio nunca
    se cierra: se conserva lo previo y `cerrada` solo puede quedar como estaba
    (un dispositivo que ya sabía que lo cerraron sigue cerrado hasta que el
    usuario elija)."""
    nuevo = dict(previo)
    if resp.get("_sin_conexion") or resp.get("_sin_servicio"):
        nuevo["sin_conexion"] = bool(resp.get("_sin_conexion"))
        return nuevo
    if resp.get("_sin_sesion"):
        nuevo.update(cerrada=False, otra=None, sin_conexion=False)
        return nuevo
    nuevo.update(
        cerrada=resp["activa"] is False,
        modo=resp.get("modo") if isinstance(resp.get("modo"), str) else None,
        otra=_otra(resp.get("otra")),
        sin_conexion=False,
        verificada_en=time.time(),
        heartbeat_segundos=_intervalo_de(resp),
    )
    return nuevo


def _para_ui(estado: dict, instalacion: str, etiqueta: Optional[str]) -> dict:
    return {
        "cerrada": bool(estado.get("cerrada")),
        "modo": estado.get("modo"),
        "otra": estado.get("otra"),
        "sin_conexion": bool(estado.get("sin_conexion")),
        "instalacion_id": instalacion,
        "etiqueta": etiqueta,
        "heartbeat_segundos": estado.get("heartbeat_segundos") or LATIDO_S,
    }


def _operar(
    ruta: str,
    instalacion: Optional[str],
    etiqueta: Optional[str],
    interaccion_hace_s: Optional[float],
) -> dict:
    if es_modo_hosted():
        # Web: la instalación es el navegador; no hay estado global.
        if not es_valida(instalacion):
            raise ValueError("Falta el id de instalación del navegador.")
        body = {
            "instalacion_id": instalacion,
            "tipo": "web",
            "etiqueta": etiqueta,
            "interaccion_hace_s": interaccion_hace_s,
        }
        estado = _estado_de(_llamar(ruta, body), {"cerrada": False, "heartbeat_segundos": LATIDO_S})
        return _para_ui(estado, instalacion, etiqueta)

    # Escritorio: la instalación es este agente (se ignora lo que mande la UI).
    registrar_interaccion(interaccion_hace_s)
    propia, etiqueta_propia = instalacion_id(), etiqueta_local()
    body = {
        "instalacion_id": propia,
        "tipo": "desktop",
        "etiqueta": etiqueta_propia,
        "version": _version_app(),
        "interaccion_hace_s": _interaccion_hace_s(),
    }
    resp = _llamar(ruta, body)
    global _estado
    with _lock:
        _estado = _estado_de(resp, _estado)
        if ruta == RUTA_RECLAMAR and not isinstance(resp.get("activa"), bool):
            # "Continuar aquí" sin respuesta del servicio (sin internet, error):
            # nunca se queda cerrada sin una respuesta que lo pida.
            _estado["cerrada"] = False
        actual = dict(_estado)
    return _para_ui(actual, propia, etiqueta_propia)


def reclamar(
    instalacion: Optional[str] = None,
    etiqueta: Optional[str] = None,
    interaccion_hace_s: Optional[float] = 0,
) -> dict:
    """Reclama la cuenta para esta instalación (abrir la app, iniciar sesión,
    "Continuar aquí"). Las demás se cierran en su siguiente latido."""
    return _operar(RUTA_RECLAMAR, instalacion, etiqueta, interaccion_hace_s)


def latido(
    instalacion: Optional[str] = None,
    etiqueta: Optional[str] = None,
    interaccion_hace_s: Optional[float] = None,
) -> dict:
    """Pregunta si otra instalación reclamó la cuenta."""
    return _operar(RUTA_LATIDO, instalacion, etiqueta, interaccion_hace_s)


def estado(interaccion_hace_s: Optional[float] = None) -> dict:
    """Estado local (sin red). En la web no aplica: la UI lo sabe por su latido."""
    if es_modo_hosted():
        return _para_ui({"cerrada": False, "heartbeat_segundos": LATIDO_S}, "", None)
    registrar_interaccion(interaccion_hace_s)
    with _lock:
        actual = dict(_estado)
    return _para_ui(actual, instalacion_id(), etiqueta_local())


def cerrada() -> bool:
    """True si otra instalación reclamó la cuenta y el servicio pidió cerrar
    esta (modo exigir). Siempre False en la web y sin datos del servicio."""
    if es_modo_hosted():
        return False
    with _lock:
        return bool(_estado.get("cerrada"))


def desde_licencia(payload: Any) -> None:
    """Aplica el campo `sesion` de GET /api/desktop/license (solo escritorio)."""
    if es_modo_hosted() or not isinstance(payload, dict):
        return
    sesion = payload.get("sesion")
    if not isinstance(sesion, dict) or not isinstance(sesion.get("activa"), bool):
        return
    if sesion.get("instalacion_id") not in (None, instalacion_id()):
        return
    global _estado
    with _lock:
        _estado = _estado_de(sesion, _estado)


def reiniciar() -> None:
    """Olvida el estado (cerrar o iniciar sesión): sin cuenta no hay cierre."""
    global _estado
    with _lock:
        _estado = {
            "cerrada": False,
            "modo": None,
            "otra": None,
            "sin_conexion": False,
            "verificada_en": None,
            "heartbeat_segundos": LATIDO_S,
        }


# ---------------------------------------------------------------------------
# Hilo de latidos (escritorio)
# ---------------------------------------------------------------------------


def iniciar_latidos() -> None:
    """Arranca el hilo (idempotente). No corre en la web ni con
    SAT_DM_SIN_SESION_UNICA=1 (tests/debug)."""
    global _thread
    if es_modo_hosted() or os.environ.get("SAT_DM_SIN_SESION_UNICA") == "1":
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="sesion-latidos", daemon=True)
    _thread.start()


def detener_latidos() -> None:
    _stop.set()


def _intervalo() -> int:
    with _lock:
        return int(_estado.get("heartbeat_segundos") or LATIDO_S)


def _loop() -> None:
    if _stop.wait(ARRANQUE_DELAY_S):
        return
    while not _stop.is_set():
        try:
            _un_latido()
        except Exception:  # noqa: BLE001 — el hilo nunca muere
            logger.exception("[sesion] falló el latido")
        if _stop.wait(_intervalo()):
            return


def _un_latido() -> None:
    """Un latido del hilo. Una instalación cerrada ya no late: espera a que el
    usuario elija "Continuar aquí" (reclamar) o "Cerrar sesión"."""
    if cerrada():
        return
    # Sin sesión guardada, proxy_desktop responde 401 sin tocar la red.
    latido()

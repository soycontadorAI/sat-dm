"""
Telemetría de errores del agente (Sentry) — opcional y apagada por defecto.

Solo se enciende si hay `SENTRY_DSN` en el entorno: el cascarón Electron lo inyecta
al spawnear el agente en builds empaquetados, y la imagen Docker del agente web
(docker/agente/Dockerfile) lo trae horneado. Sin DSN —o sin `sentry-sdk`
instalado— TODO es no-op: ni en dev ni en CLI se envía nada.

Desktop y web reportan al MISMO proyecto; se distinguen por `environment`
(`production` = desktop, `hosted` = versión web), así un mismo fallo del SAT queda
en un solo issue con ambos entornos.

Privacidad (esta app maneja datos fiscales: RFC, e.firma, CFDIs):
  - `send_default_pii=False`.
  - `max_request_body_size="never"`: los cuerpos de request NUNCA se envían (los
    POST /empresas/* traen la contraseña de la e.firma y la CIEC en el form).
  - `before_send` redacta RFCs y rutas con nombre de usuario, y elimina claves
    sensibles (password/contraseña/ciec/secreto/token) que pudieran colarse en
    `extra`/`contexts`/breadcrumbs.
  - Nunca se envían .cer/.key ni contraseñas (viven en el keychain del SO).
"""

import logging
import os
import re

logger = logging.getLogger(__name__)

# RFC de persona física (13) o moral (12). Se redacta en cualquier string.
_RFC_RE = re.compile(r"\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{2,3}\b")

# Prefijos de home con nombre de usuario (PII) → se anonimizan conservando la forma.
_HOME_RES = (
    (re.compile(r"([A-Za-z]:\\Users\\)[^\\/]+", re.IGNORECASE), r"\1<usuario>"),
    (re.compile(r"(/Users/)[^/]+"), r"\1<usuario>"),
    (re.compile(r"(/home/)[^/]+"), r"\1<usuario>"),
)

# Claves de diccionario cuyo VALOR se elimina por completo si aparecen en el evento.
_CLAVE_SENSIBLE_RE = re.compile(
    r"(password|contrase|ciec|secreto|secret|token|api[_-]?key)", re.IGNORECASE
)

_inicializado = False


def _environment() -> str:
    """`SENTRY_ENVIRONMENT` si viene; si no, `hosted` en la versión web y
    `production` en la desktop (Electron siempre lo manda explícito)."""
    from .config import es_modo_hosted

    return os.getenv("SENTRY_ENVIRONMENT") or ("hosted" if es_modo_hosted() else "production")


def _release():
    """`SENTRY_RELEASE` si viene (Electron manda la versión de la app); si no, la
    versión del paquete instalado (la imagen del agente web se construye con
    `pip install .`, así que coincide con la versión del release)."""
    rel = os.getenv("SENTRY_RELEASE")
    if rel:
        return rel
    try:
        from importlib.metadata import version

        return version("sat-descarga-masiva")
    except Exception:  # noqa: BLE001 — sin metadata (p. ej. código suelto) → sin release
        return None


def init_sentry() -> bool:
    """Inicializa Sentry si hay `SENTRY_DSN`. Devuelve True si quedó activo.

    Idempotente y silencioso: sin DSN o sin sentry-sdk instalado, no hace nada.
    """
    global _inicializado
    if _inicializado:
        return True

    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "SENTRY_DSN presente pero sentry-sdk no está instalado; telemetría apagada."
        )
        return False

    # Un HTTPException(503) NO crea evento: por convención del agente, 503 =
    # "servicio externo no disponible, reintenta" (el SAT caído/lento en los
    # endpoints WS, playwright instalándose en los del portal). Es condición
    # esperada y transitoria, no un bug — reportarla inundaba Sentry en cada
    # tormenta del SAT (TODOCONTA-DESKTOP-13). Los demás 5xx siguen
    # reportándose, y las excepciones no manejadas se reportan SIEMPRE
    # (failed_request_status_codes solo filtra HTTPException).
    integrations = []
    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        codigos_falla = {*range(500, 600)} - {503}
        integrations = [
            StarletteIntegration(failed_request_status_codes=codigos_falla),
            FastApiIntegration(failed_request_status_codes=codigos_falla),
        ]
    except Exception:  # noqa: BLE001 — sin starlette (CLI pura) usa los defaults
        pass

    environment = _environment()
    sentry_sdk.init(
        dsn=dsn,
        release=_release(),
        environment=environment,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_before_send,
        integrations=integrations,
    )
    _inicializado = True
    logger.info("Telemetría Sentry activada (environment=%s).", environment)
    return True


def capturar_excepcion(exc: BaseException) -> None:
    """Reporta una excepción a Sentry si está activo; no-op si no.

    Útil para fallos que se degradan a un HTTP 4xx (p. ej. el alta de empresa que
    revienta y se devuelve como 400): la integración de FastAPI solo captura
    excepciones NO atrapadas, así que estos hay que reportarlos a mano."""
    if not _inicializado:
        return
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 — la telemetría jamás debe romper el flujo
        logger.debug("No se pudo capturar la excepción en Sentry", exc_info=True)


# ---------------------------------------------------------------------------
# Scrubbing de PII
# ---------------------------------------------------------------------------

def _redactar_texto(texto: str) -> str:
    texto = _RFC_RE.sub("<RFC>", texto)
    for patron, reemplazo in _HOME_RES:
        texto = patron.sub(reemplazo, texto)
    return texto


def _scrub(obj):
    """Recorre el evento: redacta RFCs/rutas en strings y borra valores sensibles."""
    if isinstance(obj, dict):
        limpio = {}
        for clave, valor in obj.items():
            if isinstance(clave, str) and _CLAVE_SENSIBLE_RE.search(clave):
                limpio[clave] = "<redactado>"
            else:
                limpio[clave] = _scrub(valor)
        return limpio
    if isinstance(obj, (list, tuple)):
        return [_scrub(v) for v in obj]
    if isinstance(obj, str):
        return _redactar_texto(obj)
    return obj


def _es_ruido_conexion_cliente(event) -> bool:
    """ConnectionResetError [WinError 10054] en el proactor de asyncio: el
    renderer cerró la conexión (SSE, refresh, cierre de la app) y Windows lo
    reporta como error en el callback de asyncio (TODOCONTA-DESKTOP-1H). Es el
    ciclo de vida normal de un cliente HTTP local, no un bug del agente."""
    try:
        for exc in (event.get("exception", {}) or {}).get("values", []) or []:
            if exc.get("type") == "ConnectionResetError" and "10054" in str(
                exc.get("value", "")
            ):
                return True
    except Exception:  # noqa: BLE001 — el filtro jamás debe tirar el evento
        pass
    return False


def _before_send(event, hint):  # noqa: ARG001 — `hint` lo exige la firma de Sentry
    try:
        if _es_ruido_conexion_cliente(event):
            return None
        return _scrub(event)
    except Exception:  # noqa: BLE001 — ante la duda, deja pasar el evento original
        return event

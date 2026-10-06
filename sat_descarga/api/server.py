"""
FastAPI server para exponer el cliente SAT Descarga Masiva via HTTP local.

Corre en localhost:8787. La app web (todoconta-apps) se conecta a este endpoint
para iniciar descargas sin que la e-firma salga de la máquina del usuario.

Arquitectura:
    [app.todoconta.com] ──── fetch(localhost:8787) ────→ [Python local]
                                                                 │
                                                         [SAT Web Service]
                                                         [e-firma local]

Los endpoints viven en routers por dominio (`api/routers/`): webservice, portal,
empresas, procesador, utilidades y system. El estado de sesión y los helpers
compartidos viven en `api/state.py`. Este módulo solo arma la app: CORS,
middleware de token del shell, lifespan e include_router(s).

Uso:
    uvicorn sat_descarga.api.server:app --port 8787 --host 127.0.0.1

    O desde código:
        from sat_descarga.server import start
        start()
"""

import hmac
import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI y dependencias (lazy-import para no romper el módulo base si no
# están instalados)
# ---------------------------------------------------------------------------

try:
    from fastapi import FastAPI, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse
except ImportError:
    raise ImportError(
        "fastapi no está instalado. Ejecuta:\n"
        "  pip install fastapi uvicorn[standard]"
    )

# Re-export para compatibilidad con los tests: limpian/inspeccionan la sesión
# vía `server._limpiar_session()` y `server._session` (viven en api/state.py).
from .state import _session, _limpiar_session  # noqa: F401

from .routers import (
    webservice_router,
    portal_router,
    certifica_router,
    empresas_router,
    procesador_router,
    utilidades_router,
    calculadoras_router,
    ce_router,
    diot_router,
    tareas_router,
    system_router,
    descargas_router,
    sesion_router,
)

# Telemetría de errores (Sentry). Apagada salvo que haya SENTRY_DSN en el entorno
# (lo inyecta el shell Electron en builds empaquetados). Debe inicializarse antes
# de crear la app para que la integración de FastAPI enganche el manejo de errores.
from ..core.telemetria import init_sentry

init_sentry()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: "FastAPI"):
    # IMPORTANTE: NO autocargar la e.firma aquí. Antes hacíamos
    # `_autocargar_empresa_default()` en el lifespan para sincronizar "empresa
    # activa" con "e.firma en sesión", pero esa función llama a
    # `keyring.get_password()` y en Windows con el binario PyInstaller sin
    # firma, el Credential Manager bloquea esperando un prompt UI que nunca
    # llega (proceso non-interactive). Resultado: el lifespan jamás
    # completaba, uvicorn nunca aceptaba conexiones y `/health` no respondía
    # → el shell Electron quedaba en "Cargando…" infinito.
    #
    # Solución: carga lazy. El renderer invoca POST /auth/autocargar
    # explícitamente después del login (no bloquea startup), o cada endpoint
    # que necesite FIEL la carga on-demand. Ver memoria
    # `feedback-keyring-macos-unsigned-hang`.

    # Warm-up del navegador del portal en un hilo daemon: descarga/actualiza
    # Chromium en background (primera vez o tras actualizar la app, cuando
    # Playwright pide una revisión nueva). No toca keyring ni bloquea el
    # startup — /health responde de inmediato y reporta el progreso.
    try:
        from ..portal.setup import warmup_async

        warmup_async()
    except Exception:
        logger.exception("No se pudo iniciar el warm-up del navegador")

    # Poller de solicitudes WS en background (hilo daemon): verifica y descarga
    # las solicitudes pendientes de TODAS las empresas, aunque el usuario cambie
    # de empresa o de pantalla. Arranca con delay y solo toca el keychain cuando
    # una empresa tiene solicitudes pendientes (ver api/poller.py).
    try:
        from .poller import iniciar_poller, detener_poller

        iniciar_poller()
    except Exception:
        logger.exception("No se pudo iniciar el poller de solicitudes WS")
        detener_poller = None

    # Sesión única (F1.1): en escritorio, un hilo late cada 60 s para enterarse
    # de que otra instalación reclamó la cuenta (y pausar lo de fondo). En la
    # web no corre: ahí late cada navegador.
    try:
        from .sesion_unica import iniciar_latidos, detener_latidos

        iniciar_latidos()
    except Exception:
        logger.exception("No se pudo iniciar el latido de la sesión")
        detener_latidos = None
    yield
    if detener_poller is not None:
        detener_poller()
    if detener_latidos is not None:
        detener_latidos()


app = FastAPI(
    title="SAT Descarga Masiva — Agente Local",
    description=(
        "Servidor local para descargar CFDIs del SAT sin exponer la e-firma. "
        "La e-firma nunca sale de tu máquina."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS: el agente bindea a 127.0.0.1 y NUNCA expone puerto a la red externa,
# así que aceptar cualquier origin es seguro (no hay superficie de ataque
# cross-site real). En Electron empacado el renderer corre desde
# `file://...resources/ui/index.html` y el browser envía `Origin: null` o
# `file://`, NO incluidos en la antigua allow-list — eso bloqueaba todas las
# requests del renderer en producción y dejaba la app stuck en "Cargando…"
# (el agente recibía y respondía 200, pero el browser tiraba el response
# por CORS antes de entregárselo al JS).
#
# `allow_credentials=False` + `allow_origins=["*"]` es la combinación válida
# por especificación CORS — no se pueden combinar `*` con `True`. Es OK
# para nosotros: el renderer NO manda cookies ni credenciales (el Bearer
# token de Supabase vive solo en el agente Python, nunca llega al renderer).
#
# En modo hosted el agente SÍ está expuesto a internet (detrás de Traefik), así
# que SAT_DM_CORS_ORIGINS (lista separada por comas, la inyecta el provisioner)
# restringe los orígenes al dominio de la web app. Sin la env, comportamiento
# local de siempre.
_cors_origins = [
    o.strip()
    for o in os.environ.get("SAT_DM_CORS_ORIGINS", "").split(",")
    if o.strip()
] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Autenticación con el shell (token efímero)
# ---------------------------------------------------------------------------
# Electron genera un token aleatorio por arranque y se lo pasa al agente vía
# env SAT_AGENT_TOKEN; cualquier request sin ese token se rechaza con 401.
# Cierra el hueco de que OTRO proceso local del usuario le pegue al agente
# (que mantiene la FIEL cargada en sesión). Sin la env (CLI o `uvicorn`
# manual en dev) no se exige nada.
_AGENT_TOKEN = os.environ.get("SAT_AGENT_TOKEN", "")


@app.middleware("http")
async def _verificar_token_del_shell(request: Request, call_next):
    # El preflight CORS (OPTIONS) no puede traer headers custom — se deja pasar;
    # no ejecuta ningún endpoint.
    if _AGENT_TOKEN and request.method != "OPTIONS":
        recibido = (
            request.headers.get("x-agent-token")
            or request.query_params.get("token")  # EventSource no acepta headers
            or ""
        )
        if not hmac.compare_digest(recibido, _AGENT_TOKEN):
            return JSONResponse(
                status_code=401,
                content={"detail": "Token del agente inválido o ausente."},
            )
    return await call_next(request)

# ---------------------------------------------------------------------------
# Límites del plan (F1): tope de empresas y descargas del mes → HTTP 402 con
# `{detail, codigo, <codigo>: datos}` (ver api/limites_plan.py).
# ---------------------------------------------------------------------------

from .limites_plan import LimitePlanAlcanzado  # noqa: E402


@app.exception_handler(LimitePlanAlcanzado)
async def _limite_plan(request: Request, exc: LimitePlanAlcanzado):
    return JSONResponse(status_code=402, content=exc.respuesta())


# ---------------------------------------------------------------------------
# Routers por dominio (las rutas completas viven en cada decorador)
# ---------------------------------------------------------------------------

app.include_router(system_router)
app.include_router(webservice_router)
app.include_router(utilidades_router)
app.include_router(portal_router)
app.include_router(certifica_router)
app.include_router(empresas_router)
app.include_router(procesador_router)
app.include_router(calculadoras_router)
app.include_router(diot_router)
app.include_router(ce_router)
app.include_router(tareas_router)
app.include_router(descargas_router)
app.include_router(sesion_router)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def start(port: int = 8787, host: str = "127.0.0.1"):
    """
    Inicia el servidor FastAPI local.

    Llamado automáticamente cuando el app de escritorio (Electron) levanta
    el proceso Python. La app web se conecta a http://localhost:8787.
    """
    try:
        import uvicorn
    except ImportError:
        raise ImportError(
            "uvicorn no está instalado. Ejecuta:\n"
            "  pip install uvicorn[standard]"
        )

    logger.info("Iniciando SAT Descarga Masiva en http://%s:%d", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    start()

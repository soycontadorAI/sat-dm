"""
Gateway de la API pública y el servidor MCP (api.todoconta.com / agente.todoconta.com).

Da los servicios de TodoConta a integradores (REST v1) y a LLMs (MCP,
Streamable HTTP) SIN pasar por la UI: valida la API key contra Supabase
(solo el hash vive ahí), deriva el agente personal del usuario (misma master
key que el provisioner), lo enciende si hace falta y le rutea las operaciones.
Los documentos salen del espacio privado del usuario; la base de datos
compartida solo conoce hashes de keys y metadata.

Endpoints y tools MCP: docs/producto/especificaciones.md (Parte I). Emisión de keys:
emitir-key.py.
"""

from __future__ import annotations

import base64
import contextvars
from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from typing import Optional

import requests
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

import capacidades as caps_srv
import oauth as oauth_srv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get("TODOCONTA_SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
AGENTE_IMAGEN = os.environ.get("AGENTE_IMAGEN", "todoconta/agente:dev")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://agente.todoconta.com").rstrip("/")
DOMINIO = PUBLIC_BASE.split("://", 1)[-1]
RED_AGENTES = os.environ.get("RED_AGENTES", "agentes")
CORS_WEB = os.environ.get("CORS_ORIGINS", "https://app.todoconta.com")

_TIMEOUT = 30
_TIMEOUT_DOCUMENTO = 240  # portal del SAT: la CSF/32-D puede tardar ~1-2 min


def _master_key() -> bytes:
    raw = os.environ.get("SAT_DM_MASTER_KEY", "")
    if not raw:
        raise RuntimeError("SAT_DM_MASTER_KEY no está configurada")
    return base64.b64decode(raw)


# ---------------------------------------------------------------------------
# Enlaces de descarga firmados (para clientes MCP que no renderizan el PDF
# embebido — p. ej. claude.ai web hoy: "Resources of type 'application/pdf'
# are not currently supported"). El token HMAC lleva su propia autorización:
# el usuario lo abre en su navegador SIN API key ni sesión. Firmado con una
# clave derivada de la master key (no expone nada nuevo), scope a un user_id +
# ruta concretos y expiración corta.
# ---------------------------------------------------------------------------

_LINK_TTL_S = 3600  # 1 h: suficiente para que el usuario dé clic


def _clave_firma() -> bytes:
    return hmac.new(_master_key(), b"descargas-firmadas:v1", hashlib.sha256).digest()


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_dec(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _firmar_token(payload_dict: dict, expira: int) -> str:
    """Token opaco firmado con HMAC. `expira` es epoch (se pasa desde el request; el
    módulo no llama a time.time en la firma para ser determinista en tests)."""
    payload = _b64u(json.dumps({**payload_dict, "e": expira}, separators=(",", ":")).encode())
    firma = _b64u(hmac.new(_clave_firma(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{firma}"


def _verificar_descarga(token: str, ahora: int) -> Optional[dict]:
    """Valida firma + expiración; devuelve el payload (dict) o None. El payload trae
    `u` (user_id) y o bien `r`/`z` (archivo del agente) o `x` (export del procesador)."""
    try:
        payload, firma = token.split(".", 1)
    except ValueError:
        return None
    esperada = _b64u(hmac.new(_clave_firma(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(firma, esperada):
        return None
    try:
        datos = json.loads(_b64u_dec(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(datos.get("e", 0)) < ahora:
        return None
    return datos


def _url_firmada(payload_dict: dict) -> str:
    token = _firmar_token(payload_dict, int(time.time()) + _LINK_TTL_S)
    api = PUBLIC_BASE.replace("agente.", "api.")
    return f"{api}/v1/descargas/firmada?t={token}"


def _link_firmado(user_id: str, ruta: str, zip_: bool = False) -> str:
    """Enlace público (sin API key) que baja un archivo guardado del agente."""
    return _url_firmada({"u": user_id, "r": ruta, "z": 1 if zip_ else 0})


def _link_export(user_id: str, params: dict) -> str:
    """Enlace público (sin API key) que re-ejecuta un export del procesador (Excel/CSV,
    que no es un archivo guardado sino una consulta en vivo)."""
    return _url_firmada({"u": user_id, "x": params})


# ---------------------------------------------------------------------------
# API keys (Supabase; solo hashes) + rate limit
# ---------------------------------------------------------------------------

# Cache corto de validación: {hash: (expira, user_id, scopes)}
_keys_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_S = 60

# Rate limit por key: {hash: [timestamps]}
_rate: dict = {}
_RATE_MAX = 120
_RATE_VENTANA_S = 300

# Contexto del request autenticado (lo usan las tools MCP).
ctx_user: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "ctx_user", default=None
)


def _validar_key(api_key: str) -> dict:
    """Devuelve {user_id, scopes} o lanza HTTPException 401/429."""
    if not api_key or not api_key.startswith("tc_"):
        raise HTTPException(status_code=401, detail="API key inválida o ausente.")
    h = hashlib.sha256(api_key.encode()).hexdigest()

    ahora = time.monotonic()
    with _cache_lock:
        marcas = [t for t in _rate.get(h, []) if ahora - t < _RATE_VENTANA_S]
        if len(marcas) >= _RATE_MAX:
            raise HTTPException(status_code=429, detail="Límite de peticiones alcanzado. Espera unos minutos.")
        marcas.append(ahora)
        _rate[h] = marcas

        cacheada = _keys_cache.get(h)
        if cacheada and cacheada[0] > ahora:
            return {"user_id": cacheada[1], "scopes": cacheada[2]}

    try:
        resp = requests.get(
            f"{SUPABASE_URL}/rest/v1/api_keys",
            params={
                "key_hash": f"eq.{h}",
                "revocada_en": "is.null",
                "select": "user_id,scopes",
            },
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="No se pudo validar la API key. Intenta más tarde.")
    filas = resp.json() if resp.status_code == 200 else []
    if not filas:
        raise HTTPException(status_code=401, detail="API key inválida o revocada.")
    user = {"user_id": filas[0]["user_id"], "scopes": filas[0].get("scopes") or []}
    with _cache_lock:
        _keys_cache[h] = (ahora + _CACHE_S, user["user_id"], user["scopes"])
    # Marca de uso (best-effort, sin bloquear).
    threading.Thread(
        target=lambda: requests.patch(
            f"{SUPABASE_URL}/rest/v1/api_keys",
            params={"key_hash": f"eq.{h}"},
            json={"ultima_vez_usada": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
            timeout=10,
        ),
        daemon=True,
    ).start()
    return user


def _exigir_scope(user: dict, scope: str) -> None:
    """El scope en la key Y la capacidad en el plan del dueño (F1): `mcp`
    exige `capacidades.mcp`; los scopes REST, `capacidades.api` (o Abacus).
    La parte del plan depende de CAPACIDADES_MODO (ver capacidades.py)."""
    if scope not in user["scopes"]:
        raise HTTPException(status_code=403, detail=f"Tu API key no tiene el permiso `{scope}`.")
    capacidad = caps_srv.capacidad_de_scope(scope)
    if capacidad:
        caps_srv.exigir(user["user_id"], capacidad, via=f"key:{scope}")


# ---------------------------------------------------------------------------
# Agente del usuario (espejo de deploy/provisioner/main.py — misma derivación)
# ---------------------------------------------------------------------------

_docker_lock = threading.Lock()


def _derivar(user_id: str) -> dict:
    master = _master_key()

    def _h(etiqueta: str) -> bytes:
        return hmac.new(master, f"{etiqueta}:{user_id}".encode(), hashlib.sha256).digest()

    return {
        "slug": _h("slug").hex()[:12],
        "token": _h("token").hex(),
        "secrets_key": base64.b64encode(_h("secretos")).decode(),
    }


def _asegurar_agente(user_id: str) -> tuple[str, dict]:
    """Devuelve (base_url_interna, headers) del agente del usuario, encendiéndolo si hace falta."""
    import docker as docker_sdk

    d = _derivar(user_id)
    slug = d["slug"]
    nombre = f"agente-{slug}"

    with _docker_lock:
        cli = docker_sdk.from_env()
        try:
            cli.networks.get(RED_AGENTES)
        except docker_sdk.errors.NotFound:
            cli.networks.create(RED_AGENTES, driver="bridge")
        try:
            cli.volumes.get(f"agente-datos-{slug}")
        except docker_sdk.errors.NotFound:
            cli.volumes.create(f"agente-datos-{slug}")
        try:
            cont = cli.containers.get(nombre)
            if cont.status != "running":
                cont.start()
        except docker_sdk.errors.NotFound:
            r = f"agente-{slug}"
            cli.containers.run(
                AGENTE_IMAGEN,
                name=nombre,
                detach=True,
                network=RED_AGENTES,
                mem_limit="1g",
                restart_policy={"Name": "unless-stopped"},
                volumes={f"agente-datos-{slug}": {"bind": "/data", "mode": "rw"}},
                environment={
                    "SAT_AGENT_TOKEN": d["token"],
                    "SAT_DM_SECRETS_KEY": d["secrets_key"],
                    "SAT_DM_CORS_ORIGINS": CORS_WEB,
                },
                labels={
                    "traefik.enable": "true",
                    f"traefik.http.routers.{r}.rule": f"Host(`{DOMINIO}`) && PathPrefix(`/u/{slug}`)",
                    f"traefik.http.routers.{r}.entrypoints": "websecure",
                    f"traefik.http.routers.{r}.tls.certresolver": "letsencrypt",
                    f"traefik.http.middlewares.{r}-strip.stripprefix.prefixes": f"/u/{slug}",
                    f"traefik.http.routers.{r}.middlewares": f"{r}-strip",
                    f"traefik.http.services.{r}.loadbalancer.server.port": "8787",
                    "traefik.docker.network": RED_AGENTES,
                    "todoconta.agente": "1",
                },
                log_config={"type": "json-file", "config": {"max-size": "10m", "max-file": "3"}},
            )
            logger.info("contenedor %s creado", nombre)

    base = f"http://{nombre}:8787"
    headers = {"X-Agent-Token": d["token"]}
    limite = time.monotonic() + 45
    while time.monotonic() < limite:
        try:
            if requests.get(f"{base}/health", headers=headers, timeout=3).status_code == 200:
                return base, headers
        except requests.RequestException:
            pass
        time.sleep(1.5)
    raise HTTPException(status_code=503, detail="El espacio del usuario está arrancando; reintenta en unos segundos.")


def _agente_de(user: dict) -> tuple[str, dict]:
    return _asegurar_agente(user["user_id"])


def _activar_empresa(base: str, headers: dict, rfc: str) -> dict:
    r = requests.post(f"{base}/empresas/{rfc}/activar", headers=headers, timeout=60)
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=f"La empresa {rfc} no existe en el espacio del usuario.")
    if r.status_code != 200:
        detalle = _detalle(r)
        raise HTTPException(status_code=409, detail=detalle or f"No se pudo activar la empresa {rfc}.")
    try:
        return r.json()  # {ok, rfc, metodos, efirma_lista}
    except ValueError:
        return {}


def _doc_archivado(base: str, headers: dict, rfc: str, prefijo: str = "csf") -> tuple[Optional[str], Optional[str]]:
    """Último documento en archivo según el catálogo del agente → (ruta, fecha) o
    (None, None). prefijo: csf | opinion (campos {prefijo}_path / {prefijo}_descargada_en)."""
    try:
        r = requests.get(f"{base}/empresas", headers=headers, timeout=_TIMEOUT)
        if r.status_code != 200:
            return None, None
        for e in r.json().get("empresas", []):
            if e.get("rfc") == rfc:
                return e.get(f"{prefijo}_path") or None, e.get(f"{prefijo}_descargada_en") or None
    except requests.RequestException:
        pass
    return None, None


def _edad_dias(fecha_iso: Optional[str]) -> Optional[int]:
    """Días transcurridos desde un timestamp ISO del catálogo (None si no se puede leer)."""
    if not fecha_iso:
        return None
    try:
        from datetime import datetime

        fecha = datetime.fromisoformat(fecha_iso.replace("Z", "+00:00"))
        if fecha.tzinfo is not None:
            fecha = fecha.replace(tzinfo=None)
        return max(0, (datetime.now() - fecha).days)
    except ValueError:
        return None


def _ruta_zip_solicitud(base: str, headers: dict, rfc: str, id_solicitud: str) -> Optional[str]:
    """Ruta de descarga de una solicitud WS ya bajada. El registro de la solicitud
    no la trae (update_solicitud no la persiste); la fuente real es el HISTORIAL,
    donde el poller y la descarga manual registran la ruta con el id corto en la
    descripción ("Descarga WS · solicitud 12345678…") — misma lista blanca que
    valida /descargas/zip."""
    try:
        r = requests.get(f"{base}/empresas/{rfc}/solicitudes", headers=headers, timeout=_TIMEOUT)
        for s in (r.json().get("solicitudes", []) if r.status_code == 200 else []):
            if s.get("id_solicitud") == id_solicitud and (s.get("ruta_descarga") or s.get("ruta")):
                return s.get("ruta_descarga") or s.get("ruta")
        r = requests.get(f"{base}/empresas/{rfc}/historial", headers=headers, timeout=_TIMEOUT)
        for d in (r.json().get("descargas", []) if r.status_code == 200 else []):
            if d.get("canal") == "ws" and id_solicitud[:8] in (d.get("descripcion") or "") and d.get("ruta"):
                return d["ruta"]
    except requests.RequestException:
        pass
    return None


def _detalle(r: requests.Response) -> Optional[str]:
    try:
        return r.json().get("detail")
    except ValueError:
        return None


def _descargar_de_agente(base: str, headers: dict, ruta: str, zip_: bool) -> Response:
    endpoint = "zip" if zip_ else "archivo"
    r = requests.get(
        f"{base}/descargas/{endpoint}",
        params={"ruta": ruta},
        headers=headers,
        timeout=_TIMEOUT_DOCUMENTO,
        stream=True,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo obtener el archivo.")
    media = r.headers.get("content-type", "application/octet-stream")
    disp = r.headers.get("content-disposition", "attachment")
    return StreamingResponse(r.iter_content(chunk_size=65536), media_type=media, headers={"Content-Disposition": disp})


def _bytes_de_agente(base: str, headers: dict, ruta: str, zip_: bool = False) -> bytes:
    """Como _descargar_de_agente pero en memoria — para adjuntar el archivo
    embebido en la respuesta de una tool MCP en vez de servirlo como link."""
    endpoint = "zip" if zip_ else "archivo"
    r = requests.get(
        f"{base}/descargas/{endpoint}", params={"ruta": ruta}, headers=headers, timeout=_TIMEOUT_DOCUMENTO,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo obtener el archivo.")
    return r.content


# ---------------------------------------------------------------------------
# App REST v1
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TodoConta — API pública",
    description=(
        "Servicios fiscales del SAT (México) para integradores: Constancia de "
        "Situación Fiscal, Opinión 32-D, descarga masiva de CFDIs, procesador + "
        "Excel, calculadoras fiscales/laborales y listas negras 69/69-B. "
        "Autenticación: header `X-Api-Key` con tu API key (`tc_live_…`)."
    ),
    version="1",
    docs_url="/v1/docs",
    redoc_url=None,
    openapi_url="/v1/openapi.json",
)

# OAuth 2.1 para los conectores MCP (claude.ai/ChatGPT): descubrimiento,
# registro dinámico, autorización (login TodoConta + consentimiento) y tokens.
# Se registra ANTES del mount de /mcp para que /.well-known y /oauth ganen;
# fuera del Swagger público (el /v1/openapi.json solo documenta la REST).
app.include_router(oauth_srv.router)
app.middleware("http")(oauth_srv.middleware_cors)


def _auth(x_api_key: Optional[str], authorization: Optional[str]) -> dict:
    key = x_api_key or ""
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    user = _validar_key(key)
    ctx_user.set(user)
    return user


class SolicitudCfdiRequest(BaseModel):
    rfc: str
    fecha_inicio: str
    fecha_fin: str
    tipo_comprobante: str = "E"  # E emitidos | R recibidos
    tipo_solicitud: str = "CFDI"  # CFDI | Metadata


class RfcRequest(BaseModel):
    rfc: str


@app.get("/v1/health")
def health():
    return {"status": "ok", "servicio": "gateway"}


@app.get("/v1/descargas/firmada", include_in_schema=False)
def v1_descarga_firmada(t: str = ""):
    """Baja un archivo con un token firmado — SIN API key ni sesión. Lo emiten
    las tools MCP para que el usuario abra el PDF/ZIP/Excel en su navegador cuando
    su cliente no puede renderizar el recurso embebido. El token (HMAC) lleva su
    propia autorización: user_id + qué bajar + expiración, imposible de falsificar
    sin la master key; las rutas de archivo las revalida la lista blanca del agente."""
    datos = _verificar_descarga(t, int(time.time()))
    if not datos:
        raise HTTPException(status_code=403, detail="Enlace inválido o expirado. Pide uno nuevo al asistente.")
    base, headers = _asegurar_agente(datos.get("u", ""))
    export = datos.get("x")
    if export is not None:
        # Export del procesador (Excel/CSV): consulta en vivo, no un archivo guardado.
        r = requests.get(
            f"{base}/procesador/cfdi/exportar", headers=headers, params=export, timeout=300, stream=True,
        )
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo exportar.")
        return StreamingResponse(
            r.iter_content(chunk_size=65536),
            media_type=r.headers.get("content-type", "application/octet-stream"),
            headers={"Content-Disposition": r.headers.get("content-disposition", "attachment")},
        )
    return _descargar_de_agente(base, headers, datos.get("r", ""), zip_=bool(datos.get("z")))


@app.get("/v1/empresas")
def v1_empresas(x_api_key: str = Header(None), authorization: str = Header(None)):
    """Catálogo del espacio del usuario (metadata; nunca credenciales ni rutas)."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "documentos:leer")
    base, headers = _agente_de(user)
    r = requests.get(f"{base}/empresas", headers=headers, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="No se pudo leer el catálogo.")
    empresas = [
        {k: e.get(k) for k in ("rfc", "nombre", "metodos", "vencimiento", "archived_at")}
        for e in r.json().get("empresas", [])
    ]
    return {"empresas": empresas}


def _documento(user: dict, rfc: str, endpoint: str, nombre_doc: str, fallback_archivo: bool = False) -> Response:
    _exigir_scope(user, "documentos:leer")
    rfc = rfc.strip().upper()
    base, headers = _agente_de(user)

    def _entregar_archivada(motivo: str) -> Optional[Response]:
        ruta, fecha = _doc_archivado(base, headers, rfc)
        if not ruta:
            return None
        try:
            resp = _descargar_de_agente(base, headers, ruta, zip_=False)
        except HTTPException:
            return None  # archivo ilegible/fuera de lista blanca → seguir al error claro
        resp.headers["X-Documento-Origen"] = "archivo"
        resp.headers["X-Documento-Motivo"] = motivo
        if fecha:
            resp.headers["X-Documento-Fecha"] = fecha
        return resp

    try:
        activacion = _activar_empresa(base, headers, rfc)
    except HTTPException as exc:
        # e.firma cargada pero inutilizable (contraseña/vigencia/cert): con
        # fallback intenta la copia en archivo; 404 (empresa no existe) sí pasa.
        if fallback_archivo and exc.status_code == 409:
            resp = _entregar_archivada("efirma-invalida")
            if resp is not None:
                return resp
        raise

    # La generación al momento requiere e.firma; la opinión 32-D NO tiene
    # fallback a archivo (es una foto de cumplimiento puntual — una vieja engaña).
    sin_fiel = "fiel" not in (activacion.get("metodos") or []) or not activacion.get("efirma_lista")

    if sin_fiel:
        if fallback_archivo:
            resp = _entregar_archivada("sin-efirma")
            if resp is not None:
                return resp
        raise HTTPException(
            status_code=409,
            detail=(
                f"La empresa {rfc} no tiene e.firma cargada en TodoConta, así que la {nombre_doc} "
                "no se puede generar al momento. Carga su e.firma (TodoConta Desktop → Empresas) "
                "y vuelve a intentarlo."
            ),
        )

    r = requests.post(f"{base}/{endpoint}", headers=headers, json={}, timeout=_TIMEOUT_DOCUMENTO)
    if r.status_code != 200:
        if fallback_archivo:
            resp = _entregar_archivada("sat-fallo")
            if resp is not None:
                return resp
        raise HTTPException(status_code=502, detail=_detalle(r) or f"No se pudo descargar la {nombre_doc}.")
    # El agente responde {"ok": True, "archivo": ruta} (routers/portal.py).
    ruta = r.json().get("archivo") or r.json().get("path") or r.json().get("ruta")
    if not ruta:
        raise HTTPException(status_code=502, detail=f"El agente no reportó la ruta de la {nombre_doc}.")
    return _descargar_de_agente(base, headers, ruta, zip_=False)


@app.post("/v1/csf")
def v1_csf(req: RfcRequest, x_api_key: str = Header(None), authorization: str = Header(None)):
    """
    Descarga la Constancia de Situación Fiscal (PDF) de la empresa.

    Sin e.firma cargada (o con el SAT caído) entrega la última CSF en archivo del
    catálogo, marcada con X-Documento-Origen: archivo + X-Documento-Fecha.
    """
    return _documento(_auth(x_api_key, authorization), req.rfc, "constancia/fiel", "constancia", fallback_archivo=True)


@app.post("/v1/opinion")
def v1_opinion(req: RfcRequest, x_api_key: str = Header(None), authorization: str = Header(None)):
    """Descarga la Opinión de Cumplimiento 32-D (PDF) de la empresa."""
    return _documento(_auth(x_api_key, authorization), req.rfc, "opinion/fiel", "opinión 32-D")


@app.post("/v1/cfdi/solicitudes")
def v1_solicitar(req: SolicitudCfdiRequest, x_api_key: str = Header(None), authorization: str = Header(None)):
    """Crea una solicitud de descarga masiva WS. El poller del espacio la resuelve solo."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "cfdi:solicitar")
    rfc = req.rfc.strip().upper()
    base, headers = _agente_de(user)
    _activar_empresa(base, headers, rfc)
    r = requests.post(
        f"{base}/solicitar",
        headers=headers,
        json={
            "fecha_inicio": req.fecha_inicio,
            "fecha_fin": req.fecha_fin,
            "tipo_comprobante": req.tipo_comprobante,
            "tipo_solicitud": req.tipo_solicitud,
        },
        timeout=120,
    )
    if r.status_code == 503:
        raise HTTPException(status_code=503, detail=_detalle(r) or "El SAT no está disponible; reintenta.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "El SAT rechazó la solicitud.")
    return {"rfc": rfc, **r.json()}


@app.get("/v1/cfdi/solicitudes/{rfc}/{id_solicitud}")
def v1_estado_solicitud(rfc: str, id_solicitud: str, x_api_key: str = Header(None), authorization: str = Header(None)):
    """Estado de una solicitud (el poller del espacio descarga solo al estar lista)."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "cfdi:solicitar")
    rfc = rfc.strip().upper()
    base, headers = _agente_de(user)
    r = requests.get(f"{base}/empresas/{rfc}/solicitudes", headers=headers, timeout=_TIMEOUT)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="No se pudieron leer las solicitudes.")
    for s in r.json().get("solicitudes", []):
        if s.get("id_solicitud") == id_solicitud:
            return s
    raise HTTPException(status_code=404, detail="Solicitud no encontrada.")


@app.get("/v1/cfdi/solicitudes/{rfc}/{id_solicitud}/zip")
def v1_zip_solicitud(rfc: str, id_solicitud: str, x_api_key: str = Header(None), authorization: str = Header(None)):
    """ZIP con los XML de una solicitud ya descargada por el espacio."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "cfdi:solicitar")
    rfc = rfc.strip().upper()
    base, headers = _agente_de(user)
    ruta = _ruta_zip_solicitud(base, headers, rfc, id_solicitud)
    if not ruta:
        raise HTTPException(
            status_code=409,
            detail="La solicitud no existe o aún no está descargada; consulta su estado y reintenta.",
        )
    return _descargar_de_agente(base, headers, ruta, zip_=True)


class ProcesarRequest(BaseModel):
    rfc: str
    desde: Optional[str] = None   # YYYY-MM-DD
    hasta: Optional[str] = None
    tipo: Optional[str] = None    # E emitidos | R recibidos | None ambos


def _params_filtros(rfc: str, desde, hasta, direccion) -> dict:
    params = {"rfc": rfc.strip().upper()}
    if desde:
        params["desde"] = desde
    if hasta:
        params["hasta"] = hasta
    if direccion:
        params["direccion"] = direccion
    return params


@app.post("/v1/cfdi/procesar")
def v1_procesar(req: ProcesarRequest, x_api_key: str = Header(None), authorization: str = Header(None)):
    """Carga al procesador los XML YA descargados de la empresa (por período).

    Flujo completo: POST /v1/cfdi/solicitudes → (el espacio descarga solo) →
    este endpoint → /v1/cfdi/resumen | /v1/cfdi/excel.
    """
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "cfdi:solicitar")
    base, headers = _agente_de(user)
    r = requests.post(
        f"{base}/procesador/cfdi/cargar-desde-empresa",
        headers=headers,
        json={"rfc": req.rfc.strip().upper(), "desde": req.desde, "hasta": req.hasta, "tipo": req.tipo},
        timeout=300,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudieron procesar los CFDIs.")
    return r.json()


@app.get("/v1/cfdi/resumen")
def v1_resumen(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    direccion: Optional[str] = None,
    x_api_key: str = Header(None),
    authorization: str = Header(None),
):
    """KPIs del período (totales, IVA/ISR, conteos) — para que la IA analice."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "documentos:leer")
    base, headers = _agente_de(user)
    r = requests.get(
        f"{base}/procesador/cfdi/stats",
        headers=headers,
        params=_params_filtros(rfc, desde, hasta, direccion),
        timeout=120,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo obtener el resumen.")
    return r.json()


@app.get("/v1/cfdi/reporte/{nombre}")
def v1_reporte(
    nombre: str,
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    direccion: Optional[str] = None,
    x_api_key: str = Header(None),
    authorization: str = Header(None),
):
    """Reportes JSON: totales-mes · top-contrapartes · integridad."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "documentos:leer")
    base, headers = _agente_de(user)
    r = requests.get(
        f"{base}/procesador/cfdi/reporte/{nombre}",
        headers=headers,
        params=_params_filtros(rfc, desde, hasta, direccion),
        timeout=120,
    )
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail=_detalle(r) or "Reporte desconocido.")
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo generar el reporte.")
    return r.json()


@app.get("/v1/cfdi/excel")
def v1_excel(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    direccion: Optional[str] = None,
    formato: str = "xlsx",
    x_api_key: str = Header(None),
    authorization: str = Header(None),
):
    """El Excel (o CSV) del período con el detalle de impuestos, en streaming."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "documentos:leer")
    base, headers = _agente_de(user)
    params = _params_filtros(rfc, desde, hasta, direccion)
    params["formato"] = formato
    r = requests.get(
        f"{base}/procesador/cfdi/exportar",
        headers=headers,
        params=params,
        timeout=300,
        stream=True,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo exportar.")
    return StreamingResponse(
        r.iter_content(chunk_size=65536),
        media_type=r.headers.get("content-type", "application/octet-stream"),
        headers={"Content-Disposition": r.headers.get("content-disposition", "attachment")},
    )


@app.post("/v1/calculadoras/{tipo}")
def v1_calculadora(tipo: str, body: dict, x_api_key: str = Header(None), authorization: str = Header(None)):
    """Calculadoras fiscales/laborales (sbc, isr, aguinaldo, finiquito,
    liquidacion, carga-patronal, ptu). El agente valida y responde en español
    (p. ej. salario por debajo del mínimo) — los 400/422 se propagan tal cual."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "documentos:leer")
    base, headers = _agente_de(user)
    r = requests.post(f"{base}/calculadoras/{tipo}", headers=headers, json=body, timeout=60)
    if r.status_code in (200, 400, 404, 422):
        return Response(content=r.content, status_code=r.status_code, media_type="application/json")
    raise HTTPException(status_code=502, detail=_detalle(r) or "No se pudo calcular.")


@app.post("/v1/listas-negras")
def v1_listas_negras(body: dict, x_api_key: str = Header(None), authorization: str = Header(None)):
    """Consulta RFCs contra las listas 69/69-B (vía RPC de Supabase, sin agente)."""
    user = _auth(x_api_key, authorization)
    _exigir_scope(user, "listas-negras:consultar")
    rfcs = body.get("rfcs") or []
    if not isinstance(rfcs, list) or not rfcs or len(rfcs) > 200:
        raise HTTPException(status_code=400, detail="Manda `rfcs` (lista de 1 a 200).")
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/rpc/check_rfcs_listas_negras",
        json={"p_rfcs": [str(x).strip().upper() for x in rfcs]},
        headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
        timeout=_TIMEOUT,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail="No se pudieron consultar las listas.")
    return {"resultados": r.json()}


# ---------------------------------------------------------------------------
# Interno: vínculos del asistente (Abacus) — WhatsApp → API key cifrada
# ---------------------------------------------------------------------------

# El plugin abacus-todoconta (OpenClaw, mismo VPS) resuelve aquí el remitente
# de WhatsApp a la key cifrada del usuario, en vez de hablar con Supabase
# directamente: así el proceso del bot no necesita el service key. La key
# viaja cifrada (AES-256-GCM, ASISTENTE_VINCULOS_KEY); el gateway nunca la ve
# en claro. DDL: migración 031_asistente_vinculos.sql (todoconta-apps) ·
# el diseño vive en la documentación interna de operación (repo privado).
VINCULOS_INTERNAL_TOKEN = os.environ.get("VINCULOS_INTERNAL_TOKEN", "")


@app.get("/internal/vinculos/{whatsapp}", include_in_schema=False)
def internal_vinculo(whatsapp: str, x_interno_token: str = Header(None)):
    """Vínculo activo de un número E.164 (solo para el plugin de Abacus)."""
    if not VINCULOS_INTERNAL_TOKEN or not hmac.compare_digest(
        x_interno_token or "", VINCULOS_INTERNAL_TOKEN
    ):
        raise HTTPException(status_code=401, detail="Token interno inválido.")
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/asistente_vinculos",
            params={
                "whatsapp_e164": f"eq.{whatsapp}",
                "estado": "eq.activo",
                "select": "user_id,api_key_cifrada",
            },
            headers={
                "apikey": SUPABASE_SERVICE_KEY,
                "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="No se pudo consultar el vínculo.")
    filas = r.json() if r.status_code == 200 else []
    if not filas:
        raise HTTPException(status_code=404, detail="Número sin vínculo activo.")
    # Abacus solo con un plan que lo incluya (Completo, legado con IA, a la medida).
    caps_srv.exigir(filas[0]["user_id"], "abacus", via="vinculo")
    return {"user_id": filas[0]["user_id"], "api_key_cifrada": filas[0]["api_key_cifrada"]}


# ---------------------------------------------------------------------------
# Servidor MCP (Streamable HTTP) — mismas operaciones como tools
# ---------------------------------------------------------------------------

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.transport_security import TransportSecuritySettings
    from mcp.types import BlobResourceContents, EmbeddedResource, TextContent

    mcp_srv = FastMCP(
        "TodoConta",
        instructions=(
            "Servicios fiscales del SAT (México) del usuario autenticado: catálogo "
            "de empresas, Constancia de Situación Fiscal, Opinión 32-D, descarga "
            "masiva de CFDIs y listas negras 69/69-B."
        ),
        stateless_http=True,
        streamable_http_path="/mcp",
        # Anti DNS-rebinding del SDK: sin esto solo acepta Host localhost.
        transport_security=TransportSecuritySettings(
            allowed_hosts=[DOMINIO, f"{DOMINIO}:443", "localhost", "127.0.0.1:8795"],
            allowed_origins=[f"https://{DOMINIO}", "https://app.todoconta.com"],
        ),
    )

    def _mcp_user() -> dict:
        user = ctx_user.get()
        if user is None:
            raise RuntimeError("Sesión MCP sin API key válida.")
        return user

    # Por encima de esto no se adjunta el blob (un ZIP de meses de CFDIs o un
    # Excel grande sí pueden pesarlo) — se entrega solo el enlace firmado.
    _LIMITE_ADJUNTO_MCP = 20 * 1024 * 1024  # 20 MB

    # No todos los clientes MCP renderizan un recurso embebido: claude.ai web hoy
    # responde "Resources of type 'application/pdf' are not currently supported".
    # Por eso TODA respuesta con archivo incluye además un enlace firmado (sin
    # API key, expira en 1 h) que el usuario abre en su navegador — es el camino
    # que sí funciona en cualquier cliente. El blob se conserva para los que sí
    # lo pintan (Claude Desktop, connector vía API).
    def _texto_enlace(url: str) -> str:
        return f" Descárgalo aquí (enlace directo, sin contraseña, válido 1 hora): {url}"

    def _mcp_adjuntar(uri: str, mime: str, contenido: bytes, mensaje: str, enlace_url: str) -> list:
        """Como _mcp_pdf pero genérico y con tope de tamaño — ZIPs de CFDIs y Excel
        del procesador. Siempre incluye el enlace firmado; adjunta el blob salvo que
        pese de más. `enlace_url` es la URL firmada ya construida (archivo o export)."""
        link = _texto_enlace(enlace_url)
        if len(contenido) > _LIMITE_ADJUNTO_MCP:
            peso = len(contenido) / 1_048_576
            return [TextContent(type="text", text=f"{mensaje} Pesa {peso:.1f} MB, muy grande para adjuntar aquí.{link}")]
        blob = base64.b64encode(contenido).decode()
        return [
            TextContent(type="text", text=f"{mensaje}{link}"),
            EmbeddedResource(type="resource", resource=BlobResourceContents(uri=uri, mimeType=mime, blob=blob)),
        ]

    def _mcp_pdf(rfc: str, nombre_doc: str, esquema: str, contenido: bytes, origen: str,
                 user_id: str, ruta: str, fecha: Optional[str] = None, nota: str = "") -> list:
        """Empaqueta un PDF: enlace firmado en el texto (funciona en todo cliente) +
        el recurso embebido (para los que lo pintan). Así el usuario nunca se queda
        sin el archivo aunque su cliente no renderice el PDF adjunto."""
        if not nota:
            nota = f" (última copia en archivo, generada el {fecha[:10]})" if origen == "archivo" and fecha else (
                " (última copia en archivo)" if origen == "archivo" else ""
            )
        blob = base64.b64encode(contenido).decode()
        texto = f"{nombre_doc} de {rfc}{nota}.{_texto_enlace(_link_firmado(user_id, ruta))}"
        return [
            TextContent(type="text", text=texto),
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri=f"todoconta://{esquema}/{rfc}.pdf", mimeType="application/pdf", blob=blob
                ),
            ),
        ]

    def _mcp_documento(rfc: str, endpoint: str, nombre_doc: str, esquema: str,
                        fallback_archivo: bool = False, forzar_nueva: bool = False,
                        frescura_dias: int = 0, prefijo_archivo: str = "csf") -> list:
        """Entrega un documento embebido — mismo criterio que _documento() (REST)
        pero sin requerir una segunda llamada con API key.

        Con frescura_dias > 0, una copia en archivo dentro de esa ventana se
        entrega AL INSTANTE (sin scrapear el portal), declarando su antigüedad y
        cómo pedir una nueva (forzar_nueva=true) — el asistente puede ofrecer al
        usuario "tengo una de hace X días, ¿te sirve o genero una nueva?"."""
        user = _mcp_user()
        uid = user["user_id"]
        rfc = rfc.strip().upper()
        base, headers = _agente_de(user)

        def _archivada() -> Optional[tuple]:
            ruta, fecha = _doc_archivado(base, headers, rfc, prefijo_archivo)
            if not ruta:
                return None
            try:
                return _bytes_de_agente(base, headers, ruta), fecha, ruta
            except HTTPException:
                return None

        if frescura_dias and not forzar_nueva:
            ruta, fecha = _doc_archivado(base, headers, rfc, prefijo_archivo)
            edad = _edad_dias(fecha)
            if ruta and edad is not None and edad <= frescura_dias:
                try:
                    contenido = _bytes_de_agente(base, headers, ruta)
                except HTTPException:
                    contenido = None
                if contenido:
                    dias = "hoy" if edad == 0 else (f"hace {edad} día" + ("s" if edad != 1 else ""))
                    nota = (
                        f" — copia descargada {dias} (dentro de la vigencia típica de "
                        f"{frescura_dias} días), entregada al instante; si el usuario necesita "
                        f"una recién emitida por el SAT, vuelve a llamar con forzar_nueva=true"
                    )
                    return _mcp_pdf(rfc, nombre_doc, esquema, contenido, "reciente", uid, ruta, nota=nota)

        try:
            activacion = _activar_empresa(base, headers, rfc)
        except HTTPException as exc:
            if fallback_archivo and exc.status_code == 409:
                archivada = _archivada()
                if archivada:
                    contenido, fecha, ruta = archivada
                    return _mcp_pdf(rfc, nombre_doc, esquema, contenido, "archivo", uid, ruta, fecha=fecha)
            return [TextContent(type="text", text=str(exc.detail))]

        sin_fiel = "fiel" not in (activacion.get("metodos") or []) or not activacion.get("efirma_lista")
        if sin_fiel:
            if fallback_archivo:
                archivada = _archivada()
                if archivada:
                    contenido, fecha, ruta = archivada
                    return _mcp_pdf(rfc, nombre_doc, esquema, contenido, "archivo", uid, ruta, fecha=fecha)
            return [TextContent(type="text", text=(
                f"La empresa {rfc} no tiene e.firma cargada, así que {nombre_doc.lower()} no se "
                "puede generar al momento. Carga su e.firma en TodoConta y vuelve a intentarlo."
            ))]

        r = requests.post(f"{base}/{endpoint}", headers=headers, json={}, timeout=_TIMEOUT_DOCUMENTO)
        if r.status_code != 200:
            if fallback_archivo:
                archivada = _archivada()
                if archivada:
                    contenido, fecha, ruta = archivada
                    return _mcp_pdf(rfc, nombre_doc, esquema, contenido, "archivo", uid, ruta, fecha=fecha)
            return [TextContent(type="text", text=f"No se pudo generar {nombre_doc.lower()}: {_detalle(r) or 'error del portal del SAT'}")]

        # El agente responde {"ok": True, "archivo": ruta} (routers/portal.py).
        ruta = r.json().get("archivo") or r.json().get("path") or r.json().get("ruta")
        if not ruta:
            return [TextContent(type="text", text=f"El agente no reportó la ruta de {nombre_doc.lower()}.")]
        contenido = _bytes_de_agente(base, headers, ruta)
        return _mcp_pdf(rfc, nombre_doc, esquema, contenido, "generado", uid, ruta)

    @mcp_srv.tool()
    def listar_empresas() -> str:
        """Lista las empresas (RFC, nombre, métodos) del espacio del usuario."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        r = requests.get(f"{base}/empresas", headers=headers, timeout=_TIMEOUT)
        filas = [
            f"- {e['rfc']} · {e['nombre']} · métodos: {', '.join(e.get('metodos') or []) or 'sin credenciales'}"
            for e in r.json().get("empresas", [])
            if not e.get("archived_at")
        ]
        return "\n".join(filas) or "No hay empresas registradas."

    @mcp_srv.tool(structured_output=False)
    def descargar_csf(rfc: str, forzar_nueva: bool = False) -> list:
        """Constancia de Situación Fiscal de la empresa, adjunta como PDF en esta misma
        respuesta. Si hay una copia de hace 90 días o menos la entrega al instante
        indicando su antigüedad — ofrece al usuario regenerarla con forzar_nueva=true si
        necesita una recién emitida por el SAT. Sin e.firma cargada (o con el SAT caído)
        entrega la última copia en archivo si existe."""
        return _mcp_documento(rfc, "constancia/fiel", "la Constancia de Situación Fiscal", "csf",
                              fallback_archivo=True, forzar_nueva=forzar_nueva,
                              frescura_dias=90, prefijo_archivo="csf")

    @mcp_srv.tool(structured_output=False)
    def descargar_opinion(rfc: str, forzar_nueva: bool = False) -> list:
        """Opinión de Cumplimiento 32-D de la empresa, adjunta como PDF en esta misma
        respuesta. Si hay una copia de hace 30 días o menos (la vigencia típica de la
        opinión ante terceros) la entrega al instante indicando su antigüedad — ofrece al
        usuario regenerarla con forzar_nueva=true. Fuera de esa ventana requiere e.firma
        cargada; no se entregan opiniones viejas (una foto de cumplimiento vencida engaña)."""
        return _mcp_documento(rfc, "opinion/fiel", "la Opinión de Cumplimiento 32-D", "opinion",
                              forzar_nueva=forzar_nueva, frescura_dias=30,
                              prefijo_archivo="opinion")

    @mcp_srv.tool()
    def solicitar_cfdis(rfc: str, fecha_inicio: str, fecha_fin: str, tipo: str = "E") -> str:
        """Crea una solicitud de descarga masiva de CFDIs (tipo: E emitidos, R recibidos). Fechas YYYY-MM-DD."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        rfc = rfc.strip().upper()
        _activar_empresa(base, headers, rfc)
        r = requests.post(
            f"{base}/solicitar",
            headers=headers,
            json={"fecha_inicio": fecha_inicio, "fecha_fin": fecha_fin, "tipo_comprobante": tipo},
            timeout=120,
        )
        if r.status_code != 200:
            return f"No se pudo: {_detalle(r) or 'el SAT rechazó la solicitud'}"
        sid = r.json().get("id_solicitud")
        return (
            f"Solicitud {sid} creada para {rfc}. El espacio del usuario la descarga "
            f"solo cuando el SAT la libere (horas); consulta con estado_solicitud."
        )

    @mcp_srv.tool()
    def estado_solicitud(rfc: str, id_solicitud: str) -> str:
        """Estado de una solicitud de descarga masiva."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        r = requests.get(
            f"{base}/empresas/{rfc.strip().upper()}/solicitudes", headers=headers, timeout=_TIMEOUT
        )
        for s in r.json().get("solicitudes", []):
            if s.get("id_solicitud") == id_solicitud:
                return str(s)
        return "Solicitud no encontrada."

    @mcp_srv.tool(structured_output=False)
    def descargar_zip_cfdis(rfc: str, id_solicitud: str) -> list:
        """Adjunta el ZIP de XMLs de una solicitud de descarga masiva ya lista —
        llamar después de que estado_solicitud confirme que terminó."""
        user = _mcp_user()
        rfc = rfc.strip().upper()
        base, headers = _agente_de(user)
        ruta = _ruta_zip_solicitud(base, headers, rfc, id_solicitud)
        if not ruta:
            return [TextContent(type="text", text=(
                "Esa solicitud no existe o aún no está descargada; confirma con estado_solicitud "
                "y reintenta cuando esté lista."
            ))]
        contenido = _bytes_de_agente(base, headers, ruta, zip_=True)
        return _mcp_adjuntar(
            f"todoconta://cfdi-zip/{rfc}-{id_solicitud}.zip", "application/zip", contenido,
            f"ZIP de CFDIs de {rfc} (solicitud {id_solicitud}).",
            _link_firmado(user["user_id"], ruta, zip_=True),
        )

    @mcp_srv.tool()
    def consultar_listas_negras(rfcs: list[str]) -> str:
        """Consulta hasta 200 RFCs contra las listas negras del SAT (Art. 69 y 69-B)."""
        _mcp_user()
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/check_rfcs_listas_negras",
            json={"p_rfcs": [x.strip().upper() for x in rfcs[:200]]},
            headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
            timeout=_TIMEOUT,
        )
        return str(r.json()) if r.status_code == 200 else "No se pudieron consultar las listas."

    @mcp_srv.tool()
    def procesar_cfdis(rfc: str, desde: str = "", hasta: str = "", tipo: str = "") -> str:
        """Carga al procesador los XML ya descargados de la empresa (fechas YYYY-MM-DD; tipo E/R o vacío para ambos). Correr después de que una solicitud esté descargada."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        r = requests.post(
            f"{base}/procesador/cfdi/cargar-desde-empresa",
            headers=headers,
            json={"rfc": rfc.strip().upper(), "desde": desde or None, "hasta": hasta or None, "tipo": tipo or None},
            timeout=300,
        )
        if r.status_code != 200:
            return f"No se pudo procesar: {_detalle(r) or r.status_code}"
        d = r.json()
        return (
            f"Procesados: {d.get('agregados', 0)} nuevos, {d.get('duplicados', 0)} ya estaban, "
            f"{d.get('archivos_encontrados', 0)} archivos encontrados, {len(d.get('errores', []))} con error."
        )

    @mcp_srv.tool()
    def resumen_cfdis(rfc: str, desde: str = "", hasta: str = "", direccion: str = "") -> str:
        """KPIs del período procesado (totales, IVA/ISR retenidos y trasladados, conteos). direccion: E emitidos, R recibidos, vacío ambos."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        r = requests.get(
            f"{base}/procesador/cfdi/stats",
            headers=headers,
            params=_params_filtros(rfc, desde or None, hasta or None, direccion or None),
            timeout=120,
        )
        return str(r.json()) if r.status_code == 200 else f"No se pudo: {_detalle(r) or r.status_code}"

    @mcp_srv.tool()
    def reporte_cfdis(rfc: str, nombre: str, desde: str = "", hasta: str = "") -> str:
        """Reporte JSON del período: totales-mes | top-contrapartes | integridad."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        r = requests.get(
            f"{base}/procesador/cfdi/reporte/{nombre}",
            headers=headers,
            params=_params_filtros(rfc, desde or None, hasta or None, None),
            timeout=120,
        )
        return str(r.json()) if r.status_code == 200 else f"No se pudo: {_detalle(r) or r.status_code}"

    @mcp_srv.tool(structured_output=False)
    def excel_cfdis(rfc: str, desde: str = "", hasta: str = "", direccion: str = "", formato: str = "xlsx") -> list:
        """Genera y adjunta el Excel/CSV con el detalle de impuestos de los CFDIs ya
        procesados del período (correr después de procesar_cfdis). formato: xlsx|csv."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        params = _params_filtros(rfc, desde or None, hasta or None, direccion or None)
        params["formato"] = formato
        r = requests.get(f"{base}/procesador/cfdi/exportar", headers=headers, params=params, timeout=300)
        if r.status_code != 200:
            return [TextContent(type="text", text=f"No se pudo exportar: {_detalle(r) or r.status_code}")]
        mime = (
            "text/csv" if formato == "csv"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return _mcp_adjuntar(
            f"todoconta://cfdi-excel/{params['rfc']}.{formato}", mime, r.content,
            f"Excel de CFDIs de {params['rfc']}.", _link_export(user["user_id"], params),
        )

    def _calc(tipo: str, payload: dict) -> str:
        """Llama una calculadora del agente; los errores de validación (en
        español: p. ej. «salario por debajo del mínimo») se devuelven como
        texto para que la IA pida los datos correctos o explique el límite."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        payload = {k: v for k, v in payload.items() if v is not None}
        r = requests.post(f"{base}/calculadoras/{tipo}", headers=headers, json=payload, timeout=60)
        if r.status_code == 200:
            return str(r.json())
        if r.status_code == 422:
            try:
                faltas = "; ".join(
                    f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}"
                    for e in r.json().get("detail", [])
                )
            except Exception:  # noqa: BLE001
                faltas = r.text[:300]
            return f"Datos inválidos o incompletos — {faltas}"
        return f"No se pudo calcular: {_detalle(r) or r.status_code}"

    @mcp_srv.tool()
    def calcular_sbc(
        salario: float,
        tipo_salario: str = "mensual",
        antiguedad_anios: int = 0,
        dias_aguinaldo: int = 15,
        prima_vacacional: float = 0.25,
        es_zona_fronteriza: bool = False,
        anio: int = 2026,
    ) -> str:
        """Salario Base de Cotización IMSS. tipo_salario: diario|mensual. Valida contra el salario mínimo vigente."""
        return _calc("sbc", {
            "salario": salario, "tipo_salario": tipo_salario, "antiguedad_anios": antiguedad_anios,
            "dias_aguinaldo": dias_aguinaldo, "prima_vacacional": prima_vacacional,
            "es_zona_fronteriza": es_zona_fronteriza, "anio": anio,
        })

    @mcp_srv.tool()
    def calcular_isr_salarios(
        ingreso_gravado: float,
        periodicidad: str = "mensual",
        mes: int = 2,
        es_asimilado: bool = False,
        es_zona_fronteriza: bool = False,
        anio: int = 2026,
    ) -> str:
        """ISR de salarios (tarifas SAT vigentes + subsidio). periodicidad: diario|semanal|decenal|quincenal|mensual."""
        return _calc("isr", {
            "ingreso_gravado": ingreso_gravado, "periodicidad": periodicidad, "mes": mes,
            "es_asimilado": es_asimilado, "es_zona_fronteriza": es_zona_fronteriza, "anio": anio,
        })

    @mcp_srv.tool()
    def calcular_aguinaldo(
        salario: float,
        tipo_salario: str,
        fecha_ingreso: str,
        dias_aguinaldo: int = 15,
        anio: int = 2026,
    ) -> str:
        """Aguinaldo proporcional con su ISR. fecha_ingreso: YYYY-MM-DD."""
        return _calc("aguinaldo", {
            "salario": salario, "tipo_salario": tipo_salario, "fecha_ingreso": fecha_ingreso,
            "dias_aguinaldo": dias_aguinaldo, "anio": anio,
        })

    @mcp_srv.tool()
    def calcular_finiquito(
        salario: float,
        tipo_salario: str,
        fecha_ingreso: str,
        fecha_baja: str,
        anio: int = 2026,
    ) -> str:
        """Finiquito (renuncia): proporcionales de aguinaldo, vacaciones y prima. Fechas YYYY-MM-DD."""
        return _calc("finiquito", {
            "salario": salario, "tipo_salario": tipo_salario, "fecha_ingreso": fecha_ingreso,
            "fecha_baja": fecha_baja, "anio": anio,
        })

    @mcp_srv.tool()
    def calcular_carga_patronal(
        salario: float,
        tipo_salario: str = "mensual",
        antiguedad_anios: int = 0,
        clase_riesgo: str = "I",
        codigo_estado: str = "CDMX",
        anio: int = 2026,
    ) -> str:
        """Costo patronal total (IMSS, Infonavit, impuesto estatal) de un sueldo."""
        return _calc("carga-patronal", {
            "salario": salario, "tipo_salario": tipo_salario, "antiguedad_anios": antiguedad_anios,
            "clase_riesgo": clase_riesgo, "codigo_estado": codigo_estado, "anio": anio,
        })

    @mcp_srv.tool()
    def indicadores_fiscales(anio: int = 2026) -> str:
        """Indicadores vigentes del año: UMA, salarios mínimos (general y ZLFN), etc."""
        user = _mcp_user()
        base, headers = _agente_de(user)
        r = requests.get(f"{base}/calculadoras/indicadores/{anio}", headers=headers, timeout=30)
        return str(r.json()) if r.status_code == 200 else f"No disponible: {r.status_code}"

    _mcp_app = mcp_srv.streamable_http_app()

    # El session manager del SDK exige correr dentro de un lifespan; al montar
    # el sub-app, FastAPI NO ejecuta el suyo — se engancha al del app padre.
    @asynccontextmanager
    async def _lifespan(_app):
        async with mcp_srv.session_manager.run():
            yield

    app.router.lifespan_context = _lifespan

    @app.middleware("http")
    async def _mcp_auth(request: Request, call_next):
        # /v1 se autentica por endpoint; /mcp aquí (las tools leen ctx_user).
        # Dos credenciales sirven: la API key `tc_…` (Claude Code, harnesses,
        # Abacus) o un access token OAuth (conectores de claude.ai/ChatGPT).
        if request.url.path.startswith("/mcp"):
            bearer = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
            api_key = request.headers.get("x-api-key") or (bearer if bearer.startswith("tc_") else "")
            try:
                if api_key:
                    user = _validar_key(api_key)
                    _exigir_scope(user, "mcp")
                else:
                    user = oauth_srv.validar_access_token(bearer)
                    # El token OAuth dura y se renueva solo: el plan se revisa
                    # en cada uso, no solo al autorizar.
                    caps_srv.exigir(user["user_id"], "mcp", via="oauth")
            except HTTPException as e:
                from fastapi.responses import JSONResponse

                # El WWW-Authenticate del 401 es lo que lleva al conector a
                # descubrir el authorization server (RFC 9728).
                headers = (
                    {
                        "WWW-Authenticate": (
                            f'Bearer resource_metadata="{PUBLIC_BASE}/.well-known/oauth-protected-resource"'
                        )
                    }
                    if e.status_code == 401
                    else {}
                )
                return JSONResponse(status_code=e.status_code, content={"detail": e.detail}, headers=headers)
            ctx_user.set(user)
        return await call_next(request)

    # Mount en raíz con path interno /mcp: sirve /mcp EXACTO (sin el 307 a
    # /mcp/ que rompe a los clientes). Las rutas /v1 se registran antes y ganan.
    app.mount("/", _mcp_app)
    logger.info("servidor MCP montado en /mcp")
except ImportError:  # pragma: no cover — sin SDK, la REST sigue funcionando
    logger.warning("SDK de MCP no disponible; /mcp deshabilitado")


# ---------------------------------------------------------------------------
# Logging de uso (básico): diagnóstico + insumo para facturación futura.
# Vive en los logs del contenedor (`docker logs gateway`), no en Supabase
# todavía — evita persistir de más antes de validar el MVP. Se registra AL
# FINAL (fuera del try/except de MCP) para quedar como middleware más externo
# y así también capturar los 401 tempranos del auth de /mcp.
# ---------------------------------------------------------------------------


@app.middleware("http")
async def _log_uso(request: Request, call_next):
    path = request.url.path
    if not (path.startswith("/v1") or path.startswith("/mcp")):
        return await call_next(request)
    inicio = time.monotonic()
    clave = request.headers.get("x-api-key") or (
        request.headers.get("authorization") or ""
    ).removeprefix("Bearer ").strip()
    huella = hashlib.sha256(clave.encode()).hexdigest()[:12] if clave else "-"
    response = await call_next(request)
    dur_ms = int((time.monotonic() - inicio) * 1000)
    logger.info(
        "uso key=%s %s %s -> %s (%sms)", huella, request.method, path, response.status_code, dur_ms
    )
    return response

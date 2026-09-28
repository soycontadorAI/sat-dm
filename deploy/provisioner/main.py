"""
Provisioner de la versión online (agente.todoconta.com/provision/*).

Resuelve el "primer login" de la web: el navegador todavía no conoce su agente,
así que este servicio (a) autentica las credenciales contra Supabase (GoTrue),
(b) valida que la cuenta tenga plan vigente contra todoconta-apps, (c) crea o
arranca el contenedor personal del usuario (docker SDK) y (d) devuelve
`{base_url, token, session}` para que la UI conecte y le entregue la sesión al
agente vía POST /auth/adopt-session.

Derivación determinista (sin base de datos): slug, token del agente y clave de
secretos salen de HMAC(SAT_DM_MASTER_KEY, user_id) — un login desde otro
navegador recupera exactamente el mismo contenedor, y recrearlo (upgrade de
imagen) conserva el acceso a `secretos.enc`. `registry.json` es solo
bookkeeping (email, fechas), no estado crítico.

⚠️ Rotar SAT_DM_MASTER_KEY invalida los secretos de TODOS los usuarios
(recapturarían contraseñas FIEL/CIEC). Ver deploy/vps/README.md.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("provisioner")

# ---------------------------------------------------------------------------
# Config (env)
# ---------------------------------------------------------------------------

SUPABASE_URL = os.environ.get(
    "TODOCONTA_SUPABASE_URL", "https://pyyyzvicjpffohwjsmzi.supabase.co"
).rstrip("/")
# La anon key es pública (la misma que trae el agente desktop).
SUPABASE_ANON_KEY = os.environ.get(
    "TODOCONTA_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InB5eXl6dmljanBmZm9od2pzbXppIiwicm9sZSI6"
    "ImFub24iLCJpYXQiOjE3NjgxNjAyNjIsImV4cCI6MjA4MzczNjI2Mn0."
    "kkOVRZu-u1Iyn6jOqoA7ti5crKJFqgCulsGtOodrLQQ",
)

# Directo al dominio de servicios (api.todoconta.com), sin pasar por el proxy
# del espejo — app.todoconta.com solo debe importar como origen CORS.
LICENCIA_URL = os.environ.get(
    "LICENCIA_URL", "https://api.todoconta.com/api/desktop/license"
)
# Kill switch para la beta: con "0" cualquier cuenta autenticada entra.
EXIGIR_LICENCIA = os.environ.get("EXIGIR_LICENCIA", "1") != "0"
# Allow-list de correos (beta cerrada / soporte): brincan la validación de plan.
ALLOWLIST_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWLIST_EMAILS", "").split(",")
    if e.strip()
}

AGENTE_IMAGEN = os.environ.get("AGENTE_IMAGEN", "todoconta/agente:dev")
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://agente.todoconta.com").rstrip("/")
DOMINIO = PUBLIC_BASE.split("://", 1)[-1]
RED_AGENTES = os.environ.get("RED_AGENTES", "agentes")
CORS_WEB = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "https://app.todoconta.com").split(",")
    if o.strip()
]
REGISTRO_PATH = Path(os.environ.get("REGISTRO_PATH", "/registro/registry.json"))

_TIMEOUT = 15


def _master_key() -> bytes:
    raw = os.environ.get("SAT_DM_MASTER_KEY", "")
    if not raw:
        raise RuntimeError("SAT_DM_MASTER_KEY no está configurada")
    clave = base64.b64decode(raw)
    if len(clave) < 32:
        raise RuntimeError("SAT_DM_MASTER_KEY debe ser >= 32 bytes en base64")
    return clave


# ---------------------------------------------------------------------------
# Derivación determinista por usuario
# ---------------------------------------------------------------------------


def _derivar(user_id: str) -> dict:
    master = _master_key()

    def _hmac(etiqueta: str) -> bytes:
        return hmac.new(master, f"{etiqueta}:{user_id}".encode(), hashlib.sha256).digest()

    return {
        "slug": _hmac("slug").hex()[:12],
        "token": _hmac("token").hex(),
        # 32 bytes exactos → clave AES-256 de secretos.enc del agente.
        "secrets_key": base64.b64encode(_hmac("secretos")).decode(),
    }


# ---------------------------------------------------------------------------
# GoTrue (Supabase) — mismas llamadas REST que el agente desktop
# ---------------------------------------------------------------------------

_MENSAJES = {
    "invalid_credentials": "Correo o contraseña incorrectos.",
    "email_not_confirmed": "Tu correo aún no está confirmado. Entra con un código de acceso.",
    "otp_expired": "El código expiró o no es válido. Pide uno nuevo.",
    "otp_disabled": "No encontramos una cuenta con ese correo.",
    "over_email_send_rate_limit": "Demasiados intentos. Espera un minuto y vuelve a intentar.",
    "over_request_rate_limit": "Demasiados intentos. Espera un momento y vuelve a intentar.",
}


def _error_gotrue(resp: requests.Response) -> HTTPException:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    code = data.get("error_code") or data.get("error") or ""
    msg = data.get("msg") or data.get("error_description") or ""
    if code == "invalid_grant" or "Invalid login credentials" in str(msg):
        code = "invalid_credentials"
    detalle = _MENSAJES.get(code, "No pudimos completar la operación. Intenta de nuevo.")
    status = resp.status_code if 400 <= resp.status_code < 500 else 502
    return HTTPException(status_code=status, detail=detalle)


def _gotrue_post(path: str, payload: dict, params: Optional[dict] = None) -> dict:
    try:
        resp = requests.post(
            f"{SUPABASE_URL}/auth/v1{path}",
            json=payload,
            params=params,
            headers={"apikey": SUPABASE_ANON_KEY},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="No pudimos conectar con el servicio de cuentas.")
    if resp.status_code >= 400:
        raise _error_gotrue(resp)
    try:
        return resp.json()
    except ValueError:
        return {}


def _gotrue_user(access_token: str) -> dict:
    try:
        resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="No pudimos conectar con el servicio de cuentas.")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="La sesión no es válida. Vuelve a iniciar sesión.")
    return resp.json()


def _sesion_de(data: dict) -> dict:
    user = data.get("user") or {}
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "user_id": user.get("id", ""),
        "email": user.get("email"),
    }


# ---------------------------------------------------------------------------
# Licencia (todoconta-apps)
# ---------------------------------------------------------------------------


# Planes que abren la versión web. Los calcula `getDesktopLicense`
# (todoconta-apps, apps/web/src/lib/desktop/auth.ts): free | trial | premium |
# founder. El trial entra: son los 15 días que promete el producto.
PLANES_CON_ACCESO = ("trial", "premium", "founder")


def _plan_da_acceso(lic: dict) -> bool:
    """True si la licencia que devolvió /api/desktop/license abre la web.

    Ese endpoint expone `plan`, `is_founder` y `premium_features_unlocked` —
    NO `subscription_active` ni `subscription_status`. Mirar esos dos (como se
    hacía antes) dejaba muerta la rama del trial: quien estaba dentro de sus 15
    días rebotaba con el mismo 403 que una cuenta sin plan, y como el checkout
    vive detrás del agente, no tenía por dónde salir.
    """
    return bool(
        lic.get("plan") in PLANES_CON_ACCESO
        or lic.get("is_founder")
        or lic.get("premium_features_unlocked")
    )


def _validar_licencia(access_token: str, email: Optional[str]) -> None:
    """403 si la cuenta no tiene plan que dé acceso a la versión web."""
    if email and email.lower() in ALLOWLIST_EMAILS:
        return
    if not EXIGIR_LICENCIA:
        return
    try:
        resp = requests.get(
            LICENCIA_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="No pudimos validar tu plan. Intenta más tarde.")
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="La sesión no es válida. Vuelve a iniciar sesión.")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="No pudimos validar tu plan. Intenta más tarde.")
    if not _plan_da_acceso(resp.json()):
        raise HTTPException(
            status_code=403,
            detail=(
                "Tu prueba de TodoConta terminó o tu plan no está activo. "
                "Actívalo en todoconta.com/planes y vuelve a entrar."
            ),
        )


# ---------------------------------------------------------------------------
# Docker: asegurar el contenedor del usuario
# ---------------------------------------------------------------------------

_docker_lock = threading.Lock()


def _docker():
    import docker

    return docker.from_env()


def _labels_traefik(slug: str) -> dict:
    r = f"agente-{slug}"
    return {
        "traefik.enable": "true",
        f"traefik.http.routers.{r}.rule": f"Host(`{DOMINIO}`) && PathPrefix(`/u/{slug}`)",
        f"traefik.http.routers.{r}.entrypoints": "websecure",
        f"traefik.http.routers.{r}.tls.certresolver": "letsencrypt",
        f"traefik.http.middlewares.{r}-strip.stripprefix.prefixes": f"/u/{slug}",
        f"traefik.http.routers.{r}.middlewares": f"{r}-strip",
        f"traefik.http.services.{r}.loadbalancer.server.port": "8787",
        "traefik.docker.network": RED_AGENTES,
        # Marca propia para poder listar/administrar los agentes.
        "todoconta.agente": "1",
    }


def _asegurar_agente(user_id: str) -> dict:
    """Crea (o arranca) el contenedor del usuario. Devuelve la derivación."""
    import docker as docker_sdk

    d = _derivar(user_id)
    slug = d["slug"]
    nombre = f"agente-{slug}"

    with _docker_lock:
        cli = _docker()
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
                    "SAT_DM_CORS_ORIGINS": ",".join(CORS_WEB),
                },
                labels=_labels_traefik(slug),
                log_config={"type": "json-file", "config": {"max-size": "10m", "max-file": "3"}},
            )
            logger.info("contenedor %s creado", nombre)

    # Esperar a que el agente responda (primer arranque tarda unos segundos).
    # El provisioner comparte la red `agentes`: resuelve por nombre de contenedor.
    limite = time.monotonic() + 45
    url = f"http://{nombre}:8787/health?token={d['token']}"
    while time.monotonic() < limite:
        try:
            if requests.get(url, timeout=3).status_code == 200:
                return d
        except requests.RequestException:
            pass
        time.sleep(1.5)
    raise HTTPException(
        status_code=503,
        detail="Tu espacio está arrancando; intenta de nuevo en unos segundos.",
    )


# ---------------------------------------------------------------------------
# Registro (bookkeeping, no estado crítico)
# ---------------------------------------------------------------------------

_registro_lock = threading.Lock()


def _registrar_login(user_id: str, email: Optional[str], slug: str) -> None:
    try:
        with _registro_lock:
            datos = {}
            if REGISTRO_PATH.exists():
                try:
                    datos = json.loads(REGISTRO_PATH.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    datos = {}
            ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
            entrada = datos.get(user_id) or {"creado_en": ahora}
            entrada.update({"email": email, "slug": slug, "ultimo_login": ahora})
            datos[user_id] = entrada
            REGISTRO_PATH.parent.mkdir(parents=True, exist_ok=True)
            REGISTRO_PATH.write_text(
                json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            os.chmod(REGISTRO_PATH, 0o600)
    except OSError:
        logger.warning("no se pudo escribir registry.json", exc_info=True)


# ---------------------------------------------------------------------------
# Rate limit simple (en memoria, por IP)
# ---------------------------------------------------------------------------

_intentos: dict = {}
_intentos_lock = threading.Lock()
_RATE_MAX = 8
_RATE_VENTANA_S = 300


def _rate_limit(request: Request) -> None:
    ip = (request.client.host if request.client else "?") or "?"
    ahora = time.monotonic()
    with _intentos_lock:
        marcas = [t for t in _intentos.get(ip, []) if ahora - t < _RATE_VENTANA_S]
        if len(marcas) >= _RATE_MAX:
            raise HTTPException(
                status_code=429,
                detail="Demasiados intentos. Espera unos minutos y vuelve a intentar.",
            )
        marcas.append(ahora)
        _intentos[ip] = marcas


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="TodoConta — Provisioner", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_WEB,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginPasswordRequest(BaseModel):
    email: str
    password: str


class OtpSendRequest(BaseModel):
    email: str


class OtpVerifyRequest(BaseModel):
    email: str
    token: str


class ConTokenRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None


def _aprovisionar(sesion: dict) -> dict:
    """Valida licencia + asegura contenedor. Devuelve el payload para la UI."""
    user_id = sesion["user_id"]
    if not user_id:
        raise HTTPException(status_code=401, detail="La sesión no es válida.")
    _validar_licencia(sesion["access_token"], sesion.get("email"))
    d = _asegurar_agente(user_id)
    _registrar_login(user_id, sesion.get("email"), d["slug"])
    return {
        "base_url": f"{PUBLIC_BASE}/u/{d['slug']}",
        "token": d["token"],
        "session": sesion,
    }


@app.get("/provision/health")
def health():
    return {"status": "ok", "servicio": "provisioner"}


@app.post("/provision/login-password")
def login_password(req: LoginPasswordRequest, request: Request):
    _rate_limit(request)
    data = _gotrue_post(
        "/token",
        {"email": req.email.strip(), "password": req.password},
        params={"grant_type": "password"},
    )
    return _aprovisionar(_sesion_de(data))


@app.post("/provision/otp-send")
def otp_send(req: OtpSendRequest, request: Request):
    _rate_limit(request)
    # create_user=False: la web no registra cuentas nuevas (el provisioner
    # exigiría plan de todas formas); el registro vive en la desktop.
    _gotrue_post("/otp", {"email": req.email.strip(), "create_user": False})
    return {"ok": True}


@app.post("/provision/otp-verify")
def otp_verify(req: OtpVerifyRequest, request: Request):
    _rate_limit(request)
    data = _gotrue_post(
        "/verify",
        {"type": "email", "email": req.email.strip(), "token": req.token.strip()},
    )
    return _aprovisionar(_sesion_de(data))


@app.post("/provision/con-token")
def con_token(req: ConTokenRequest, request: Request):
    """OAuth (Google) y magic links: tokens ya emitidos por Supabase."""
    _rate_limit(request)
    user = _gotrue_user(req.access_token.strip())
    sesion = {
        "access_token": req.access_token.strip(),
        "refresh_token": req.refresh_token,
        "user_id": user.get("id", ""),
        "email": user.get("email"),
    }
    return _aprovisionar(sesion)

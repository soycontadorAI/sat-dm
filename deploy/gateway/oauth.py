"""
OAuth 2.1 del gateway — el authorization server que piden los conectores MCP.

Los conectores de claude.ai (web/Work) y ChatGPT NO aceptan headers custom:
descubren este servidor vía RFC 9728/8414, se registran solos (RFC 7591),
mandan al usuario a /oauth/authorize (login TodoConta contra GoTrue + pantalla
de consentimiento) y canjean el code con PKCE en /oauth/token. El middleware
de /mcp (main.py) acepta el access token resultante ADEMÁS de la API key
`tc_…` de siempre.

Almacenamiento: SQLite en el volumen del gateway (/data/oauth.db) — tablas
clients/codes/tokens; de los tokens y codes solo se guarda el hash SHA-256.
Login GoTrue y validación de licencia: mismas llamadas que
deploy/provisioner/main.py (el gateway es una unidad de deploy autónoma, por
eso se replican aquí en vez de importarse).
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlparse

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

logger = logging.getLogger("gateway")

# ---------------------------------------------------------------------------
# Config (mismos defaults que el provisioner)
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
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://agente.todoconta.com").rstrip("/")
LICENCIA_URL = os.environ.get(
    "LICENCIA_URL", "https://api.todoconta.com/api/desktop/license"
)
EXIGIR_LICENCIA = os.environ.get("EXIGIR_LICENCIA", "1") != "0"
ALLOWLIST_EMAILS = {
    e.strip().lower()
    for e in os.environ.get("ALLOWLIST_EMAILS", "").split(",")
    if e.strip()
}
DB_PATH = Path(os.environ.get("OAUTH_DB_PATH", "/data/oauth.db"))

_TIMEOUT = 15
CODE_TTL_S = 300            # el code es one-shot y de vida corta
ACCESS_TTL_S = 3600
REFRESH_TTL_S = 90 * 24 * 3600
SCOPE = "mcp"

# ---------------------------------------------------------------------------
# Store (SQLite, un solo proceso uvicorn; lock para los hilos del pool)
# ---------------------------------------------------------------------------

_db_lock = threading.Lock()
_db: Optional[sqlite3.Connection] = None


def _conexion() -> sqlite3.Connection:
    global _db
    if _db is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(DB_PATH, check_same_thread=False)
        _db.execute("PRAGMA journal_mode=WAL")
        _db.executescript(
            """
            CREATE TABLE IF NOT EXISTS clients (
                client_id TEXT PRIMARY KEY,
                client_name TEXT,
                redirect_uris TEXT NOT NULL,
                creado_en INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS codes (
                code_hash TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                code_challenge TEXT NOT NULL,
                user_id TEXT NOT NULL,
                email TEXT,
                familia TEXT NOT NULL,
                expira INTEGER NOT NULL,
                usado INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS tokens (
                token_hash TEXT PRIMARY KEY,
                tipo TEXT NOT NULL,
                client_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                email TEXT,
                familia TEXT NOT NULL,
                expira INTEGER NOT NULL,
                revocado INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        _db.commit()
    return _db


def _hash(valor: str) -> str:
    return hashlib.sha256(valor.encode()).hexdigest()


def _limpiar(db: sqlite3.Connection) -> None:
    """Borra codes/tokens ya inservibles (expirados hace más de un día)."""
    corte = int(time.time()) - 24 * 3600
    db.execute("DELETE FROM codes WHERE expira < ?", (corte,))
    db.execute("DELETE FROM tokens WHERE expira < ?", (corte,))


# ---------------------------------------------------------------------------
# Rate limit por IP (detrás de Traefik: primer salto de X-Forwarded-For)
# ---------------------------------------------------------------------------

_rate: dict = {}
_rate_lock = threading.Lock()


def _ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _limitar(request: Request, cubeta: str, maximo: int, ventana_s: int) -> None:
    clave = f"{cubeta}:{_ip(request)}"
    ahora = time.monotonic()
    with _rate_lock:
        marcas = [t for t in _rate.get(clave, []) if ahora - t < ventana_s]
        if len(marcas) >= maximo:
            raise HTTPException(
                status_code=429, detail="Demasiados intentos. Espera unos minutos."
            )
        marcas.append(ahora)
        _rate[clave] = marcas


# ---------------------------------------------------------------------------
# GoTrue + licencia (espejo de deploy/provisioner/main.py)
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


# Mismos planes que abre el provisioner (deploy/provisioner/main.py). Los
# calcula `getDesktopLicense` en todoconta-apps: free | trial | premium | founder.
PLANES_CON_ACCESO = ("trial", "premium", "founder")


def _plan_da_acceso(lic: dict) -> bool:
    """True si la licencia de /api/desktop/license abre el espacio del usuario.

    Ese endpoint expone `plan`, `is_founder` y `premium_features_unlocked` —
    NO `subscription_active` ni `subscription_status`, que es lo que se miraba
    antes: la rama del trial nunca se cumplía.
    """
    return bool(
        lic.get("plan") in PLANES_CON_ACCESO
        or lic.get("is_founder")
        or lic.get("premium_features_unlocked")
    )


def _validar_licencia(access_token: str, email: Optional[str]) -> None:
    """Mismo criterio que el provisioner: sin plan vigente no se abre espacio."""
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
                "Actívalo en todoconta.com/planes y vuelve a intentar."
            ),
        )


def _autenticar(email: str, password: str, otp: str) -> dict:
    """Login contra GoTrue (password u OTP) → {user_id, email, access_token}."""
    email = email.strip()
    if not email:
        raise HTTPException(status_code=400, detail="Escribe tu correo.")
    if otp.strip():
        data = _gotrue_post(
            "/verify", {"type": "email", "email": email, "token": otp.strip()}
        )
    elif password:
        data = _gotrue_post(
            "/token", {"email": email, "password": password}, params={"grant_type": "password"}
        )
    else:
        raise HTTPException(status_code=400, detail="Pide un código a tu correo y escríbelo aquí (o entra con tu contraseña).")
    user = data.get("user") or {}
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="La sesión no es válida. Intenta de nuevo.")
    return {
        "user_id": user["id"],
        "email": user.get("email"),
        "access_token": data["access_token"],
    }


# ---------------------------------------------------------------------------
# Metadata de descubrimiento (RFC 9728 + RFC 8414)
# ---------------------------------------------------------------------------

router = APIRouter(include_in_schema=False)


def _metadata_recurso() -> dict:
    return {
        "resource": f"{PUBLIC_BASE}/mcp",
        "authorization_servers": [PUBLIC_BASE],
        "bearer_methods_supported": ["header"],
        "scopes_supported": [SCOPE],
        "resource_name": "TodoConta MCP",
        "resource_documentation": "https://todoconta.com/mcp",
    }


def _metadata_as() -> dict:
    return {
        "issuer": PUBLIC_BASE,
        "authorization_endpoint": f"{PUBLIC_BASE}/oauth/authorize",
        "token_endpoint": f"{PUBLIC_BASE}/oauth/token",
        "registration_endpoint": f"{PUBLIC_BASE}/oauth/register",
        "revocation_endpoint": f"{PUBLIC_BASE}/oauth/revoke",
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": [SCOPE],
        "service_documentation": "https://todoconta.com/mcp",
    }


# Los clientes arman la URL well-known con y sin el path del recurso (/mcp);
# se responden ambas variantes para no depender de cuál pruebe cada conector.
@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def well_known_recurso():
    return _metadata_recurso()


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
@router.get("/.well-known/openid-configuration")
@router.get("/.well-known/openid-configuration/mcp")
def well_known_as():
    return _metadata_as()


# ---------------------------------------------------------------------------
# Dynamic Client Registration (RFC 7591) — claude.ai lo exige
# ---------------------------------------------------------------------------


def _redirect_valida(uri: str) -> bool:
    try:
        p = urlparse(uri)
    except ValueError:
        return False
    if p.scheme == "https" and p.netloc:
        return True
    # http solo para clientes locales (MCP Inspector, desarrollo).
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")


@router.post("/oauth/register", status_code=201)
async def oauth_register(request: Request):
    _limitar(request, "register", 60, 3600)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    uris = body.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or len(uris) > 10:
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_redirect_uri",
                "error_description": "Manda redirect_uris (lista de 1 a 10 URLs).",
            },
        )
    uris = [str(u) for u in uris]
    if not all(_redirect_valida(u) for u in uris):
        return JSONResponse(
            status_code=400,
            content={
                "error": "invalid_redirect_uri",
                "error_description": "Las redirect_uris deben ser https (o http en localhost).",
            },
        )
    client_id = "tcc_" + secrets.token_urlsafe(24)
    nombre = str(body.get("client_name") or "")[:100]
    ahora = int(time.time())
    with _db_lock:
        db = _conexion()
        db.execute(
            "INSERT INTO clients (client_id, client_name, redirect_uris, creado_en) VALUES (?,?,?,?)",
            (client_id, nombre, json.dumps(uris), ahora),
        )
        db.commit()
    logger.info("oauth cliente registrado %s (%s)", client_id, nombre or "sin nombre")
    return {
        "client_id": client_id,
        "client_id_issued_at": ahora,
        "client_name": nombre,
        "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": SCOPE,
    }


def _cliente(client_id: str) -> Optional[dict]:
    with _db_lock:
        fila = _conexion().execute(
            "SELECT client_name, redirect_uris FROM clients WHERE client_id = ?",
            (client_id,),
        ).fetchone()
    if not fila:
        return None
    return {"client_name": fila[0] or "", "redirect_uris": json.loads(fila[1])}


# ---------------------------------------------------------------------------
# /oauth/authorize — login TodoConta + consentimiento
# ---------------------------------------------------------------------------

_PAGINA = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autorizar acceso — TodoConta</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; margin: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f4f5f7; color: #1c1c1e; min-height: 100vh;
    display: flex; align-items: center; justify-content: center; padding: 24px;
  }
  .tarjeta {
    background: #fff; border: 1px solid #e3e4e8; border-radius: 14px;
    max-width: 420px; width: 100%; padding: 32px 28px;
    box-shadow: 0 8px 30px rgba(20, 20, 40, .06);
  }
  .marca { font-weight: 700; font-size: 15px; letter-spacing: -.2px; color: #4f46e5; margin-bottom: 18px; }
  h1 { font-size: 19px; letter-spacing: -.3px; margin-bottom: 6px; }
  .sub { color: #6b6b70; font-size: 13.5px; margin-bottom: 18px; }
  .permisos { background: #f7f7fa; border: 1px solid #ececf1; border-radius: 10px; padding: 14px 16px; margin-bottom: 18px; }
  .permisos p { font-size: 12.5px; font-weight: 600; color: #4b4b52; margin-bottom: 8px; }
  .permisos ul { padding-left: 18px; font-size: 12.5px; color: #55555c; line-height: 1.55; }
  .permisos .nota { margin-top: 10px; margin-bottom: 0; font-weight: 600; color: #15803d; font-size: 12px; }
  label { display: block; font-size: 12.5px; font-weight: 600; color: #4b4b52; margin: 12px 0 5px; }
  input[type=email], input[type=password], input[type=text] {
    width: 100%; padding: 9px 11px; font-size: 14px;
    border: 1px solid #d6d7de; border-radius: 8px; outline: none;
  }
  input:focus { border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79, 70, 229, .12); }
  .error { background: #fef2f2; border: 1px solid #fecaca; color: #b91c1c; border-radius: 8px; padding: 10px 12px; font-size: 13px; margin-bottom: 4px; }
  .aviso { background: #f0fdf4; border: 1px solid #bbf7d0; color: #15803d; border-radius: 8px; padding: 10px 12px; font-size: 13px; margin-bottom: 4px; }
  button {
    width: 100%; margin-top: 18px; padding: 11px; font-size: 14.5px; font-weight: 600;
    color: #fff; background: #4f46e5; border: 0; border-radius: 8px; cursor: pointer;
  }
  button:hover { background: #4338ca; }
  button.secundario { background: #fff; color: #4f46e5; border: 1px solid #c7c8f4; margin-top: 10px; }
  button.secundario:hover { background: #f5f5ff; }
  .alterno { display: block; text-align: center; margin-top: 14px; font-size: 13px; color: #4f46e5; cursor: pointer; text-decoration: none; }
  .pie { margin-top: 18px; font-size: 11.5px; color: #9a9aa0; text-align: center; line-height: 1.5; }
  .oculto { display: none; }
</style>
</head>
<body>
<main class="tarjeta">
  <div class="marca">TodoConta</div>
  <h1>Conectar «__CLIENTE__»</h1>
  <p class="sub">Inicia sesión con tu cuenta de TodoConta para autorizar la conexión.</p>
  <div class="permisos">
    <p>Si autorizas, este asistente podrá, en tu nombre:</p>
    <ul>
      <li>Ver tu catálogo de empresas (RFC y nombre)</li>
      <li>Descargar la Constancia de Situación Fiscal y la Opinión 32-D</li>
      <li>Solicitar, procesar y resumir tus CFDIs</li>
      <li>Consultar RFCs en las listas negras 69 y 69-B</li>
      <li>Usar las calculadoras fiscales y laborales</li>
    </ul>
    <p class="nota">Nunca verá tus contraseñas, tu CIEC ni tu e.firma.</p>
  </div>
  __MENSAJE__
  <form method="post" action="/oauth/authorize" id="form">
    __CAMPOS__
    <label for="email">Correo</label>
    <input type="email" name="email" id="email" value="__EMAIL__" required autocomplete="email">
    <div id="zona-password" class="oculto">
      <label for="password">Contraseña</label>
      <input type="password" name="password" id="password" autocomplete="current-password">
    </div>
    <div id="zona-otp">
      <button type="button" class="secundario" id="btn-enviar">Enviar código a mi correo</button>
      <label for="otp">Código (te lo enviamos por correo)</label>
      <input type="text" name="otp" id="otp" inputmode="numeric" autocomplete="one-time-code">
    </div>
    <button type="submit">Autorizar</button>
    <a class="alterno" id="alternar">Prefiero entrar con un código a mi correo</a>
  </form>
  <p class="pie">Solo autoriza asistentes en los que confíes. Puedes revocar el acceso
  desconectando el conector desde tu asistente.</p>
</main>
<script>
  var conOtp = __CON_OTP__;
  var zp = document.getElementById("zona-password");
  var zo = document.getElementById("zona-otp");
  var alt = document.getElementById("alternar");
  function pintar() {
    zp.classList.toggle("oculto", conOtp);
    zo.classList.toggle("oculto", !conOtp);
    alt.textContent = conOtp ? "Prefiero entrar con mi contraseña"
                             : "Prefiero entrar con un código a mi correo";
    if (conOtp) { document.getElementById("password").value = ""; }
    else { document.getElementById("otp").value = ""; }
  }
  alt.addEventListener("click", function () { conOtp = !conOtp; pintar(); });
  document.getElementById("btn-enviar").addEventListener("click", function () {
    var email = document.getElementById("email").value.trim();
    if (!email) { alert("Escribe tu correo primero."); return; }
    var btn = this;
    btn.disabled = true; btn.textContent = "Enviando…";
    fetch("/oauth/otp-send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email }),
    }).then(function (r) { return r.json().catch(function () { return {}; }).then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        btn.disabled = false;
        btn.textContent = res.ok ? "Código enviado — revisa tu correo" : "Enviar código a mi correo";
        if (!res.ok) { alert(res.d.detail || "No se pudo enviar el código."); }
      })
      .catch(function () { btn.disabled = false; btn.textContent = "Enviar código a mi correo"; });
  });
  pintar();
</script>
</body>
</html>
"""


# OTP-first: el código al correo es el camino default (igual que el login de
# la app) — sirve tal cual a quien entró con Google (no tiene contraseña,
# pero el código a su correo le llega igual); la contraseña queda como
# alternativa detrás del link.
def _pagina(params: dict, mensaje: str = "", con_otp: bool = True, email: str = "",
            cliente_nombre: str = "", status: int = 200) -> HTMLResponse:
    campos = "".join(
        f'<input type="hidden" name="{html.escape(k, quote=True)}" value="{html.escape(v, quote=True)}">'
        for k, v in params.items()
        if v
    )
    cuerpo = (
        _PAGINA
        .replace("__CLIENTE__", html.escape(cliente_nombre or "tu asistente"))
        .replace("__MENSAJE__", f'<div class="error">{html.escape(mensaje)}</div>' if mensaje else "")
        .replace("__CAMPOS__", campos)
        .replace("__EMAIL__", html.escape(email, quote=True))
        .replace("__CON_OTP__", "true" if con_otp else "false")
    )
    return HTMLResponse(cuerpo, status_code=status)


def _pagina_error(titulo: str) -> HTMLResponse:
    # Para peticiones malformadas (cliente/redirect desconocidos) NUNCA se
    # redirige: se corta aquí con un aviso.
    cuerpo = (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<title>Solicitud inválida — TodoConta</title></head>"
        "<body style='font-family:sans-serif;padding:40px;max-width:560px;margin:auto'>"
        "<h1 style='font-size:20px'>Solicitud inválida</h1>"
        f"<p style='color:#555'>{html.escape(titulo)}</p>"
        "<p style='color:#999;font-size:13px'>Cierra esta pestaña y vuelve a intentar la conexión desde tu asistente.</p>"
        "</body></html>"
    )
    return HTMLResponse(cuerpo, status_code=400)


def _redirigir_error(redirect_uri: str, error: str, descripcion: str, state: str) -> RedirectResponse:
    q = {"error": error, "error_description": descripcion}
    if state:
        q["state"] = state
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(q)}", status_code=302)


def _validar_authorize(q: dict) -> tuple[Optional[dict], Optional[Response]]:
    """Valida los parámetros OAuth. Devuelve (contexto, None) o (None, respuesta de error)."""
    client_id = (q.get("client_id") or "").strip()
    redirect_uri = (q.get("redirect_uri") or "").strip()
    cliente = _cliente(client_id) if client_id else None
    if not cliente:
        return None, _pagina_error("El cliente no está registrado (client_id desconocido).")
    if not redirect_uri and len(cliente["redirect_uris"]) == 1:
        redirect_uri = cliente["redirect_uris"][0]
    if redirect_uri not in cliente["redirect_uris"]:
        return None, _pagina_error("La URL de retorno no coincide con la registrada por el cliente.")

    state = q.get("state") or ""
    if (q.get("response_type") or "") != "code":
        return None, _redirigir_error(redirect_uri, "unsupported_response_type",
                                      "Solo se soporta response_type=code.", state)
    challenge = (q.get("code_challenge") or "").strip()
    metodo = q.get("code_challenge_method") or ""
    if not challenge or metodo != "S256":
        return None, _redirigir_error(redirect_uri, "invalid_request",
                                      "PKCE S256 es obligatorio (code_challenge + code_challenge_method=S256).", state)
    recurso = (q.get("resource") or "").strip().rstrip("/")
    if recurso and recurso not in (PUBLIC_BASE, f"{PUBLIC_BASE}/mcp"):
        return None, _redirigir_error(redirect_uri, "invalid_target",
                                      f"Este servidor solo emite tokens para {PUBLIC_BASE}/mcp.", state)
    return {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "cliente_nombre": cliente["client_name"],
    }, None


@router.get("/oauth/authorize")
def oauth_authorize(request: Request):
    _limitar(request, "authorize", 60, 300)
    ctx, error = _validar_authorize(dict(request.query_params))
    if error is not None:
        return error
    return _pagina(
        {
            "response_type": "code",
            "client_id": ctx["client_id"],
            "redirect_uri": ctx["redirect_uri"],
            "state": ctx["state"],
            "code_challenge": ctx["code_challenge"],
            "code_challenge_method": "S256",
            "resource": request.query_params.get("resource") or "",
        },
        cliente_nombre=ctx["cliente_nombre"],
    )


@router.post("/oauth/otp-send")
async def oauth_otp_send(request: Request):
    _limitar(request, "otp", 5, 900)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    email = str(body.get("email") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Escribe tu correo.")
    # create_user=False: aquí no se registran cuentas nuevas.
    _gotrue_post("/otp", {"email": email, "create_user": False})
    return {"ok": True}


@router.post("/oauth/authorize")
async def oauth_authorize_decision(request: Request):
    _limitar(request, "login", 10, 300)
    form = dict(await request.form())
    ctx, error = _validar_authorize(form)
    if error is not None:
        return error

    email = str(form.get("email") or "")
    otp = str(form.get("otp") or "")
    ocultos = {
        "response_type": "code",
        "client_id": ctx["client_id"],
        "redirect_uri": ctx["redirect_uri"],
        "state": ctx["state"],
        "code_challenge": ctx["code_challenge"],
        "code_challenge_method": "S256",
        "resource": str(form.get("resource") or ""),
    }
    password = str(form.get("password") or "")
    try:
        sesion = _autenticar(email, password, otp)
        _validar_licencia(sesion["access_token"], sesion.get("email"))
    except HTTPException as exc:
        # Re-render en el modo que el usuario estaba usando (password solo si
        # la escribió; si no, el default OTP).
        return _pagina(ocultos, mensaje=str(exc.detail), con_otp=not password,
                       email=email, cliente_nombre=ctx["cliente_nombre"],
                       status=exc.status_code if exc.status_code < 500 else 502)

    code = "mcp_ac_" + secrets.token_urlsafe(32)
    with _db_lock:
        db = _conexion()
        _limpiar(db)
        db.execute(
            "INSERT INTO codes (code_hash, client_id, redirect_uri, code_challenge, user_id, email, familia, expira)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                _hash(code),
                ctx["client_id"],
                ctx["redirect_uri"],
                ctx["code_challenge"],
                sesion["user_id"],
                sesion.get("email"),
                secrets.token_hex(8),
                int(time.time()) + CODE_TTL_S,
            ),
        )
        db.commit()
    logger.info("oauth code emitido para user=%s cliente=%s", sesion["user_id"], ctx["client_id"])
    q = {"code": code}
    if ctx["state"]:
        q["state"] = ctx["state"]
    sep = "&" if "?" in ctx["redirect_uri"] else "?"
    return RedirectResponse(f"{ctx['redirect_uri']}{sep}{urlencode(q)}", status_code=303)


# ---------------------------------------------------------------------------
# /oauth/token — canje del code (PKCE) + refresh rotativo
# ---------------------------------------------------------------------------


def _json_error(error: str, descripcion: str, status: int = 400) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": error, "error_description": descripcion},
        headers={"Cache-Control": "no-store"},
    )


def _emitir_tokens(client_id: str, user_id: str, email: Optional[str], familia: str) -> JSONResponse:
    access = "mcp_at_" + secrets.token_urlsafe(32)
    refresh = "mcp_rt_" + secrets.token_urlsafe(32)
    ahora = int(time.time())
    with _db_lock:
        db = _conexion()
        _limpiar(db)
        db.executemany(
            "INSERT INTO tokens (token_hash, tipo, client_id, user_id, email, familia, expira) VALUES (?,?,?,?,?,?,?)",
            [
                (_hash(access), "access", client_id, user_id, email, familia, ahora + ACCESS_TTL_S),
                (_hash(refresh), "refresh", client_id, user_id, email, familia, ahora + REFRESH_TTL_S),
            ],
        )
        db.commit()
    return JSONResponse(
        content={
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL_S,
            "refresh_token": refresh,
            "scope": SCOPE,
        },
        headers={"Cache-Control": "no-store"},
    )


def _revocar_familia(db: sqlite3.Connection, familia: str) -> None:
    db.execute("UPDATE tokens SET revocado = 1 WHERE familia = ?", (familia,))


def _canjear_code(datos: dict) -> JSONResponse:
    code = str(datos.get("code") or "")
    verifier = str(datos.get("code_verifier") or "")
    if not code:
        return _json_error("invalid_request", "Falta el parámetro code.")
    if not (43 <= len(verifier) <= 128):
        return _json_error("invalid_request", "Falta o es inválido el code_verifier (PKCE).")
    with _db_lock:
        db = _conexion()
        fila = db.execute(
            "SELECT client_id, redirect_uri, code_challenge, user_id, email, familia, expira, usado"
            " FROM codes WHERE code_hash = ?",
            (_hash(code),),
        ).fetchone()
        if not fila:
            return _json_error("invalid_grant", "El código no existe o ya expiró.")
        client_id, redirect_uri, challenge, user_id, email, familia, expira, usado = fila
        if usado:
            # Replay del code: se revoca todo lo emitido a partir de él.
            _revocar_familia(db, familia)
            db.commit()
            return _json_error("invalid_grant", "El código ya fue usado; se revocó la autorización.")
        if expira < int(time.time()):
            return _json_error("invalid_grant", "El código expiró; vuelve a autorizar.")
        db.execute("UPDATE codes SET usado = 1 WHERE code_hash = ?", (_hash(code),))
        db.commit()
    if datos.get("client_id") and str(datos["client_id"]) != client_id:
        return _json_error("invalid_grant", "El client_id no corresponde al código.")
    if datos.get("redirect_uri") and str(datos["redirect_uri"]) != redirect_uri:
        return _json_error("invalid_grant", "La redirect_uri no corresponde al código.")
    esperado = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    if not secrets.compare_digest(esperado, challenge):
        return _json_error("invalid_grant", "El code_verifier no corresponde al code_challenge.")
    logger.info("oauth tokens emitidos para user=%s cliente=%s", user_id, client_id)
    return _emitir_tokens(client_id, user_id, email, familia)


def _refrescar(datos: dict) -> JSONResponse:
    refresh = str(datos.get("refresh_token") or "")
    if not refresh:
        return _json_error("invalid_request", "Falta el refresh_token.")
    ahora = int(time.time())
    with _db_lock:
        db = _conexion()
        fila = db.execute(
            "SELECT client_id, user_id, email, familia, expira, revocado FROM tokens"
            " WHERE token_hash = ? AND tipo = 'refresh'",
            (_hash(refresh),),
        ).fetchone()
        if not fila:
            return _json_error("invalid_grant", "El refresh_token no existe o ya expiró.")
        client_id, user_id, email, familia, expira, revocado = fila
        if revocado:
            # Rotación: un refresh viejo reutilizado delata robo → fuera toda la familia.
            _revocar_familia(db, familia)
            db.commit()
            return _json_error("invalid_grant", "El refresh_token fue rotado; se revocó la autorización.")
        if expira < ahora:
            return _json_error("invalid_grant", "El refresh_token expiró; vuelve a autorizar.")
        db.execute("UPDATE tokens SET revocado = 1 WHERE token_hash = ?", (_hash(refresh),))
        db.commit()
    if datos.get("client_id") and str(datos["client_id"]) != client_id:
        return _json_error("invalid_grant", "El client_id no corresponde al refresh_token.")
    return _emitir_tokens(client_id, user_id, email, familia)


async def _datos_token(request: Request) -> dict:
    # El estándar manda form-urlencoded; se acepta JSON por liberalidad.
    ctype = request.headers.get("content-type", "")
    if "json" in ctype:
        try:
            return dict(await request.json())
        except Exception:  # noqa: BLE001
            return {}
    try:
        return dict(await request.form())
    except Exception:  # noqa: BLE001
        return {}


@router.post("/oauth/token")
async def oauth_token(request: Request):
    _limitar(request, "token", 240, 300)
    datos = await _datos_token(request)
    grant = str(datos.get("grant_type") or "")
    if grant == "authorization_code":
        return _canjear_code(datos)
    if grant == "refresh_token":
        return _refrescar(datos)
    return _json_error("unsupported_grant_type", "Usa authorization_code o refresh_token.")


@router.post("/oauth/revoke")
async def oauth_revoke(request: Request):
    """RFC 7009: el conector avisa al desconectarse. Siempre responde 200."""
    _limitar(request, "token", 240, 300)
    datos = await _datos_token(request)
    token = str(datos.get("token") or "")
    if token:
        with _db_lock:
            db = _conexion()
            fila = db.execute(
                "SELECT familia FROM tokens WHERE token_hash = ?", (_hash(token),)
            ).fetchone()
            if fila:
                _revocar_familia(db, fila[0])
                db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Validación del access token (la usa el middleware de /mcp en main.py)
# ---------------------------------------------------------------------------


def validar_access_token(token: str) -> dict:
    """Devuelve {user_id, scopes, email} o lanza HTTPException 401."""
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Autenticación requerida: API key (X-Api-Key) o token OAuth (Authorization: Bearer).",
        )
    with _db_lock:
        fila = _conexion().execute(
            "SELECT user_id, email, expira, revocado FROM tokens"
            " WHERE token_hash = ? AND tipo = 'access'",
            (_hash(token),),
        ).fetchone()
    if not fila or fila[3] or fila[2] < int(time.time()):
        raise HTTPException(status_code=401, detail="El token no es válido o ya expiró.")
    return {"user_id": fila[0], "scopes": [SCOPE], "email": fila[1]}


# ---------------------------------------------------------------------------
# CORS solo para descubrimiento y OAuth (clientes MCP de navegador, Inspector)
# ---------------------------------------------------------------------------

_CORS_PREFIJOS = ("/oauth", "/.well-known")
_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type, Mcp-Protocol-Version",
    "Access-Control-Max-Age": "3600",
}


async def middleware_cors(request: Request, call_next):
    if not request.url.path.startswith(_CORS_PREFIJOS):
        return await call_next(request)
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=_CORS_HEADERS)
    response = await call_next(request)
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    return response

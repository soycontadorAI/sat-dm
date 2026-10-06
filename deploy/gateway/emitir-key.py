#!/usr/bin/env python3
"""
Emite una API key de TodoConta (v1: manual, corre donde haya el service key).

    python3 emitir-key.py --email usuario@x.mx --nombre "Sistema de Facturación" \
        [--scopes documentos:leer,cfdi:solicitar,listas-negras:consultar,mcp] \
        [--whatsapp +5215512345678]

Imprime la key COMPLETA una sola vez (solo el hash queda en Supabase).

Con `--whatsapp` además vincula el número al usuario en `asistente_vinculos`
(la consume el plugin abacus-todoconta de OpenClaw): la key viaja cifrada con
AES-256-GCM para que el bot pueda usarla sin que Supabase la conozca en claro.
Formato guardado: base64( nonce(12) || ciphertext || tag(16) ).

Env requeridas: TODOCONTA_SUPABASE_URL, SUPABASE_SERVICE_KEY.
Con --whatsapp: ASISTENTE_VINCULOS_KEY (32 bytes en base64; la misma que
descifra el plugin en el VPS) y el paquete `cryptography`.

Plan del dueño (F1): con LICENCIA_GATEWAY_SECRET (secreto del gateway para GET /api/admin/license
en todoconta-apps) revisa las capacidades antes de emitir. Vincular Abacus exige
`capacidades.abacus` (se puede saltar con --forzar); un scope que el plan no
incluye solo avisa, porque el gateway lo rechaza con CAPACIDADES_MODO=exigir.
Sin el token, avisa y sigue como antes.
"""

import argparse
import base64
import hashlib
import os
import re
import secrets
import sys

import requests

SCOPES_DEFAULT = "documentos:leer,cfdi:solicitar,listas-negras:consultar,mcp"
# Scopes que necesita Abacus (sin `mcp`: el plugin usa REST, no el conector).
SCOPES_ABACUS = "documentos:leer,cfdi:solicitar,listas-negras:consultar"
WHATSAPP_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
SCOPES_REST = {"documentos:leer", "cfdi:solicitar", "listas-negras:consultar"}


def _capacidades(user_id: str):
    """Capacidades del plan del usuario según la API de servicios, o None."""
    token = os.environ.get("LICENCIA_GATEWAY_SECRET", "")
    if not token:
        print("Aviso: sin LICENCIA_GATEWAY_SECRET no se revisa el plan del usuario.", file=sys.stderr)
        return None
    url = os.environ.get("LICENCIA_ADMIN_URL", "https://api.todoconta.com/api/admin/license")
    try:
        r = requests.get(url, params={"user_id": user_id},
                         headers={"Authorization": f"Bearer {token}"}, timeout=20)
    except requests.RequestException as e:
        print(f"Aviso: no se pudo leer el plan ({e}); se sigue sin revisarlo.", file=sys.stderr)
        return None
    lic = (r.json() or {}).get("license") if r.status_code == 200 else None
    if not isinstance(lic, dict) or not isinstance(lic.get("capacidades"), dict):
        print(f"Aviso: la licencia no trae capacidades (HTTP {r.status_code}); se sigue.", file=sys.stderr)
        return None
    return lic


def _cifrar_key(key: str) -> str:
    """Cifra la API key con AES-256-GCM (ASISTENTE_VINCULOS_KEY, base64)."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("Falta el paquete `cryptography` (pip install cryptography).", file=sys.stderr)
        raise SystemExit(1)

    raw = os.environ.get("ASISTENTE_VINCULOS_KEY", "")
    if not raw:
        print("Falta ASISTENTE_VINCULOS_KEY (32 bytes base64) para --whatsapp.", file=sys.stderr)
        raise SystemExit(1)
    llave = base64.b64decode(raw)
    if len(llave) != 32:
        print("ASISTENTE_VINCULOS_KEY debe decodificar a exactamente 32 bytes.", file=sys.stderr)
        raise SystemExit(1)

    nonce = os.urandom(12)
    cifrado = AESGCM(llave).encrypt(nonce, key.encode(), None)  # ciphertext||tag
    return base64.b64encode(nonce + cifrado).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--nombre", required=True)
    ap.add_argument("--scopes", default=None, help=f"default: {SCOPES_DEFAULT} (con --whatsapp: {SCOPES_ABACUS})")
    ap.add_argument(
        "--whatsapp",
        default=None,
        metavar="+52...",
        help="Número E.164 a vincular en asistente_vinculos (para Abacus).",
    )
    ap.add_argument(
        "--forzar",
        action="store_true",
        help="Vincula Abacus aunque el plan del usuario no lo incluya.",
    )
    args = ap.parse_args()

    if args.whatsapp and not WHATSAPP_RE.match(args.whatsapp):
        print(f"Número inválido: {args.whatsapp} (formato E.164, ej. +5215512345678)", file=sys.stderr)
        return 1
    scopes = args.scopes or (SCOPES_ABACUS if args.whatsapp else SCOPES_DEFAULT)

    url = os.environ["TODOCONTA_SUPABASE_URL"].rstrip("/")
    svc = os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": svc, "Authorization": f"Bearer {svc}"}

    # user_id por email (GoTrue admin).
    r = requests.get(f"{url}/auth/v1/admin/users", params={"page": 1, "per_page": 1000}, headers=h, timeout=30)
    r.raise_for_status()
    user = next((u for u in r.json().get("users", []) if u.get("email") == args.email), None)
    if not user:
        print(f"No existe usuario con email {args.email}", file=sys.stderr)
        return 1

    # Plan del dueño (F1): Abacus solo con un plan que lo incluya.
    lic = _capacidades(user["id"])
    if lic is not None:
        caps = lic["capacidades"]
        lista = {s.strip() for s in scopes.split(",") if s.strip()}
        plan = lic.get("plan_codigo") or "?"
        if args.whatsapp and caps.get("abacus") is not True and not args.forzar:
            print(f"El plan del usuario ({plan}) no incluye Abacus. Usa --forzar si es a propósito.",
                  file=sys.stderr)
            return 1
        if "mcp" in lista and caps.get("mcp") is not True:
            print(f"Aviso: el plan ({plan}) no incluye MCP; el scope `mcp` se rechazará con "
                  "CAPACIDADES_MODO=exigir.", file=sys.stderr)
        if lista & SCOPES_REST and caps.get("api") is not True and caps.get("abacus") is not True:
            print(f"Aviso: el plan ({plan}) no incluye la API; los scopes REST se rechazarán con "
                  "CAPACIDADES_MODO=exigir.", file=sys.stderr)

    # Con --whatsapp, cifrar ANTES de insertar nada (si falta la llave, no dejamos key huérfana).
    key = f"tc_live_{secrets.token_urlsafe(32)}"
    key_cifrada = _cifrar_key(key) if args.whatsapp else None

    fila = {
        "user_id": user["id"],
        "nombre": args.nombre,
        "key_hash": hashlib.sha256(key.encode()).hexdigest(),
        "prefijo": key[:16],
        "scopes": [s.strip() for s in scopes.split(",") if s.strip()],
    }
    r = requests.post(
        f"{url}/rest/v1/api_keys",
        json=fila,
        headers={**h, "Prefer": "return=representation"},
        timeout=30,
    )
    if r.status_code not in (200, 201):
        print(f"Error al insertar: {r.status_code} {r.text}", file=sys.stderr)
        return 1
    key_id = (r.json() or [{}])[0].get("id")

    if args.whatsapp:
        vinculo = {
            "user_id": user["id"],
            "whatsapp_e164": args.whatsapp,
            "api_key_id": key_id,
            "api_key_cifrada": key_cifrada,
            "estado": "activo",
        }
        # Upsert por número: re-vincular reemplaza la key anterior del mismo WhatsApp.
        r = requests.post(
            f"{url}/rest/v1/asistente_vinculos",
            json=vinculo,
            headers={**h, "Prefer": "resolution=merge-duplicates,return=minimal"},
            params={"on_conflict": "whatsapp_e164"},
            timeout=30,
        )
        if r.status_code not in (200, 201, 204):
            print(f"Key emitida pero falló el vínculo WhatsApp: {r.status_code} {r.text}", file=sys.stderr)
            return 1

    print("API key emitida (guárdala AHORA; no se puede recuperar):\n")
    print(f"  {key}\n")
    print(f"  usuario: {args.email} · scopes: {fila['scopes']} · prefijo: {fila['prefijo']}")
    if args.whatsapp:
        print(f"  vínculo Abacus: {args.whatsapp} → {args.email} (key cifrada en asistente_vinculos)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

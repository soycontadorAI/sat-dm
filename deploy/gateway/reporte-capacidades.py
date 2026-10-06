#!/usr/bin/env python3
"""
Simulacro (solo lectura) de F1 en el gateway: qué credenciales existentes se
rechazarían con CAPACIDADES_MODO=exigir. Imprime SOLO conteos por plan: nunca
correos, user_ids, nombres ni prefijos de keys.

    python3 deploy/gateway/reporte-capacidades.py [--oauth-db /data/oauth.db]

Reglas que simula (las mismas de capacidades.py):
- Key con scope `mcp`        → necesita `capacidades.mcp`.
- Key con scopes REST        → necesita `capacidades.api` (o `abacus`).
- Vínculo activo de Abacus   → necesita `capacidades.abacus`.
- Con --oauth-db (dentro del contenedor del gateway): usuarios con
  autorizaciones OAuth vivas (refresh sin revocar ni vencer) → necesitan
  `capacidades.mcp`.

La licencia de cada dueño sale de GET /api/admin/license?user_id= (todoconta-apps,
solo lectura: no arranca pruebas ni toca el CRM).

Env: TODOCONTA_SUPABASE_URL, SUPABASE_SERVICE_KEY (lectura de api_keys y
asistente_vinculos), LICENCIA_ADMIN_TOKEN (Bearer del endpoint de admin) y,
opcional, LICENCIA_ADMIN_URL (default https://api.todoconta.com/api/admin/license).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import requests

SCOPES_REST = {"documentos:leer", "cfdi:solicitar", "listas-negras:consultar"}
RECIENTE_DIAS = 30


def _env(nombre: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        print(f"Falta la variable {nombre}.", file=sys.stderr)
        raise SystemExit(2)
    return valor


def _supabase_get(url: str, svc: str, tabla: str, params: dict) -> list[dict]:
    filas: list[dict] = []
    desde = 0
    while True:
        r = requests.get(
            f"{url}/rest/v1/{tabla}",
            params=params,
            headers={
                "apikey": svc,
                "Authorization": f"Bearer {svc}",
                "Range-Unit": "items",
                "Range": f"{desde}-{desde + 999}",
            },
            timeout=30,
        )
        r.raise_for_status()
        pagina = r.json()
        filas.extend(pagina)
        if len(pagina) < 1000:
            return filas
        desde += 1000


def _licencia(admin_url: str, token: str, user_id: str) -> dict | None:
    try:
        r = requests.get(
            admin_url,
            params={"user_id": user_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    lic = (r.json() or {}).get("license")
    if not isinstance(lic, dict) or not isinstance(lic.get("capacidades"), dict):
        return None
    return lic


def _tiene(lic: dict | None, cap: str) -> bool | None:
    """None = sin datos (el gateway deja pasar)."""
    if lic is None:
        return None
    caps = lic["capacidades"]
    if cap == "api":
        return caps.get("api") is True or caps.get("abacus") is True
    return caps.get(cap) is True


def _reciente(iso: str | None, ahora: datetime) -> bool:
    if not iso:
        return False
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return ahora - t <= timedelta(days=RECIENTE_DIAS)


def _usuarios_oauth(ruta: str) -> set[str]:
    db = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    filas = db.execute(
        "SELECT DISTINCT user_id FROM tokens WHERE tipo='refresh' AND revocado=0 AND expira > ?",
        (int(time.time()),),
    ).fetchall()
    db.close()
    return {f[0] for f in filas}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--oauth-db", default=None, help="SQLite del OAuth (dentro del contenedor: /data/oauth.db)")
    args = ap.parse_args()

    url = _env("TODOCONTA_SUPABASE_URL").rstrip("/")
    svc = _env("SUPABASE_SERVICE_KEY")
    token = _env("LICENCIA_ADMIN_TOKEN")
    admin_url = os.environ.get(
        "LICENCIA_ADMIN_URL", "https://api.todoconta.com/api/admin/license"
    ).strip()

    keys = _supabase_get(
        url, svc, "api_keys",
        {"revocada_en": "is.null", "select": "id,user_id,scopes,ultima_vez_usada"},
    )
    vinculos = _supabase_get(
        url, svc, "asistente_vinculos",
        {"estado": "eq.activo", "select": "user_id,api_key_id"},
    )
    oauth = _usuarios_oauth(args.oauth_db) if args.oauth_db else set()

    dueños = {k["user_id"] for k in keys} | {v["user_id"] for v in vinculos} | oauth
    licencias = {uid: _licencia(admin_url, token, uid) for uid in sorted(dueños)}

    def plan(uid: str) -> str:
        lic = licencias.get(uid)
        return (lic or {}).get("plan_codigo") or "sin datos"

    ahora = datetime.now(timezone.utc)
    por_plan: dict[str, Counter] = defaultdict(Counter)
    dueños_por_plan: dict[str, set] = defaultdict(set)

    for k in keys:
        uid = k["user_id"]
        p = plan(uid)
        c = por_plan[p]
        dueños_por_plan[p].add(uid)
        scopes = set(k.get("scopes") or [])
        reciente = _reciente(k.get("ultima_vez_usada"), ahora)
        c["keys"] += 1
        c["usadas_30d"] += reciente
        pierde_algo = False
        pierde_todo = True
        if "mcp" in scopes:
            ok = _tiene(licencias[uid], "mcp")
            c["con_mcp"] += 1
            if ok is False:
                c["mcp_rechazada"] += 1
                pierde_algo = True
            else:
                pierde_todo = False
        if scopes & SCOPES_REST:
            ok = _tiene(licencias[uid], "api")
            c["con_rest"] += 1
            if ok is False:
                c["rest_rechazada"] += 1
                pierde_algo = True
            else:
                pierde_todo = False
        if not scopes:
            pierde_todo = False
        c["afectadas"] += pierde_algo
        c["inservibles"] += pierde_algo and pierde_todo
        c["afectadas_usadas_30d"] += pierde_algo and reciente

    vinc = Counter()
    vinc_plan: Counter = Counter()
    for v in vinculos:
        ok = _tiene(licencias.get(v["user_id"]), "abacus")
        vinc["activos"] += 1
        vinc["rechazados"] += ok is False
        vinc["sin_datos"] += ok is None
        if ok is False:
            vinc_plan[plan(v["user_id"])] += 1

    oa = Counter()
    oa_plan: Counter = Counter()
    for uid in oauth:
        ok = _tiene(licencias.get(uid), "mcp")
        oa["usuarios"] += 1
        oa["rechazados"] += ok is False
        oa["sin_datos"] += ok is None
        if ok is False:
            oa_plan[plan(uid)] += 1

    columnas = [
        ("keys", "keys"), ("dueños", None), ("con_mcp", "con MCP"),
        ("mcp_rechazada", "MCP rechazada"), ("con_rest", "con REST"),
        ("rest_rechazada", "REST rechazada"), ("afectadas", "afectadas"),
        ("inservibles", "sin nada útil"), ("usadas_30d", "usadas 30 d"),
        ("afectadas_usadas_30d", "afectadas y usadas 30 d"),
    ]
    print(f"Simulacro CAPACIDADES_MODO=exigir ({ahora:%Y-%m-%d %H:%M} UTC). Solo conteos.\n")
    print("Keys activas por plan del dueño:")
    encabezado = ["plan"] + [t or "dueños" for _, t in columnas]
    filas = []
    total = Counter()
    for p in sorted(por_plan):
        c = por_plan[p]
        fila = [p]
        for clave, _ in columnas:
            valor = len(dueños_por_plan[p]) if clave == "dueños" else c[clave]
            fila.append(str(valor))
            total[clave] += valor
        filas.append(fila)
    filas.append(["TOTAL"] + [str(total[clave]) for clave, _ in columnas])
    anchos = [max(len(r[i]) for r in [encabezado] + filas) for i in range(len(encabezado))]
    for r in [encabezado] + filas:
        print("  " + "  ".join(v.ljust(anchos[i]) for i, v in enumerate(r)))

    def _desglose(c: Counter) -> str:
        return f" ({', '.join(f'{p}: {n}' for p, n in sorted(c.items()))})" if c else ""

    print(f"\nVínculos de Abacus activos: {vinc['activos']} · rechazados: {vinc['rechazados']}"
          f"{_desglose(vinc_plan)} · sin datos de licencia: {vinc['sin_datos']}")
    if args.oauth_db:
        print(f"Usuarios con OAuth (MCP) vivo: {oa['usuarios']} · rechazados: {oa['rechazados']}"
              f"{_desglose(oa_plan)} · sin datos de licencia: {oa['sin_datos']}")
    else:
        print("OAuth: no revisado (corre con --oauth-db /data/oauth.db dentro del contenedor del gateway).")
    sin_datos = sum(1 for lic in licencias.values() if lic is None)
    print(f"Dueños sin licencia legible (el gateway los deja pasar): {sin_datos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

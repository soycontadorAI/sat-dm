"""
Capacidades del plan del dueño de una credencial (F1 de planes v3,
docs/operacion/plan-app-v3.md en todoconta-apps).

Reglas:
- Scope `mcp` de una API key y token OAuth de /mcp: exigen `capacidades.mcp`.
- Scopes REST (`documentos:leer`, `cfdi:solicitar`, `listas-negras:consultar`):
  exigen `capacidades.api`. También pasan con `capacidades.abacus`, porque el
  plugin de Abacus trabaja sobre la REST con la key de su vínculo (en el
  catálogo, Abacus siempre viene con API).
- Vínculo de Abacus (/internal/vinculos): exige `capacidades.abacus`.
- El legado conserva la MCP (decidido por Israel 2026-10-05): lo resuelve la
  licencia (`capacidadesDePlan()` en todoconta-apps), no este archivo.

El gateway NO calcula planes: pide la licencia calculada del dueño a la API de
servicios por user_id (`GET /api/admin/license?user_id=`, solo lectura) con un
secreto de servidor a servidor, y la guarda 5 minutos. Así hay una sola fuente
de verdad para el mapeo de planes y legados.

Modo (env `CAPACIDADES_MODO`):
- `observar` (default): calcula y deja en el log lo que se rechazaría, pero
  deja pasar. Desplegar el gateway no le quita nada a nadie.
- `exigir`: rechaza con 403 y un mensaje con la liga a los planes.
- `apagado`: no consulta nada (como antes de F1).

Sin datos nunca hay candado: si falta el secreto, la API de servicios no
responde o la licencia no trae `capacidades`, se deja pasar (y se registra).
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Optional

import requests
from fastapi import HTTPException

logger = logging.getLogger("gateway")

LICENCIA_ADMIN_URL = os.environ.get(
    "LICENCIA_ADMIN_URL", "https://api.todoconta.com/api/admin/license"
)
LICENCIA_ADMIN_TOKEN = os.environ.get("LICENCIA_ADMIN_TOKEN", "")

MODOS = ("observar", "exigir", "apagado")
MODO = os.environ.get("CAPACIDADES_MODO", "observar").strip().lower()
if MODO not in MODOS:
    logger.warning("CAPACIDADES_MODO=%r no existe; se usa 'observar'", MODO)
    MODO = "observar"

SCOPES_REST = ("documentos:leer", "cfdi:solicitar", "listas-negras:consultar")

MENSAJES = {
    "mcp": (
        "Tu plan no incluye la conexión con IA (MCP). Viene en los planes Pro y "
        "Completo: todoconta.com/planes"
    ),
    "api": (
        "Tu plan no incluye la API. Viene en el plan Completo: todoconta.com/planes"
    ),
    "abacus": (
        "Tu plan no incluye Abacus. Viene en el plan Completo: todoconta.com/planes"
    ),
}

_TIMEOUT = 10
_TTL_OK_S = 300
_TTL_FALLA_S = 60
_AVISO_CADA_S = 3600

_lock = threading.Lock()
_cache: dict[str, tuple[float, Optional[dict]]] = {}
_avisos: dict[tuple[str, str], float] = {}
_sin_token_avisado = False


def capacidad_de_scope(scope: str) -> Optional[str]:
    """Qué capacidad del plan exige un scope de API key (None = ninguna)."""
    if scope == "mcp":
        return "mcp"
    if scope in SCOPES_REST:
        return "api"
    return None


def _huella(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()[:12]


def licencia_de(user_id: str) -> Optional[dict]:
    """
    Licencia calculada del usuario (dict con `capacidades`) o None si no se
    pudo saber. Cachea éxitos 5 min y fallas 1 min (no martilla al servicio).
    """
    global _sin_token_avisado
    if not user_id:
        return None
    if not LICENCIA_ADMIN_TOKEN:
        if not _sin_token_avisado:
            _sin_token_avisado = True
            logger.warning(
                "LICENCIA_ADMIN_TOKEN sin configurar: las capacidades del plan no se consultan"
            )
        return None
    ahora = time.monotonic()
    with _lock:
        guardada = _cache.get(user_id)
        if guardada and guardada[0] > ahora:
            return guardada[1]

    lic: Optional[dict] = None
    try:
        resp = requests.get(
            LICENCIA_ADMIN_URL,
            params={"user_id": user_id},
            headers={"Authorization": f"Bearer {LICENCIA_ADMIN_TOKEN}"},
            timeout=_TIMEOUT,
        )
        if resp.status_code == 200:
            datos = resp.json()
            # /api/admin/license responde {perfil, license, notas}; un endpoint
            # dedicado podría responder la licencia directo. Se aceptan ambos.
            candidata = datos.get("license") if isinstance(datos, dict) else None
            if not isinstance(candidata, dict):
                candidata = datos if isinstance(datos, dict) else None
            if isinstance(candidata, dict) and isinstance(candidata.get("capacidades"), dict):
                lic = {
                    "plan_codigo": candidata.get("plan_codigo"),
                    "legado": candidata.get("legado") is True,
                    "capacidades": candidata["capacidades"],
                }
        else:
            logger.warning(
                "licencia de user=%s respondió %s", _huella(user_id), resp.status_code
            )
    except (requests.RequestException, ValueError) as e:
        logger.warning("no se pudo leer la licencia de user=%s: %s", _huella(user_id), e)

    with _lock:
        _cache[user_id] = (ahora + (_TTL_OK_S if lic else _TTL_FALLA_S), lic)
    return lic


def permite(lic: dict, capacidad: str) -> bool:
    caps = lic.get("capacidades") or {}
    if capacidad == "api":
        return caps.get("api") is True or caps.get("abacus") is True
    return caps.get(capacidad) is True


def _decidir(user_id: str, lic: Optional[dict], capacidad: str, via: str) -> None:
    if lic is None or not isinstance(lic.get("capacidades"), dict):
        return  # sin datos, nunca candado
    if permite(lic, capacidad):
        return
    plan = lic.get("plan_codigo") or "?"
    if MODO != "exigir":
        clave = (user_id, capacidad)
        ahora = time.monotonic()
        with _lock:
            ultimo = _avisos.get(clave, 0.0)
            if ahora - ultimo < _AVISO_CADA_S:
                return
            _avisos[clave] = ahora
        logger.warning(
            "capacidad faltante (modo observar, se deja pasar): cap=%s plan=%s user=%s via=%s",
            capacidad, plan, user_id, via,
        )
        return
    logger.info(
        "capacidad faltante, rechazo: cap=%s plan=%s user=%s via=%s",
        capacidad, plan, user_id, via,
    )
    raise HTTPException(status_code=403, detail=MENSAJES[capacidad])


def exigir(user_id: str, capacidad: str, via: str = "") -> None:
    """Lanza HTTPException 403 si (en modo `exigir`) el plan del dueño no trae
    `capacidad`. En `observar` solo lo registra; en `apagado` ni consulta."""
    if MODO == "apagado":
        return
    _decidir(user_id, licencia_de(user_id), capacidad, via)


def exigir_en_licencia(lic: dict, capacidad: str, user_id: str = "", via: str = "") -> None:
    """Como `exigir`, con una licencia que ya se tiene a la mano (p. ej. la
    que el OAuth pide con el JWT del usuario). Sin `capacidades`, deja pasar."""
    if MODO == "apagado":
        return
    caps = lic.get("capacidades")
    if not isinstance(caps, dict):
        return
    _decidir(
        user_id or str(lic.get("user_id") or ""),
        {"plan_codigo": lic.get("plan_codigo"), "capacidades": caps},
        capacidad,
        via,
    )


def limpiar_cache() -> None:
    """Para pruebas."""
    with _lock:
        _cache.clear()
        _avisos.clear()

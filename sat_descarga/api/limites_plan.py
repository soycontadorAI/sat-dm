"""
Piezas comunes de los límites por plan (F1 de planes v3): el error 402 y cómo
se obtiene la licencia para decidir.

- `LimitePlanAlcanzado`: base de los rechazos por plan (tope de empresas, tope
  de descargas del mes). `server.py` lo traduce a HTTP 402 con
  `{detail, codigo, <codigo>: datos}`: `detail` es el texto para mostrar tal
  cual (como cualquier error del agente) y los datos alimentan el diálogo con
  la liga a los planes.
- La licencia sale del cache local (sin red, dentro de la gracia offline de 30
  días). Solo cuando el cache dice "no hay lugar" se pide una fresca antes de
  rechazar, por si el usuario acaba de cambiar de plan. Sin licencia = sin
  límite: la falta de datos nunca bloquea.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from . import license_client as lc

logger = logging.getLogger(__name__)

# No volver a pedir la licencia al servicio si el cache tiene menos de esto.
LICENCIA_RECIENTE_S = 60


class LimitePlanAlcanzado(Exception):
    """El plan no alcanza para lo que se pidió (HTTP 402)."""

    def __init__(self, mensaje: str, codigo: str, datos: dict):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.datos = datos

    def respuesta(self) -> dict:
        return {"detail": self.mensaje, "codigo": self.codigo, self.codigo: self.datos}


def licencia_en_cache() -> Optional[dict]:
    """Payload de la licencia en cache si está dentro de la gracia offline
    (30 días), igual que `get_license_status` sin red. Sin cache: None."""
    cache = lc._cache_read()
    if not cache:
        return None
    if int(time.time()) - int(cache.get("cached_at", 0) or 0) >= lc.CACHE_GRACE_SECONDS:
        return None
    payload = cache.get("payload")
    return payload if isinstance(payload, dict) else None


def cache_es_reciente() -> bool:
    cache = lc._cache_read() or {}
    return int(time.time()) - int(cache.get("cached_at", 0) or 0) < LICENCIA_RECIENTE_S


def licencia_fresca() -> Optional[dict]:
    """Licencia recién pedida al servicio (o la del cache si no hay red), o
    None si el cache ya es reciente o algo falla. Nunca lanza."""
    if cache_es_reciente():
        return None
    try:
        return lc.get_license_status(force_refresh=True)
    except Exception as e:  # noqa: BLE001 — un límite nunca debe tumbar la operación con 500
        logger.warning("[limites] no se pudo refrescar la licencia: %s", e)
        return None

"""
Sync del catálogo de empresas entre instalaciones (desktop ⇄ online).

Un PUT a /api/desktop/empresas-sync (todoconta-apps) hace push y pull en un
roundtrip: manda el catálogo local (SOLO metadata — las credenciales nunca
viajan) y aplica el fusionado que regresa (merge last-write-wins por empresa,
ver config_store.aplicar_sync_remoto).

Best-effort SIEMPRE: sin sesión, sin red, o con el endpoint aún no desplegado
(404/500) simplemente no pasa nada — el catálogo local es la fuente de verdad
de esta instalación y el sync solo lo enriquece.
"""

from __future__ import annotations

import logging
import threading

import requests

logger = logging.getLogger(__name__)

# Un sync a la vez; si llegan triggers mientras corre uno, se recuerda con
# `_pendiente` y se corre UNA pasada más al terminar (coalescing simple).
_lock = threading.Lock()
_corriendo = False
_pendiente = False


def sincronizar_catalogo() -> int | None:
    """
    Una pasada de sync síncrona. Devuelve cuántas entradas locales cambiaron,
    o None si no se pudo (sin sesión / red / endpoint). Nunca lanza.
    """
    from ..cli import config_store
    from . import license_client as lc

    try:
        session = lc.load_session()
    except Exception:  # noqa: BLE001 — keyring/secretos no disponibles
        return None
    if session is None:
        return None

    try:
        from . import cupo_descargas

        # `descargas_mes` (F1): descargas al SAT del mes en esta instalación,
        # para el tope del plan gratis. Campo aditivo: un backend viejo lo ignora.
        payload = {
            "empresas": config_store.catalogo_para_sync(),
            "descargas_mes": cupo_descargas.resumen(),
        }
        resp = requests.put(
            f"{lc.API_BASE_URL}/api/desktop/empresas-sync",
            json=payload,
            headers={"Authorization": f"Bearer {session.access_token}"},
            timeout=20,
        )
        if resp.status_code == 401:
            # Bearer expirado: mismo patrón que license — refresh y un reintento.
            nueva = lc.try_refresh_session(session)
            if nueva is None:
                return None
            resp = requests.put(
                f"{lc.API_BASE_URL}/api/desktop/empresas-sync",
                json=payload,
                headers={"Authorization": f"Bearer {nueva.access_token}"},
                timeout=20,
            )
        if resp.status_code != 200:
            logger.info("[sync-empresas] backend respondió %s; se omite", resp.status_code)
            return None
        remotas = resp.json().get("empresas", [])
        aplicadas = config_store.aplicar_sync_remoto(remotas)
        if aplicadas:
            logger.info("[sync-empresas] %d empresas actualizadas desde la nube", aplicadas)
        return aplicadas
    except requests.RequestException as e:
        logger.info("[sync-empresas] sin red hacia el backend: %s", e)
        return None
    except Exception:  # noqa: BLE001 — el sync jamás debe tumbar al caller
        logger.warning("[sync-empresas] pasada falló", exc_info=True)
        return None


def sincronizar_async(motivo: str = "") -> None:
    """
    Dispara un sync en background (hilo daemon). Coalescing: si ya hay uno
    corriendo, se agenda UNA pasada extra al terminar (no se encima).
    """
    global _corriendo, _pendiente
    with _lock:
        if _corriendo:
            _pendiente = True
            return
        _corriendo = True

    def _worker():
        global _corriendo, _pendiente
        try:
            while True:
                sincronizar_catalogo()
                # Continuidad de credenciales (pieza 2): solo desde la desktop
                # (la nube no puede alcanzar el equipo; este lado inicia).
                from ..core.config import es_modo_hosted

                if not es_modo_hosted():
                    from .espacio_online import sincronizar_credenciales

                    sincronizar_credenciales()
                with _lock:
                    if not _pendiente:
                        _corriendo = False
                        return
                    _pendiente = False
        finally:
            with _lock:
                _corriendo = False

    threading.Thread(
        target=_worker, name=f"sync-empresas({motivo})", daemon=True
    ).start()

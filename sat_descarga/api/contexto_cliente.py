"""
Contexto del cliente para la API de conversiones de Meta (CAPI).

El servicio (api.todoconta.com) manda a Meta los eventos de registro, prueba y
pago, y Meta pide el user agent y la IP de la PERSONA. Pero quien llama al
servicio es este agente con `requests`: el servicio vería `python-requests` y,
en la versión web, la IP del VPS. Por eso el agente recuerda lo que ve del
renderer y lo reenvía en tres headers (contraparte en todoconta-apps,
`apps/web/src/lib/meta/contexto.ts`):

    X-TodoConta-Cliente-UA    user agent del navegador o de Electron
    X-TodoConta-Cliente-Modo  "web" (hosted) | "desktop"
    X-TodoConta-Cliente-IP    solo en web: primer salto de X-Forwarded-For
                              (Traefik), la IP del navegador

En desktop no se manda IP: el agente corre en la máquina de la persona y el
servicio ve su IP en la propia petición.

Solo en memoria y solo lo último que llegó: un agente sirve a una sola cuenta
(uno por máquina en desktop, un contenedor por usuario en web). Las llamadas
del gateway (MCP, REST, Abacus, marcadas con `X-Todoconta-Origen`) y todo lo
que no tenga user agent de navegador no cuentan. La IP nunca se escribe a disco.
"""

from __future__ import annotations

import ipaddress
import os
import threading
from typing import Optional

from ..core.config import es_modo_hosted

HEADER_UA = "X-TodoConta-Cliente-UA"
HEADER_MODO = "X-TodoConta-Cliente-Modo"
HEADER_IP = "X-TodoConta-Cliente-IP"

# Igual que el provisioner: detrás de Traefik la IP real viene en el primer
# salto de X-Forwarded-For. Con "0" no se confía en el header.
CONFIAR_X_FORWARDED_FOR = os.environ.get("CONFIAR_X_FORWARDED_FOR", "1") != "0"

_lock = threading.Lock()
_user_agent: Optional[str] = None
_ip: Optional[str] = None


def user_agent_valido(ua: Optional[str]) -> Optional[str]:
    """Solo user agents de navegador (todos empiezan con "Mozilla/", también Electron)."""
    v = (ua or "").strip()
    if not v or len(v) > 512 or not v.startswith("Mozilla/"):
        return None
    return v


def _ip_valida(valor: Optional[str]) -> Optional[str]:
    v = (valor or "").strip()
    if not v:
        return None
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        return None


def registrar(user_agent: Optional[str], x_forwarded_for: Optional[str], origen: Optional[str]) -> None:
    """Recuerda el contexto de una petición del renderer (la llama el middleware)."""
    global _user_agent, _ip
    if origen:  # viene del gateway (MCP, REST, Abacus), no de la persona
        return
    ua = user_agent_valido(user_agent)
    if ua is None:
        return
    ip = None
    if es_modo_hosted() and CONFIAR_X_FORWARDED_FOR and x_forwarded_for:
        ip = _ip_valida(x_forwarded_for.split(",")[0])
    with _lock:
        _user_agent = ua
        if es_modo_hosted():
            _ip = ip


def headers() -> dict[str, str]:
    """Headers para las llamadas a api.todoconta.com."""
    modo = "web" if es_modo_hosted() else "desktop"
    with _lock:
        ua, ip = _user_agent, _ip
    h = {HEADER_MODO: modo}
    if ua:
        h[HEADER_UA] = ua
    if modo == "web" and ip:
        h[HEADER_IP] = ip
    return h


def _reiniciar_para_pruebas() -> None:
    global _user_agent, _ip
    with _lock:
        _user_agent = None
        _ip = None

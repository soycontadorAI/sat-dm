"""
Uso por acción en el gateway: cuenta, por cuenta, las llamadas a tools MCP, a la
REST v1 y los mensajes de Abacus, y los manda al mismo lugar que el agente
(`POST /api/desktop/eventos` de todoconta-apps → tabla `eventos_producto`).

Del lado del servidor: el agente cuenta las ACCIONES (una CSF descargada, un
Excel), el gateway cuenta el CANAL por donde llegaron. Nunca viajan argumentos de
las tools, cuerpos de request, RFC ni el contenido de los mensajes de WhatsApp:
solo el nombre de la tool o del endpoint, y cuándo.

- Cola en memoria con tope (`deque`); se vacía cada minuto en lotes y al salir.
  Si la API de servicios no responde, se conserva (pasado el tope se tiran los
  más viejos). Un reinicio del contenedor pierde a lo más el último minuto.
- Auth: `Authorization: Bearer <EVENTOS_GATEWAY_SECRET>`, secreto propio del
  gateway (el mismo valor en Vercel de todoconta-apps; nunca CRON_SECRET ni
  LICENCIA_GATEWAY_SECRET). Cada evento lleva su `user_id`.
- Sin el secreto no se manda nada (se avisa una vez en el log). Kill switch:
  `USO_GATEWAY=0`.

Los eventos y sus valores son un subconjunto de la taxonomía del agente
(`sat_descarga/api/uso.py`); una prueba verifica que coincidan.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from itertools import islice
from typing import Optional

import requests

logger = logging.getLogger("gateway")

EVENTOS_URL = os.environ.get(
    "EVENTOS_URL", "https://api.todoconta.com/api/desktop/eventos"
)
EVENTOS_GATEWAY_SECRET = os.environ.get("EVENTOS_GATEWAY_SECRET", "")
ACTIVO = os.environ.get("USO_GATEWAY", "1") != "0"

HERRAMIENTAS_MCP = (
    "calcular_aguinaldo", "calcular_carga_patronal", "calcular_finiquito",
    "calcular_isr_salarios", "calcular_sbc", "consultar_listas_negras",
    "descargar_csf", "descargar_opinion", "descargar_zip_cfdis", "estado_solicitud",
    "excel_cfdis", "indicadores_fiscales", "listar_empresas", "procesar_cfdis",
    "reporte_cfdis", "resumen_cfdis", "solicitar_cfdis", "otra",
)
ENDPOINTS_API = (
    "calculadora", "cfdi_estado", "cfdi_excel", "cfdi_procesar", "cfdi_reporte",
    "cfdi_resumen", "cfdi_solicitar", "cfdi_zip", "csf", "empresas", "listas_negras",
    "opinion", "otro",
)

EVENTOS: dict[str, dict] = {
    "mcp_herramienta": {"herramienta": HERRAMIENTAS_MCP, "conexion": ("api_key", "oauth")},
    "api_llamada": {"endpoint": ENDPOINTS_API, "origen": ("integracion", "abacus")},
    "abacus_mensaje": {},
}

# Ruta REST → nombre del endpoint. Las rutas con RFC o id de solicitud se
# reducen a su plantilla: el dato concreto nunca viaja.
_RUTAS = (
    (re.compile(r"^/v1/empresas/?$"), "empresas"),
    (re.compile(r"^/v1/csf/?$"), "csf"),
    (re.compile(r"^/v1/opinion/?$"), "opinion"),
    (re.compile(r"^/v1/cfdi/solicitudes/?$"), "cfdi_solicitar"),
    (re.compile(r"^/v1/cfdi/solicitudes/[^/]+/[^/]+/zip/?$"), "cfdi_zip"),
    (re.compile(r"^/v1/cfdi/solicitudes/[^/]+/[^/]+/?$"), "cfdi_estado"),
    (re.compile(r"^/v1/cfdi/procesar/?$"), "cfdi_procesar"),
    (re.compile(r"^/v1/cfdi/resumen/?$"), "cfdi_resumen"),
    (re.compile(r"^/v1/cfdi/reporte/[^/]+/?$"), "cfdi_reporte"),
    (re.compile(r"^/v1/cfdi/excel/?$"), "cfdi_excel"),
    (re.compile(r"^/v1/calculadoras/[^/]+/?$"), "calculadora"),
    (re.compile(r"^/v1/listas-negras/?$"), "listas_negras"),
)

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

TOPE_COLA = 10_000
LOTE_MAX = 200
INTERVALO_S = 60
_TIMEOUT = 10

_cola: deque = deque(maxlen=TOPE_COLA)
_lock = threading.Lock()
_vaciando = threading.Lock()
_hilo: Optional[threading.Thread] = None
_sin_secreto_avisado = False


def endpoint_de(path: str) -> str:
    """Nombre del endpoint REST para el conteo (`otro` si no se reconoce)."""
    for patron, nombre in _RUTAS:
        if patron.match(path):
            return nombre
    return "otro"


def herramienta_de(nombre: str) -> str:
    """Nombre de la tool MCP para el conteo (`otra` si aún no está en la lista)."""
    return nombre if nombre in HERRAMIENTAS_MCP else "otra"


def validar(evento: str, props: dict) -> dict:
    reglas = EVENTOS.get(evento)
    if reglas is None:
        raise ValueError(f"Evento del gateway desconocido: {evento!r}")
    limpias = {}
    for clave, valor in props.items():
        if valor is None:
            continue
        permitidos = reglas.get(clave)
        if permitidos is None:
            raise ValueError(f"Propiedad no permitida en {evento}: {clave!r}")
        if not isinstance(valor, str) or valor not in permitidos:
            raise ValueError(f"Valor no permitido para {evento}.{clave}")
        limpias[clave] = valor
    return limpias


def registrar(user_id: Optional[str], evento: str, **props) -> None:
    """Cuenta una llamada de `user_id`. Nunca lanza ni bloquea la respuesta."""
    if not ACTIVO or not user_id or not _UUID_RE.match(str(user_id)):
        return
    try:
        limpias = validar(evento, props)
    except ValueError as e:
        logger.warning("[uso] evento del gateway descartado: %s", e)
        return
    with _lock:
        _cola.append({
            "id": str(uuid.uuid4()),
            "user_id": str(user_id),
            "evento": evento,
            "props": limpias,
            "ocurrido_en": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    _asegurar_hilo()


def pendientes() -> int:
    with _lock:
        return len(_cola)


def _primeros() -> list:
    """Los primeros LOTE_MAX eventos SIN sacarlos: si el envío falla, la cola
    queda intacta (y el tope de la `deque` sigue tirando solo los más viejos)."""
    with _lock:
        return list(islice(_cola, LOTE_MAX))


def _quitar(ids: set) -> None:
    with _lock:
        restantes = [e for e in _cola if e["id"] not in ids]
        _cola.clear()
        _cola.extend(restantes)


def vaciar(max_lotes: Optional[int] = None) -> bool:
    """Manda la cola en lotes. True si quedó vacía."""
    global _sin_secreto_avisado
    if not EVENTOS_GATEWAY_SECRET:
        if not _sin_secreto_avisado and pendientes():
            _sin_secreto_avisado = True
            logger.warning("EVENTOS_GATEWAY_SECRET sin configurar: el uso por canal no se envía")
        return False
    if not _vaciando.acquire(blocking=False):
        return False
    try:
        enviados = 0
        while max_lotes is None or enviados < max_lotes:
            lote = _primeros()
            if not lote:
                return True
            try:
                resp = requests.post(
                    EVENTOS_URL,
                    json={"lote": str(uuid.uuid4()), "plataforma": "gateway", "eventos": lote},
                    headers={"Authorization": f"Bearer {EVENTOS_GATEWAY_SECRET}"},
                    timeout=_TIMEOUT,
                )
            except requests.RequestException as e:
                logger.info("[uso] sin conexión con la API de servicios: %s", e)
                return False
            if resp.status_code in (400, 413, 422):
                logger.warning("[uso] la API de servicios rechazó un lote (%s); se descarta", resp.status_code)
            elif resp.status_code != 200:
                logger.info("[uso] la API de servicios respondió %s; se reintenta", resp.status_code)
                return False
            _quitar({e["id"] for e in lote})
            enviados += 1
        return pendientes() == 0
    finally:
        _vaciando.release()


def _bucle() -> None:
    while True:
        time.sleep(INTERVALO_S)
        try:
            vaciar()
        except Exception:  # noqa: BLE001 — el conteo jamás tumba al gateway
            logger.warning("[uso] el vaciado falló", exc_info=True)


def _asegurar_hilo() -> None:
    global _hilo
    if _hilo is not None and _hilo.is_alive():
        return
    with _lock:
        if _hilo is not None and _hilo.is_alive():
            return
        _hilo = threading.Thread(target=_bucle, name="uso-gateway", daemon=True)
        _hilo.start()


@atexit.register
def _al_salir() -> None:
    try:
        vaciar(max_lotes=3)
    except Exception:  # noqa: BLE001
        pass

"""
Uso de la app por acción: qué hace el usuario y cuándo, nunca con qué datos.

Una línea por acción, en el punto donde la acción salió bien:

    track("descarga_completada", canal="web_service", tipo="emitidos",
          tamano=rango(numero_cfdis))

`track()` deja el evento en una cola local (persistida en
`~/.sat-descarga/uso-pendiente.jsonl`, con tope) y un hilo la vacía en lotes cada
5 minutos y al cerrar el agente hacia la API de servicios
(`POST /api/desktop/eventos`, con el Bearer de la sesión, igual que la licencia).
La desktop y la versión web corren este mismo agente, así que la misma línea cubre
las dos plataformas. Sin red, la cola se conserva; pasado el tope se tiran los
eventos más viejos.

Privacidad (la regla que este módulo hace cumplir):
- Solo viaja QUÉ acción y CUÁNDO. Las propiedades son categóricas o rangos y están
  en una lista blanca por evento (`TAXONOMIA`): un evento, una propiedad o un valor
  fuera de la lista se descarta. Nunca RFC, nombres, UUID de CFDI, montos, nombres
  de archivo ni texto libre.
- No pide ajuste al usuario (el contenido no trae datos personales), pero
  `SAT_DM_SIN_USO=1` lo apaga todo.
- Solo se envía en producción: desktop empaquetada (`SENTRY_ENVIRONMENT=production`,
  lo inyecta el shell Electron) o modo hosted. En desarrollo y en las pruebas
  `track()` no hace nada, salvo `SAT_DM_USO=1`.

Origen: cada evento dice de dónde salió la acción (`app` | `mcp` | `api` | `abacus`).
El gateway del VPS marca sus llamadas al agente con `X-Todoconta-Origen` y un
middleware de server.py lo deja en `_origen` para toda la petición (y para el job que
la petición lance). Lo que corre en segundo plano (el poller) va sin origen.

La taxonomía es un contrato con todoconta-apps (`apps/web/src/lib/uso/taxonomia.ts`
y la migración 043): si cambias un evento aquí, cámbialo allá. `huella()` resume la
taxonomía en un hash que las pruebas de los dos repos fijan con el mismo valor.
Documento: docs/operacion/uso-por-accion.md (todoconta-apps).
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Taxonomía (contrato con todoconta-apps)
# ---------------------------------------------------------------------------

BOOLEANO = "booleano"

TAMANOS = ("0", "1_10", "11_100", "101_1000", "1001_10000", "mas_10000")
_CREDENCIAL = ("efirma", "contrasena")
_CANAL_DESCARGA = ("web_service", "rapida")
_TIPO_DESCARGA = ("emitidos", "recibidos", "metadata", "por_uuid")
_CALCULADORAS = (
    "aguinaldo", "carga_patronal", "finiquito", "isr", "liquidacion", "ptu", "sbc",
)
_PROCESADORES = ("cfdi", "nomina", "pagos")
_MODO_TRAMITE = ("validacion", "envio")

# Las emite el gateway (deploy/gateway/uso.py), no este agente. Viven aquí para
# que la huella cubra la taxonomía completa que valida el servidor.
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

# evento -> {propiedad: valores permitidos | BOOLEANO}. Toda propiedad es opcional.
TAXONOMIA: dict[str, dict] = {
    # Cuenta
    "app_abierta": {"sistema": ("windows", "macos", "linux")},
    "sesion_iniciada": {
        "metodo": ("contrasena", "codigo", "google", "dispositivo", "web"),
    },
    # Empresas
    "empresa_agregada": {"metodo": _CREDENCIAL, "nueva": BOOLEANO},
    "empresa_archivada": {},
    # Descargas
    "descarga_solicitada": {
        "canal": _CANAL_DESCARGA, "tipo": _TIPO_DESCARGA, "credencial": _CREDENCIAL,
    },
    "descarga_completada": {
        "canal": _CANAL_DESCARGA, "tipo": _TIPO_DESCARGA, "credencial": _CREDENCIAL,
        "tamano": TAMANOS, "segundo_plano": BOOLEANO,
    },
    # Documentos
    "constancia_descargada": {"credencial": _CREDENCIAL},
    "opinion_32d_descargada": {"credencial": _CREDENCIAL},
    # Validación
    "estatus_validado": {"origen": ("procesador", "directo"), "tamano": TAMANOS},
    "listas_negras_consultada": {
        "modo": ("uno", "lote"), "origen": ("procesador", "directo"),
    },
    # Procesadores
    "procesador_usado": {"tipo": _PROCESADORES},
    "excel_exportado": {"tipo": _PROCESADORES, "formato": ("xlsx", "csv")},
    # DIOT
    "diot_generada": {},
    "diot_txt_exportado": {},
    "diot_presentada": {"modo": _MODO_TRAMITE},
    # Organizador
    "organizador_usado": {"accion": ("organizar", "renombrar", "deduplicar")},
    # Calculadoras
    "calculadora_usada": {"calculadora": _CALCULADORAS},
    "calculadora_exportada": {
        "calculadora": _CALCULADORAS, "formato": ("xlsx", "pdf", "recibos_ptu"),
    },
    # Tareas
    "tarea_creada": {
        "tipo": ("fiscal", "manual", "recurrente"), "desde_sugerencia": BOOLEANO,
    },
    # Trámites con e.firma
    "contabilidad_electronica_enviada": {"modo": _MODO_TRAMITE},
    "efirma_renovada": {"certificado": ("emitido", "pendiente")},
    "csd_solicitado": {"certificado": ("emitido", "pendiente")},
    # Canales (gateway, del lado del servidor)
    "mcp_herramienta": {"herramienta": HERRAMIENTAS_MCP, "conexion": ("api_key", "oauth")},
    "api_llamada": {"endpoint": ENDPOINTS_API, "origen": ("integracion", "abacus")},
    "abacus_mensaje": {},
}

EVENTOS_DEL_GATEWAY = ("mcp_herramienta", "api_llamada", "abacus_mensaje")

# Eventos que se disparan muchas veces por una sola intención del usuario (la
# calculadora recalcula con cada tecla, el procesador lista con cada filtro, la
# app vuelve a pedir la licencia al reconectar): cuentan una vez por ventana y
# por combinación de propiedades.
VENTANAS_S: dict[str, int] = {
    "app_abierta": 30 * 60,
    "calculadora_usada": 30 * 60,
    "procesador_usado": 30 * 60,
}


def huella(taxonomia: Optional[dict] = None) -> str:
    """Hash corto de la taxonomía (eventos, propiedades y valores permitidos).
    todoconta-apps calcula el mismo hash con el mismo JSON canónico."""
    canon = {
        evento: {
            prop: (regla if regla == BOOLEANO else sorted(regla))
            for prop, regla in props.items()
        }
        for evento, props in (taxonomia or TAXONOMIA).items()
    }
    texto = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()[:12]


def validar(evento: str, props: dict) -> dict:
    """Propiedades limpias del evento, o ValueError si algo sale de la lista
    blanca. Las propiedades en None se omiten (todas son opcionales). Los
    mensajes nombran la propiedad, nunca el valor (podría ser un dato personal)."""
    reglas = TAXONOMIA.get(evento)
    if reglas is None:
        raise ValueError(f"Evento fuera de la taxonomía: {evento!r}")
    limpias: dict = {}
    for clave, valor in props.items():
        if valor is None:
            continue
        regla = reglas.get(clave)
        if regla is None:
            raise ValueError(f"Propiedad no permitida en {evento}: {clave!r}")
        if regla == BOOLEANO:
            if type(valor) is not bool:
                raise ValueError(f"{evento}.{clave} debe ser booleano")
        elif not isinstance(valor, str) or valor not in regla:
            raise ValueError(f"Valor no permitido para {evento}.{clave}")
        limpias[clave] = valor
    return limpias


# ---------------------------------------------------------------------------
# Ayudantes para las propiedades (rangos y categorías, nunca el dato crudo)
# ---------------------------------------------------------------------------


def rango(n) -> Optional[str]:
    """Cuántos (CFDIs, RFCs) en rango: el número exacto nunca viaja."""
    if isinstance(n, bool) or not isinstance(n, int):
        return None
    if n <= 0:
        return "0"
    if n <= 10:
        return "1_10"
    if n <= 100:
        return "11_100"
    if n <= 1000:
        return "101_1000"
    if n <= 10000:
        return "1001_10000"
    return "mas_10000"


def tipo_cfdi(tipo_comprobante, tipo_solicitud=None) -> Optional[str]:
    """emitidos | recibidos | metadata a partir de lo que pidió el usuario."""
    if str(tipo_solicitud or "").strip().lower() == "metadata":
        return "metadata"
    return {"E": "emitidos", "R": "recibidos"}.get(str(tipo_comprobante or "").strip().upper())


def tipo_de_solicitud(solicitud: Optional[dict]) -> Optional[str]:
    """Lo mismo, desde una solicitud WS guardada en el catálogo local."""
    sol = solicitud or {}
    if "metadata" in str(sol.get("tipo") or "").lower():
        return "metadata"
    return tipo_cfdi(sol.get("tipo_comprobante"))


def sistema() -> Optional[str]:
    """SO del equipo (solo desktop; en la web el agente corre en el servidor)."""
    from ..core.config import es_modo_hosted

    if es_modo_hosted():
        return None
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


# ---------------------------------------------------------------------------
# Encendido
# ---------------------------------------------------------------------------


def activo() -> bool:
    """¿Se registran y envían eventos en este proceso?"""
    if os.environ.get("SAT_DM_SIN_USO") == "1":
        return False
    if os.environ.get("SAT_DM_USO") == "1":
        return True
    from ..core.config import es_modo_hosted

    return es_modo_hosted() or os.environ.get("SENTRY_ENVIRONMENT") == "production"


# ---------------------------------------------------------------------------
# Origen de la acción (categórico: nunca más que estos cuatro valores)
# ---------------------------------------------------------------------------

ORIGENES = ("app", "mcp", "api", "abacus")

_origen: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("uso_origen", default=None)


def origen_de_cabecera(valor: Optional[str]) -> str:
    """Origen de una petición al agente: el gateway manda `mcp`, `api` o
    `abacus`; sin cabecera (o con otra cosa) es la app (renderer desktop o web)."""
    v = (valor or "").strip().lower()
    return v if v in ORIGENES else "app"


def fijar_origen(origen: Optional[str]) -> contextvars.Token:
    return _origen.set(origen if origen in ORIGENES else None)


def restaurar_origen(token: contextvars.Token) -> None:
    _origen.reset(token)


def origen_actual() -> Optional[str]:
    return _origen.get()


# ---------------------------------------------------------------------------
# Cola local (persistida y con tope)
# ---------------------------------------------------------------------------

ARCHIVO = "uso-pendiente.jsonl"
TOPE_COLA = 5000            # pasado esto se tiran los más viejos
LOTE_MAX = 200              # eventos por POST (el servidor acepta hasta 200)
INTERVALO_S = 5 * 60        # entre vaciados
ARRANQUE_S = 45             # primer vaciado: lo que quedó de la sesión anterior
TIMEOUT_S = 10
ANTIGUEDAD_MAX = timedelta(days=30)  # más viejos ya no sirven (y el servidor los rechaza)

_lock = threading.Lock()
_conteo: Optional[int] = None       # líneas en el archivo (se cuenta al primer uso)
_conteo_ruta: Optional[Path] = None
_ultimos: dict = {}                 # (evento, props) -> monotonic del último registro


def _ruta() -> Path:
    from ..cli import config_store

    return config_store.CONFIG_DIR / ARCHIVO


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _leer(ruta: Path) -> list[dict]:
    """Eventos de la cola. Tolera líneas rotas (corte de luz, ceros de un apagado
    abrupto en Windows): se saltan y desaparecen en la siguiente reescritura."""
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    eventos = []
    for linea in texto.splitlines():
        linea = linea.strip().strip("\x00")
        if not linea:
            continue
        try:
            ev = json.loads(linea)
        except ValueError:
            continue
        if isinstance(ev, dict) and isinstance(ev.get("id"), str) and isinstance(ev.get("evento"), str):
            eventos.append(ev)
    return eventos


def _reescribir(ruta: Path, eventos: list[dict]) -> None:
    """Reescritura atómica y durable (mismo criterio que config_store)."""
    global _conteo, _conteo_ruta
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for ev in eventos:
            f.write(json.dumps(ev, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, ruta)
    _conteo, _conteo_ruta = len(eventos), ruta


def _encolar(evento: dict) -> None:
    global _conteo, _conteo_ruta
    linea = json.dumps(evento, separators=(",", ":")) + "\n"
    with _lock:
        ruta = _ruta()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        if _conteo is None or _conteo_ruta != ruta:
            _conteo, _conteo_ruta = len(_leer(ruta)), ruta
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(linea)
        _conteo += 1
        # Holgura de 10% para no reescribir el archivo en cada evento sin red.
        if _conteo > TOPE_COLA + TOPE_COLA // 10:
            _reescribir(ruta, _leer(ruta)[-TOPE_COLA:])


def _repetido(evento: str, props: dict) -> bool:
    ventana = VENTANAS_S.get(evento)
    if not ventana:
        return False
    clave = (evento, tuple(sorted(props.items())))
    ahora = time.monotonic()
    with _lock:
        ultimo = _ultimos.get(clave)
        if ultimo is not None and ahora - ultimo < ventana:
            return True
        _ultimos[clave] = ahora
    return False


def track(evento: str, **props) -> None:
    """Registra una acción del usuario. Nunca lanza: contar jamás rompe la acción."""
    try:
        if not activo():
            return
        limpias = validar(evento, props)
        if _repetido(evento, limpias):
            return
        registro = {
            "id": str(uuid.uuid4()),
            "evento": evento,
            "props": limpias,
            "ocurrido_en": _ahora_iso(),
        }
        origen = _origen.get()
        if origen in ORIGENES:
            registro["origen"] = origen
        _encolar(registro)
    except Exception as e:  # noqa: BLE001
        logger.warning("[uso] evento %s descartado: %s", evento, e)


def pendientes() -> int:
    """Eventos en la cola (para diagnóstico y pruebas)."""
    with _lock:
        return len(_leer(_ruta()))


# ---------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}([.+-][0-9A-Za-z.-]{1,20})?$")

_vaciando = threading.Lock()
_pausa_hasta = 0.0                  # monotonic; tras un 429 del servidor


def _plataforma() -> str:
    from ..core.config import es_modo_hosted

    return "web" if es_modo_hosted() else "desktop"


def _version() -> Optional[str]:
    """Versión de la app: la del shell Electron (la misma que usa Sentry) o la del
    paquete instalado (modo hosted)."""
    valor = os.environ.get("SENTRY_RELEASE", "").strip()
    if not valor:
        try:
            from importlib.metadata import version

            valor = version("sat-descarga-masiva")
        except Exception:  # noqa: BLE001 — binario sin metadata
            return None
    return valor if _VERSION_RE.fullmatch(valor) else None


def _siguiente_lote() -> list[dict]:
    """Los primeros LOTE_MAX eventos de la cola; tira de paso los muy viejos."""
    limite = (datetime.now(timezone.utc) - ANTIGUEDAD_MAX).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _lock:
        ruta = _ruta()
        eventos = _leer(ruta)
        vigentes = [e for e in eventos if str(e.get("ocurrido_en") or "") >= limite]
        if len(vigentes) != len(eventos):
            _reescribir(ruta, vigentes)
        return vigentes[:LOTE_MAX]


def _quitar(ids: set) -> None:
    with _lock:
        ruta = _ruta()
        _reescribir(ruta, [e for e in _leer(ruta) if e.get("id") not in ids])


def _enviar(lote: list[dict], token: str, timeout: float) -> str:
    """ok | descartar | 401 | reintentar."""
    global _pausa_hasta
    from . import license_client as lc

    payload = {
        "lote": str(uuid.uuid4()),
        "plataforma": _plataforma(),
        "version_app": _version(),
        "eventos": lote,
    }
    try:
        resp = requests.post(
            f"{lc.API_BASE_URL}/api/desktop/eventos",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
        )
    except requests.RequestException as e:
        logger.info("[uso] sin red hacia el servicio: %s", e)
        return "reintentar"
    if resp.status_code == 200:
        return "ok"
    if resp.status_code == 401:
        return "401"
    if resp.status_code == 429:
        try:
            espera = int(resp.headers.get("Retry-After", "600"))
        except ValueError:
            espera = 600
        _pausa_hasta = time.monotonic() + max(60, min(espera, 6 * 3600))
        return "reintentar"
    if resp.status_code in (400, 413, 422):
        # El servidor nunca va a aceptar este lote tal cual: reintentarlo solo
        # atoraría la cola.
        logger.warning("[uso] el servicio rechazó un lote (%s); se descarta", resp.status_code)
        return "descartar"
    # 404 (endpoint aún sin desplegar), 5xx: se conserva y se reintenta.
    logger.info("[uso] el servicio respondió %s; se reintenta después", resp.status_code)
    return "reintentar"


def vaciar(timeout: float = TIMEOUT_S, max_lotes: Optional[int] = None) -> bool:
    """Envía la cola en lotes. True si quedó vacía. Nunca lanza."""
    if not activo() or time.monotonic() < _pausa_hasta:
        return False
    if not _vaciando.acquire(blocking=False):
        return False  # otro hilo ya está vaciando
    try:
        if not _siguiente_lote():
            return True  # nada que mandar: ni se toca el keychain
        from . import license_client as lc

        try:
            sesion = lc.load_session()
        except Exception:  # noqa: BLE001 — keychain no disponible
            return False
        if sesion is None:
            return False  # sin sesión se conserva hasta el próximo login
        enviados = 0
        while max_lotes is None or enviados < max_lotes:
            lote = _siguiente_lote()
            if not lote:
                return True
            estado = _enviar(lote, sesion.access_token, timeout)
            if estado == "401":
                nueva = lc.try_refresh_session(sesion)
                if nueva is None:
                    return False
                sesion = nueva
                estado = _enviar(lote, sesion.access_token, timeout)
            if estado not in ("ok", "descartar"):
                return False
            _quitar({e["id"] for e in lote})
            enviados += 1
        return not _siguiente_lote()
    except Exception:  # noqa: BLE001
        logger.warning("[uso] el vaciado falló", exc_info=True)
        return False
    finally:
        _vaciando.release()


def al_cerrar_sesion() -> None:
    """Logout explícito: manda lo pendiente con la sesión que se va y vacía la
    cola, para que nada de esta cuenta se le atribuya a la siguiente."""
    try:
        vaciar(timeout=3, max_lotes=3)
    finally:
        try:
            with _lock:
                ruta = _ruta()
                if ruta.exists():
                    _reescribir(ruta, [])
        except OSError:
            logger.warning("[uso] no se pudo vaciar la cola al cerrar sesión", exc_info=True)


# ---------------------------------------------------------------------------
# Hilo de envío (lo arranca y lo detiene el lifespan de server.py)
# ---------------------------------------------------------------------------

_stop = threading.Event()
_hilo: Optional[threading.Thread] = None


def _bucle() -> None:
    if _stop.wait(ARRANQUE_S):
        return
    while not _stop.is_set():
        vaciar()
        if _stop.wait(INTERVALO_S):
            return


def iniciar() -> None:
    """Arranca el hilo de envío (idempotente, no bloquea el arranque)."""
    global _hilo
    if not activo():
        return
    if _hilo is not None and _hilo.is_alive():
        return
    _stop.clear()
    _hilo = threading.Thread(target=_bucle, name="uso-eventos", daemon=True)
    _hilo.start()


def detener() -> None:
    """Al cerrar el agente: último envío corto. Lo que no alcance queda en la
    cola para el próximo arranque (en Windows el shell mata el proceso sin
    shutdown, por eso la cola vive en disco)."""
    _stop.set()
    vaciar(timeout=3, max_lotes=2)

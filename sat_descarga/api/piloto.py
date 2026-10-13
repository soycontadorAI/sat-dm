"""
Descarga automática (piloto): el planificador de las solicitudes al SAT.

Fase 4 de docs/producto/descarga-programada.md (F7, "Piloto automático", de
plan-app-v3 en todoconta-apps). Un hilo como el poller que cada `TICK_S` revisa
qué trabajo venció y crea las solicitudes al Web Service; el poller las verifica
y las baja como a cualquier otra, y el cuadro de control
(`procesador/calendario.py`) refleja cada día. Kill switch: `SAT_DM_SIN_PILOTO=1`.

Copiloto, no autopiloto: corre solo si el usuario lo activó y la licencia trae
la capacidad `piloto`; no consume el cupo de descargas (solo existe en planes sin
tope); no decide nada fiscal: avisa (diferencias contra el SAT, cancelaciones de
meses ya cerrados) y el contador decide.

Por empresa incluida y con e.firma vigente:

- **Pasada diaria** (tipo "diaria", periodo = el día D de la corrida, hora de la
  Ciudad de México): pide emitidos y recibidos de D-3…D-1 (un CFDI se timbra
  hasta 72 h después de emitido) más los días por descargar desde la última vez
  (si la app estuvo cerrada), sin los días ya cerrados ni los que tienen una
  solicitud viva. Corre en la madrugada con un desfase por cuenta; en escritorio,
  si la app se abre después, de inmediato ("ponerse al corriente").
- **Cierre mensual** (tipo "cierre", periodo = YYYY-MM): desde `dia_cierre` (y
  al menos `RESPIRO_CIERRE_DIAS` después de fin de mes) y sin solicitudes vivas
  del mes, pide la metadata de los últimos 12 meses (emitidos y recibidos, todos
  los estatus): trae el conteo del mes y las cancelaciones. Aplica las
  cancelaciones, compara día por día contra el índice, pide por folio (pocos) o
  por días lo que falte y al final cada día queda consolidado o diferencia. Los
  meses que vencieron con la app cerrada se cierran también.

- **Historial** (fase 5): si el usuario eligió `historial_desde`, los meses anteriores
  al primer cierre se llenan hacia atrás, del más reciente al más antiguo, con la
  misma máquina del cierre (`detalle.origen == "historial"`): la metadata pide solo
  ese mes, las cancelaciones no avisan y un solo resumen cierra todo el historial.
  Ritmo pausado (`HISTORIAL_MESES_POR_DIA` por empresa y `..._CUENTA` por cuenta al
  día) y solo cuando los cierres normales no tocaron al SAT en la vuelta.

Errores (tabla "Errores" del doc): red, 404 o 5006 → reintento con espera
creciente y, tras 3 días, error; e.firma (no abre, vencida, 300-305) → error
inmediato con aviso y la empresa se salta hasta que cambie; 5002 → error sin
reintento; 5005 → "ya pedido": nunca se varían los segundos para burlarlo (gasta
la cuota del SAT), los días quedan en proceso y el cierre los resuelve; 5004 → día
con 0 (lo resuelve la reconciliación del calendario).

Candado: `piloto_ejecuciones` (migración 012), una fila por (empresa, tipo,
periodo) que se reserva antes de pedir nada; si existe, se retoma su paso. El
candado ENTRE instalaciones (web y escritorio de la misma cuenta) necesita esa
tabla en Supabase (migración 044 de todoconta-apps), pendiente: hasta entonces
cada instalación lleva el suyo y la sesión única pausa la que no tiene la cuenta.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import threading
import time
from collections import Counter
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

import requests
from lxml import etree

from ..cli import config_store
from ..core.errores import ErrorEsperado
from ..procesador import calendario
from ..procesador.db import abrir_db, normalizar_mi_rfc

logger = logging.getLogger(__name__)

TICK_S = 300                 # entre evaluaciones (despertar() adelanta la siguiente)
ARRANQUE_DELAY_S = 45        # después del poller (20 s): el agente ya está de pie
ESCALON_S = 90               # entre empresas que piden algo al SAT…
ESCALON_VARIACION_S = 30     # …más una variación, para no pedir a la misma hora
HORA_BASE = dtime(1, 0)      # la pasada diaria arranca a la 1:00 (Ciudad de México)…
DESFASE_MAX_MIN = 240        # …más un desfase estable por cuenta de hasta 4 h
REZAGO_DIAS = 3              # un CFDI se puede timbrar hasta 72 h después de emitido
AL_CORRIENTE_DIAS = 31       # cuántos días hacia atrás recupera tras tener la app cerrada
MAX_RANGOS = 4               # solicitudes por dirección en una pasada (se juntan los huecos)
RESPIRO_CIERRE_DIAS = 3      # el cierre espera el rezago de timbrado del último día
MESES_METADATA = 12          # ventana de la metadata del cierre (cancelaciones)
HISTORIAL_MARGEN_DIAS = 7           # colchón del límite de 5 años del SAT (ver historial_minimo)
HISTORIAL_MESES_POR_DIA = 1         # meses NUEVOS del historial por empresa y día (Ciudad de México)
HISTORIAL_MESES_POR_DIA_CUENTA = 8  # …y por cuenta, para que un despacho no dispare todo el mismo día
HISTORIAL_ANIOS = 5                 # límite del WS v1.5
FOLIOS_MAX = 10              # faltantes que se piden por UUID; más, se piden los días
METADATA_INTENTOS_MAX = 3    # metadata que el SAT no completa o que no se puede leer
INDEXADO_ESPERA_S = 5        # cuánto espera el cierre al indexado de fondo de la empresa
REINTENTOS_S = (30 * 60, 2 * 3600, 6 * 3600, 12 * 3600, 24 * 3600)
REINTENTOS_HORAS_MAX = 72    # transitorios: tras 3 días sin lograrlo, error
EFIRMA_RECHEQUEO_S = 6 * 3600

_CODIGOS_EFIRMA = frozenset({"300", "302", "303", "304", "305"})
# Una solicitud que el SAT todavía va a resolver (3 = lista, falta bajarla).
_VIVAS = config_store.ESTADOS_PENDIENTES | {"3"}
# Ejecuciones con trabajo pendiente: en curso, o en error esperando a la e.firma
# (`detalle` se guarda con json.dumps, de ahí la forma exacta).
_CON_TRABAJO = ("(estado = 'en_curso' OR (estado = 'error'"
                " AND detalle LIKE '%\"reintentable\": true%'))")
_DIRECCIONES = ("E", "R")
_NOMBRE_DIR = {"E": "emitidos", "R": "recibidos"}
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")

_stop = threading.Event()
_despertar = threading.Event()
_thread: Optional[threading.Thread] = None
_evaluando = threading.Lock()   # una evaluación a la vez (hilo, /piloto/correr)


# ---------------------------------------------------------------------------
# Reloj y configuración
# ---------------------------------------------------------------------------


def _ahora() -> datetime:
    """Ahora en la Ciudad de México (las pruebas lo fijan)."""
    return calendario.ahora_mx()


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def config() -> dict:
    return config_store.get_piloto_config()


def disponible() -> bool:
    """¿La licencia (en cache, sin red) trae la capacidad `piloto`? Sin licencia,
    no: es automatización contra el SAT y aquí la falta de datos sí detiene."""
    from .license_client import capacidad
    from .limites_plan import licencia_en_cache

    lic = licencia_en_cache()
    return lic is not None and capacidad(lic, "piloto")


def _sesion_cerrada() -> bool:
    from .poller import _sesion_cerrada as cerrada

    return cerrada()


def _desfase_min() -> int:
    """Minutos de desfase de la pasada de esta cuenta (estable): no todos a la 1:00."""
    semilla = ""
    try:
        from .limites_plan import licencia_en_cache

        semilla = str((licencia_en_cache() or {}).get("user_id") or "")
    except Exception:  # noqa: BLE001
        pass
    if not semilla:
        semilla = ",".join(sorted(e["rfc"] for e in config_store.list_empresas()))
    return int(hashlib.sha256(semilla.encode()).hexdigest()[:8], 16) % DESFASE_MAX_MIN


def _hora_programada(d: date) -> datetime:
    base = datetime.combine(d, HORA_BASE, tzinfo=calendario.ZONA_MX)
    return base + timedelta(minutes=_desfase_min())


def _activado_en() -> Optional[date]:
    valor = config().get("activado_en")
    try:
        return datetime.fromisoformat(valor).astimezone(calendario.ZONA_MX).date() if valor else None
    except (TypeError, ValueError):
        return None


def _mes_anterior(periodo: str) -> str:
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    return f"{anio - 1}-12" if mes == 1 else f"{anio}-{mes - 1:02d}"


def _mes_de(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _limites_mes(periodo: str) -> tuple[date, date]:
    anio, mes = int(periodo[:4]), int(periodo[5:7])
    ini = date(anio, mes, 1)
    fin = (date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)) - timedelta(days=1)
    return ini, fin


def _fecha_cierre(periodo: str, dia_cierre: int) -> date:
    """Día en que se cierra `periodo`: el `dia_cierre` del mes siguiente, pero no
    antes de que pase el rezago de timbrado del último día del mes."""
    _ini, fin = _limites_mes(periodo)
    siguiente = fin + timedelta(days=1)
    dia = max(int(dia_cierre or 5), RESPIRO_CIERRE_DIAS + 1)
    return date(siguiente.year, siguiente.month, min(dia, 28))


def _nombre_mes(periodo: str) -> str:
    return f"{_MESES[int(periodo[5:7]) - 1]} de {periodo[:4]}"


# ---------------------------------------------------------------------------
# Hilo
# ---------------------------------------------------------------------------


def iniciar_piloto() -> None:
    """Arranca el hilo (idempotente). No bloquea el arranque del agente."""
    global _thread
    if os.environ.get("SAT_DM_SIN_PILOTO") == "1":
        logger.info("[piloto] Deshabilitado por SAT_DM_SIN_PILOTO=1")
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="piloto", daemon=True)
    _thread.start()
    logger.info("[piloto] Planificador de la descarga automática iniciado")


def detener_piloto() -> None:
    _stop.set()
    _despertar.set()


def despertar() -> None:
    """Adelanta la siguiente evaluación (cambio de configuración, "correr ahora")."""
    _despertar.set()


def _loop() -> None:
    if _stop.wait(ARRANQUE_DELAY_S):
        return
    while not _stop.is_set():
        try:
            evaluar()
        except Exception:  # noqa: BLE001 — el piloto nunca debe morir
            logger.exception("[piloto] Falló la evaluación; se reintenta en la siguiente")
        _despertar.wait(TICK_S)
        _despertar.clear()


def _escalonar() -> None:
    """Pausa entre empresas que pidieron algo al SAT (la IP en la nube es compartida)."""
    _stop.wait(ESCALON_S + random.uniform(0, ESCALON_VARIACION_S))


# ---------------------------------------------------------------------------
# Elegibilidad y e.firma
# ---------------------------------------------------------------------------


def _motivo_no_elegible(emp: dict, hoy: date) -> Optional[str]:
    if emp.get("archived_at"):
        return "Archivada"
    if emp.get("piloto_incluida") is False:
        return "No incluida"
    if "fiel" not in (emp.get("metodos") or []):
        return "Sin e.firma"
    venc = str(emp.get("vencimiento") or "")[:10]
    if venc and venc < hoy.isoformat():
        return "e.firma vencida"
    return None


def _fiel(rfc: str):
    """FIEL de la empresa (la cache del poller: no golpea el llavero en cada tick)."""
    from .poller import _fiel_cache, _fiel_de

    fiel = _fiel_de(rfc)
    if fiel is None:
        # El poller recuerda el fallo hasta que cambien los paths; aquí se vuelve a
        # probar cada EFIRMA_RECHEQUEO_S por si solo cambió la contraseña.
        marca = f"piloto:efirma:{rfc}"
        ultimo = _efirma_rechequeo.get(marca, 0.0)
        ahora = _ahora().timestamp()
        if ahora - ultimo >= EFIRMA_RECHEQUEO_S:
            _efirma_rechequeo[marca] = ahora
            _fiel_cache.pop(rfc, None)
            fiel = _fiel_de(rfc)
    return fiel


_efirma_rechequeo: dict = {}


class _SesionSat:
    """Lo necesario para pedirle algo al SAT por una empresa: su e.firma, cargada
    solo cuando de verdad hay que pedir (leerla toca el llavero del sistema y una
    vuelta sin trabajo no debe tocarlo, mismo criterio que el poller), y un token
    que se reusa mientras está fresco (dura ~5 min; una autenticación firmada por
    solicitud multiplicaría la carga desde la IP compartida)."""

    TOKEN_VIGENCIA_S = 240

    def __init__(self, rfc: str):
        self.rfc = rfc
        self._cargada = False
        self._fiel = None
        self._token: Optional[str] = None
        self._token_en = 0.0
        self._error_token: Optional[Exception] = None

    def fiel(self):
        if not self._cargada:
            self._fiel = _fiel(self.rfc)
            self._cargada = True
        return self._fiel

    def token(self) -> str:
        """Token del WS. Si la autenticación ya falló en esta vuelta, se repite el
        error sin volver a tocar al SAT (lo demás de la empresa espera su reintento)."""
        from ..webservice.auth import obtener_token

        if self._error_token is not None:
            raise self._error_token
        if self._token is None or time.monotonic() - self._token_en >= self.TOKEN_VIGENCIA_S:
            try:
                self._token = obtener_token(self.fiel())
            except Exception as e:
                self._error_token = e
                raise
            self._token_en = time.monotonic()
        return self._token


# ---------------------------------------------------------------------------
# Ejecuciones (candado) y avisos
# ---------------------------------------------------------------------------


def _fila(rfc: str, tipo: str, periodo: str) -> Optional[dict]:
    db = abrir_db()
    with db.cursor() as cur:
        r = cur.execute(
            "SELECT * FROM piloto_ejecuciones WHERE mi_rfc = ? AND tipo = ? AND periodo = ?",
            (rfc, tipo, periodo),
        ).fetchone()
    if r is None:
        return None
    fila = dict(r)
    try:
        fila["detalle"] = json.loads(fila.get("detalle") or "{}")
    except ValueError:
        fila["detalle"] = {}
    return fila


def _reservar(rfc: str, tipo: str, periodo: str, detalle: Optional[dict] = None) -> bool:
    """Reserva la ejecución. False si otra evaluación ya la tiene."""
    db = abrir_db()
    ahora = _utc(_ahora())
    with db.transaccion() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO piloto_ejecuciones (mi_rfc, tipo, periodo, estado, detalle,"
            " creado_en, actualizado_en) VALUES (?, ?, ?, 'en_curso', ?, ?, ?)",
            (rfc, tipo, periodo, json.dumps(detalle or {}, ensure_ascii=False), ahora, ahora),
        )
        return cur.rowcount == 1


def _guardar(rfc: str, tipo: str, periodo: str, **campos) -> None:
    if "detalle" in campos:
        campos["detalle"] = json.dumps(campos["detalle"], ensure_ascii=False)
    campos["actualizado_en"] = _utc(_ahora())
    sets = ", ".join(f"{k} = ?" for k in campos)
    db = abrir_db()
    with db.transaccion() as conn:
        conn.execute(
            f"UPDATE piloto_ejecuciones SET {sets} WHERE mi_rfc = ? AND tipo = ? AND periodo = ?",
            (*campos.values(), rfc, tipo, periodo),
        )


def _terminada(fila: Optional[dict]) -> bool:
    """¿Esa ejecución ya no tiene trabajo? Completa, o en error sin reintento."""
    return fila is not None and (fila["estado"] == "completa" or (
        fila["estado"] == "error" and not (fila.get("detalle") or {}).get("reintentable")))


def _toca(fila: Optional[dict], ahora: datetime) -> bool:
    """¿La ejecución tiene trabajo ahora? (nueva, en curso o en un reintento vencido)."""
    if fila is None:
        return True
    if _terminada(fila):
        return False
    proximo = fila.get("proximo_intento")
    return not proximo or proximo <= _utc(ahora)


def _avisar(tipo: str, mensaje: str, *, rfc: Optional[str] = None,
            periodo: Optional[str] = None, clave: Optional[str] = None) -> None:
    db = abrir_db()
    with db.transaccion() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO piloto_avisos (clave, tipo, mi_rfc, periodo, mensaje, creado_en)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (clave, tipo, rfc, periodo, mensaje, _utc(_ahora())),
        )
    logger.info("[piloto] Aviso (%s): %s", tipo, mensaje)


def avisos(solo_sin_leer: bool = True, limite: int = 50) -> list[dict]:
    db = abrir_db()
    donde = "WHERE leido = 0" if solo_sin_leer else ""
    with db.cursor() as cur:
        filas_ = cur.execute(
            f"SELECT id, tipo, mi_rfc, periodo, mensaje, creado_en, leido FROM piloto_avisos"
            f" {donde} ORDER BY id DESC LIMIT ?",
            (limite,),
        ).fetchall()
    return [{**dict(r), "rfc": r["mi_rfc"], "leido": bool(r["leido"])} for r in filas_]


def marcar_avisos_leidos(ids: Optional[Iterable[int]] = None) -> int:
    db = abrir_db()
    with db.transaccion() as conn:
        if ids is None:
            return conn.execute("UPDATE piloto_avisos SET leido = 1 WHERE leido = 0").rowcount
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marcas = ",".join("?" * len(ids))
        return conn.execute(f"UPDATE piloto_avisos SET leido = 1 WHERE id IN ({marcas})", ids).rowcount


# ---------------------------------------------------------------------------
# Solicitudes al SAT
# ---------------------------------------------------------------------------

# Respuestas que no se pudieron leer (HTML de mantenimiento, XML truncado): son del
# SAT. Cualquier otra excepción es un error de la app y sube con su traza.
_ERRORES_DE_LECTURA = (etree.XMLSyntaxError, etree.ParserError)


def _clasificar(mensaje: str) -> tuple[str, str, str]:
    """RuntimeError de una solicitud → (clase, código, mensaje). Sin CodEstatus
    (un SOAP Fault, una respuesta sin resultado) no es un rechazo del SAT a la
    solicitud: se reintenta como falla transitoria."""
    from ..webservice.errores import codestatus

    cod = codestatus(mensaje)
    if not cod:
        return "transitorio", "", mensaje
    if cod in _CODIGOS_EFIRMA:
        return "efirma", cod, mensaje
    if cod == "5002":
        return "agotado", cod, mensaje
    if cod == "5005":
        return "duplicada", cod, mensaje
    if cod in ("5006", "404"):
        return "transitorio", cod, mensaje
    return "rechazo", cod, mensaje


def _vivas(rfc: str) -> list[dict]:
    return [s for s in config_store.list_solicitudes(rfc) if s.get("estado") in _VIVAS]


def _igual(rfc: str, desde, hasta, direccion: str, tipo_solicitud: str,
           uuids: Optional[list], *, listas: bool = False,
           manuales: bool = False) -> Optional[str]:
    """Una solicitud viva del piloto con el mismo criterio (se reusa en vez de
    provocar un 5005). Con `listas`, también una que ya terminó bien: el SAT
    contesta 5005 a una solicitud igual a otra que ya tiene, y lo que esa bajó
    sirve igual. Con `manuales` (solo CFDI), también una manual que se guardó sin
    filtros (`sin_filtros`; las de antes no lo dicen y no se toman)."""
    candidatas = config_store.list_solicitudes(rfc) if listas else _vivas(rfc)
    for s in reversed(candidatas):  # la más reciente primero
        if s.get("ilegible"):
            continue  # una que no se pudo leer no sirve
        if s.get("origen") != "piloto" and not (
                manuales and tipo_solicitud.lower() == "cfdi" and s.get("sin_filtros")):
            continue
        if uuids:
            if sorted(s.get("uuids") or []) != sorted(uuids):
                continue
        else:
            tipo_s = "metadata" if config_store.es_metadata(s) else "cfdi"
            if (s.get("uuids") or s.get("fecha_inicio") != desde.isoformat()
                    or s.get("fecha_fin") != hasta.isoformat()
                    or s.get("tipo_comprobante") != direccion or tipo_s != tipo_solicitud.lower()):
                continue
        if _estado_solicitud(rfc, s["id_solicitud"]) in (("viva", "lista") if listas else ("viva",)):
            return s["id_solicitud"]
    return None


def _pedir(rfc: str, sesion: _SesionSat, desde: Optional[date], hasta: Optional[date], direccion: str, *,
           tipo_solicitud: str = "CFDI", proposito: str, periodo: str,
           uuids: Optional[list] = None) -> tuple[str, Optional[str], Optional[str]]:
    """Pide al SAT y guarda la solicitud en el catálogo (el poller la termina).
    Devuelve ("ok", id_solicitud, None) o (clase, código, mensaje)."""
    from ..webservice.solicitud import solicitar_descarga, solicitar_descarga_folio

    existente = _igual(rfc, desde, hasta, direccion, tipo_solicitud, uuids)
    if existente:
        return "ok", existente, None
    fiel = sesion.fiel()
    if fiel is None:
        return "efirma", "", "No se pudo abrir la e.firma de la empresa (¿cambió su contraseña?)."
    try:
        token = sesion.token()
        if uuids:
            id_sol = solicitar_descarga_folio(fiel, token, fiel.rfc, list(uuids))
        else:
            id_sol = solicitar_descarga(
                fiel=fiel, token=token, rfc_solicitante=fiel.rfc,
                fecha_inicio=desde, fecha_fin=hasta,
                tipo_solicitud=tipo_solicitud, tipo_comprobante=direccion,
                # Recibidos solo admite Vigente para CFDI (v1.5); la metadata va con
                # todos los estatus: de ahí salen las cancelaciones.
                estado_comprobante="Todos" if tipo_solicitud == "Metadata" else "Vigente",
                # Sin el truco de variar los segundos ante un 5002 (gasta cuota).
                reintentar_5002=False,
            )
    except (requests.RequestException, ErrorEsperado) as e:
        return "transitorio", "", str(e)
    except RuntimeError as e:
        return _clasificar(str(e))
    except _ERRORES_DE_LECTURA as e:  # p. ej. una página HTML en lugar del SOAP
        logger.warning("[piloto] %s: respuesta inesperada del SAT", rfc, exc_info=True)
        return "transitorio", "", f"Respuesta inesperada del SAT: {e}"
    tipo = f"{tipo_solicitud} · folios" if uuids else f"{tipo_solicitud} · {_NOMBRE_DIR[direccion]}"
    config_store.save_solicitud(
        rfc, id_sol, desde.isoformat() if desde else "", hasta.isoformat() if hasta else "",
        tipo=tipo, tipo_comprobante=direccion, tipo_solicitud=tipo_solicitud,
        uuids=list(uuids) if uuids else None,
        origen="piloto", proposito=proposito, periodo=periodo,
    )
    logger.info("[piloto] %s: solicitud %s (%s, %s, %s a %s)", rfc, id_sol, proposito,
                tipo, desde, hasta)
    return "ok", id_sol, None


def _estado_solicitud(rfc: str, id_sol: str) -> str:
    """"viva" | "lista" (descargada o 5004) | "fallida"."""
    sol = config_store.get_solicitud(rfc, id_sol)
    if sol is None:
        return "fallida"
    estado = str(sol.get("estado") or "")
    if estado in _VIVAS:
        return "viva"
    if estado == "descargada":
        return "lista"
    # El 5004 de "sin información" viene en CodigoEstadoSolicitud; el CodEstatus es el de
    # la verificación misma (su 5004 es "no se encontró la solicitud").
    codigo = str(sol.get("codigo_estado_solicitud") or "")
    if estado == "5" and (codigo == "5004" or not (codigo or sol.get("cod_estatus"))):
        return "lista"  # sin información en el periodo (o guardada sin ningún código)
    return "fallida"


def _rangos(dias: list[date]) -> list[tuple[date, date]]:
    """Rangos contiguos que cubren `dias`, a lo más MAX_RANGOS (ver `calendario`)."""
    return calendario.rangos_contiguos(dias, MAX_RANGOS)


def _backoff(intentos: int, ahora: datetime) -> str:
    espera = REINTENTOS_S[min(max(intentos - 1, 0), len(REINTENTOS_S) - 1)]
    return _utc(ahora + timedelta(seconds=espera))


def _agotado_el_plazo(fallando_desde: Optional[str], ahora: datetime) -> bool:
    """¿Pasaron REINTENTOS_HORAS_MAX desde la primera falla transitoria seguida?
    (No desde que se creó la ejecución: esperar a la e.firma o a la metadata no
    gasta el plazo.)"""
    try:
        desde = datetime.fromisoformat(fallando_desde) if fallando_desde else None
    except (TypeError, ValueError):
        return False
    return desde is not None and ahora - desde > timedelta(hours=REINTENTOS_HORAS_MAX)


# ---------------------------------------------------------------------------
# Pasada diaria
# ---------------------------------------------------------------------------


def _cubiertos_por_vivas(rfc: str) -> set[tuple[str, str]]:
    cubiertos: set[tuple[str, str]] = set()
    for s in _vivas(rfc):
        # Una manual cubre el día solo si se guardó sin filtros (contraparte).
        if (s.get("uuids") or config_store.es_metadata(s)
                or (s.get("origen") != "piloto" and not s.get("sin_filtros"))):
            continue
        try:
            desde = date.fromisoformat(str(s.get("fecha_inicio"))[:10])
            hasta = date.fromisoformat(str(s.get("fecha_fin"))[:10])
        except ValueError:
            continue
        d = desde
        while d <= hasta:
            cubiertos.add((d.isoformat(), s.get("tipo_comprobante")))
            d += timedelta(days=1)
    return cubiertos


def ventana_diaria(rfc: str, d: date) -> dict[str, list[date]]:
    """Días a pedir en la pasada de `d`, por dirección: D-3…D-1 (rezago) que no
    estén cerrados ni en error, más los días por descargar desde la activación (o
    los últimos AL_CORRIENTE_DIAS), sin los que ya tienen una solicitud viva."""
    activado = _activado_en() or d
    inicio = max(d - timedelta(days=AL_CORRIENTE_DIAS), activado - timedelta(days=REZAGO_DIAS))
    fin = d - timedelta(days=1)
    if inicio > fin:
        return {"E": [], "R": []}
    calendario.sincronizar(rfc, inicio, fin)
    filas_ = calendario.filas(rfc, inicio, fin)
    # Ni lo que ya tiene una solicitud viva ni lo que otra pasada está reintentando.
    vivas = _cubiertos_por_vivas(rfc) | _dias_en_reintento(rfc, d.isoformat())
    rezago = d - timedelta(days=REZAGO_DIAS)
    out: dict[str, list[date]] = {"E": [], "R": []}
    dia = inicio
    while dia <= fin:
        for direccion in _DIRECCIONES:
            clave = (dia.isoformat(), direccion)
            estado = (filas_.get(clave) or {}).get("estado") or "pendiente"
            if clave in vivas or estado in ("consolidado", "diferencia", "error"):
                continue
            # Fuera del rezago solo se recupera lo que nadie ha pedido.
            if dia >= rezago or estado == "pendiente":
                out[direccion].append(dia)
        dia += timedelta(days=1)
    return out


def _diarias_en_curso(rfc: str, antes_de: str) -> list[dict]:
    """Pasadas de días anteriores que quedaron esperando un reintento: en curso
    (falla del SAT) o en error reintentable (la e.firma, hasta que se corrija)."""
    db = abrir_db()
    with db.cursor() as cur:
        periodos = [r[0] for r in cur.execute(
            "SELECT periodo FROM piloto_ejecuciones WHERE mi_rfc = ? AND tipo = 'diaria'"
            f" AND {_CON_TRABAJO} AND periodo < ? ORDER BY periodo",
            (rfc, antes_de),
        ).fetchall()]
    filas_ = (_fila(rfc, "diaria", p) for p in periodos)
    return [f for f in filas_ if f is not None
            and (f["estado"] == "en_curso" or (f.get("detalle") or {}).get("reintentable"))]


def _dias_en_reintento(rfc: str, antes_de: str) -> set[tuple[str, str]]:
    dias: set[tuple[str, str]] = set()
    for fila in _diarias_en_curso(rfc, antes_de):
        for r in (fila.get("detalle") or {}).get("rangos") or []:
            if r.get("estado") != "pendiente":
                continue
            d, fin = date.fromisoformat(r["desde"]), date.fromisoformat(r["hasta"])
            while d <= fin:
                dias.add((d.isoformat(), r["dir"]))
                d += timedelta(days=1)
    return dias


def _pasada_diaria(rfc: str, sesion: _SesionSat) -> bool:
    """Una pasada por empresa (más los reintentos de días anteriores que siguen en
    curso: una falla del SAT no se abandona al cambiar el día). True si pidió algo."""
    ahora = _ahora()
    d = ahora.date()
    periodo = d.isoformat()
    pidio = False
    for vieja in _diarias_en_curso(rfc, periodo):
        if _toca(vieja, ahora):
            pidio = _pedir_rangos(rfc, sesion, "diaria", vieja["periodo"], vieja,
                                  vieja["detalle"].get("rangos") or [], proposito="diaria") or pidio
    if ahora < _hora_programada(d):
        return pidio
    return _pasada_de_hoy(rfc, sesion, ahora, periodo) or pidio


def _pasada_de_hoy(rfc: str, sesion: _SesionSat, ahora: datetime, periodo: str) -> bool:
    d = ahora.date()
    fila = _fila(rfc, "diaria", periodo)
    if not _toca(fila, ahora):
        return False
    detalle = (fila or {}).get("detalle") or {}
    rangos = detalle.get("rangos")
    if rangos is None:
        ventana = ventana_diaria(rfc, d)
        rangos = [{"dir": direccion, "desde": a.isoformat(), "hasta": b.isoformat(),
                   "estado": "pendiente"}
                  for direccion in _DIRECCIONES for a, b in _rangos(ventana[direccion])]
        if fila is None and not _reservar(rfc, "diaria", periodo):
            return False
        if not rangos:
            _guardar(rfc, "diaria", periodo, estado="completa", detalle={"rangos": []})
            return False
    return _pedir_rangos(rfc, sesion, "diaria", periodo, fila, rangos, proposito="diaria")


def _pedir_rangos(rfc: str, sesion: _SesionSat, tipo: str, periodo: str, fila: Optional[dict],
                  rangos: list[dict], *, proposito: str, extra: Optional[dict] = None) -> bool:
    """Pide los rangos "pendiente" y aplica la regla de errores. True si tocó al SAT."""
    ahora = _ahora()
    intentos = int((fila or {}).get("intentos") or 0)
    fallando_desde = ((fila or {}).get("detalle") or {}).get("fallando_desde")
    transitorio = None
    pidio = False
    for r in rangos:
        if r["estado"] != "pendiente":
            continue
        desde, hasta = date.fromisoformat(r["desde"]), date.fromisoformat(r["hasta"])
        clase, a, b = _pedir(rfc, sesion, desde, hasta, r["dir"], proposito=proposito, periodo=periodo)
        pidio = True
        if clase == "ok":
            r.update(estado="pedida", id=a)
            calendario.marcar(rfc, desde, hasta, r["dir"], "en_proceso", solicitud_id=a)
        elif clase == "transitorio":
            transitorio = b
            calendario.marcar(rfc, desde, hasta, r["dir"], "en_proceso")
        elif clase == "duplicada":
            # Ya existe una igual en el SAT (quizá la pidió la otra instalación): no
            # se burla el 5005; los días quedan en proceso y el cierre los resuelve.
            r.update(estado="duplicada", codigo=a, mensaje=b)
            calendario.marcar(rfc, desde, hasta, r["dir"], "en_proceso")
        elif clase == "efirma":
            # El rango queda pendiente: cuando se corrija la e.firma (otra contraseña,
            # un certificado nuevo) se vuelve a intentar, a lo más cada 6 h.
            r.update(codigo=a, mensaje=b)
            _falla_efirma(rfc, a, b)
            calendario.marcar(rfc, desde, hasta, r["dir"], "error", error_codigo=a or "efirma",
                              error_mensaje=_texto_efirma(a, b))
            _guardar(rfc, tipo, periodo, estado="error", error_codigo=a or "efirma",
                     error_mensaje=b, intentos=intentos + 1,
                     proximo_intento=_utc(ahora + timedelta(seconds=EFIRMA_RECHEQUEO_S)),
                     detalle={**(extra or {}), "rangos": rangos, "reintentable": True})
            return pidio
        else:  # agotado (5002) y rechazos: error con motivo, sin reintentos
            r.update(estado="error", codigo=a, mensaje=b)
            calendario.marcar(rfc, desde, hasta, r["dir"], "error", error_codigo=a or clase,
                              error_mensaje=b)
    detalle = {**(extra or {}), "rangos": rangos}
    if transitorio is not None:
        intentos += 1
        detalle["fallando_desde"] = fallando_desde = fallando_desde or _utc(ahora)
        if _agotado_el_plazo(fallando_desde, ahora):
            for r in rangos:
                if r["estado"] == "pendiente":
                    r.update(estado="error", mensaje=transitorio)
                    # Sin forzar: un día que ya cerró el cierre o que tiene datos se queda.
                    calendario.marcar(rfc, date.fromisoformat(r["desde"]), date.fromisoformat(r["hasta"]),
                                      r["dir"], "error", error_codigo="sat",
                                      error_mensaje="El SAT no respondió en 3 días: " + transitorio,
                                      intentos=intentos)
            _guardar(rfc, tipo, periodo, estado="error", intentos=intentos,
                     error_mensaje=transitorio, detalle=detalle)
        else:
            _guardar(rfc, tipo, periodo, estado="en_curso", intentos=intentos,
                     proximo_intento=_backoff(intentos, ahora), error_mensaje=transitorio,
                     detalle=detalle)
        return pidio
    _guardar(rfc, tipo, periodo, estado="completa", proximo_intento=None, error_codigo=None,
             error_mensaje=None, detalle={k: v for k, v in detalle.items() if k != "reintentable"})
    return pidio


def _texto_efirma(codigo: str, mensaje: str) -> str:
    from ..webservice.errores import mensaje_rechazo

    return mensaje_rechazo(codigo, mensaje) if codigo else mensaje


def _falla_efirma(rfc: str, codigo: str, mensaje: str) -> None:
    _avisar("efirma", f"No se pudo usar la e.firma de {rfc} en la descarga automática: "
                      f"{_texto_efirma(codigo, mensaje)}", rfc=rfc,
            clave=f"efirma:{rfc}:{_ahora().date().isoformat()}")


# ---------------------------------------------------------------------------
# Cierre mensual
# ---------------------------------------------------------------------------


def meses_por_cerrar(rfc: str, hoy: Optional[date] = None) -> list[str]:
    """Meses que ya se pueden cerrar y no están completos, del más reciente al más
    antiguo: desde el mes previo a la activación hasta el mes anterior a hoy."""
    hoy = hoy or _ahora().date()
    activado = _activado_en()
    if activado is None:
        return []
    cfg = config()
    primero = _mes_anterior(_mes_de(activado))
    mes = _mes_anterior(_mes_de(hoy))
    out = []
    while mes >= primero:
        if hoy >= _fecha_cierre(mes, cfg.get("dia_cierre")):
            fila = _fila(rfc, "cierre", mes)
            if fila is None or fila["estado"] != "completa":
                out.append(mes)
        mes = _mes_anterior(mes)
    # Un cierre empezado se termina aunque su mes quede antes del primero (se
    # pausó y se reanudó, o lo reabrió un reintento).
    return out + [p for p in _cierres_empezados(rfc) if p < primero]


def _cierres_empezados(rfc: str) -> list[str]:
    """Cierres con trabajo pendiente (en curso o esperando a la e.firma), del más
    reciente al más antiguo. Los del historial no: esos los lleva
    `_avanzar_historial`, con su ritmo."""
    db = abrir_db()
    with db.cursor() as cur:
        periodos = [r[0] for r in cur.execute(
            "SELECT periodo FROM piloto_ejecuciones WHERE mi_rfc = ? AND tipo = 'cierre'"
            f" AND {_CON_TRABAJO} ORDER BY periodo DESC",
            (rfc,),
        ).fetchall()]
    filas_ = ((p, _fila(rfc, "cierre", p)) for p in periodos)
    return [p for p, f in filas_ if f is not None
            and (f.get("detalle") or {}).get("origen") != "historial"
            and (f["estado"] == "en_curso" or (f.get("detalle") or {}).get("reintentable"))]


def _hay_vivas_del_mes(rfc: str, ini: date, fin: date) -> bool:
    """¿Queda algo por llegar del mes? Solicitudes vivas o rangos de una pasada
    diaria esperando su reintento: el cierre compara cuando todo terminó."""
    if any(ini.isoformat() <= f <= fin.isoformat() for f, _d in _dias_en_reintento(rfc, "9999-12-31")):
        return True
    for s in _vivas(rfc):
        if s.get("proposito") == "cierre_metadata":
            continue
        try:
            desde = date.fromisoformat(str(s.get("fecha_inicio"))[:10])
            hasta = date.fromisoformat(str(s.get("fecha_fin"))[:10])
        except ValueError:
            continue
        if desde <= fin and hasta >= ini:
            return True
    return False


def _leer_metadata(rfc: str, ids: dict) -> tuple[list, list[str]]:
    """Registros de metadata de las solicitudes del cierre y las que no se pudieron
    leer completas: se borró la carpeta, un ZIP no abre o faltan paquetes. Comparar
    contra una metadata incompleta marcaría días como diferencia que no lo son."""
    from ..utils.metadata import extraer_metadata_de_directorio
    from ..webservice.descarga import zip_paquete
    from .state import _salida_descarga_ws

    registros: list = []
    ilegibles: list[str] = []
    for id_sol in ids.values():
        sol = config_store.get_solicitud(rfc, id_sol) or {}
        if sol.get("estado") == "5":  # 5004: sin información
            continue
        total = int(sol.get("numero_cfdis") or 0)
        salida = Path(_salida_descarga_ws(rfc, id_sol))
        if not salida.is_dir():
            if sol.get("numero_cfdis") is not None and total == 0:
                continue  # el SAT la dio lista sin paquetes: no hay nada que leer
            ilegibles.append(id_sol)
            continue
        errores: list = []
        leidos = extraer_metadata_de_directorio(str(salida), errores=errores)
        # En local el ZIP de cada paquete se conserva: si falta el de alguno (se borró,
        # quedó solo un TXT), la metadata está incompleta. Se busca el de cada uno: la
        # carpeta es del rango y la comparten las solicitudes de la misma ventana.
        falta_zip = any(not zip_paquete(salida, pid).is_file() for pid in sol.get("package_ids") or [])
        if errores or (not leidos and total > 0) or falta_zip:
            ilegibles.append(id_sol)
            continue
        registros.extend(leidos)
    return registros, ilegibles


def _cancelaciones(rfc: str, periodo: str, registros: list, avisar: bool = True) -> int:
    """Aplica las cancelaciones de la metadata; avisa las de meses anteriores al que
    se cierra (ya cerrados: pueden mover una deducción ya declarada). El historial
    las aplica sin avisar: es importar historia, no un mes que el usuario ya declaró
    con la app."""
    canceladas = {r.uuid.upper(): (r.fecha_cancelacion or "")[:19] or None
                  for r in registros if str(r.estatus).strip() == "0" and r.uuid}
    nuevas = calendario.aplicar_cancelaciones(rfc, canceladas)
    previas = sorted((fecha[:7], uuid.upper()) for uuid, fecha in nuevas if fecha[:7] < periodo)
    if avisar and previas:
        _avisar_cancelaciones(rfc, previas)
    return len(nuevas)


def _avisar_cancelaciones(rfc: str, previas: list[tuple[str, str]]) -> None:
    """Un solo aviso por comparación: el primer cierre puede traer de golpe las
    cancelaciones de todo un año que el índice no conocía."""
    if len(previas) == 1:
        mes, uuid = previas[0]
        texto = (f"Se canceló un CFDI de {_nombre_mes(mes)} de {rfc} ({uuid}). Si ese mes ya "
                 "está declarado, revisa si cambia una deducción o el IVA acreditable.")
    else:
        por_mes = sorted(Counter(m for m, _u in previas).items())
        meses = ", ".join(f"{n} de {_nombre_mes(m)}" for m, n in por_mes)
        texto = (f"Se cancelaron {len(previas)} CFDI de meses anteriores de {rfc} ({meses}). Si "
                 "esos meses ya están declarados, revisa si cambia una deducción o el IVA "
                 "acreditable.")
    huella = hashlib.sha256(",".join(u for _m, u in previas).encode()).hexdigest()[:16]
    _avisar("cancelacion", texto, rfc=rfc, periodo=previas[0][0],
            clave=f"cancelacion:{rfc}:{huella}")


def _comparar(rfc: str, periodo: str, registros: list) -> tuple[dict, dict, set]:
    """→ (sat, bd, todos): vigentes del SAT y del índice por (día, dirección) del
    mes, y todo UUID que el SAT conoce en la ventana (cualquier estatus)."""
    ini, fin = _limites_mes(periodo)
    sat: dict[tuple[str, str], set] = {}
    todos: set[str] = set()
    for r in registros:
        uuid = (r.uuid or "").upper()
        todos.add(uuid)
        dia = (r.fecha_emision or "")[:10]
        if not (ini.isoformat() <= dia <= fin.isoformat()) or str(r.estatus).strip() != "1":
            continue
        if (r.rfc_emisor or "").strip().upper() == rfc:
            sat.setdefault((dia, "E"), set()).add(uuid)
        if (r.rfc_receptor or "").strip().upper() == rfc:
            sat.setdefault((dia, "R"), set()).add(uuid)
    bd = calendario.uuids_por_dia(rfc, ini, fin)
    return sat, bd, todos


# Lo que se conserva del detalle de un cierre al volver a pedir su metadata: de qué
# cierre se trata (un mes del historial) y el plazo que lleva fallando.
_CONSERVAR_AL_REINICIAR = ("origen", "iniciado", "fallando_desde", "canceladas",
                           "reintentos_metadata")


def _reinicio(detalle: dict, **extra) -> dict:
    """Detalle para volver al paso "inicio": se queda lo que identifica al cierre y
    el plazo que lleva fallando; lo de la metadata anterior, no."""
    return {"paso": "inicio", **{k: detalle[k] for k in _CONSERVAR_AL_REINICIAR if k in detalle},
            **extra}


def _sin(detalle: dict, *llaves: str) -> dict:
    return {k: v for k, v in detalle.items() if k not in llaves}


def _avanzar_cierre(rfc: str, sesion: _SesionSat, periodo: str, historial: bool = False) -> bool:
    """Un paso del cierre de `periodo`. True si pidió algo al SAT. `historial` solo
    importa al reservar el mes; un mes que se retoma lee `origen` de su detalle."""
    ahora = _ahora()
    fila = _fila(rfc, "cierre", periodo)
    if not _toca(fila, ahora):
        return False
    detalle = (fila or {}).get("detalle") or {}
    es_historial = detalle.get("origen") == "historial" or (fila is None and historial)
    paso = detalle.get("paso", "inicio")
    ini, fin = _limites_mes(periodo)

    if paso == "inicio":
        if _hay_vivas_del_mes(rfc, ini, fin):
            return False  # las diarias que tocan el mes todavía no terminan
        if fila is None:
            reserva = {"paso": "inicio", "origen": "historial",
                       "iniciado": ahora.date().isoformat()} if es_historial else None
            if not _reservar(rfc, "cierre", periodo, reserva):
                return False
            fila = _fila(rfc, "cierre", periodo)
            detalle = (fila or {}).get("detalle") or {}
        if es_historial and not detalle.get("metadata_parcial"):
            previa = _metadata_reusable(rfc, periodo)
            if previa is not None:
                # La metadata de 12 meses de un cierre normal ya cubre este mes: no se
                # pide otra vez al SAT.
                ids, ventana = previa
                _guardar(rfc, "cierre", periodo, estado="en_curso", proximo_intento=None,
                         detalle={**_sin(detalle, "fallando_desde"), "paso": "metadata",
                                  "metadata": ids, "ventana": ventana})
                return False
        # Un mes del historial pide solo su mes: las ventanas de los meses vecinos se
        # encimarían MESES_METADATA veces.
        ventana_ini = ini if es_historial else _limites_mes(
            _restar_meses(periodo, MESES_METADATA - 1))[0]
        # Lo que ya se pidió en un intento anterior no se vuelve a pedir.
        ids, error = dict(detalle.get("metadata_parcial") or {}), None
        for direccion in _DIRECCIONES:
            if direccion in ids:
                continue
            clase, a, b = _pedir(rfc, sesion, ventana_ini, fin, direccion, tipo_solicitud="Metadata",
                                 proposito="cierre_metadata", periodo=periodo)
            if clase == "duplicada":
                # El SAT ya tiene una igual: se usa la nuestra si existe; si no (la
                # pidió otra instalación), se espera como a una falla del SAT.
                previa = _igual(rfc, ventana_ini, fin, direccion, "Metadata", None, listas=True)
                clase, a, b = ("ok", previa, None) if previa else (
                    "transitorio", a, "El SAT ya tiene una solicitud igual; se espera a que termine.")
            if clase == "ok":
                ids[direccion] = a
            else:
                error = (clase, a, b)
                break
        if error is None:
            _guardar(rfc, "cierre", periodo, estado="en_curso", proximo_intento=None,
                     detalle={**_sin(detalle, "metadata_parcial", "fallando_desde"),
                              "paso": "metadata", "metadata": ids,
                              "ventana": [ventana_ini.isoformat(), fin.isoformat()]})
        else:
            _falla_cierre(rfc, periodo, fila, *error, detalle={**detalle, "metadata_parcial": ids})
        return True

    if paso == "metadata":
        estados = {d: _estado_solicitud(rfc, i) for d, i in detalle["metadata"].items()}
        if "viva" in estados.values():
            return False
        if "fallida" in estados.values():
            # Se vuelve a pedir la que falló (cuenta como reintento transitorio); la
            # que sí llegó se conserva.
            buenas = {d: i for d, i in detalle["metadata"].items() if estados[d] == "lista"}
            _metadata_otra_vez(rfc, periodo, fila, detalle, "no se pudo completar",
                               metadata_parcial=buenas)
            return False
        paso = "comparar"

    if paso == "faltantes":
        if any(_estado_solicitud(rfc, i) == "viva" for i in detalle.get("faltantes", [])):
            return False
        paso = "comparar"  # lo que bajó lo indexa el poller; comparar espera a que termine

    # paso == "comparar". El poller indexa lo que baja en segundo plano: se espera a
    # que termine (si tarda, se compara en la siguiente vuelta).
    from ..procesador import indexar

    if not indexar.esperar_indexado(rfc, INDEXADO_ESPERA_S):
        return False
    registros, ilegibles = _leer_metadata(rfc, detalle["metadata"])
    if ilegibles:
        logger.warning("[piloto] %s: la metadata de %s no se pudo leer completa", rfc, periodo)
        _metadata_ilegible(rfc, periodo, fila, detalle, ilegibles)
        return False
    canceladas = int(detalle.get("canceladas") or 0) + _cancelaciones(
        rfc, periodo, registros, avisar=not es_historial)
    sat, bd, todos = _comparar(rfc, periodo, registros)
    faltantes = {k: sat[k] - bd.get(k, set()) for k in sat if sat[k] - bd.get(k, set())}
    if faltantes and not detalle.get("faltantes_pedidos"):
        ids, falla = _pedir_faltantes(rfc, sesion, periodo, faltantes)
        siguiente = {**_sin(detalle, "fallando_desde"), "paso": "faltantes", "faltantes": ids,
                     "canceladas": canceladas}
        if falla is None:
            _guardar(rfc, "cierre", periodo, estado="en_curso", proximo_intento=None,
                     detalle={**siguiente, "faltantes_pedidos": True})
        else:
            # Lo que sí se pidió se espera; lo que falta se vuelve a pedir después.
            _falla_cierre(rfc, periodo, fila, *falla,
                          detalle={**siguiente, "fallando_desde": detalle.get("fallando_desde")})
        return True
    resumen = _cerrar_mes(rfc, periodo, sat, bd, todos, faltantes)
    resumen["canceladas"] = canceladas
    _guardar(rfc, "cierre", periodo, estado="completa", proximo_intento=None, error_codigo=None,
             error_mensaje=None,
             detalle={**_sin(detalle, "reintentable", "fallando_desde", "metadata_parcial",
                             "reintentos_metadata"),
                      "paso": "hecho", "resumen": resumen, "canceladas": canceladas})
    if es_historial:
        _resumen_historial()
    else:
        _resumen_si_toca(periodo)
    return False


def _metadata_reusable(rfc: str, periodo: str) -> Optional[tuple[dict, list]]:
    """Metadata de un cierre normal ya completo cuya ventana cubre `periodo`, si sus
    solicitudes siguen descargadas y legibles: (ids por dirección, ventana)."""
    ini, fin = _limites_mes(periodo)
    for fila in sorted(_cierres(rfc).values(), key=lambda f: f["actualizado_en"] or "", reverse=True):
        d = fila["detalle"]
        ids, ventana = d.get("metadata"), d.get("ventana")
        if (fila["estado"] != "completa" or d.get("origen") == "historial"
                or not isinstance(ids, dict) or set(ids) != set(_DIRECCIONES)
                or not isinstance(ventana, list) or len(ventana) != 2):
            continue
        if not (ventana[0] <= ini.isoformat() and fin.isoformat() <= ventana[1]):
            continue
        sols = [config_store.get_solicitud(rfc, i) or {} for i in ids.values()]
        if all(_metadata_lista(s) for s in sols):
            return dict(ids), list(ventana)
    return None


def _metadata_lista(sol: dict) -> bool:
    """¿Esa solicitud de metadata sirve para comparar otro mes? Descargada y legible, o
    rechazada con CodigoEstadoSolicitud 5004 (el SAT dijo que no hay datos). Más estricta
    que `_estado_solicitud` y `calendario._candidato` a propósito: por compatibilidad, esas
    aceptan solicitudes guardadas sin el código (de antes de que se guardara), y la metadata
    del piloto lo trae (lo guarda la verificación del poller); reusarla para otro mes pide
    la respuesta explícita del SAT."""
    if sol.get("ilegible"):
        return False
    if sol.get("estado") == "descargada":
        return True
    return sol.get("estado") == "5" and str(sol.get("codigo_estado_solicitud") or "") == "5004"


def _metadata_ilegible(rfc: str, periodo: str, fila: Optional[dict], detalle: dict,
                       ilegibles: list[str]) -> None:
    """La metadata que bajó no se pudo leer completa. Pedirla igual otra vez contesta
    5005, así que se vuelve a bajar la misma (sus paquetes duran 72 h en el SAT; si
    ya vencieron, el poller la marca vencida y el cierre la pide de nuevo)."""
    if _ultimo_intento_metadata(detalle):
        # No se gasta otra descarga del paquete que nadie va a leer.
        _metadata_otra_vez(rfc, periodo, fila, detalle, "descargada no se pudo leer")
        return
    for id_sol in ilegibles:
        sol = config_store.get_solicitud(rfc, id_sol) or {}
        if sol.get("package_ids") and not sol.get("rebajada") and _paquetes_vigentes(sol):
            # Una sola vez: el SAT limita cuántas veces se baja un paquete (5008).
            config_store.marcar_solicitud(rfc, id_sol, rebajada=True)
            config_store.update_solicitud(rfc, id_sol, "3")  # el poller la vuelve a bajar
        else:
            config_store.marcar_solicitud(rfc, id_sol, ilegible=True)
    if all((config_store.get_solicitud(rfc, i) or {}).get("estado") == "3" for i in ilegibles):
        _metadata_otra_vez(rfc, periodo, fila, detalle, "descargada no se pudo leer",
                           esperar=True)
        return
    buenas = {d: i for d, i in detalle["metadata"].items() if i not in ilegibles}
    _metadata_otra_vez(rfc, periodo, fila, detalle, "descargada no se pudo leer",
                       metadata_parcial=buenas)


def _ultimo_intento_metadata(detalle: dict) -> bool:
    """¿El siguiente intento de la metadata ya es el último permitido?"""
    return int(detalle.get("reintentos_metadata") or 0) + 1 >= METADATA_INTENTOS_MAX


def _paquetes_vigentes(sol: dict) -> bool:
    """¿Los paquetes de la solicitud siguen en el SAT? Duran 72 h desde que quedó
    lista (con una hora de margen)."""
    try:
        lista = datetime.fromisoformat(str(sol.get("lista_en")))
    except (TypeError, ValueError):
        return False
    horas = config_store.SOLICITUD_VENCIMIENTO_HORAS - 1
    return datetime.now(lista.tzinfo) - lista < timedelta(hours=horas)


def _metadata_otra_vez(rfc: str, periodo: str, fila: Optional[dict], detalle: dict,
                       motivo: str, *, esperar: bool = False, **extra) -> None:
    """La metadata no se completó o no se pudo leer: se vuelve a pedir con la
    espera de una falla del SAT, y a la METADATA_INTENTOS_MAX el cierre queda en
    error (pedirla bien no reinicia nada: sin tope, daría vueltas para siempre)."""
    n = int(detalle.get("reintentos_metadata") or 0) + 1
    if n >= METADATA_INTENTOS_MAX:
        _falla_cierre(rfc, periodo, fila, "rechazo", "",
                      f"La metadata del SAT {motivo} ({n} intentos)", detalle=_reinicio(detalle))
        return
    if esperar:
        # Se vuelve a bajar la misma: se espera en el paso "metadata", y la
        # comparación que siga es nueva (puede volver a pedir lo que falte).
        _guardar(rfc, "cierre", periodo, estado="en_curso", proximo_intento=None,
                 detalle={**_sin(detalle, "faltantes", "faltantes_pedidos"), "paso": "metadata",
                          "reintentos_metadata": n})
        return
    _falla_cierre(rfc, periodo, fila, "transitorio", "", f"La metadata del SAT {motivo}",
                  detalle=_reinicio(detalle, reintentos_metadata=n, **extra))


def _restar_meses(periodo: str, n: int) -> str:
    for _ in range(n):
        periodo = _mes_anterior(periodo)
    return periodo


def _pedir_faltantes(rfc: str, sesion: _SesionSat, periodo: str,
                     faltantes: dict) -> tuple[list[str], Optional[tuple[str, str, str]]]:
    """Pide los XML que el SAT lista y la base no tiene: por UUID si son pocos, si
    no por los días donde faltan. Devuelve (ids pedidos, falla): la falla es la
    primera transitoria o de e.firma (lo demás se vuelve a pedir en el reintento);
    un 5002 o un rechazo dejan ese rango en diferencia."""
    uuids = sorted(set().union(*faltantes.values()))
    if len(uuids) <= FOLIOS_MAX:
        clase, a, b = _pedir(rfc, sesion, None, None, "R", proposito="cierre_faltantes",
                             periodo=periodo, uuids=uuids)
        if clase == "ok":
            return [a], None
        if clase == "efirma":
            return [], (clase, a, b)
        # Cualquier otra falla (el SAT real puede no aceptar varios folios, y lo dice
        # con un SOAP Fault sin CodEstatus), 5002 o 5005: por días. Si el SAT está
        # caído, la primera de esas falla igual y el cierre espera.
    ids: list[str] = []
    for direccion in _DIRECCIONES:
        dias = [date.fromisoformat(f) for (f, d) in faltantes if d == direccion]
        for desde, hasta in _rangos(dias):
            clase, a, b = _pedir(rfc, sesion, desde, hasta, direccion, proposito="cierre_faltantes",
                                 periodo=periodo)
            if clase == "duplicada":
                # El SAT ya tiene una igual: se usa si la conocemos. Si no (una manual de
                # antes, otra instalación), seguirá contestando 5005 aunque se espere:
                # ese rango queda en diferencia (se ve y se puede reintentar por día) y
                # se siguen pidiendo los demás.
                previa = _igual(rfc, desde, hasta, direccion, "CFDI", None, listas=True,
                                manuales=True)
                if previa:
                    clase, a = "ok", previa
                else:
                    logger.info("[piloto] %s: %s a %s (%s) ya pedido igual (5005)", rfc, desde,
                                hasta, direccion)
            if clase == "ok":
                ids.append(a)
            elif clase in ("transitorio", "efirma"):
                return ids, (clase, a, b)
    return ids, None


def _cerrar_mes(rfc: str, periodo: str, sat: dict, bd: dict, todos: set, faltantes: dict) -> dict:
    ini, fin = _limites_mes(periodo)
    resultados = {}
    diferencias = 0
    dia = ini
    while dia <= fin:
        for direccion in _DIRECCIONES:
            clave = (dia.isoformat(), direccion)
            s, b = sat.get(clave, set()), bd.get(clave, set())
            faltan = sorted(s - b)
            sobran = sorted(b - todos)  # vigentes en la base que el SAT no conoce
            if faltan or sobran:
                diferencias += 1
                partes = [f"SAT {len(s)} · BD {len(b)}"]
                if faltan:
                    partes.append(f"faltan en la base: {', '.join(faltan[:20])}"
                                  + (" …" if len(faltan) > 20 else ""))
                if sobran:
                    partes.append(f"el SAT no lista: {', '.join(sobran[:20])}"
                                  + (" …" if len(sobran) > 20 else ""))
                resultados[clave] = ("diferencia", len(s), "; ".join(partes))
            else:
                resultados[clave] = ("consolidado", len(s), None)
        dia += timedelta(days=1)
    calendario.cerrar_dias(rfc, resultados)
    return {"dias_con_diferencia": diferencias,
            "faltantes": sum(len(v) for v in faltantes.values())}


def _falla_cierre(rfc: str, periodo: str, fila: Optional[dict], clase: str, codigo: str,
                  mensaje: str, *, detalle: Optional[dict] = None) -> None:
    """Aplica la regla de errores a un paso del cierre. `detalle`: con qué queda la
    fila (por omisión, el que tenía)."""
    ahora = _ahora()
    intentos = int((fila or {}).get("intentos") or 0) + 1
    if detalle is None:
        detalle = (fila or {}).get("detalle") or {"paso": "inicio"}
    detalle = _sin(detalle, "reintentable")
    es_historial = detalle.get("origen") == "historial"
    if clase == "efirma":
        # Se reintenta cuando se corrija la e.firma (a lo más cada 6 h); no es un
        # cierre fallido para el resumen ni gasta el plazo de las fallas del SAT.
        _falla_efirma(rfc, codigo, mensaje)
        _guardar(rfc, "cierre", periodo, estado="error", intentos=intentos,
                 error_codigo=codigo or "efirma", error_mensaje=mensaje,
                 proximo_intento=_utc(ahora + timedelta(seconds=EFIRMA_RECHEQUEO_S)),
                 detalle={**_sin(detalle, "fallando_desde"), "reintentable": True})
        return
    if clase == "transitorio":
        detalle["fallando_desde"] = detalle.get("fallando_desde") or _utc(ahora)
        if not _agotado_el_plazo(detalle["fallando_desde"], ahora):
            _guardar(rfc, "cierre", periodo, estado="en_curso", intentos=intentos,
                     proximo_intento=_backoff(intentos, ahora), error_codigo=codigo or None,
                     error_mensaje=mensaje, detalle=detalle)
            return
    _guardar(rfc, "cierre", periodo, estado="error", intentos=intentos, error_codigo=codigo or None,
             error_mensaje=mensaje, detalle=detalle)
    if es_historial:
        # Sin aviso por mes: el aviso final del historial ya cuenta los que no se pudieron cerrar.
        _resumen_historial()
        return
    _avisar("error", f"No se pudo cerrar {_nombre_mes(periodo)} de {rfc}: {mensaje}", rfc=rfc,
            periodo=periodo, clave=f"cierre-error:{rfc}:{periodo}")
    _resumen_si_toca(periodo)


def _resumen_si_toca(periodo: str) -> None:
    """Un solo aviso cuando todas las empresas incluidas terminaron el cierre del mes."""
    hoy = _ahora().date()
    empresas = [e for e in config_store.list_empresas() if _motivo_no_elegible(e, hoy) is None]
    if not empresas:
        return
    filas_ = {e["rfc"]: _fila(e["rfc"], "cierre", periodo) for e in empresas}
    if not all(_terminada(f) for f in filas_.values()):
        return
    nombres = {e["rfc"]: e.get("nombre") or e["rfc"] for e in empresas}
    con_diferencias = [nombres[r] for r, f in filas_.items() if f["estado"] == "completa"
                       and (f["detalle"].get("resumen") or {}).get("dias_con_diferencia")]
    fallidas = [nombres[r] for r, f in filas_.items() if f["estado"] == "error"]
    completas = len(empresas) - len(con_diferencias) - len(fallidas)
    mes = _nombre_mes(periodo)
    if not con_diferencias and not fallidas:
        texto = (f"Tus {len(empresas)} empresas tienen {mes} completo." if len(empresas) > 1
                 else f"Tu empresa tiene {mes} completo.")
    else:
        partes = [f"{completas} de {len(empresas)} empresas tienen {mes} completo"]
        if con_diferencias:
            partes.append(f"con diferencias contra el SAT: {', '.join(con_diferencias)}")
        if fallidas:
            partes.append(f"no se pudo cerrar: {', '.join(fallidas)}")
        texto = "; ".join(partes) + "."
    _avisar("resumen", texto, periodo=periodo, clave=f"resumen:{periodo}")


# ---------------------------------------------------------------------------
# Historial (fase 5)
# ---------------------------------------------------------------------------


def historial_minimo(hoy: Optional[date] = None) -> date:
    """Primer mes que el WS v1.5 todavía entrega: el siguiente al de hoy hace 5 años.
    Se calcula con un margen (HISTORIAL_MARGEN_DIAS): un mes que se empieza puede seguir
    pidiendo días al SAT un par de días después, y no se empieza uno que en esos días
    quede fuera de los 5 años."""
    hoy = (hoy or _ahora().date()) + timedelta(days=HISTORIAL_MARGEN_DIAS)
    anio, mes = hoy.year - HISTORIAL_ANIOS, hoy.month + 1
    return date(anio + 1, 1, 1) if mes == 13 else date(anio, mes, 1)


def historial_maximo() -> date:
    """Último mes que admite el historial: el anterior al primer cierre del piloto.
    Con el piloto apagado se calcula como si se activara hoy (activar o reanudar mueve
    `activado_en` a hoy, ver `configurar`)."""
    hoy = _ahora().date()
    activado = (_activado_en() or hoy) if config().get("activo") else hoy
    primer_cierre = _mes_anterior(_mes_de(activado))
    mes = _mes_anterior(primer_cierre)
    return date(int(mes[:4]), int(mes[5:7]), 1)


def _historial_desde() -> Optional[date]:
    try:
        valor = config().get("historial_desde")
        return date.fromisoformat(str(valor)[:10]).replace(day=1) if valor else None
    except ValueError:
        return None


def _meses_rango(hoy: date) -> list[str]:
    """Meses del historial elegido, del más reciente al más antiguo (sin descontar
    los completos). Vacío sin `historial_desde` ni piloto activado."""
    desde = _historial_desde()
    if desde is None or _activado_en() is None:
        return []
    desde = max(desde, historial_minimo(hoy))
    mes, tope = _mes_de(historial_maximo()), _mes_de(desde)
    out = []
    while mes >= tope:
        out.append(mes)
        mes = _mes_anterior(mes)
    return out


def _cierres(rfc: Optional[str] = None, desde: Optional[str] = None,
             hasta: Optional[str] = None) -> dict[tuple[str, str], dict]:
    """Las filas de cierre, por (rfc, periodo): las de la empresa `rfc`, o todas;
    `desde` y `hasta` (YYYY-MM) acotan el rango de periodos en la consulta."""
    db = abrir_db()
    sql = "SELECT mi_rfc, periodo, estado, detalle, actualizado_en FROM piloto_ejecuciones WHERE tipo = 'cierre'"
    params: list = []
    if rfc:
        sql += " AND mi_rfc = ?"
        params.append(rfc)
    if desde:
        sql += " AND periodo >= ?"
        params.append(desde)
    if hasta:
        sql += " AND periodo <= ?"
        params.append(hasta)
    with db.cursor() as cur:
        filas_ = cur.execute(sql, tuple(params)).fetchall()
    out = {}
    for r in filas_:
        try:
            detalle = json.loads(r["detalle"] or "{}")
        except ValueError:
            detalle = {}
        out[(r["mi_rfc"], r["periodo"])] = {"estado": r["estado"], "detalle": detalle,
                                            "actualizado_en": r["actualizado_en"]}
    return out


def _iniciados_hoy(hoy: date) -> list[str]:
    """RFC de cada mes del historial que se empezó hoy (todas las empresas), sin leer
    ni decodificar el resto de los cierres."""
    db = abrir_db()
    with db.cursor() as cur:
        filas_ = cur.execute(
            "SELECT mi_rfc FROM piloto_ejecuciones WHERE tipo = 'cierre' AND detalle LIKE ?"
            " AND detalle LIKE ?",
            ('%' + json.dumps({"origen": "historial"})[1:-1] + '%',
             '%' + json.dumps({"iniciado": hoy.isoformat()})[1:-1] + '%'),
        ).fetchall()
    return [r["mi_rfc"] for r in filas_]


def _rfc(emp: dict) -> str:
    """RFC de una empresa del catálogo como lo guarda `piloto_ejecuciones` (sin
    validar: un RFC raro no debe tumbar el estado ni el resumen)."""
    return str(emp.get("rfc") or "").strip().upper()


def meses_de_historial(rfc: str, hoy: Optional[date] = None,
                       cierres: Optional[dict] = None) -> list[str]:
    """Meses del historial que faltan (no completos), del más reciente al más antiguo:
    desde el mes anterior al primer cierre hasta `historial_desde`. `cierres`: la
    lectura de `_cierres()` si el llamador ya la tiene."""
    hoy = hoy or _ahora().date()
    if cierres is None:
        cierres = _cierres(rfc)
    return [m for m in _meses_rango(hoy) if (cierres.get((rfc, m)) or {}).get("estado") != "completa"]


def _avanzar_historial(rfc: str, sesion: _SesionSat, hoy: date) -> bool:
    """Un paso del historial de la empresa: primero los meses ya empezados (sin
    límite), luego a lo más un mes nuevo por empresa y por día (y
    HISTORIAL_MESES_POR_DIA_CUENTA por cuenta). True si pidió algo al SAT."""
    if _ahora() < _hora_programada(hoy):
        return False
    cierres = _cierres(rfc)
    empezados = sorted((p for (r, p), f in cierres.items()
                        if f["estado"] != "completa"
                        and f["detalle"].get("origen") == "historial"), reverse=True)
    for mes in empezados:
        if _avanzar_cierre(rfc, sesion, mes):
            return True
    de_hoy = _iniciados_hoy(hoy)
    if de_hoy.count(rfc) >= HISTORIAL_MESES_POR_DIA or len(de_hoy) >= HISTORIAL_MESES_POR_DIA_CUENTA:
        return False
    for mes in meses_de_historial(rfc, hoy, cierres=cierres):
        if (rfc, mes) in cierres:
            continue
        pidio = _avanzar_cierre(rfc, sesion, mes, historial=True)
        if _fila(rfc, "cierre", mes) is not None:
            return pidio  # se reservó: es el mes nuevo de hoy
    return False


def _resumen_historial() -> None:
    """Avisa cuando todas las empresas incluidas terminaron todo el historial: una vez por
    elección del usuario y otra, solo de lo nuevo, si después se suman meses (al reanudar)
    o empresas que el historial llena. `historial_revisado` guarda hasta qué mes ya se
    revisó completa cada empresa: eso no se vuelve a leer ni a anunciar."""
    hoy = _ahora().date()
    cfg = config()
    desde = _historial_desde()
    meses = _meses_rango(hoy)
    nombres = {_rfc(e): e.get("nombre") or _rfc(e) for e in config_store.list_empresas()
               if _motivo_no_elegible(e, hoy) is None}
    rfcs = sorted(nombres)
    if desde is None or not meses or not rfcs:
        return
    # La base sale de lo que eligió el usuario, no del rango: `historial_minimo` avanza
    # cada mes y un historial terminado no debe volver a anunciarse.
    fijado = cfg.get("historial_fijado_en")
    base = f"historial:{desde.isoformat()}" + (f":{fijado}" if fijado else "")
    revisado = cfg.get("historial_revisado")
    if not isinstance(revisado, dict) or revisado.get("clave") != base:
        revisado = {"clave": base, "hasta": {}, "avisos": 0}
    hasta = dict(revisado.get("hasta") or {})
    if all(hasta.get(r, "") >= meses[0] for r in rfcs):
        return  # nada nuevo desde la última revisión
    cierres = _cierres(desde=meses[-1], hasta=meses[0])  # solo los del rango
    todas, nuevas = [], []
    for r in rfcs:
        for m in meses:
            f = cierres.get((r, m))
            if not _terminada(f):
                return
            todas.append((r, m, f))
            if m > hasta.get(r, ""):
                nuevas.append((r, m, f))
    # Solo se avisa lo que llenó el historial después de fijarlo: un rango que ya estaba
    # completo, o meses que al reanudar entran ya cerrados por el cierre normal, no.
    llenas = [(r, m, f) for r, m, f in nuevas
              if f["detalle"].get("origen") == "historial"
              and (not fijado or (f.get("actualizado_en") or "") >= fijado)]
    if llenas:
        # La primera revisión de esta elección habla de todo el rango; las siguientes,
        # solo de lo que el historial sumó.
        primero = not hasta
        filas_ = todas if primero else llenas
        de = {r for r, _m, _f in filas_}
        # Si lo sumado es de una sola de varias empresas, el aviso dice de cuál.
        sola = next(iter(de)) if not primero and len(de) == 1 and len(rfcs) > 1 else None
        avisos = int(revisado.get("avisos") or 0)
        _avisar("resumen", _texto_historial(meses[-1], filas_, primero,
                                            empresa=nombres[sola] if sola else None),
                rfc=sola, periodo=min(m for _r, m, _f in filas_), clave=f"{base}:{avisos}")
        revisado["avisos"] = avisos + 1
    config_store.set_piloto_config({"historial_revisado": {
        **revisado, "hasta": {**hasta, **{r: meses[0] for r in rfcs}}}})


def _texto_historial(desde_mes: str, filas_: list[tuple[str, str, dict]], primero: bool,
                     empresa: Optional[str] = None) -> str:
    """El primer aviso habla de todo el rango; los siguientes, solo de lo que el historial
    sumó (de `empresa`, si viene). Con varias empresas cuenta cierres (un mes por
    empresa)."""
    completas = [f for _r, _m, f in filas_ if f["estado"] == "completa"]
    n = len(completas)
    con_diferencias = sum(1 for f in completas if (f["detalle"].get("resumen") or {}).get("dias_con_diferencia"))
    fallidos = len(filas_) - n
    rfcs = sorted({r for r, _m, _f in filas_})
    if len(rfcs) == 1:
        cuenta = f"{n} {'mes' if n == 1 else 'meses'}, {con_diferencias} con diferencias."
        para = ""
    else:
        cuenta = (f"{n} {'cierre' if n == 1 else 'cierres'} (un mes por empresa), "
                  f"{con_diferencias} con diferencias.")
        para = f" para {len(rfcs)} empresas"
    if primero:
        texto = f"El historial desde {_nombre_mes(desde_mes)} ya está en la base{para}: {cuenta}"
    else:
        de = f" de {empresa}" if empresa else ""
        meses_ = _meses_en_palabras([m for _r, m, _f in filas_])
        texto = f"Ya está en la base lo que se sumó al historial{de} ({meses_}){para}: {cuenta}"
    if fallidos:
        texto += f" {fallidos} no se {'pudo' if fallidos == 1 else 'pudieron'} cerrar."
    return texto


def _meses_en_palabras(periodos: list[str]) -> str:
    """Los meses en palabras, los seguidos en tramos: "julio de 2026", "julio de 2026 a
    octubre de 2026" o "enero de 2025 a mayo de 2025 y julio de 2025"."""
    tramos: list[list[str]] = []
    for p in sorted(set(periodos)):
        if tramos and _mes_anterior(p) == tramos[-1][-1]:
            tramos[-1].append(p)
        else:
            tramos.append([p])
    textos = [_nombre_mes(t[0]) if len(t) == 1 else f"{_nombre_mes(t[0])} a {_nombre_mes(t[-1])}"
              for t in tramos]
    return textos[0] if len(textos) == 1 else ", ".join(textos[:-1]) + f" y {textos[-1]}"


# ---------------------------------------------------------------------------
# Evaluación
# ---------------------------------------------------------------------------


def pausado_por() -> Optional[str]:
    """Por qué no corre (None = corre): inactivo, licencia o sesión."""
    if not config().get("activo"):
        return "inactivo"
    if not disponible():
        return "licencia"
    if _sesion_cerrada():
        return "sesion"
    return None


def evaluar() -> dict:
    """Una evaluación completa: cierres y pasada diaria de cada empresa incluida."""
    if not _evaluando.acquire(blocking=False):
        return {"corrio": False, "motivo": "ocupado"}
    try:
        motivo = pausado_por()
        if motivo:
            return {"corrio": False, "motivo": motivo}
        hoy = _ahora().date()
        hechas = 0
        for emp in config_store.list_empresas():
            if _stop.is_set():
                break
            if _motivo_no_elegible(emp, hoy):
                continue
            pidio = False
            try:
                rfc = normalizar_mi_rfc(emp["rfc"])
                sesion = _SesionSat(rfc)
                _reabrir_cierres_por_reintentos(rfc)
                # Un cierre a la vez, del más reciente al más antiguo: si la app
                # estuvo cerrada meses, no se pide la metadata de todos a la vez (el
                # siguiente empieza cuando este termina).
                for mes in meses_por_cerrar(rfc, hoy):
                    if _avanzar_cierre(rfc, sesion, mes):
                        pidio = True
                        break
                    if not _terminada(_fila(rfc, "cierre", mes)):
                        break
                # Sin cierre normal que toque al SAT, avanza el historial.
                if not pidio:
                    pidio = _avanzar_historial(rfc, sesion, hoy)
                pidio = _pasada_diaria(rfc, sesion) or pidio
            except Exception:  # noqa: BLE001 — una empresa con problemas no frena a las demás
                logger.exception("[piloto] %s: falló la evaluación", emp.get("rfc"))
            hechas += 1
            if pidio:
                _escalonar()
        # El aviso final no se pierde si la última empresa pendiente se archivó o dejó
        # de ser elegible: se revisa una vez por vuelta.
        try:
            _resumen_historial()
        except Exception:  # noqa: BLE001
            logger.exception("[piloto] falló el aviso final del historial")
        return {"corrio": True, "empresas": hechas}
    finally:
        _evaluando.release()


# ---------------------------------------------------------------------------
# Reintentar un día (desde el cuadro de control)
# ---------------------------------------------------------------------------


_NO_REINTENTA = {
    "inactivo": "No se puede reintentar con la descarga automática en pausa.",
    "licencia": "Tu plan no incluye la descarga automática.",
    "sesion": "La cuenta está abierta en otra instalación: reintenta desde ahí.",
}


def reintentar(rfc: str, fecha: date, direccion: str) -> dict:
    """Vuelve a pedir un día en error o diferencia. Si su mes ya estaba cerrado, el
    cierre lo vuelve a comparar cuando llegue. Lanza ValueError si no aplica."""
    rfc = normalizar_mi_rfc(rfc)
    if direccion not in _DIRECCIONES:
        raise ValueError("Dirección inválida.")
    fila = calendario.filas(rfc, fecha, fecha).get((fecha.isoformat(), direccion))
    if not fila or fila["estado"] not in ("error", "diferencia"):
        raise ValueError("Solo se reintentan los días con error o con diferencia.")
    emp = next((e for e in config_store.list_empresas() if e["rfc"] == rfc), None)
    motivo = _motivo_no_elegible(emp or {}, _ahora().date()) if emp else "No está en el catálogo"
    if motivo:
        raise ValueError(f"No se puede reintentar: {motivo}.")
    pausa = pausado_por()
    if pausa:
        # Es el planificador el que vuelve a comparar el mes cuando el día llega.
        raise ValueError(_NO_REINTENTA.get(pausa, "No se puede reintentar ahora."))
    sesion = _SesionSat(rfc)
    if sesion.fiel() is None:
        raise ValueError("No se pudo abrir la e.firma de la empresa.")
    # `_pedir` solo reusa solicitudes del piloto: el cierre del mes vuelve a comparar
    # las de reintento (`_reabrir_cierres_por_reintentos`), no una manual.
    clase, a, b = _pedir(rfc, sesion, fecha, fecha, direccion, proposito="reintento",
                         periodo=fecha.isoformat())
    if clase == "duplicada":
        # El SAT ya tiene una igual que no es del piloto (una del piloto viva se
        # habría reusado arriba): una manual en camino o ya terminada. No acepta
        # repetirla por ahora.
        raise ValueError("El SAT ya tiene una solicitud igual para ese día y no acepta repetirla "
                         "por ahora. Intenta más tarde.")
    if clase != "ok":
        raise ValueError(f"El SAT no aceptó la solicitud: {b}")
    calendario.marcar(rfc, fecha, fecha, direccion, "en_proceso", solicitud_id=a, forzar=True)
    # Si su mes ya estaba cerrado, el hilo del piloto (el único que escribe los
    # cierres) lo vuelve a comparar cuando esta solicitud termine.
    despertar()
    return {"ok": True, "id_solicitud": a}


def _reabrir_cierres_por_reintentos(rfc: str) -> None:
    """Un día reintentado de un mes ya cerrado: cuando su solicitud termina, el
    cierre del mes se vuelve a comparar (sin pedir otra metadata)."""
    for s in config_store.list_solicitudes(rfc):
        if (s.get("origen") != "piloto" or s.get("proposito") != "reintento"
                or s.get("recomparada")):
            continue
        id_sol = s["id_solicitud"]
        if _estado_solicitud(rfc, id_sol) == "viva":
            continue
        periodo = str(s.get("periodo") or "")[:7]
        cierre = _fila(rfc, "cierre", periodo) if periodo else None
        detalle = (cierre or {}).get("detalle") or {}
        if cierre is not None and cierre["estado"] == "en_curso" and \
                detalle.get("paso") not in (None, "inicio", "metadata"):
            continue  # ese cierre ya comparó y sigue en curso: se reabre cuando termine
        if cierre is not None and cierre["estado"] in ("completa", "error") and detalle.get("metadata"):
            _guardar(rfc, "cierre", periodo, estado="en_curso", proximo_intento=None,
                     detalle={**detalle, "paso": "faltantes", "faltantes_pedidos": True,
                              "faltantes": [id_sol]})
        # Sin cierre o sin comparar todavía: ese cierre ya lo va a ver.
        config_store.marcar_solicitud(rfc, id_sol, recomparada=True)


# ---------------------------------------------------------------------------
# Estado para la UI
# ---------------------------------------------------------------------------


def estado() -> dict:
    cfg = config()
    ahora = _ahora()
    hoy = ahora.date()
    meses_rango = _meses_rango(hoy)
    cierres = _cierres()
    empresas = []
    for e in config_store.list_empresas():
        if e.get("archived_at"):
            continue
        motivo = _motivo_no_elegible(e, hoy)
        completos = total = 0
        if motivo is None:
            total = len(meses_rango)
            completos = sum(1 for m in meses_rango
                            if (cierres.get((_rfc(e), m)) or {}).get("estado")
                            == "completa")
        empresas.append({"rfc": e["rfc"], "nombre": e.get("nombre") or e["rfc"],
                         "incluida": e.get("piloto_incluida") is not False,
                         "elegible": motivo is None, "motivo": motivo,
                         "historial_completos": completos, "historial_total": total})
    hora = _hora_programada(hoy)
    elegibles = [e for e in empresas if e["elegible"]]
    hecha_hoy = bool(elegibles) and all(
        (_fila(e["rfc"], "diaria", hoy.isoformat()) or {}).get("estado") == "completa"
        for e in elegibles
    )
    if ahora < hora:
        proxima = hora
    elif hecha_hoy:
        proxima = _hora_programada(hoy + timedelta(days=1))
    else:
        proxima = ahora  # ya le toca: corre en la siguiente vuelta
    cierre_periodo = _mes_anterior(_mes_de(hoy))
    db = abrir_db()
    with db.cursor() as cur:
        ejecuciones = [dict(r) for r in cur.execute(
            "SELECT mi_rfc, tipo, periodo, estado, intentos, error_mensaje, actualizado_en"
            " FROM piloto_ejecuciones ORDER BY actualizado_en DESC LIMIT 30"
        ).fetchall()]
    for ej in ejecuciones:
        ej["rfc"] = ej.pop("mi_rfc")
    desde = _historial_desde()
    elegibles_rfc = [_rfc(e) for e in elegibles]
    estados = {(r, m): cierres.get((r, m)) for r in elegibles_rfc for m in meses_rango}
    # El mes más reciente que todavía tiene trabajo en alguna empresa (un mes que
    # falló sin reintento ya no lo tiene).
    siguiente = next((m for m in meses_rango
                      if not all(_terminada(estados[(r, m)]) for r in elegibles_rfc)), None)
    historial = {
        "desde": desde.isoformat() if desde else None,
        "minimo": historial_minimo(hoy).isoformat(),
        "maximo": historial_maximo().isoformat(),
        "meses": len(meses_rango),
        "empresas": len(elegibles_rfc),
        # Cierres del historial que siguen con trabajo (aunque `desde` sea null: tras
        # Detener, los empezados terminan).
        "empezados": sum(1 for (r, _p), f in cierres.items()
                         if r in elegibles_rfc and f["detalle"].get("origen") == "historial"
                         and not _terminada(f)),
        "meses_total": len(estados),
        "meses_completos": sum(1 for f in estados.values() if (f or {}).get("estado") == "completa"),
        "meses_con_diferencia": sum(
            1 for f in estados.values() if (f or {}).get("estado") == "completa"
            and (f["detalle"].get("resumen") or {}).get("dias_con_diferencia")),
        "meses_con_error": sum(1 for f in estados.values()
                               if _terminada(f) and f["estado"] == "error"),
        "siguiente": siguiente,
    }
    return {
        "disponible": disponible(),
        "activo": bool(cfg.get("activo")),
        "dia_cierre": int(cfg.get("dia_cierre") or 5),
        "activado_en": cfg.get("activado_en"),
        "pausado_por": pausado_por(),
        "proxima_pasada": proxima.isoformat(timespec="minutes"),
        "cierre": {"periodo": cierre_periodo,
                   "fecha": _fecha_cierre(cierre_periodo, cfg.get("dia_cierre")).isoformat()},
        "empresas": empresas,
        "historial": historial,
        "ejecuciones": ejecuciones,
        "avisos": avisos(),
    }


_SIN_CAMBIO = object()


def configurar(*, activo: Optional[bool] = None, dia_cierre: Optional[int] = None,
               historial_desde=_SIN_CAMBIO) -> dict:
    """Cambia la configuración. Activar o fijar el historial exige la capacidad (lo
    valida el router). `historial_desde`: una fecha (se normaliza al día 1), None para
    detener (los meses empezados terminan) o no pasarlo para dejarlo como está."""
    patch: dict = {}
    if historial_desde is not _SIN_CAMBIO and historial_desde is not None:
        if isinstance(historial_desde, str):
            try:
                historial_desde = date.fromisoformat(historial_desde[:10])
            except ValueError:
                raise ValueError("La fecha del historial no es válida.")
        mes = historial_desde.replace(day=1)
        minimo, maximo = historial_minimo(), historial_maximo()
        if not minimo <= mes <= maximo:
            raise ValueError(f"El historial se puede llenar desde {_nombre_mes(_mes_de(minimo))} "
                             f"hasta {_nombre_mes(_mes_de(maximo))}.")
        patch["historial_desde"] = mes.isoformat()
        if config().get("historial_desde") != mes.isoformat():
            patch["historial_fijado_en"] = _utc(_ahora())
    elif historial_desde is None:
        patch["historial_desde"] = None
    if dia_cierre is not None:
        if not 1 <= int(dia_cierre) <= 28:
            raise ValueError("El día de cierre va del 1 al 28.")
        patch["dia_cierre"] = int(dia_cierre)
    if activo is not None:
        patch["activo"] = bool(activo)
        if activo and not config().get("activo"):
            # Activar (o reanudar tras una pausa) empieza desde hoy: lo que estuvo en
            # pausa no se pide solo; para eso está llenar el historial.
            patch["activado_en"] = _ahora().isoformat(timespec="seconds")
    config_store.set_piloto_config(patch)
    despertar()
    return estado()

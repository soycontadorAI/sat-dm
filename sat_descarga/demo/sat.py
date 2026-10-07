"""
Simulador del SAT para el modo de grabación.

Cada función que habla con el SAT (Web Service, portal, estatus, listas negras)
pregunta `demo.aplica(rfc)` y, si es una empresa de demo con el modo prendido,
llama aquí en vez de salir a la red. Las respuestas imitan las del SAT en forma
(códigos, mensajes, nombres de archivo, paquetes ZIP) para que el resto del
agente (routers, poller, catálogo, historial, procesadores) siga su camino
normal sin saber que el SAT es de mentira.

Estado: las solicitudes del Web Service de demo se guardan en
`<config>/grabacion/solicitudes.json` (sobreviven a un reinicio del agente, igual
que las reales viven en el SAT). La solicitud queda "En proceso" y pasa a
"Terminada" a los `SAT_DM_GRABACION_ESPERA` segundos de creada.
"""

from __future__ import annotations

import io
import json
import logging
import math
import threading
import time
import uuid as uuidlib
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from . import cfdi, documentos, espera_ws, ritmo
from .escenario import LISTAS_NEGRAS

logger = logging.getLogger("sat_descarga.demo")

PAQUETE_MAX = 2000  # XML por paquete del Web Service de demo
_lock = threading.RLock()


def _pausa(segundos: float) -> None:
    s = segundos * ritmo()
    if s > 0:
        time.sleep(s)


def _a_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


# ---------------------------------------------------------------------------
# Avance por SSE (solo cuando corre dentro de un job del agente)
# ---------------------------------------------------------------------------

def _job():
    try:
        from ..api import jobs
    except Exception:  # noqa: BLE001 - sin FastAPI (CLI): no hay jobs
        return None
    job = jobs.registry.activo()
    if job is None or threading.current_thread().name != f"job-{job.id}":
        return None
    return job


def _avisar(mensaje: str, nivel: str = "info") -> None:
    logger.info("[modo-grabacion] %s", mensaje)
    job = _job()
    if job is not None:
        from ..api import jobs

        jobs.registry.emitir(job, "log", nivel=nivel, mensaje=mensaje)


def _progreso(actual: int, total: int, mensaje: str) -> None:
    job = _job()
    if job is not None:
        from ..api import jobs

        jobs.registry.emitir(job, "progreso", actual=actual, total=total, mensaje=mensaje)


# ---------------------------------------------------------------------------
# Web Service (autenticación, solicitud, verificación, paquetes)
# ---------------------------------------------------------------------------

def token(rfc: str) -> str:
    return f"DEMO-TOKEN%26wrap_subject%3d{rfc.upper()}"


def _ruta_store() -> Path:
    from ..cli import config_store

    d = config_store.get_config_dir() / "grabacion"
    d.mkdir(parents=True, exist_ok=True)
    return d / "solicitudes.json"


def _leer() -> dict:
    ruta = _ruta_store()
    if not ruta.exists():
        return {}
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _escribir(data: dict) -> None:
    from ..cli.config_store import _write_json_atomico

    _write_json_atomico(_ruta_store(), data)


def solicitar(rfc: str, fecha_inicio, fecha_fin, tipo_solicitud: str = "CFDI",
              tipo_comprobante: str = "E", rfc_emisor: Optional[str] = None,
              rfc_receptor: Optional[str] = None, uuids: Optional[list] = None) -> str:
    """SolicitaDescarga de demo: devuelve el IdSolicitud."""
    _pausa(0.8)
    id_solicitud = str(uuidlib.uuid4())
    registro = {
        "rfc": rfc.upper(),
        "fecha_inicio": _a_fecha(fecha_inicio).isoformat() if fecha_inicio else None,
        "fecha_fin": _a_fecha(fecha_fin).isoformat() if fecha_fin else None,
        "tipo_solicitud": tipo_solicitud or "CFDI",
        "tipo_comprobante": (tipo_comprobante or "E").upper(),
        "rfc_emisor": (rfc_emisor or "").upper() or None,
        "rfc_receptor": (rfc_receptor or "").upper() or None,
        "uuids": [u.upper() for u in uuids] if uuids else None,
        "creada": datetime.now().isoformat(timespec="milliseconds"),
    }
    with _lock:
        data = _leer()
        data[id_solicitud] = registro
        _escribir(data)
    logger.info("[modo-grabacion] %s: solicitud de demo %s (%s %s, %s a %s)",
                rfc, id_solicitud, registro["tipo_solicitud"], registro["tipo_comprobante"],
                registro["fecha_inicio"], registro["fecha_fin"])
    return id_solicitud


def _es_metadata(sol: dict) -> bool:
    return str(sol.get("tipo_solicitud", "")).lower() == "metadata"


def _comprobantes(sol: dict) -> list:
    rfc = sol["rfc"]
    if sol.get("uuids"):
        buscados = set(sol["uuids"])
        hoy = date.today()
        desde = date(hoy.year - 2, hoy.month, 1)
        return [c for c in cfdi.en_rango(rfc, desde, hoy) if c.uuid in buscados]
    tipo = sol.get("tipo_comprobante")
    contraparte = sol.get("rfc_emisor") if tipo == "R" else sol.get("rfc_receptor")
    return cfdi.en_rango(rfc, _a_fecha(sol["fecha_inicio"]), _a_fecha(sol["fecha_fin"]),
                         tipo, contraparte)


def verificar(rfc: str, id_solicitud: str):
    """VerificaSolicitudDescarga de demo (misma forma que `_parse_estado`)."""
    from ..webservice.verificacion import EstadoSolicitud

    data = _leer()
    sol = data.get(id_solicitud) or data.get(id_solicitud.lower())
    if not sol or sol.get("rfc") != rfc.upper():
        return EstadoSolicitud("", "5004", "No se encontró la solicitud", 0, [], False)
    transcurrido = (datetime.now() - datetime.fromisoformat(sol["creada"])).total_seconds()
    espera = 0.0 if _es_metadata(sol) else espera_ws()
    if transcurrido < espera * 0.3:
        return EstadoSolicitud("1", "5000", "Solicitud Aceptada", 0, [], False)
    if transcurrido < espera:
        return EstadoSolicitud("2", "5000", "Solicitud Aceptada", 0, [], False)
    comps = _comprobantes(sol)
    if not comps:
        return EstadoSolicitud("5", "5004", "No se encontró la información", 0, [], False)
    paquetes = math.ceil(len(comps) / PAQUETE_MAX)
    ids = [f"{id_solicitud.upper()}_{i:02d}" for i in range(1, paquetes + 1)]
    return EstadoSolicitud("3", "5000", "Solicitud Aceptada", len(comps), ids, True)


def paquete_zip(rfc: str, package_id: str) -> bytes:
    """DescargaMasiva de demo: el ZIP del paquete (XML o metadata)."""
    id_sol, _, num = package_id.rpartition("_")
    data = _leer()
    sol = data.get(id_sol.lower()) or data.get(id_sol)
    if not sol or sol.get("rfc") != rfc.upper() or not num.isdigit():
        raise RuntimeError(f"El paquete {package_id} no existe para {rfc}.")
    comps = _comprobantes(sol)
    i = int(num) - 1
    parte = comps[i * PAQUETE_MAX:(i + 1) * PAQUETE_MAX]
    _pausa(1.5)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if _es_metadata(sol):
            zf.writestr(f"{package_id}.txt", cfdi.metadata_txt(parte))
        else:
            for c in parte:
                zf.writestr(cfdi.nombre_archivo(c), cfdi.xml(c))
    logger.info("[modo-grabacion] %s: paquete de demo %s con %d archivos", rfc, package_id, len(parte))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Portal: captcha, Descarga rápida, constancia y opinión
# ---------------------------------------------------------------------------

def _captcha(pedir_captcha: Optional[Callable]) -> None:
    """El captcha aparece en la app (job + SSE); cualquier respuesta no vacía
    entra. Sin callback (CLI) no hay a quién preguntarle: se omite."""
    if pedir_captcha is None:
        return
    for intento in (1, 2, 3):
        _texto, png = documentos.captcha_png()
        respuesta = pedir_captcha(png, intento, 3)
        if respuesta is None:
            raise RuntimeError("Captcha cancelado por el usuario.")
        if str(respuesta).strip():
            return
    raise RuntimeError("El captcha no se capturó después de 3 intentos.")


def _login(con_captcha: bool, pedir_captcha: Optional[Callable]) -> None:
    if con_captcha:
        _captcha(pedir_captcha)
    _pausa(1.0)
    _avisar("Sesión iniciada en el portal del SAT"
            + (" con Contraseña." if con_captcha else " con e.firma."))


def _tipos(tipo: str) -> list:
    t = (tipo or "").strip().upper()
    if t in ("E", "EMITIDOS"):
        return ["E"]
    if t in ("R", "RECIBIDOS"):
        return ["R"]
    return ["R", "E"]


def portal_cfdi(rfc: str, fecha_inicio, fecha_fin, tipo_comprobante: str = "RE",
                directorio_salida: str = "./cfdi/", max_registros: int = 2000,
                pedir_captcha: Optional[Callable] = None, con_captcha: bool = True) -> List[Path]:
    """Descarga rápida de demo: escribe los XML uno por uno con avance."""
    from ..core import paths

    fi, ff = _a_fecha(fecha_inicio), _a_fecha(fecha_fin)
    _login(con_captcha, pedir_captcha)
    base = Path(directorio_salida)
    descargados: List[Path] = []
    for tipo in _tipos(tipo_comprobante):
        if len(descargados) >= max_registros:
            break
        etiqueta = "emitidos" if tipo == "E" else "recibidos"
        out_dir = base / etiqueta
        if paths.AGRUPAR_POR_EVENTO:
            out_dir = out_dir / paths.etiqueta_rango(fi, ff)
        out_dir.mkdir(parents=True, exist_ok=True)
        comps = cfdi.en_rango(rfc, fi, ff, tipo)[: max_registros - len(descargados)]
        total = len(comps)
        _avisar(f"{total} CFDIs {etiqueta} del {fi:%d/%m/%Y} al {ff:%d/%m/%Y}.")
        paso = max(1, total // 25)
        for i, c in enumerate(comps, start=1):
            destino = out_dir / cfdi.nombre_archivo(c)
            destino.write_bytes(cfdi.xml(c))
            descargados.append(destino)
            _pausa(0.04)
            if i % paso == 0 or i == total:
                _progreso(i, total, f"XML {i} de {total}")
            if i % max(paso * 5, 1) == 0 and i != total:
                _avisar(f"Descargando XML {i} de {total}…")
    _avisar(f"Descarga completada: {len(descargados)} XML.", "ok")
    return descargados


def _hoy() -> date:
    return date.today()


def constancia(rfc: str, directorio_salida: str, pedir_captcha: Optional[Callable] = None,
               con_captcha: bool = True) -> Path:
    rfc = rfc.upper()
    _login(con_captcha, pedir_captcha)
    _avisar("Generando la Constancia de Situación Fiscal…")
    _pausa(1.2)
    destino = Path(directorio_salida) / f"constancia_{rfc}_{_hoy():%Y%m%d}.pdf"
    documentos.constancia_pdf(rfc, destino, _hoy())
    _avisar("Constancia de Situación Fiscal descargada.", "ok")
    return destino


def opinion(rfc: str, directorio_salida: str, pedir_captcha: Optional[Callable] = None,
            con_captcha: bool = True) -> Path:
    rfc = rfc.upper()
    _login(con_captcha, pedir_captcha)
    _avisar("Solicitando la Opinión de Cumplimiento 32-D…")
    _pausa(1.2)
    destino = Path(directorio_salida) / f"opinion32d_{rfc}_{_hoy():%Y%m%d}.pdf"
    documentos.opinion_pdf(rfc, destino, _hoy())
    _avisar("Opinión 32-D descargada.", "ok")
    return destino


# ---------------------------------------------------------------------------
# Estatus de CFDI (ConsultaCFDIService)
# ---------------------------------------------------------------------------

def estatus(uuid: str, emisor_rfc: str, receptor_rfc: str, total: float):
    from ..utils.validacion import EstadoCFDI

    _pausa(0.025)
    estado = cfdi.estatus(uuid, emisor_rfc or "", receptor_rfc or "")
    lista = LISTAS_NEGRAS.get((emisor_rfc or "").upper())
    efos = "100" if lista is not None and lista.situacion_69b in ("Definitivo", "Presunto") else "200"
    if estado == "Cancelado":
        return EstadoCFDI(uuid=uuid, estado="Cancelado", es_cancelable="Cancelable con aceptación",
                          estatus_cancelacion="Cancelado con aceptación", validacion_efos=efos)
    return EstadoCFDI(uuid=uuid, estado="Vigente", es_cancelable="Cancelable con aceptación",
                      estatus_cancelacion="", validacion_efos=efos)


# ---------------------------------------------------------------------------
# Listas negras 69 / 69-B
# ---------------------------------------------------------------------------

def _fecha_imposible(rfc: str) -> bool:
    """RFC con fecha que no existe (31 de febrero…): no puede estar en una
    lista del SAT, así que se contesta "limpio" sin salir a la red."""
    import calendar

    rfc = (rfc or "").strip().upper()
    if len(rfc) not in (12, 13):
        return False
    fecha = rfc[len(rfc) - 9:len(rfc) - 3]
    if not fecha.isdigit():
        return False
    mm, dd = int(fecha[2:4]), int(fecha[4:6])
    if not 1 <= mm <= 12:
        return True
    return dd < 1 or dd > calendar.monthrange(2000, mm)[1]  # 2000: bisiesto


def es_rfc_de_demo(rfc: str) -> bool:
    from . import es_demo
    from .catalogo import rfcs_del_escenario

    rfc = (rfc or "").strip().upper()
    return es_demo(rfc) or rfc in rfcs_del_escenario() or _fecha_imposible(rfc)


def match_lista(rfc: str):
    from ..utils.listas_negras import MatchListaNegra

    rfc = rfc.strip().upper()
    e = LISTAS_NEGRAS.get(rfc)
    if e is None:
        return MatchListaNegra(rfc=rfc, en_lista_69b=False, situacion_69b=None,
                               fecha_publicacion_69b=None, en_lista_69=False,
                               supuestos_69=[], risk_level="limpio")
    return MatchListaNegra(
        rfc=rfc, en_lista_69b=bool(e.situacion_69b), situacion_69b=e.situacion_69b,
        fecha_publicacion_69b=e.fecha_publicacion_69b, en_lista_69=bool(e.supuestos_69),
        supuestos_69=list(e.supuestos_69), risk_level=e.risk_level,
    )


def metadata_listas():
    """Corte de las listas como lo deja el cron mensual (día 5)."""
    from ..utils.listas_negras import ListasMetadata

    hoy = datetime.now(timezone.utc)
    anio, mes = hoy.year, hoy.month
    if hoy.day < 5:
        anio, mes = (anio - 1, 12) if mes == 1 else (anio, mes - 1)
    corte = datetime(anio, mes, 5, 6, 0, 0, tzinfo=timezone.utc).isoformat()
    return ListasMetadata(lista_69b_updated_at=corte, lista_69_updated_at=corte,
                          record_count_69b=12486, record_count_69=145302)


def consultar_listas(rfcs: list) -> list:
    _pausa(0.6)
    return [match_lista(r) for r in rfcs]

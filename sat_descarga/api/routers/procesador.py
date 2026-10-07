"""
Router: procesador de comprobantes (CFDI, Pagos, Nómina) + listas negras del SAT.

Endpoints: /procesador/cfdi/*, /procesador/pagos/*, /procesador/nomina/* y
/listas-negras/*.
"""

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..state import _descargas_base
from ..uso import rango, track

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Procesador de comprobantes — CFDI
# ---------------------------------------------------------------------------
#
# Buffer persistente en SQLite (~/.sat-descarga/procesador.db), AISLADO POR
# EMPRESA: cada fila tiene dueño (mi_rfc) y todos los endpoints exigen el RFC
# explícito desde el cliente — sin empresa activa no hay procesador (no hay
# bucket general). El usuario carga XMLs explícitamente (drag&drop / examinar
# carpeta / desde empresa); no se autoescanea el filesystem. Lo cargado se
# queda hasta que el usuario pulse "Borrar" (que solo vacía SU empresa).
# Filtros también persisten por empresa para que la sesión se recupere al
# reabrir la app o al regresar a la empresa (A→B→A).


class CargarDesdeEmpresaRequest(BaseModel):
    rfc: str
    desde: Optional[str] = None  # YYYY-MM-DD (inclusive)
    hasta: Optional[str] = None  # YYYY-MM-DD (inclusive)
    # 'E' (emitidos) o 'R' (recibidos). Cuando se omite, escanea ambos —
    # reservado para uso programático futuro (p. ej. una calculadora de IVA
    # que necesite cruzar el total emitido vs recibido del periodo).
    tipo: Optional[str] = None


class ValidarSatRequest(BaseModel):
    rfc: str
    # Si se omite, valida solo los CFDIs del buffer sin estado_sat asignado.
    uuids: Optional[List[str]] = None


class ProcesadorFiltrosRequest(BaseModel):
    rfc: str  # empresa dueña — NO se persiste dentro de los filtros
    desde: Optional[str] = None
    hasta: Optional[str] = None
    tipo: Optional[str] = None
    direccion: Optional[str] = None  # 'E' | 'R' | None
    busqueda: Optional[str] = None
    solo_con_errores: Optional[bool] = False
    monto_min: Optional[float] = None
    monto_max: Optional[float] = None
    diot: Optional[str] = None  # 'pasa' | 'excluido' | 'noaplica' | None


class CfdiFlagsRequest(BaseModel):
    """Flags editables por comprobante. 'Sin analizar' se persiste como NULL."""

    rfc: str
    incluir_diot: Optional[bool] = None
    deducible: Optional[Literal["Sin analizar", "Deducible", "No deducible"]] = None


def _filtros_de_query(
    mi_rfc: str,
    desde: Optional[str],
    hasta: Optional[str],
    tipo: Optional[str],
    busqueda: Optional[str],
    solo_con_errores: bool,
    monto_min: Optional[float],
    monto_max: Optional[float],
    direccion: Optional[str] = None,
    emisor_lista_negra: Optional[str] = None,
    diot: Optional[str] = None,
) -> dict:
    """Construye el dict de filtros para `procesador.db` (acotado al dueño)."""
    return {
        "mi_rfc": mi_rfc,
        "desde": desde,
        "hasta": hasta,
        "tipo": tipo,
        "direccion": direccion,
        "busqueda": busqueda,
        "solo_con_errores": bool(solo_con_errores),
        "monto_min": monto_min,
        "monto_max": monto_max,
        "emisor_lista_negra": emisor_lista_negra,
        "diot": diot,
    }


def _rfc_requerido(rfc: Optional[str], *, del_catalogo: bool = False) -> str:
    """Normaliza y valida el RFC dueño del buffer; 400 si es inválido.

    No hay fallback a la "empresa activa" del agente: el RFC viaja SIEMPRE
    explícito desde el cliente (mismo contrato que las calculadoras) para que
    un desfase entre la UI y la sesión del agente jamás mezcle empresas.
    Con `del_catalogo=True` además exige que sea una empresa registrada
    (se usa en las vías de carga, donde se escriben datos nuevos).
    """
    from ...procesador.db import normalizar_mi_rfc

    try:
        limpio = normalizar_mi_rfc(rfc)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="RFC inválido o faltante. Activa una empresa para usar el procesador.",
        )
    if del_catalogo:
        from ...cli import config_store

        if limpio not in config_store.load_empresas().get("empresas", {}):
            raise HTTPException(
                status_code=400,
                detail=f"La empresa {limpio} no está registrada en el catálogo.",
            )
    return limpio


def _pertenece_a(cfdi, mi_rfc: str) -> bool:
    """¿El CFDI menciona a la empresa como emisor O receptor?

    Es la restricción de la vía "Examinar": solo se aceptan comprobantes de
    la empresa activa (emitidos o recibidos, incluso descargados con otro
    software). strip+upper porque hay XMLs con el RFC en minúsculas.
    """
    lados = {
        (cfdi.emisor_rfc or "").strip().upper(),
        (cfdi.receptor_rfc or "").strip().upper(),
    }
    return mi_rfc in lados


@router.post("/procesador/cfdi/cargar")
async def procesador_cargar(
    files: List[UploadFile] = File(...),
    rfc: str = Form(...),
):
    """
    Recibe `.xml` por multipart y los agrega al buffer de la empresa `rfc`.
    Hasta `MAX_BATCH_SIZE` archivos por request. Los XML que no correspondan
    al RFC (ni emisor ni receptor) se OMITEN y se reporta el conteo.
    """
    from ...procesador import abrir_db, parse_cfdi, MAX_BATCH_SIZE
    from ...procesador.cfdi_parser import CfdiParseError
    from ...procesador.validaciones import validar_y_anotar

    mi_rfc = _rfc_requerido(rfc, del_catalogo=True)

    if len(files) > MAX_BATCH_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Demasiados archivos en un batch (máx {MAX_BATCH_SIZE})",
        )
    track("procesador_usado", tipo="cfdi")

    db = abrir_db()
    parseados = []
    errores: list[dict] = []
    omitidos_rfc = 0

    for f in files:
        try:
            contenido = await f.read()
            cfdi = parse_cfdi(contenido, file_name=f.filename or "")
            if not _pertenece_a(cfdi, mi_rfc):
                omitidos_rfc += 1
                continue
            validar_y_anotar(cfdi)
            parseados.append(cfdi)
        except CfdiParseError as e:
            errores.append({"filename": f.filename, "mensaje": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.exception("[procesador] error parseando %s", f.filename)
            errores.append({"filename": f.filename, "mensaje": str(e)})

    # Drag&drop: la dirección se infiere comparando con el RFC dueño
    # (autofactura emisor==receptor==rfc queda como 'E').
    resultado = db.agregar(parseados, mi_rfc=mi_rfc)
    return {
        "agregados": resultado["agregados"],
        "duplicados": resultado["duplicados"],
        "omitidos_rfc": omitidos_rfc,
        "errores": errores,
    }


@router.post("/procesador/cfdi/cargar-desde-empresa")
def procesador_cargar_desde_empresa(req: CargarDesdeEmpresaRequest):
    """
    Escanea `descargas/cfdi/<RFC>/.../*.xml` filtrando por fecha (opcional)
    y agrega los CFDIs encontrados al buffer de esa empresa.
    """
    from ...procesador import abrir_db, parse_cfdi
    from ...procesador.cfdi_parser import CfdiParseError
    from ...procesador.validaciones import validar_y_anotar
    from ...core import paths

    mi_rfc = _rfc_requerido(req.rfc, del_catalogo=True)
    track("procesador_usado", tipo="cfdi")

    base = paths.dir_cfdi_base(mi_rfc, salida_base=_descargas_base())
    if not base.exists():
        return {
            "agregados": 0,
            "duplicados": 0,
            "omitidos_rfc": 0,
            "errores": [],
            "archivos_encontrados": 0,
        }

    # Filtrar por subcarpeta según el tipo solicitado. Si el caller omite
    # `tipo`, escanea ambos (uso programático futuro).
    if req.tipo == "E":
        scan_dirs = [base / "emitidos"]
    elif req.tipo == "R":
        scan_dirs = [base / "recibidos"]
    else:
        scan_dirs = [base]

    xmls: list = []
    for d in scan_dirs:
        if d.exists():
            xmls.extend(d.rglob("*.xml"))

    db = abrir_db()
    parseados = []
    errores: list[dict] = []
    omitidos_rfc = 0

    desde = req.desde or ""
    hasta = req.hasta + "T23:59:59" if req.hasta else ""

    for xml_path in xmls:
        try:
            contenido = xml_path.read_bytes()
            cfdi = parse_cfdi(contenido, file_name=xml_path.name)
            # Filtro de fecha post-parseo (la fecha real vive en el XML)
            if desde and cfdi.fecha_emision and cfdi.fecha_emision < desde:
                continue
            if hasta and cfdi.fecha_emision and cfdi.fecha_emision > hasta:
                continue
            # Defensa extra: la carpeta de descargas puede contener XMLs
            # movidos a mano que no son de esta empresa.
            if not _pertenece_a(cfdi, mi_rfc):
                omitidos_rfc += 1
                continue
            validar_y_anotar(cfdi)
            parseados.append(cfdi)
        except CfdiParseError as e:
            errores.append({"filename": xml_path.name, "mensaje": str(e)})
        except Exception as e:  # noqa: BLE001
            logger.exception("[procesador] error parseando %s", xml_path.name)
            errores.append({"filename": xml_path.name, "mensaje": str(e)})

    # En "cargar-desde-empresa" la dirección está implícita por el `tipo`
    # solicitado (E/R) — se la pasamos directa y de paso usamos `mi_rfc` como
    # respaldo si `tipo` viene en None.
    resultado = db.agregar(
        parseados,
        mi_rfc=mi_rfc,
        direccion_fija=req.tipo if req.tipo in ("E", "R") else None,
    )
    return {
        "agregados": resultado["agregados"],
        "duplicados": resultado["duplicados"],
        "omitidos_rfc": omitidos_rfc,
        "errores": errores,
        "archivos_encontrados": len(xmls),
    }


@router.post("/procesador/cfdi/validar-sat")
def procesador_validar_sat(req: ValidarSatRequest):
    """
    Valida contra el endpoint público del SAT los CFDIs indicados (o todos los
    que no tengan `estado_sat` aún). Actualiza la columna correspondiente y
    devuelve un summary por estado.
    """
    from ...procesador import abrir_db
    from ...utils.validacion import validar_masivo

    mi_rfc = _rfc_requerido(req.rfc)
    db = abrir_db()

    if req.uuids:
        uuids = req.uuids
    else:
        uuids = db.uuids_sin_validar(mi_rfc)

    if not uuids:
        return {"validados": 0, "vigentes": 0, "cancelados": 0,
                "no_encontrados": 0, "errores": 0}

    # Construye payloads para validar_masivo. Acotado al dueño: el mismo
    # uuid puede vivir bajo dos empresas y no queremos validarlo doble.
    payloads = []
    with db.cursor() as cur:
        placeholders = ",".join("?" for _ in uuids)
        cur.execute(
            f"""
            SELECT uuid, emisor_rfc, receptor_rfc, total
            FROM cfdis WHERE mi_rfc = ? AND uuid IN ({placeholders})
            """,
            (mi_rfc, *uuids),
        )
        for r in cur.fetchall():
            payloads.append({
                "uuid": r["uuid"],
                "emisor_rfc": r["emisor_rfc"] or "",
                "receptor_rfc": r["receptor_rfc"] or "",
                "total": r["total"] or 0.0,
            })

    resultados = validar_masivo(payloads, concurrency=10)
    track("estatus_validado", origen="procesador", tamano=rango(len(resultados)))

    contadores = {"vigentes": 0, "cancelados": 0, "no_encontrados": 0, "errores": 0}
    for est in resultados:
        estado = (est.estado or "").strip()
        if estado.lower().startswith("vigente"):
            contadores["vigentes"] += 1
            db.actualizar_estado_sat(est.uuid, "Vigente")
        elif estado.lower().startswith("cancel"):
            contadores["cancelados"] += 1
            db.actualizar_estado_sat(est.uuid, "Cancelado")
        elif estado.lower().startswith("no encontrado") or estado.lower().startswith("not"):
            contadores["no_encontrados"] += 1
            db.actualizar_estado_sat(est.uuid, "No encontrado")
        else:
            contadores["errores"] += 1

    return {"validados": len(resultados), **contadores}


@router.get("/procesador/cfdi")
def procesador_listar(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    tipo: Optional[str] = None,
    direccion: Optional[str] = None,
    busqueda: Optional[str] = None,
    solo_con_errores: bool = False,
    monto_min: Optional[float] = None,
    monto_max: Optional[float] = None,
    emisor_lista_negra: Optional[str] = None,
    diot: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    """Lista paginada del buffer de la empresa con filtros."""
    from ...procesador import abrir_db
    filtros = _filtros_de_query(
        _rfc_requerido(rfc),
        desde, hasta, tipo, busqueda, solo_con_errores, monto_min, monto_max,
        direccion, emisor_lista_negra, diot,
    )
    db = abrir_db()
    track("procesador_usado", tipo="cfdi")  # una vez cada 30 min, no por filtro
    return db.listar(filtros, page=page, page_size=page_size)


@router.get("/procesador/cfdi/stats")
def procesador_stats(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    tipo: Optional[str] = None,
    direccion: Optional[str] = None,
    busqueda: Optional[str] = None,
    solo_con_errores: bool = False,
    monto_min: Optional[float] = None,
    monto_max: Optional[float] = None,
    diot: Optional[str] = None,
):
    """KPIs agregados (stats cards)."""
    from ...procesador import abrir_db
    from ...procesador.reportes_cfdi import stats_generales
    filtros = _filtros_de_query(
        _rfc_requerido(rfc),
        desde, hasta, tipo, busqueda, solo_con_errores, monto_min, monto_max,
        direccion, diot=diot,
    )
    return stats_generales(abrir_db(), filtros)


@router.get("/procesador/cfdi/reporte/{nombre}")
def procesador_reporte(
    nombre: str,
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    tipo: Optional[str] = None,
    direccion: Optional[str] = None,
    busqueda: Optional[str] = None,
    solo_con_errores: bool = False,
    monto_min: Optional[float] = None,
    monto_max: Optional[float] = None,
    diot: Optional[str] = None,
):
    """Reportes específicos: `totales-mes`, `top-contrapartes`, `integridad`."""
    from ...procesador import abrir_db
    from ...procesador import reportes_cfdi as rep

    filtros = _filtros_de_query(
        _rfc_requerido(rfc),
        desde, hasta, tipo, busqueda, solo_con_errores, monto_min, monto_max,
        direccion, diot=diot,
    )
    db = abrir_db()
    if nombre == "totales-mes":
        return {"reporte": "totales-mes", "items": rep.totales_por_mes(db, filtros)}
    if nombre == "top-contrapartes":
        return {"reporte": "top-contrapartes", **rep.top_contrapartes(db, filtros)}
    if nombre == "integridad":
        return {"reporte": "integridad", "items": rep.integridad(db, filtros)}
    raise HTTPException(status_code=404, detail=f"Reporte desconocido: {nombre}")


@router.get("/procesador/cfdi/filtros")
def procesador_filtros_get(rfc: str):
    from ...procesador import abrir_db
    return abrir_db().filtros_get(key=f"actuales:{_rfc_requerido(rfc)}")


@router.put("/procesador/cfdi/filtros")
def procesador_filtros_set(req: ProcesadorFiltrosRequest):
    from ...procesador import abrir_db
    mi_rfc = _rfc_requerido(req.rfc)
    db = abrir_db()
    # `rfc` es la key, no un filtro — no se persiste dentro del JSON.
    db.filtros_set(req.model_dump(exclude={"rfc"}), key=f"actuales:{mi_rfc}")
    return {"ok": True}


@router.delete("/procesador/cfdi")
def procesador_borrar(rfc: str):
    """Vacía el buffer y los filtros de UNA empresa (las demás no se tocan)."""
    from ...procesador import abrir_db
    abrir_db().borrar(_rfc_requerido(rfc))
    return {"ok": True}


@router.patch("/procesador/cfdi/{uuid}")
def procesador_actualizar_cfdi(uuid: str, req: CfdiFlagsRequest):
    """Actualiza flags editables (incluir_diot / deducible) de un CFDI.

    - `incluir_diot` solo se acepta en filas elegibles para la DIOT (400 si no).
    - `deducible` acepta 'Sin analizar' (→ NULL), 'Deducible' o 'No deducible'.
    Devuelve la fila actualizada + contadores globales para que la UI refresque
    la línea-resumen sin otro roundtrip.
    """
    from ...procesador import abrir_db
    from ...procesador.reportes_cfdi import contadores_diot_deducible

    mi_rfc = _rfc_requerido(req.rfc)
    campos: dict = {}
    if req.incluir_diot is not None:
        campos["incluir_diot"] = req.incluir_diot
    if "deducible" in req.model_fields_set:
        campos["deducible"] = None if req.deducible == "Sin analizar" else req.deducible
    if not campos:
        raise HTTPException(
            status_code=400,
            detail="Nada que actualizar: envía incluir_diot y/o deducible.",
        )

    db = abrir_db()
    try:
        item = db.actualizar_flags_cfdi(uuid, mi_rfc, campos)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"El CFDI {uuid} no está en el buffer de {mi_rfc}.",
        )
    return {"ok": True, "item": item, "contadores": contadores_diot_deducible(db, mi_rfc)}


@router.get("/procesador/cfdi/exportar")
def procesador_exportar(
    rfc: str,
    formato: str = "xlsx",
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    tipo: Optional[str] = None,
    direccion: Optional[str] = None,
    busqueda: Optional[str] = None,
    solo_con_errores: bool = False,
    monto_min: Optional[float] = None,
    monto_max: Optional[float] = None,
    diot: Optional[str] = None,
):
    """Descarga el buffer filtrado como XLSX o CSV."""
    from ...procesador import abrir_db
    from ...procesador.exportar import to_csv, to_xlsx

    filtros = _filtros_de_query(
        _rfc_requerido(rfc),
        desde, hasta, tipo, busqueda, solo_con_errores, monto_min, monto_max,
        direccion, diot=diot,
    )
    db = abrir_db()

    if formato == "xlsx":
        data = to_xlsx(db, filtros)
        track("excel_exportado", tipo="cfdi", formato="xlsx")
        return StreamingResponse(
            iter([data]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="cfdis.xlsx"'},
        )
    if formato == "csv":
        data = to_csv(db, filtros)
        track("excel_exportado", tipo="cfdi", formato="csv")
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="cfdis.csv"'},
        )
    raise HTTPException(status_code=400, detail=f"Formato no soportado: {formato}")


# ---------------------------------------------------------------------------
# Listas negras del SAT (Art. 69 y 69-B)
# ---------------------------------------------------------------------------
#
# Consume la API de todoconta-apps (Vercel cron mensual → Supabase). La fuente
# de verdad vive en un solo lugar; aquí solo consultamos y persistimos el
# último resultado por RFC en el buffer del procesador para filtrar/ordenar.
#
# Requiere sesión iniciada (Bearer en keyring). Sin sesión → 401.


class ListasNegrasConsultarRequest(BaseModel):
    rfcs: List[str]


class ValidarListasNegrasRequest(BaseModel):
    rfc: str
    # Si se omite, valida todos los RFCs del buffer cuya última validación
    # esté fuera del TTL (30 días). `force_refresh=true` ignora el TTL.
    uuids: Optional[List[str]] = None
    force_refresh: bool = False


def _match_to_payload(m) -> dict:
    """Serializa un MatchListaNegra al shape que consume la UI."""
    return {
        "rfc": m.rfc,
        "en_lista_69b": m.en_lista_69b,
        "situacion_69b": m.situacion_69b,
        "fecha_publicacion_69b": m.fecha_publicacion_69b,
        "en_lista_69": m.en_lista_69,
        "supuestos_69": m.supuestos_69,
        "risk_level": m.risk_level,
        "error": m.error,
    }


def _metadata_to_payload(meta) -> dict:
    return {
        "lista_69b_updated_at": meta.lista_69b_updated_at,
        "lista_69_updated_at": meta.lista_69_updated_at,
        "record_count_69b": meta.record_count_69b,
        "record_count_69": meta.record_count_69,
    }


@router.post("/listas-negras/consultar")
def listas_negras_consultar(req: ListasNegrasConsultarRequest):
    """Consulta ad-hoc de RFCs contra las listas negras. No toca SQLite.

    Útil para la pestaña "Validar RFCs" de la UI: el usuario pega/sube
    una lista y obtiene el veredicto sin tener XMLs cargados.
    """
    from ...utils.listas_negras import consultar_rfcs

    if not req.rfcs:
        raise HTTPException(status_code=400, detail="La lista de RFCs está vacía.")
    try:
        matches, metadata = consultar_rfcs(req.rfcs)
    except RuntimeError as e:
        # Sin sesión / sesión expirada / error de red
        msg = str(e)
        status = 401 if "Sesión" in msg or "sesión" in msg else 502
        raise HTTPException(status_code=status, detail=msg)
    track("listas_negras_consultada", origen="directo",
          modo="uno" if len(req.rfcs) == 1 else "lote")
    return {
        "matches": [_match_to_payload(m) for m in matches],
        "metadata": _metadata_to_payload(metadata),
    }


@router.get("/listas-negras/metadata")
def listas_negras_metadata():
    """Cuándo se actualizaron por última vez las listas en el origen.

    La UI lo muestra como chip "Listas al 2026-06-05" y enseña una advertencia
    si pasaron > 35 días sin refresh (el cron normal es mensual).
    """
    from ...utils.listas_negras import consultar_metadata

    try:
        metadata = consultar_metadata()
    except RuntimeError as e:
        msg = str(e)
        status = 401 if "Sesión" in msg or "sesión" in msg else 502
        raise HTTPException(status_code=status, detail=msg)
    return _metadata_to_payload(metadata)


@router.post("/procesador/cfdi/validar-listas-negras")
def procesador_validar_listas_negras(req: ValidarListasNegrasRequest):
    """Valida los RFCs del buffer contra listas negras y persiste por fila.

    Si `req.uuids` viene, restringe a los RFCs (emisor + receptor) de esos
    CFDIs; si no, usa el universo del buffer respetando TTL (30 días) salvo
    `force_refresh=true`.
    """
    from ...utils.listas_negras import consultar_rfcs, clasificar, match_to_json_dict
    from ...procesador import abrir_db
    import json as _json

    mi_rfc = _rfc_requerido(req.rfc)
    db = abrir_db()

    if req.uuids:
        # RFCs únicos de los CFDIs solicitados (ambos lados, de esta empresa).
        with db.cursor() as cur:
            placeholders = ",".join("?" for _ in req.uuids)
            cur.execute(
                f"""
                SELECT DISTINCT rfc FROM (
                  SELECT emisor_rfc AS rfc FROM cfdis
                  WHERE mi_rfc = ? AND uuid IN ({placeholders})
                  UNION
                  SELECT receptor_rfc AS rfc FROM cfdis
                  WHERE mi_rfc = ? AND uuid IN ({placeholders})
                ) WHERE rfc IS NOT NULL AND rfc != ''
                """,
                (mi_rfc, *req.uuids, mi_rfc, *req.uuids),
            )
            rfcs = [r[0] for r in cur.fetchall()]
    else:
        rfcs = db.rfcs_sin_validar_listas(mi_rfc, force_refresh=req.force_refresh)

    if not rfcs:
        return {
            "validados": 0, "efos": 0, "aclarados": 0, "lista_69": 0, "limpios": 0,
            "metadata": {
                "lista_69b_updated_at": None, "lista_69_updated_at": None,
                "record_count_69b": None, "record_count_69": None,
            },
        }

    try:
        matches, metadata = consultar_rfcs(rfcs)
    except RuntimeError as e:
        msg = str(e)
        status = 401 if "Sesión" in msg or "sesión" in msg else 502
        raise HTTPException(status_code=status, detail=msg)
    track("listas_negras_consultada", origen="procesador",
          modo="uno" if len(rfcs) == 1 else "lote")

    contadores = {"efos": 0, "aclarados": 0, "lista_69": 0, "limpios": 0}
    for m in matches:
        etiqueta = clasificar(m)
        db.actualizar_lista_negra_rfc(
            m.rfc, etiqueta, _json.dumps(match_to_json_dict(m), ensure_ascii=False),
        )
        if etiqueta == "EFOS":
            contadores["efos"] += 1
        elif etiqueta == "Aclarado":
            contadores["aclarados"] += 1
        elif etiqueta == "69":
            contadores["lista_69"] += 1
        else:
            contadores["limpios"] += 1

    return {
        "validados": len(matches),
        **contadores,
        "metadata": _metadata_to_payload(metadata),
    }


@router.get("/procesador/cfdi/listas-negras/stats")
def procesador_listas_negras_stats(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    tipo: Optional[str] = None,
    direccion: Optional[str] = None,
    busqueda: Optional[str] = None,
    solo_con_errores: bool = False,
    monto_min: Optional[float] = None,
    monto_max: Optional[float] = None,
):
    """KPIs (EFOS / EDOS / aclarados / 69 / limpios / sin validar) sobre el
    buffer filtrado. Usa los mismos filtros del procesador CFDI."""
    from ...procesador import abrir_db

    filtros = _filtros_de_query(
        _rfc_requerido(rfc),
        desde, hasta, tipo, busqueda, solo_con_errores, monto_min, monto_max, direccion,
    )
    return abrir_db().stats_listas_negras(filtros)


@router.get("/procesador/cfdi/listas-negras/por-emisor")
def procesador_listas_negras_por_emisor(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    tipo: Optional[str] = None,
    direccion: Optional[str] = None,
    busqueda: Optional[str] = None,
    solo_con_errores: bool = False,
    monto_min: Optional[float] = None,
    monto_max: Optional[float] = None,
    emisor_lista_negra: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    """Lista paginada agregada por `emisor_rfc` con total acumulado y conteo
    de CFDIs. Para la vista de listas negras donde lo accionable es por
    proveedor, no por comprobante individual."""
    from ...procesador import abrir_db

    filtros = _filtros_de_query(
        _rfc_requerido(rfc),
        desde, hasta, tipo, busqueda, solo_con_errores, monto_min, monto_max,
        direccion, emisor_lista_negra,
    )
    return abrir_db().listar_emisores_listas_negras(filtros, page=page, page_size=page_size)


# ---------------------------------------------------------------------------
# Procesador de comprobantes — Pagos
# ---------------------------------------------------------------------------
#
# Vista especializada sobre el buffer compartido `cfdis` + tabla
# `pagos_relaciones` (migración 004). Relaciona PPD ↔ complemento, detecta
# huérfanos, extemporáneos e incidencias PUE+complemento. NO tiene endpoints
# de cargar/borrar — los XMLs entran por `/procesador/cfdi/cargar`.


class PagosFiltrosRequest(BaseModel):
    rfc: str  # empresa dueña — NO se persiste dentro de los filtros
    desde: Optional[str] = None
    hasta: Optional[str] = None
    busqueda: Optional[str] = None
    status: Optional[List[str]] = None  # ['sin_complemento', 'pago_parcial', ...]
    solo_extemporaneos: Optional[bool] = False


def _filtros_pagos_de_query(
    mi_rfc: str,
    desde: Optional[str],
    hasta: Optional[str],
    busqueda: Optional[str],
) -> dict:
    return {"mi_rfc": mi_rfc, "desde": desde, "hasta": hasta, "busqueda": busqueda}


@router.get("/procesador/pagos")
def procesador_pagos_listar(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
    status: Optional[str] = None,  # CSV: "sin_complemento,pago_parcial"
    page: int = 1,
    page_size: int = 50,
):
    """Facturas PPD paginadas con status calculado."""
    from ...procesador import abrir_db
    from ...procesador import reportes_pagos as rep

    filtros = _filtros_pagos_de_query(_rfc_requerido(rfc), desde, hasta, busqueda)
    status_list = [s for s in (status or "").split(",") if s] or None
    track("procesador_usado", tipo="pagos")  # una vez cada 30 min, no por filtro
    return rep.facturas_ppd(
        abrir_db(), filtros, status_in=status_list, page=page, page_size=page_size,
    )


@router.get("/procesador/pagos/stats")
def procesador_pagos_stats(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
):
    from ...procesador import abrir_db
    from ...procesador.reportes_pagos import stats_pagos
    filtros = _filtros_pagos_de_query(_rfc_requerido(rfc), desde, hasta, busqueda)
    return stats_pagos(abrir_db(), filtros)


@router.get("/procesador/pagos/factura/{uuid}/pagos")
def procesador_pagos_detalle_factura(uuid: str, rfc: str):
    """Drilldown: pagos asociados a una factura PPD específica (el uuid ya
    no es único — puede vivir bajo dos empresas)."""
    from ...procesador import abrir_db
    from ...procesador.reportes_pagos import detalle_pagos_de_ppd
    return {
        "uuid": uuid,
        "items": detalle_pagos_de_ppd(abrir_db(), uuid, _rfc_requerido(rfc)),
    }


@router.get("/procesador/pagos/reporte/{nombre}")
def procesador_pagos_reporte(
    nombre: str,
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
):
    """Reportes: `analisis-fechas`, `huerfanos`, `incidencias-pue`."""
    from ...procesador import abrir_db
    from ...procesador import reportes_pagos as rep

    filtros = _filtros_pagos_de_query(_rfc_requerido(rfc), desde, hasta, busqueda)
    db = abrir_db()
    if nombre == "analisis-fechas":
        return {"reporte": "analisis-fechas", "items": rep.analisis_fechas(db, filtros)}
    if nombre == "huerfanos":
        return {"reporte": "huerfanos", "items": rep.pagos_huerfanos(db, filtros)}
    if nombre == "incidencias-pue":
        return {"reporte": "incidencias-pue", "items": rep.incidencias_pue(db, filtros)}
    raise HTTPException(status_code=404, detail=f"Reporte desconocido: {nombre}")


@router.get("/procesador/pagos/filtros")
def procesador_pagos_filtros_get(rfc: str):
    from ...procesador import abrir_db
    f = abrir_db().filtros_get(key=f"pagos_actuales:{_rfc_requerido(rfc)}")
    # Default explicito si nunca se han guardado.
    return f or {
        "desde": None, "hasta": None, "busqueda": None,
        "status": None, "solo_extemporaneos": False,
    }


@router.put("/procesador/pagos/filtros")
def procesador_pagos_filtros_set(req: PagosFiltrosRequest):
    from ...procesador import abrir_db
    mi_rfc = _rfc_requerido(req.rfc)
    abrir_db().filtros_set(req.model_dump(exclude={"rfc"}), key=f"pagos_actuales:{mi_rfc}")
    return {"ok": True}


@router.get("/procesador/pagos/exportar")
def procesador_pagos_exportar(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
):
    """XLSX multi-sheet del procesador de Pagos."""
    from ...procesador import abrir_db
    from ...procesador.exportar_pagos import to_xlsx
    filtros = _filtros_pagos_de_query(_rfc_requerido(rfc), desde, hasta, busqueda)
    data = to_xlsx(abrir_db(), filtros)
    track("excel_exportado", tipo="pagos", formato="xlsx")
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="pagos.xlsx"'},
    )


# ---------------------------------------------------------------------------
# Procesador de comprobantes — Nómina
# ---------------------------------------------------------------------------
#
# Vista especializada sobre el buffer compartido `cfdis` + tablas
# `nomina_recibos` y `nomina_conceptos` (migración 005). 3 reportes:
# Deductibilidad fiscal, Conciliación IMSS, Periodo vs Periodo.
# NO tiene endpoints de cargar/borrar — los XMLs entran por `/procesador/cfdi/cargar`
# y el borrado por `/procesador/cfdi/borrar`.


class NominaFiltrosRequest(BaseModel):
    rfc: str  # empresa dueña — NO se persiste dentro de los filtros
    desde: Optional[str] = None
    hasta: Optional[str] = None
    busqueda: Optional[str] = None
    tipo_nomina: Optional[str] = None        # 'O' | 'E'
    periodicidad: Optional[str] = None
    solo_con_errores: Optional[bool] = False


def _filtros_nomina_de_query(
    mi_rfc: str,
    desde: Optional[str],
    hasta: Optional[str],
    busqueda: Optional[str],
    tipo_nomina: Optional[str],
    periodicidad: Optional[str],
    solo_con_errores: bool,
) -> dict:
    return {
        "mi_rfc": mi_rfc,
        "desde": desde,
        "hasta": hasta,
        "busqueda": busqueda,
        "tipo_nomina": tipo_nomina,
        "periodicidad": periodicidad,
        "solo_con_errores": solo_con_errores,
    }


@router.get("/procesador/nomina")
def procesador_nomina_listar(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
    tipo_nomina: Optional[str] = None,
    periodicidad: Optional[str] = None,
    solo_con_errores: bool = False,
    page: int = 1,
    page_size: int = 50,
):
    """Recibos paginados (1 fila por CFDI tipo N)."""
    from ...procesador import abrir_db
    from ...procesador.reportes_nomina import listar_recibos

    filtros = _filtros_nomina_de_query(
        _rfc_requerido(rfc),
        desde, hasta, busqueda, tipo_nomina, periodicidad, solo_con_errores,
    )
    track("procesador_usado", tipo="nomina")  # una vez cada 30 min, no por filtro
    return listar_recibos(abrir_db(), filtros, page=page, page_size=page_size)


@router.get("/procesador/nomina/stats")
def procesador_nomina_stats(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
    tipo_nomina: Optional[str] = None,
    periodicidad: Optional[str] = None,
    solo_con_errores: bool = False,
):
    from ...procesador import abrir_db
    from ...procesador.reportes_nomina import stats_nomina

    filtros = _filtros_nomina_de_query(
        _rfc_requerido(rfc),
        desde, hasta, busqueda, tipo_nomina, periodicidad, solo_con_errores,
    )
    return stats_nomina(abrir_db(), filtros)


@router.get("/procesador/nomina/recibo/{uuid}/conceptos")
def procesador_nomina_conceptos_de_recibo(uuid: str, rfc: str):
    """Drilldown: conceptos de un recibo de nómina ordenados por clase (el
    uuid ya no es único — puede vivir bajo dos empresas)."""
    from ...procesador import abrir_db
    from ...procesador.reportes_nomina import conceptos_de_recibo
    return {
        "uuid": uuid,
        "items": conceptos_de_recibo(abrir_db(), uuid, _rfc_requerido(rfc)),
    }


@router.get("/procesador/nomina/reporte/{nombre}")
def procesador_nomina_reporte(
    nombre: str,
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
    tipo_nomina: Optional[str] = None,
    periodicidad: Optional[str] = None,
    solo_con_errores: bool = False,
):
    """Reportes: 'deducibilidad' | 'imss' | 'periodo-vs-periodo'."""
    from ...procesador import abrir_db
    from ...procesador import reportes_nomina as rep

    filtros = _filtros_nomina_de_query(
        _rfc_requerido(rfc),
        desde, hasta, busqueda, tipo_nomina, periodicidad, solo_con_errores,
    )
    db = abrir_db()
    if nombre == "deducibilidad":
        return rep.reporte_deducibilidad(db, filtros)
    if nombre == "imss":
        return rep.reporte_imss(db, filtros)
    if nombre == "periodo-vs-periodo":
        return rep.reporte_periodo_vs_periodo(db, filtros)
    raise HTTPException(status_code=404, detail=f"Reporte desconocido: {nombre}")


@router.get("/procesador/nomina/filtros")
def procesador_nomina_filtros_get(rfc: str):
    from ...procesador import abrir_db
    f = abrir_db().filtros_get(key=f"nomina_actuales:{_rfc_requerido(rfc)}")
    return f or {
        "desde": None, "hasta": None, "busqueda": None,
        "tipo_nomina": None, "periodicidad": None, "solo_con_errores": False,
    }


@router.put("/procesador/nomina/filtros")
def procesador_nomina_filtros_set(req: NominaFiltrosRequest):
    from ...procesador import abrir_db
    mi_rfc = _rfc_requerido(req.rfc)
    abrir_db().filtros_set(req.model_dump(exclude={"rfc"}), key=f"nomina_actuales:{mi_rfc}")
    return {"ok": True}


@router.get("/procesador/nomina/exportar")
def procesador_nomina_exportar(
    rfc: str,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    busqueda: Optional[str] = None,
    tipo_nomina: Optional[str] = None,
    periodicidad: Optional[str] = None,
    solo_con_errores: bool = False,
):
    """XLSX multi-sheet del procesador de Nómina (con disclaimer fiscal)."""
    from ...procesador import abrir_db
    from ...procesador.exportar_nomina import to_xlsx

    filtros = _filtros_nomina_de_query(
        _rfc_requerido(rfc),
        desde, hasta, busqueda, tipo_nomina, periodicidad, solo_con_errores,
    )
    data = to_xlsx(abrir_db(), filtros)
    track("excel_exportado", tipo="nomina", formato="xlsx")
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="nomina.xlsx"'},
    )

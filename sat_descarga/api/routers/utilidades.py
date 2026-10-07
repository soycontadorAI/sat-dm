"""
Router: utilidades sobre CFDIs que no requieren sesión del portal.

Endpoints: /metadata (Web Service, requiere FIEL), /validar (servicio público),
/organizar, /renombrar, /deduplicar (operan sobre archivos locales).
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...utils.validacion import validar_masivo, EstadoCFDI  # noqa: F401
from ..state import _session, _get_fiel, SolicitudRequest
from ..uso import rango, track

router = APIRouter()

# ---------------------------------------------------------------------------
# Modelos de request/response
# ---------------------------------------------------------------------------


class CfdiValidarInput(BaseModel):
    uuid: str
    emisor_rfc: str
    receptor_rfc: str
    total: float


class ValidarRequest(BaseModel):
    cfdis: List[CfdiValidarInput]
    concurrency: int = 10


# ---------------------------------------------------------------------------
# Endpoints: Metadata
# ---------------------------------------------------------------------------

@router.post("/metadata")
def descargar_metadata_endpoint(req: SolicitudRequest):
    """
    Descarga metadata de CFDIs del SAT y retorna el CSV parseado.

    La metadata es un resumen rápido (UUID, RFC, monto, estatus) procesado
    en segundos/minutos (vs 24-72 hrs para CFDIs completos).
    """
    from ...webservice.client import descargar_metadata
    from ...utils.metadata import metadata_to_dicts
    from .. import cupo_descargas

    fiel = _get_fiel()
    cupo_descargas.exigir(rfc=fiel.rfc)  # cuenta como descarga del mes (plan gratis)

    try:
        records = descargar_metadata(
            cer_path=_session["cer_path"],
            key_path=_session["key_path"],
            password=_session["password"],
            fecha_inicio=req.fecha_inicio,
            fecha_fin=req.fecha_fin,
            tipo_comprobante=req.tipo_comprobante,
            rfc_emisor=req.rfc_emisor,
            rfc_receptor=req.rfc_receptor,
        )
        cupo_descargas.registrar("metadata", rfc=fiel.rfc)
        track("descarga_solicitada", canal="web_service", credencial="efirma", tipo="metadata")
        track("descarga_completada", canal="web_service", credencial="efirma",
              tipo="metadata", tamano=rango(len(records)), segundo_plano=False)
        return {
            "ok": True,
            "total": len(records),
            "records": metadata_to_dicts(records),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoints: Validación CFDI (NO requiere FIEL — servicio público del SAT)
# ---------------------------------------------------------------------------

@router.post("/validar")
def validar_cfdis(req: ValidarRequest):
    """
    Valida el estatus de CFDIs ante el SAT (Vigente/Cancelado/No Encontrado).

    NO requiere e-firma. Usa el endpoint público del SAT en
    consultaqr.facturaelectronica.sat.gob.mx.

    Interfaz compatible con todoconta-apps — puede reemplazar la API route
    /api/sat/verify de Next.js, delegando la validación al agente Python local
    (más rápido, sin workarounds de DNS de Next.js/undici).

    Body: { cfdis: [{ uuid, emisor_rfc, receptor_rfc, total }], concurrency: 10 }
    Response: { results: [{ uuid, estado, es_cancelable, estatus_cancelacion, error }] }
    """
    cfdis = [
        {
            "uuid": c.uuid,
            "emisor_rfc": c.emisor_rfc,
            "receptor_rfc": c.receptor_rfc,
            "total": c.total,
        }
        for c in req.cfdis
    ]

    try:
        resultados = validar_masivo(cfdis, concurrency=req.concurrency)
        track("estatus_validado", origen="directo", tamano=rango(len(resultados)))
        return {
            "results": [
                {
                    "uuid": r.uuid,
                    "estado": r.estado,
                    "es_cancelable": r.es_cancelable,
                    "estatus_cancelacion": r.estatus_cancelacion,
                    "validacion_efos": r.validacion_efos,
                    "error": r.error,
                }
                for r in resultados
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoints: Organizador de XMLs (NO requiere FIEL)
# ---------------------------------------------------------------------------

class OrganizarRequest(BaseModel):
    origen: str
    destino: str
    estructura: str = "rfc_emisor/anio/mes"
    copiar: bool = False
    # RFC de la empresa (la activa en la UI); requerido si la estructura usa
    # "rfc" o "flujo". Lo que no es de la empresa se omite — nunca hay "Otros".
    rfc: Optional[str] = None


class RenombrarRequest(BaseModel):
    directorio: str
    patron: str = "emisor_fecha_total"
    # Modo por partes (builder): tokens de NOMBRE_TOKENS o "txt:Literal";
    # si viene, `patron` se ignora.
    partes: Optional[List[str]] = None
    separador: str = "-"


class DeduplicarRequest(BaseModel):
    directorio: str
    dry_run: bool = False


@router.post("/organizar")
def organizar_endpoint(req: OrganizarRequest):
    """Organiza archivos XML en carpetas basándose en su contenido."""
    from ...utils.organizador import organizar

    try:
        result = organizar(
            req.origen, req.destino, req.estructura, req.copiar, rfc=req.rfc
        )
        track("organizador_usado", accion="organizar")
        return {
            "archivos_procesados": result.archivos_procesados,
            "archivos_movidos": result.archivos_movidos,
            "archivos_omitidos": result.archivos_omitidos,
            "errores": result.errores,
            "de_otro_rfc": result.de_otro_rfc,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/renombrar")
def renombrar_endpoint(req: RenombrarRequest):
    """Renombra masivamente archivos XML basándose en su contenido."""
    from ...utils.organizador import renombrar

    try:
        result = renombrar(
            req.directorio, req.patron, partes=req.partes, separador=req.separador
        )
        track("organizador_usado", accion="renombrar")
        return {
            "archivos_procesados": result.archivos_procesados,
            "archivos_movidos": result.archivos_movidos,
            "archivos_omitidos": result.archivos_omitidos,
            "errores": result.errores,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deduplicar")
def deduplicar_endpoint(req: DeduplicarRequest):
    """Elimina archivos XML duplicados basándose en el UUID."""
    from ...utils.organizador import eliminar_duplicados

    try:
        result = eliminar_duplicados(req.directorio, dry_run=req.dry_run)
        track("organizador_usado", accion="deduplicar")
        return {
            "archivos_analizados": result.archivos_analizados,
            "duplicados_encontrados": result.duplicados_encontrados,
            "duplicados_eliminados": result.duplicados_eliminados,
            "errores": result.errores,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

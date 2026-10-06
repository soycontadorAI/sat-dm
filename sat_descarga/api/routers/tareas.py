"""
Router: tareas personales — CRUD + descartes de sugerencias.

Endpoints: /tareas*. Un solo estado global del usuario
(~/.sat-descarga/tareas.json); las sugerencias se derivan en el cliente
(e.firma por vencer, DIOT del mes) y aquí solo persisten sus descartes.

El modelo ya trae ``gcal_event_id`` reservado para la sincronización
unidireccional con Google Calendar (plan: docs/producto/tareas-gcal-sync.md).

Cada mutación dispara el sync desktop ⇄ online en background (best-effort,
ver ``api/sync_tareas.py``) — mismo patrón que el catálogo de empresas.
"""

import logging
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..sync_tareas import sincronizar_async
from ..uso import track

logger = logging.getLogger(__name__)

router = APIRouter()


class TareaCrearRequest(BaseModel):
    titulo: str
    rfc: Optional[str] = None
    tipo: Literal["fiscal", "manual", "recurrente"] = "manual"
    estado: Literal["pendiente", "curso", "hecho"] = "pendiente"
    prioridad: Literal["alta", "media", "baja"] = "media"
    fecha: Optional[str] = None  # YYYY-MM-DD
    sugerencia_id: Optional[str] = None


class TareaPatchRequest(BaseModel):
    """Patch parcial: solo se aplican los campos enviados (exclude_unset)."""

    titulo: Optional[str] = None
    rfc: Optional[str] = None
    tipo: Optional[Literal["fiscal", "manual", "recurrente"]] = None
    estado: Optional[Literal["pendiente", "curso", "hecho"]] = None
    prioridad: Optional[Literal["alta", "media", "baja"]] = None
    fecha: Optional[str] = None


class SugerenciaDescartarRequest(BaseModel):
    id: str


@router.get("/tareas")
def listar_tareas() -> dict:
    from ...tareas import listar

    return listar()


@router.post("/tareas")
def crear_tarea(req: TareaCrearRequest) -> dict:
    from ...tareas import crear

    try:
        tarea = crear(
            req.titulo,
            rfc=req.rfc,
            tipo=req.tipo,
            estado=req.estado,
            prioridad=req.prioridad,
            fecha=req.fecha,
            sugerencia_id=req.sugerencia_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sincronizar_async("crear")
    track("tarea_creada", tipo=req.tipo, desde_sugerencia=bool(req.sugerencia_id))
    return tarea


@router.patch("/tareas/{tarea_id}")
def actualizar_tarea(tarea_id: str, req: TareaPatchRequest) -> dict:
    from ...tareas import actualizar

    cambios = req.model_dump(exclude_unset=True)
    try:
        tarea = actualizar(tarea_id, cambios)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if tarea is None:
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    sincronizar_async("editar")
    return tarea


@router.delete("/tareas/{tarea_id}")
def eliminar_tarea(tarea_id: str) -> dict:
    from ...tareas import eliminar

    if not eliminar(tarea_id):
        raise HTTPException(status_code=404, detail="Tarea no encontrada")
    sincronizar_async("eliminar")
    return {"ok": True}


@router.post("/tareas/sugerencias/descartar")
def descartar_sugerencia(req: SugerenciaDescartarRequest) -> dict:
    from ...tareas import descartar_sugerencia as descartar

    try:
        descartadas = descartar(req.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sincronizar_async("descartar")
    return {"ok": True, "sugerencias_descartadas": descartadas}

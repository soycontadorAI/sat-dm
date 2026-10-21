"""
Router: descarga automática (piloto, docs/producto/descarga-programada.md fase 4).

El planificador vive en `api/piloto.py`; aquí, lo que la UI necesita: el estado
(activo, próxima pasada, cierre, empresas, avisos), activarlo o pausarlo, el día
de cierre, incluir o excluir una empresa, "buscar ahora" y reintentar un día del
cuadro de control. Igual en escritorio y en la versión web.
"""

from datetime import date
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..limites_plan import LimitePlanAlcanzado

router = APIRouter()

_SIN_PILOTO = ("La descarga automática viene en los planes Pro y Completo y en la prueba. "
               "Cambia de plan para activarla.")


class PilotoConfigRequest(BaseModel):
    activo: Optional[bool] = None
    dia_cierre: Optional[int] = Field(None, ge=1, le=28)


class PilotoEmpresaRequest(BaseModel):
    incluida: bool


class AvisosLeidosRequest(BaseModel):
    # Sin ids: todos los avisos sin leer.
    ids: Optional[List[int]] = None


class ReintentarDiaRequest(BaseModel):
    fecha: date
    direccion: Literal["E", "R"]


def _exigir_capacidad() -> None:
    from .. import piloto

    if not piloto.disponible():
        raise LimitePlanAlcanzado(_SIN_PILOTO, "piloto", {"capacidad": "piloto"})


@router.get("/piloto/estado")
def piloto_estado():
    from .. import piloto

    return piloto.estado()


@router.put("/piloto/config")
def piloto_config(req: PilotoConfigRequest):
    """Activa o pausa la descarga automática y fija el día de cierre. Activarla
    exige la capacidad `piloto` (402 si el plan no la trae)."""
    from .. import piloto

    if req.activo:
        _exigir_capacidad()
    try:
        return piloto.configurar(activo=req.activo, dia_cierre=req.dia_cierre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/empresas/{rfc}/piloto")
def piloto_empresa(rfc: str, req: PilotoEmpresaRequest):
    """Incluye o excluye una empresa de la descarga automática."""
    from ...cli import config_store
    from .. import piloto

    limpio = rfc.strip().upper()
    try:
        config_store.set_piloto_incluida(limpio, req.incluida)
    except KeyError:
        raise HTTPException(status_code=404, detail="Esa empresa no está en el catálogo.")
    piloto.despertar()
    return {"ok": True, "rfc": limpio, "incluida": req.incluida}


@router.post("/piloto/correr")
def piloto_correr():
    """Adelanta la siguiente evaluación (no espera a que termine)."""
    from .. import piloto

    piloto.despertar()
    return {"ok": True}


@router.post("/piloto/avisos/leidos")
def piloto_avisos_leidos(req: AvisosLeidosRequest):
    from .. import piloto

    return {"ok": True, "marcados": piloto.marcar_avisos_leidos(req.ids)}


@router.post("/calendario/{rfc}/reintentar")
def calendario_reintentar(rfc: str, req: ReintentarDiaRequest):
    """Vuelve a pedir al SAT un día en error o diferencia (con la e.firma de la
    empresa; no consume el cupo: solo existe con la capacidad `piloto`)."""
    from .. import piloto

    _exigir_capacidad()
    try:
        return piloto.reintentar(rfc, req.fecha, req.direccion)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

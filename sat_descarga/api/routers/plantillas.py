"""
Router: plantillas de export del procesador de CFDI (reportes personalizables).

- `GET /procesador/cfdi/campos`: catálogo de campos para armar plantillas.
- `GET|POST /procesador/plantillas`, `PUT|DELETE /procesador/plantillas/{id}`
  y `PUT /procesador/plantillas/{id}/predeterminada`: las del usuario (las del
  sistema se listan pero no se editan ni se borran).
- `POST /procesador/cfdi/vista-previa`: los primeros renglones de una empresa
  con una plantilla guardada o con la que se está editando.

El archivo sale de `GET /procesador/cfdi/exportar?plantilla=…`
(routers/procesador.py). Diseño: procesador/plantillas.py.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .procesador import _rfc_requerido

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_VISTA_PREVIA = 50


class ColumnaIn(BaseModel):
    campo: str
    encabezado: str = ""


class PlantillaIn(BaseModel):
    nombre: str
    columnas: list[ColumnaIn]
    detalle_concepto: list[ColumnaIn] = Field(default_factory=list)


class VistaPreviaIn(BaseModel):
    rfc: str
    # Una plantilla guardada (id) o la que se edita (columnas sin guardar).
    plantilla: Optional[str] = None
    columnas: Optional[list[ColumnaIn]] = None
    detalle_concepto: list[ColumnaIn] = Field(default_factory=list)
    por_concepto: bool = False
    convertir_mxn: bool = False
    limite: int = 5


def _dicts(cols: list[ColumnaIn]) -> list[dict]:
    return [c.model_dump() for c in cols]


@router.get("/procesador/cfdi/campos")
def campos():
    from ...procesador.plantillas import catalogo

    return catalogo()


@router.get("/procesador/plantillas")
def listar():
    from ...procesador import plantillas_store

    return plantillas_store.listar()


@router.post("/procesador/plantillas")
def crear(req: PlantillaIn):
    from ...procesador import plantillas_store

    try:
        return plantillas_store.crear(req.nombre, _dicts(req.columnas),
                                      _dicts(req.detalle_concepto))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/procesador/plantillas/{plantilla_id}")
def actualizar(plantilla_id: str, req: PlantillaIn):
    from ...procesador import plantillas_store

    try:
        p = plantillas_store.actualizar(plantilla_id, req.nombre, _dicts(req.columnas),
                                        _dicts(req.detalle_concepto))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if p is None:
        raise HTTPException(status_code=404, detail="Esa plantilla no existe.")
    return p


@router.delete("/procesador/plantillas/{plantilla_id}")
def eliminar(plantilla_id: str):
    from ...procesador import plantillas_store

    try:
        borrada = plantillas_store.eliminar(plantilla_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not borrada:
        raise HTTPException(status_code=404, detail="Esa plantilla no existe.")
    return {"ok": True}


@router.put("/procesador/plantillas/{plantilla_id}/predeterminada")
def predeterminada(plantilla_id: str):
    from ...procesador import plantillas_store

    try:
        return {"predeterminada": plantillas_store.fijar_predeterminada(plantilla_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/procesador/cfdi/vista-previa")
def vista_previa(req: VistaPreviaIn):
    """Los CFDIs más recientes de la empresa como texto (lo mismo que saldría
    en el CSV), para ver la plantilla antes de exportar."""
    from ...procesador import abrir_db, plantillas_store
    from ...procesador.plantillas import (
        Plantilla,
        columnas_de,
        normalizar_columnas,
        renglones,
        texto,
    )

    mi_rfc = _rfc_requerido(req.rfc)
    if req.columnas is not None:
        try:
            plantilla = Plantilla(
                id="", nombre="",
                columnas=normalizar_columnas(_dicts(req.columnas), "cfdi"),
                detalle_concepto=normalizar_columnas(_dicts(req.detalle_concepto), "concepto"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif req.plantilla:
        plantilla = plantillas_store.obtener(req.plantilla)
        if plantilla is None:
            raise HTTPException(status_code=404, detail="Esa plantilla no existe.")
    else:
        plantilla = plantillas_store.predeterminada()

    columnas = columnas_de(plantilla, por_concepto=req.por_concepto,
                           convertir_mxn=req.convertir_mxn)
    filas = renglones(
        abrir_db(), {"mi_rfc": mi_rfc}, columnas,
        por_concepto=req.por_concepto, convertir_mxn=req.convertir_mxn,
        ascendente=False, limite=max(1, min(req.limite, MAX_VISTA_PREVIA)),
    )
    return {
        "encabezados": [c.encabezado for c in columnas],
        "tipos": [c.campo.tipo for c in columnas],
        "filas": [[texto(v, c.campo.tipo) for v, c in zip(fila, columnas)] for fila in filas],
    }

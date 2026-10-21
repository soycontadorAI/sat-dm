"""
Router: cuadro de control de descargas (calendario por empresa, día y dirección).

Lee `descarga_dias` del procesador (procesador/calendario.py) para la pantalla
del calendario: el año completo, el detalle de un día y el ZIP de XML de un
mes (para CONTPAQi). No usa el SO, así que funciona igual en escritorio y en
la versión web.
"""

import os
import tempfile
import zipfile
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

router = APIRouter()


def _rfc_del_catalogo(rfc: str) -> str:
    """Normaliza el RFC (400 si es inválido) y exige que esté en el catálogo
    (archivadas incluidas; 404 si no)."""
    from ...cli import config_store
    from ...procesador.db import normalizar_mi_rfc

    try:
        limpio = normalizar_mi_rfc(rfc)
    except ValueError:
        raise HTTPException(status_code=400, detail="RFC inválido o faltante.")
    if limpio not in {e["rfc"] for e in config_store.list_empresas()}:
        raise HTTPException(status_code=404, detail="Esa empresa no está en el catálogo.")
    return limpio


@router.get("/calendario/{rfc}")
def calendario_anio(rfc: str, anio: Optional[int] = Query(None, ge=1990, le=2100)):
    """Estado por día y dirección del año (default: el año de hoy)."""
    from ...procesador import calendario

    mi_rfc = _rfc_del_catalogo(rfc)
    anio = anio or calendario.hoy().year
    # Solo el año que se ve: el poller y el indexado mantienen el resto al día.
    calendario.sincronizar(mi_rfc, date(anio, 1, 1), date(anio, 12, 31))
    return calendario.anio(mi_rfc, anio)


@router.get("/calendario/{rfc}/dia")
def calendario_dia(rfc: str, fecha: date):
    """Detalle de un día: E/R, solicitudes que lo cubren y CFDIs."""
    from ...procesador import calendario

    return calendario.dia(_rfc_del_catalogo(rfc), fecha)


@router.get("/calendario/{rfc}/zip")
def calendario_zip(
    rfc: str,
    anio: int = Query(..., ge=1990, le=2100),
    mes: int = Query(...),
    direccion: Optional[str] = Query(None, pattern="^[ER]$"),
):
    """ZIP con los XML del mes (`{UUID}.xml`, planos) desde el índice. Los CFDI
    sin XML guardado se listan en `sin_xml.txt`."""
    from ...procesador import calendario

    mi_rfc = _rfc_del_catalogo(rfc)
    if not 1 <= mes <= 12:
        raise HTTPException(status_code=400, detail="El mes debe estar entre 1 y 12.")

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    total = 0
    sin_xml: list[str] = []
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for uuid, xml in calendario.xml_del_mes(mi_rfc, anio, mes, direccion):
                total += 1
                if xml is None:
                    sin_xml.append(uuid)
                else:
                    zf.writestr(f"{uuid}.xml", xml)
            if sin_xml:
                zf.writestr("sin_xml.txt", "\n".join(sin_xml) + "\n")
    except Exception:
        os.unlink(tmp.name)
        raise
    if total == 0:
        os.unlink(tmp.name)
        raise HTTPException(status_code=404, detail="No hay CFDI de ese mes en la base.")

    sufijo = {"E": "_emitidos", "R": "_recibidos"}.get(direccion or "", "")
    return FileResponse(
        tmp.name,
        filename=f"cfdi_{mi_rfc}_{anio:04d}-{mes:02d}{sufijo}.zip",
        media_type="application/zip",
        headers={
            "X-Total-Xml": str(total - len(sin_xml)),
            "X-Sin-Xml": str(len(sin_xml)),
        },
        background=BackgroundTask(os.unlink, tmp.name),
    )

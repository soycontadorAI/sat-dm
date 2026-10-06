"""
Router: descarga de archivos por HTTP (versión web).

En la desktop el renderer abre carpetas/archivos con el SO (POST /abrir); en la
versión web eso no existe: estos endpoints sirven el archivo (o la carpeta
empaquetada como ZIP) directamente por HTTP para que el navegador lo descargue.

Seguridad: misma lista blanca que /abrir — solo rutas registradas en el
historial de descargas, comparadas canonicalizadas. La autenticación va por el
middleware de token del agente (acepta `?token=` en el query string, necesario
porque `<a download>` y window.open no mandan headers custom).
"""

import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

router = APIRouter()


def _resolver_ruta_permitida(ruta: str) -> Path:
    """Canonicaliza `ruta` y valida que esté en el historial (lista blanca).

    resolve() normaliza ".." y sigue symlinks: una variante de la misma ruta o
    un symlink no brincan la lista blanca (mismo criterio que /abrir).
    """
    from ...cli import config_store

    rutas = set()
    for d in config_store.list_todas_descargas():
        if not d.get("ruta"):
            continue
        try:
            rutas.add(Path(d["ruta"]).resolve())
        except OSError:
            continue

    try:
        objetivo = Path(ruta).resolve()
    except OSError:
        raise HTTPException(status_code=400, detail="Ruta inválida.")
    if objetivo not in rutas:
        raise HTTPException(status_code=403, detail="Ruta no permitida (no está en el historial).")
    if not objetivo.exists():
        raise HTTPException(status_code=404, detail="La ruta ya no existe (¿se movió o borró?).")
    return objetivo


@router.get("/descargas/archivo")
def descargar_archivo(ruta: str):
    """Sirve un archivo del historial como attachment (p. ej. el PDF de la CSF)."""
    objetivo = _resolver_ruta_permitida(ruta)
    if objetivo.is_dir():
        raise HTTPException(status_code=400, detail="La ruta es una carpeta; usa /descargas/zip.")
    return FileResponse(objetivo, filename=objetivo.name)


@router.get("/descargas/zip")
def descargar_zip(ruta: str):
    """Sirve una descarga del historial empaquetada como ZIP (carpetas de CFDIs, etc.)."""
    objetivo = _resolver_ruta_permitida(ruta)

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            if objetivo.is_file():
                zf.write(objetivo, objetivo.name)
            else:
                for f in sorted(objetivo.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(objetivo))
    except Exception:
        os.unlink(tmp.name)
        raise

    nombre = (objetivo.name if objetivo.is_dir() else objetivo.stem) + ".zip"
    return FileResponse(
        tmp.name,
        filename=nombre,
        media_type="application/zip",
        # El temporal se borra cuando termina de servirse (cleanup en background).
        background=BackgroundTask(os.unlink, tmp.name),
    )


# ---------------------------------------------------------------------------
# Descargas al SAT del mes (plan gratis, F1): lo consulta la UI para el aviso
# ---------------------------------------------------------------------------


@router.get("/descargas/cupo")
def descargas_cupo():
    """Descargas al SAT de este mes y, si aplica, el tope del plan:
    `{aplica, tope, usadas, mes, reinicia, plan_codigo, plan_nombre,
    siguiente_plan}`. Sin red: usa la licencia en cache (sin ella, no aplica)."""
    from .. import cupo_descargas

    return cupo_descargas.estado().como_dict()

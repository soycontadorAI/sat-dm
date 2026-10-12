"""
Router: DIOT 2025 — prellenado, estado editable y export del TXT de carga masiva.

Endpoints: /diot/*. El estado vive por empresa Y periodo
(~/.sat-descarga/diot/{RFC}.json); el prellenado lee el buffer del procesador.
Layout y reglas del archivo: docs/producto/diot-2025.md.

Como en calculadoras, el gating premium del export vive en el frontend: el
agente local es del usuario y no re-valida licencia por endpoint.
"""

import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..uso import track

logger = logging.getLogger(__name__)

router = APIRouter()


def _rfc_requerido(rfc: Optional[str]) -> str:
    """Normaliza y valida el RFC dueño del estado; 400 si es inválido.

    Sin fallback a la "empresa activa" del agente: el RFC viaja SIEMPRE
    explícito desde el cliente (mismo contrato que procesador/calculadoras).
    """
    from ...procesador.db import normalizar_mi_rfc

    try:
        return normalizar_mi_rfc(rfc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validar_periodo_http(periodo: str) -> str:
    from ...diot import validar_periodo

    try:
        return validar_periodo(periodo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _estado_con_validaciones(estado: Optional[dict]) -> dict:
    """Anexa errores/advertencias calculados server-side al estado guardado."""
    from ...diot import validar_filas

    if estado is None:
        return {"filas": [], "origen": None, "generado_en": None,
                "actualizado_en": None, "errores": [], "advertencias": []}
    validacion = validar_filas(estado.get("filas", []))
    return {**estado, **validacion}


class GuardarDiotRequest(BaseModel):
    rfc: str
    periodo: str  # YYYY-MM
    filas: List[dict]


class PrellenarDiotRequest(BaseModel):
    rfc: str
    periodo: str  # YYYY-MM


@router.get("/diot/estado")
def diot_estado(rfc: str, periodo: str):
    """Estado guardado del periodo (filas + validaciones), vacío si no existe."""
    from ...diot import get_periodo

    mi_rfc = _rfc_requerido(rfc)
    _validar_periodo_http(periodo)
    return _estado_con_validaciones(get_periodo(mi_rfc, periodo))


@router.put("/diot/estado")
def diot_guardar(req: GuardarDiotRequest):
    """Guarda la tabla completa del periodo (full-replace) y la re-valida."""
    from ...diot import set_periodo

    mi_rfc = _rfc_requerido(req.rfc)
    _validar_periodo_http(req.periodo)
    estado = set_periodo(mi_rfc, req.periodo, req.filas, origen="manual")
    return _estado_con_validaciones(estado)


@router.post("/diot/prellenar")
def diot_prellenar(req: PrellenarDiotRequest):
    """Prellena el periodo desde el buffer del procesador y lo persiste.

    Pisa los renglones de origen CFDI del periodo (la UI confirma antes si
    había ediciones); los renglones capturados a mano se conservan.
    """
    from ...diot import prellenar_y_guardar

    mi_rfc = _rfc_requerido(req.rfc)
    _validar_periodo_http(req.periodo)
    estado = prellenar_y_guardar(mi_rfc, req.periodo)
    track("diot_generada")
    respuesta = _estado_con_validaciones(estado)
    respuesta["resumen"] = estado.get("resumen")
    return respuesta


def _txt_del_periodo(rfc: str, periodo: str) -> bytes:
    """TXT de carga masiva del periodo guardado: lo que baja GET /diot/exportar
    y lo que sube /diot/presentar con usar_generado=true (un solo camino).

    400 si el periodo no tiene renglones, o con la lista de errores si la tabla
    viola el instructivo del SAT.
    """
    from ...diot import DiotInvalida, exportar_txt, get_periodo

    estado = get_periodo(rfc, periodo)
    if estado is None or not estado.get("filas"):
        raise HTTPException(status_code=400, detail="No hay renglones en este periodo")
    try:
        return exportar_txt(estado["filas"])
    except DiotInvalida as e:
        raise HTTPException(
            status_code=400,
            detail={"mensaje": str(e), "errores": e.errores},
        )


@router.get("/diot/exportar")
def diot_exportar(rfc: str, periodo: str):
    """Genera y descarga el TXT de carga masiva del periodo.

    400 con la lista de errores si la tabla viola el instructivo del SAT.
    """
    from ...diot import nombre_archivo

    mi_rfc = _rfc_requerido(rfc)
    _validar_periodo_http(periodo)
    data = _txt_del_periodo(mi_rfc, periodo)

    filename = nombre_archivo(mi_rfc, periodo)
    track("diot_txt_exportado")
    return StreamingResponse(
        iter([data]),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/diot/catalogos")
def diot_catalogos():
    """Catálogos oficiales para los selects de la UI."""
    from ...diot import (
        MANIFIESTO,
        OPERACIONES_POR_TERCERO,
        PAISES,
        TIPO_OPERACION,
        TIPO_TERCERO,
    )
    from ...diot.layout import CAMPOS_DIOT

    return {
        "tipo_tercero": TIPO_TERCERO,
        "tipo_operacion": TIPO_OPERACION,
        "operaciones_por_tercero": OPERACIONES_POR_TERCERO,
        "manifiesto": MANIFIESTO,
        "paises": PAISES,
        "campos": [
            {"clave": c.clave, "etiqueta": c.etiqueta, "tipo": c.tipo, "seccion": c.seccion}
            for c in CAMPOS_DIOT
        ],
    }


# ---------------------------------------------------------------------------
# Presentación en el portal (job + SSE, FIEL-only) — patrón certifica.py
# ---------------------------------------------------------------------------

class DiotPresentarRequest(BaseModel):
    rfc: str
    ejercicio: int
    periodo: int                       # 1-12
    txt_path: Optional[str] = None     # TXT del software contable del usuario…
    usar_generado: bool = False        # …o el que exporta la propia app
    confirmar: bool = False            # presentar es IRREVERSIBLE → 400 sin esto
    solo_validar: bool = False         # sube y coteja totales, no envía
    sin_estimulos: bool = False        # el flujo con estímulos NO está soportado
    tipo_declaracion: str = "001"


class DiotAcuseRequest(BaseModel):
    rfc: str
    ejercicio: int
    periodo: int


def _carpeta_presentacion(rfc: str, ejercicio: int, periodo: int) -> Path:
    """{descargas}/diot/presentaciones/{RFC}/{AAAA}/{MM}-{AAAA}: evidencia,
    acuse y el TXT generado de esa declaración (misma ruta que el CLI)."""
    from ...cli.config_store import get_descargas_dir

    return (Path(get_descargas_dir()) / "diot" / "presentaciones" / rfc
            / str(ejercicio) / f"{periodo:02d}-{ejercicio}")


def _resolver_txt(req: DiotPresentarRequest, rfc: str, salida: Path) -> str:
    """Ruta del TXT a subir: el del usuario (`txt_path`) tal cual, o el que
    genera la app (`usar_generado`), escrito en la carpeta de la presentación."""
    if req.txt_path:
        path = Path(req.txt_path)
        if not path.is_file():
            raise HTTPException(status_code=400,
                                detail=f"No existe el TXT: {req.txt_path}")
        return str(path)
    if req.usar_generado:
        from ...diot import nombre_archivo

        periodo = _validar_periodo_http(f"{req.ejercicio}-{req.periodo:02d}")
        data = _txt_del_periodo(rfc, periodo)
        destino = salida / nombre_archivo(rfc, periodo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(data)
        return str(destino)
    raise HTTPException(status_code=400,
                        detail="Falta txt_path o usar_generado=true.")


@router.post("/diot/presentar")
def diot_presentar(req: DiotPresentarRequest):
    """Presenta (o solo valida) la DIOT por carga masiva. Devuelve {job_id}.

    Two-step recomendado para la UI: primer request con solo_validar=true (el
    `done` trae los totales que el PORTAL calculó), mostrar al usuario, y
    segundo request con confirmar=true.
    """
    from .certifica import _credenciales_keychain, _lanzar_job_certifica

    if not req.sin_estimulos:
        # Limitante como CONTRATO, no como nota: el flujo con estímulos
        # fiscales no está mapeado (roadmap: capturar los estímulos en la app
        # y poblarlos en la declaración). La UI está obligada a preguntarlo.
        raise HTTPException(
            status_code=400,
            detail=("El flujo solo soporta declaraciones SIN estímulos "
                    "fiscales (se responde «No»). Si la empresa aplica "
                    "estímulos, presenta a mano; confirma con "
                    "sin_estimulos=true."),
        )
    if not req.confirmar and not req.solo_validar:
        raise HTTPException(
            status_code=400,
            detail=("Falta la confirmación explícita de la presentación "
                    "(confirmar=true), o usa solo_validar=true."),
        )
    if not (1 <= req.periodo <= 12):
        raise HTTPException(status_code=400, detail="Periodo inválido (1-12).")

    rfc = _rfc_requerido(req.rfc)
    salida = _carpeta_presentacion(rfc, req.ejercicio, req.periodo)
    txt = _resolver_txt(req, rfc, salida)
    empresa = _credenciales_keychain(rfc)

    def fn_factory(emitir_fase):
        def fn():
            from ...portal.diot_presentacion import PresentadorDiot

            presentador = PresentadorDiot(
                headless=True,
                # la irreversibilidad ya se resolvió con confirmar=true en el
                # request (patrón certifica); no hay callback bloqueante aquí
                confirmar=None,
                on_progreso=lambda fase, data: emitir_fase(fase, data),
            )
            return presentador.presentar(
                empresa["cer_path"], empresa["key_path"], empresa["password"],
                txt_path=txt, ejercicio=req.ejercicio, periodo=req.periodo,
                tipo_declaracion=req.tipo_declaracion,
                directorio_salida=str(salida),
                enviar=bool(req.confirmar and not req.solo_validar),
                rfc=rfc,
            )
        return fn

    modo = "envio" if req.confirmar and not req.solo_validar else "validacion"
    return _lanzar_job_certifica(
        fn_factory, al_completar=lambda _resultado: track("diot_presentada", modo=modo),
    )


@router.post("/diot/acuse")
def diot_acuse(req: DiotAcuseRequest):
    """Reimprime el acuse de una DIOT ya presentada. Devuelve {job_id}.

    OJO: baja el PDF del primer resultado del grid; NO verifica estatus (ver
    docs/producto/pendientes-envios-sat.md — acuse de aceptación DIOT).
    """
    from .certifica import _credenciales_keychain, _lanzar_job_certifica
    from .. import cupo_descargas

    empresa = _credenciales_keychain(req.rfc)
    rfc = _rfc_requerido(req.rfc)
    cupo_descargas.exigir()  # el acuse cuenta como descarga del mes (plan gratis)
    salida = _carpeta_presentacion(rfc, req.ejercicio, req.periodo)

    def fn_factory(emitir_fase):
        def fn():
            from ...portal.diot_presentacion import PresentadorDiot

            presentador = PresentadorDiot(
                headless=True,
                on_progreso=lambda fase, data: emitir_fase(fase, data),
            )
            acuse = presentador.descargar_acuse(
                empresa["cer_path"], empresa["key_path"], empresa["password"],
                ejercicio=req.ejercicio, periodo=req.periodo,
                directorio_salida=str(salida), rfc=rfc,
            )
            if acuse:
                cupo_descargas.registrar("acuse")
            return {"acuse": str(acuse) if acuse else None}
        return fn

    return _lanzar_job_certifica(fn_factory)

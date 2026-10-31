"""
Contabilidad electrónica (Anexo 24): envío de ZIPs y consulta de acuses.

Mismo patrón que `certifica.py`: trámites largos con Playwright → job + SSE
(`GET /events/{job_id}`), un job a la vez, `emitir_fase` con los nombres de
fase estables de `portal/contabilidad_electronica.py`. FIEL-only (sin captcha).

Seguridad del envío (irreversible ante el SAT):
- `confirmar=true` obligatorio para envío real; `solo_validar=true` llega al
  modal de resumen del portal y cancela sin enviar.
- El sellado es decisión VISIBLE del usuario: `sellar` viaja en el request, en
  las fases (`sellando` / `sin_sellar`) y en el resultado.
- Los ZIP se revisan antes de crear el job (nomenclatura vs contenido del XML)
  y los ya presentados se omiten consultando el portal (idempotencia).

El acuse de RECEPCIÓN (AR_) no ampara el cumplimiento; el de ACEPTACIÓN (AP_)
sí — por eso `/ce/acuses` existe y la UI debe mostrar el estatus.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ...core import paths
from ...core.errores import ErrorEsperado
from .. import jobs
from ..state import _descargas_base
from ..uso import track
from .certifica import _credenciales_keychain, _lanzar_job_certifica

logger = logging.getLogger(__name__)
router = APIRouter()


def _destino_todoconta():
    base = _descargas_base()
    return lambda f: paths.dir_ce(f["rfc"], f["anio"], salida_base=base)


class CeEnviarRequest(BaseModel):
    rfc: str
    archivos: list[str]           # rutas absolutas a .zip, o carpetas con .zip
    confirmar: bool = False       # el envío real es irreversible → 400 sin esto
    solo_validar: bool = False    # llega al resumen del portal y cancela
    sellar: bool = True           # decisión visible del usuario
    motivo: str = "mensual"
    reenviar: bool = False        # True: no omitir lo ya presentado


class CeAcusesRequest(BaseModel):
    rfc: str
    anio: int
    mes_ini: int = 1
    mes_fin: int = 13
    bajar: bool = True


class CeReanudarRequest(BaseModel):
    rfc: str


class CeInventarioRequest(BaseModel):
    archivos: list[str]           # rutas a .zip, o carpetas con .zip


RE_FOLIO_ACUSE = re.compile(r"^\d{6,30}$")
_MAX_ZIP_BYTES = 50 * 1024 * 1024   # un ZIP de CE pesa KB; esto es solo una valla


def _expandir_zips(rutas: list[str]) -> list[Path]:
    zips: list[Path] = []
    for r in rutas:
        p = Path(r)
        if p.is_dir():
            zips.extend(sorted(p.glob("*.zip")))
        elif p.is_file() and p.suffix.lower() == ".zip":
            zips.append(p)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"No existe o no es .zip: {r}",
            )
    if not zips:
        raise HTTPException(status_code=400,
                            detail="No hay archivos .zip en esas rutas.")
    return zips


def _dir_acuses(rfc: str, anio: int) -> Path:
    return paths.dir_ce(rfc.strip().upper(), anio, salida_base=_descargas_base())


def _empresa_existente(rfc: str) -> str:
    from ...cli import config_store

    rfc = rfc.strip().upper()
    try:
        config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404,
                            detail=f"No se encontró empresa con RFC {rfc}")
    return rfc


@router.post("/ce/inventario")
def ce_inventario(req: CeInventarioRequest):
    """Revisión previa de los ZIP (nomenclatura vs XML) SIN tocar el portal.

    Es la misma `inventario()` del CLI. Los ZIP con `problemas` no se pueden
    enviar; `/ce/enviar` repite esta revisión por su cuenta.
    """
    from ...portal.contabilidad_electronica import inventario

    return {"archivos": inventario(_expandir_zips(req.archivos))}


@router.post("/ce/subir")
async def ce_subir(archivos: list[UploadFile] = File(...)):
    """Recibe ZIPs desde el navegador (versión web: no hay rutas locales que
    pasar) y los deja en una carpeta de paso del agente. Devuelve el inventario
    con las rutas del agente, que luego se mandan a `/ce/enviar`.

    El nombre del archivo es parte del contrato (Anexo 24), así que se conserva;
    solo se toma el basename para que un nombre con `..` no escape de la carpeta.
    """
    from ...cli import config_store
    from ...portal.contabilidad_electronica import inventario

    if not archivos:
        raise HTTPException(status_code=400, detail="No se recibió ningún archivo.")
    destino = config_store.get_config_dir() / "ce_subidos" / uuid.uuid4().hex
    destino.mkdir(parents=True, exist_ok=True)
    guardados: list[Path] = []
    for up in archivos:
        nombre = Path(up.filename or "").name
        if not nombre.lower().endswith(".zip"):
            etiqueta = nombre or "sin nombre"
            raise HTTPException(status_code=400,
                                detail=f'"{etiqueta}" no es un .zip.')
        datos = await up.read(_MAX_ZIP_BYTES + 1)
        if len(datos) > _MAX_ZIP_BYTES:
            raise HTTPException(status_code=413,
                                detail=f'"{nombre}" es demasiado grande para ser un envío de contabilidad.')
        dest = destino / nombre
        dest.write_bytes(datos)
        guardados.append(dest)
    return {"archivos": inventario(guardados)}


@router.get("/ce/acuse")
def ce_acuse(rfc: str, anio: int, folio: str, tipo: str = "AR"):
    """Sirve un acuse ya descargado: `AR` (recepción) o `AP` (aceptación/rechazo).

    La ruta se DERIVA de rfc+año+folio (no se acepta una ruta del cliente) y el
    folio solo admite dígitos, así que no hay forma de salir de la carpeta de
    acuses de la empresa. No usa la lista blanca del historial.
    """
    tipo = tipo.upper()
    if tipo not in ("AR", "AP"):
        raise HTTPException(status_code=400, detail="tipo debe ser AR o AP.")
    if not RE_FOLIO_ACUSE.match(folio):
        raise HTTPException(status_code=400, detail="Folio inválido.")
    rfc = _empresa_existente(rfc)
    pdf = _dir_acuses(rfc, anio) / f"{tipo}_{folio}.pdf"
    if not pdf.is_file():
        raise HTTPException(status_code=404,
                            detail="Ese acuse no está descargado. Actualiza desde el SAT.")
    return FileResponse(pdf, filename=pdf.name, media_type="application/pdf")


def _guardar_consulta(rfc: str, anio: int, filas: list[dict]) -> None:
    """Última consulta al SAT, para mostrarla sin volver a entrar al portal."""
    d = _dir_acuses(rfc, anio)
    d.mkdir(parents=True, exist_ok=True)
    (d / "consulta.json").write_text(
        json.dumps({"consultado_en": datetime.now(timezone.utc).isoformat(),
                    "filas": filas}, ensure_ascii=False, indent=2),
        encoding="utf-8")


@router.get("/ce/acuses")
def ce_acuses_guardados(rfc: str, anio: int):
    """Última consulta de acuses guardada (sin tocar el SAT).

    Cada fila trae `tiene_ar` / `tiene_ap`: si el PDF está en disco, calculado
    en el momento (el usuario puede haber movido o borrado archivos).
    """
    rfc = _empresa_existente(rfc)
    d = _dir_acuses(rfc, anio)
    archivo = d / "consulta.json"
    if not archivo.is_file():
        return {"consultado_en": None, "filas": []}
    try:
        data = json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"consultado_en": None, "filas": []}
    filas = []
    for f in data.get("filas", []):
        folio = str(f.get("folio") or "")
        ok = bool(RE_FOLIO_ACUSE.match(folio))
        filas.append({
            **{k: v for k, v in f.items()
               if k not in ("acuse_recepcion", "acuse_resultado")},
            "tiene_ar": ok and (d / f"AR_{folio}.pdf").is_file(),
            "tiene_ap": ok and (d / f"AP_{folio}.pdf").is_file(),
        })
    return {"consultado_en": data.get("consultado_en"), "filas": filas}


@router.post("/ce/enviar")
def ce_enviar(req: CeEnviarRequest):
    """Sube ZIPs de contabilidad electrónica. Devuelve `{job_id}` (SSE)."""
    from ...portal.contabilidad_electronica import EnviadorCE, inventario

    if not req.confirmar and not req.solo_validar:
        raise HTTPException(
            status_code=400,
            detail=("Falta la confirmación explícita del envío "
                    "(confirmar=true), o usa solo_validar=true."),
        )

    zips = _expandir_zips(req.archivos)
    fichas = inventario(zips)
    con_problemas = [f for f in fichas if f["problemas"]]
    if con_problemas:
        raise HTTPException(
            status_code=400,
            detail={"mensaje": "Hay ZIPs que no pasan la revisión previa.",
                    "problemas": {f["archivo"]: f["problemas"]
                                  for f in con_problemas}},
        )

    empresa = _credenciales_keychain(req.rfc)
    rutas = [f["path"] for f in fichas]
    destino_de = _destino_todoconta()

    def fn_factory(emitir_fase):
        def fn():
            enviador = EnviadorCE(
                headless=True,
                on_progreso=lambda fase, data: emitir_fase(fase, data),
            )
            return enviador.enviar(
                empresa["cer_path"], empresa["key_path"], empresa["password"],
                rutas,
                sellar=req.sellar,
                enviar=bool(req.confirmar and not req.solo_validar),
                motivo=req.motivo,
                destino_de=destino_de,
                omitir_enviados=not req.reenviar,
            )
        return fn

    def al_completar(resultado):
        # si el SAT dejó fallidos transitorios, a la cola: el poller o
        # /ce/reanudar los retoman sin que el usuario recuerde nada
        from ...portal.contabilidad_electronica import RE_ERROR_TRANSITORIO
        from ...cli.config_store import save_envio_pendiente

        track("contabilidad_electronica_enviada",
              modo="envio" if req.confirmar and not req.solo_validar else "validacion")
        if not isinstance(resultado, dict):
            return
        transitorios = [f for f in resultado.get("fallidos", [])
                        if RE_ERROR_TRANSITORIO.search(f.get("mensaje") or "")]
        if transitorios and req.confirmar and not req.solo_validar:
            save_envio_pendiente(
                req.rfc, "ce", [f["path"] for f in transitorios],
                params={"sellar": req.sellar, "motivo": req.motivo,
                        "salida": None, "junto_al_zip": False},
                error=(transitorios[0].get("mensaje") or "")[:300])

    return _lanzar_job_certifica(fn_factory, al_completar=al_completar)


@router.post("/ce/acuses")
def ce_acuses(req: CeAcusesRequest):
    """Consulta estatus (Recibido/Aceptado/Rechazado) y baja los acuses. Job."""
    from ...portal.contabilidad_electronica import ConsultorCE

    if not (1 <= req.mes_ini <= 13 and req.mes_ini <= req.mes_fin <= 13):
        raise HTTPException(status_code=400, detail="Rango de meses inválido.")
    empresa = _credenciales_keychain(req.rfc)
    destino = paths.dir_ce(req.rfc.strip().upper(), req.anio,
                           salida_base=_descargas_base())

    def fn_factory(emitir_fase):
        def fn():
            consultor = ConsultorCE(
                headless=True,
                on_progreso=lambda fase, data: emitir_fase(fase, data),
            )
            return consultor.consultar(
                empresa["cer_path"], empresa["key_path"], empresa["password"],
                anio=req.anio, mes_ini=req.mes_ini, mes_fin=req.mes_fin,
                bajar_acuses=req.bajar, destino=destino,
            )
        return fn

    def al_completar(resultado):
        if isinstance(resultado, list):
            try:
                _guardar_consulta(req.rfc, req.anio, resultado)
            except OSError:
                logger.warning("No se pudo guardar la consulta de acuses",
                               exc_info=True)

    return _lanzar_job_certifica(fn_factory, al_completar=al_completar)


@router.get("/ce/pendientes")
def ce_pendientes(rfc: Optional[str] = None):
    """Cola de envíos en espera de reintento (SAT lento / mantenimiento)."""
    from ...cli.config_store import get_envios_pendientes

    return {"pendientes": get_envios_pendientes(rfc)}


@router.post("/ce/reanudar")
def ce_reanudar(req: CeReanudarRequest):
    """Retoma los envíos pendientes del RFC. Idempotente (consulta antes). Job."""
    from ...cli.config_store import get_envios_pendientes
    from ...portal.reanudar_envios import reanudar_envios_ce

    if not get_envios_pendientes(req.rfc):
        raise HTTPException(status_code=404,
                            detail="No hay envíos pendientes para ese RFC.")
    empresa = _credenciales_keychain(req.rfc)
    destino_de = _destino_todoconta()

    def fn_factory(emitir_fase):
        def fn():
            try:
                return reanudar_envios_ce(
                    req.rfc, empresa["cer_path"], empresa["key_path"],
                    empresa["password"], headless=True,
                    destino_de=destino_de,
                    on_progreso=lambda fase, data: emitir_fase(fase, data),
                )
            except ErrorEsperado:
                raise  # jobs.py lo degrada a warning; el pendiente sigue en cola
        return fn

    return _lanzar_job_certifica(fn_factory)

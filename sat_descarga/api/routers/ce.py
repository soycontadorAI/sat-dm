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

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
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

    return _lanzar_job_certifica(fn_factory)


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

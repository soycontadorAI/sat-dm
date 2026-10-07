"""
Router: catálogo de empresas (persistente; credenciales en keychain del SO)
+ historial global de descargas.

Endpoints: /empresas* (CRUD, activar, default, archive, unarchive, solicitudes,
historial) y /historial (global).

Tope de empresas del plan (F1, `api/tope_empresas.py`): alta con e.firma, alta
con Contraseña y desarchivar responden 402 con `detail` + `tope_empresas`
cuando no hay lugar. Mismo código en escritorio y en la web.
"""

import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ...core.config import es_modo_hosted
from ..state import _cargar_fiel_empresa
from ..sync_empresas import sincronizar_async
from ..uso import track
from ..tope_empresas import (
    TopeEmpresasAlcanzado,
    exigir_cupo_para_alta,
    exigir_cupo_para_desarchivar,
)

router = APIRouter()


def _respuesta_tope(e: TopeEmpresasAlcanzado) -> JSONResponse:
    """402 Payment Required: el plan no tiene lugar para otra empresa activa."""
    return JSONResponse(status_code=402, content=e.respuesta())


def _rfcs_del_catalogo() -> set:
    """RFCs ya registrados (uso por acción: ¿el alta es una empresa nueva o una
    credencial más para una que ya estaba?)."""
    from ...cli import config_store

    try:
        return set(config_store.load_empresas().get("empresas", {}))
    except Exception:  # noqa: BLE001
        return set()

# ---------------------------------------------------------------------------
# Modelos de request/response
# ---------------------------------------------------------------------------


class EmpresaCiecRequest(BaseModel):
    rfc: str
    # Opcional: si viene vacío, config_store usa el RFC como nombre provisional.
    nombre: str = ""
    ciec: str


class SubirEspacioRequest(BaseModel):
    # Métodos a subir; se filtra a {"fiel", "ciec"}.
    metodos: List[str]


class RegimenFiscalItem(BaseModel):
    clave: str
    descripcion: str


class ActividadEconomicaItem(BaseModel):
    descripcion: str
    principal: Optional[bool] = None
    # % de ingresos según la CSF; presente cuando se rellenó desde la constancia.
    porcentaje: Optional[float] = None


class EmpresaUpdateRequest(BaseModel):
    regimenes_fiscales: Optional[list[RegimenFiscalItem]] = None
    actividades_economicas: Optional[list[ActividadEconomicaItem]] = None
    # Override manual de la obligación DIOT; ausente = la UI deriva del régimen.
    presenta_diot: Optional[bool] = None


# ---------------------------------------------------------------------------
# Endpoints: catálogo de empresas (persistente; credenciales en keychain del SO)
# ---------------------------------------------------------------------------
#
# Reusa cli.config_store (capa de datos sin I/O de terminal): catálogo en
# ~/.sat-descarga/empresas.json + contraseñas en el keychain del SO (core.secretos).
# Así el usuario registra su e.firma/CIEC una vez y no las reingresa cada descarga.

@router.get("/empresas")
def empresas_list():
    """Lista las empresas registradas (sin credenciales)."""
    from ...cli import config_store
    return {"empresas": config_store.list_empresas()}


@router.post("/empresas/fiel")
async def empresas_add_fiel(
    cer_file: UploadFile = File(...),
    key_file: UploadFile = File(...),
    password: str = Form(...),
    nombre: str = Form(""),
    rfc_esperado: Optional[str] = Form(None),
):
    """
    Registra una empresa por e.firma. La contraseña se guarda en el keychain.
    `nombre` es opcional: si viene vacío se usa la razón social del certificado.
    Si se manda `rfc_esperado` (al agregar e.firma a una empresa existente), se valida
    que el RFC del certificado coincida y se rechaza si es de otro contribuyente.
    """
    from ...cli import config_store

    cer_data = await cer_file.read()
    key_data = await key_file.read()
    cer_tmp = tempfile.NamedTemporaryFile(suffix=".cer", delete=False)
    key_tmp = tempfile.NamedTemporaryFile(suffix=".key", delete=False)
    antes = _rfcs_del_catalogo()
    try:
        cer_tmp.write(cer_data); cer_tmp.flush(); cer_tmp.close()
        key_tmp.write(key_data); key_tmp.flush(); key_tmp.close()
        # En un hilo: validar la e.firma es CPU y el tope puede consultar la
        # licencia al servicio (solo cuando el cache dice que no hay lugar).
        rfc = await run_in_threadpool(
            config_store.add_empresa,
            nombre, cer_tmp.name, key_tmp.name, password,
            rfc_esperado=rfc_esperado,
            antes_de_guardar=exigir_cupo_para_alta,
        )
        sincronizar_async("alta-fiel")
        track("empresa_agregada", metodo="efirma", nueva=rfc not in antes)
        return {"ok": True, "rfc": rfc}
    except TopeEmpresasAlcanzado as e:
        return _respuesta_tope(e)
    except ValueError as e:
        # Error de VALIDACIÓN / usuario: contraseña de la .key incorrecta, RFC del
        # cert que no coincide, par cert↔llave inválido, etc. (config_store/FIEL
        # solo lanzan ValueError en estos casos). NO es un bug: es 400 esperado y
        # NO debe reportarse a Sentry (estaba inundándolo con la contraseña mal).
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # Fallo OPERATIVO inesperado (p. ej. el WinError 5 de permisos): sí
        # repórtalo a Sentry, que si no la integración de FastAPI no lo ve (solo
        # captura excepciones no atrapadas).
        from ...core.telemetria import capturar_excepcion

        capturar_excepcion(e)
        raise HTTPException(status_code=400, detail=f"No se pudo registrar la empresa: {e}")
    finally:
        for p in (cer_tmp.name, key_tmp.name):
            try:
                os.unlink(p)
            except Exception:
                pass


@router.post("/empresas/ciec")
def empresas_add_ciec(req: EmpresaCiecRequest):
    """Registra una empresa por CIEC. La contraseña CIEC se guarda en el keychain."""
    from ...cli import config_store
    try:
        exigir_cupo_para_alta(req.rfc)
    except TopeEmpresasAlcanzado as e:
        return _respuesta_tope(e)
    antes = _rfcs_del_catalogo()
    rfc = config_store.add_empresa_ciec(req.rfc, req.nombre, req.ciec)
    sincronizar_async("alta-ciec")
    track("empresa_agregada", metodo="contrasena", nueva=rfc not in antes)
    return {"ok": True, "rfc": rfc}


@router.delete("/empresas/{rfc}")
def empresas_remove(rfc: str):
    """Elimina la empresa del catálogo y borra sus credenciales del keychain."""
    from ...cli import config_store
    config_store.remove_empresa(rfc)
    return {"ok": True}


@router.delete("/empresas/{rfc}/fiel")
def empresas_remove_fiel(rfc: str):
    """
    Quita SOLO la e.firma de la empresa (archivos, contraseña del keychain y
    campos del catálogo); la CIEC no se toca. Si esa e.firma estaba cargada en
    la sesión, también se descarga de memoria.
    """
    from ...cli import config_store
    from ..state import _limpiar_session, _session

    try:
        config_store.remove_efirma(rfc)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if _session.get("rfc") == rfc:
        _limpiar_session()
    sincronizar_async("quitar-fiel")
    return {"ok": True}


@router.post("/empresas/{rfc}/activar")
def empresas_activar(rfc: str):
    """
    Activa una empresa para la sesión. Para FIEL, carga la e.firma guardada en memoria
    (como /auth/cargar-fiel, pero desde el catálogo). Para CIEC no carga e.firma.
    """
    from ...cli import config_store
    try:
        empresa = config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")

    metodos = empresa.get("metodos", [])
    try:
        cargada = _cargar_fiel_empresa(empresa)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001 — cert/llave/contraseña ilegibles
        raise HTTPException(status_code=400, detail=f"No se pudo cargar la e.firma: {e}")
    return {"ok": True, "rfc": rfc, "metodos": metodos, "efirma_lista": cargada}


@router.post("/empresas/{rfc}/default")
def empresas_default(rfc: str):
    """Marca la empresa como predeterminada (activa) del catálogo."""
    from ...cli import config_store
    try:
        config_store.set_default(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")
    return {"ok": True, "rfc": rfc}


@router.post("/empresas/{rfc}/archive")
def empresas_archive(rfc: str):
    """Soft-delete: archiva la empresa (la oculta de la lista principal)."""
    from ...cli import config_store
    try:
        config_store.archive_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")
    sincronizar_async("archivar")
    track("empresa_archivada")
    return {"ok": True, "rfc": rfc}


@router.post("/empresas/{rfc}/unarchive")
def empresas_unarchive(rfc: str):
    """Desarchiva la empresa (la regresa a la lista principal). Ocupa un lugar
    del tope del plan: sin lugar → 402."""
    from ...cli import config_store
    try:
        exigir_cupo_para_desarchivar(rfc)
    except TopeEmpresasAlcanzado as e:
        return _respuesta_tope(e)
    try:
        config_store.unarchive_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")
    sincronizar_async("desarchivar")
    return {"ok": True, "rfc": rfc}


@router.post("/empresas/{rfc}/subir-al-espacio")
def empresas_subir_al_espacio(rfc: str, req: SubirEspacioRequest):
    """
    (Solo desktop) Sube las credenciales de la empresa al espacio en línea del
    usuario: viajan cifradas (HTTPS) DIRECTO a su agente personal en la nube —
    nunca a la base de datos compartida. Es la misma alta que usa la versión
    web, solo que iniciada desde este equipo. Acción explícita del usuario,
    empresa por empresa.
    """
    if es_modo_hosted():
        raise HTTPException(
            status_code=400,
            detail="Ya estás en tu espacio en línea; aquí no hay nada que subir.",
        )
    from ..espacio_online import EspacioOnlineError, subir_credenciales

    metodos = [m for m in req.metodos if m in ("fiel", "ciec")]
    try:
        resultado = subir_credenciales(rfc.strip().upper(), metodos)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC {rfc}")
    except EspacioOnlineError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # El alta remota ya disparó el push del otro lado; este converge el local.
    sincronizar_async("subir-espacio")
    return resultado


@router.get("/empresas/{rfc}/credenciales")
def empresas_exportar_credenciales(rfc: str):
    """
    (Solo modo hosted) Exporta las credenciales de la empresa para la
    continuidad con la desktop: el equipo del usuario las JALA de su espacio
    en la nube (la nube no puede alcanzar su equipo, así que la desktop
    siempre inicia). Protegido por el token del agente — solo se obtiene con
    la sesión de la cuenta vía el provisioner. En desktop no existe (404):
    el agente local solo escucha en loopback y no exporta credenciales.
    """
    if not es_modo_hosted():
        raise HTTPException(status_code=404, detail="Not Found")
    import base64

    from ...cli import config_store

    rfc = rfc.strip().upper()
    try:
        e = config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC {rfc}")

    fiel = None
    cer, key, pwd = e.get("cer_path"), e.get("key_path"), e.get("password")
    if cer and key and pwd and os.path.exists(cer) and os.path.exists(key):
        with open(cer, "rb") as fc, open(key, "rb") as fk:
            fiel = {
                "cer_b64": base64.b64encode(fc.read()).decode(),
                "key_b64": base64.b64encode(fk.read()).decode(),
                "password": pwd,
            }
    return {
        "rfc": rfc,
        "nombre": e.get("nombre") or rfc,
        "fiel": fiel,
        "ciec": e.get("ciec"),
    }


@router.patch("/empresas/{rfc}")
def empresas_update(rfc: str, req: EmpresaUpdateRequest):
    """
    Actualiza campos editables de la empresa (regimenes_fiscales, actividades_economicas).
    Body parcial: solo los campos presentes (no nulos) se aplican.
    """
    from ...cli import config_store
    patch = req.model_dump(exclude_none=True)
    try:
        config_store.update_empresa(rfc, patch)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sincronizar_async("editar")
    return {"ok": True, "rfc": rfc}


@router.post("/empresas/{rfc}/parsear-csf")
def empresas_parsear_csf(rfc: str):
    """
    Re-parsea la Constancia de Situación Fiscal YA descargada (csf_path) y
    aplica nombre, regímenes fiscales y actividades económicas al catálogo —
    sin volver a ir al SAT. Lo usa el botón "Rellenar desde la constancia".
    """
    from ...cli import config_store
    from ...utils.csf_parser import parsear_csf

    try:
        empresa = config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC {rfc}")

    csf_path = empresa.get("csf_path") or ""
    if not csf_path:
        raise HTTPException(
            status_code=409,
            detail="Esta empresa no tiene una constancia descargada. Descárgala primero.",
        )
    if not os.path.isfile(csf_path):
        raise HTTPException(
            status_code=409,
            detail="El archivo de la constancia ya no está en el equipo; descárgala de nuevo.",
        )

    try:
        datos = parsear_csf(csf_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo leer la constancia: {e}")

    if datos.rfc and datos.rfc.upper() != rfc.upper():
        raise HTTPException(
            status_code=409,
            detail=f"La constancia guardada es de otro RFC ({datos.rfc}); descarga la de esta empresa.",
        )

    regimenes = [{"clave": r.clave, "descripcion": r.descripcion} for r in datos.regimenes]
    actividades = [
        {k: v for k, v in {
            "descripcion": a.descripcion,
            "principal": a.principal,
            "porcentaje": a.porcentaje,
        }.items() if v is not None}
        for a in datos.actividades
    ]
    config_store.aplicar_datos_csf(rfc, nombre=datos.nombre,
                                   regimenes=regimenes, actividades=actividades)
    sincronizar_async("editar")
    return {
        "ok": True,
        "rfc": rfc,
        "nombre": datos.nombre,
        "regimenes_fiscales": regimenes,
        "actividades_economicas": actividades,
    }


@router.post("/empresas/{rfc}/parsear-opinion")
def empresas_parsear_opinion(rfc: str):
    """
    Re-parsea la Opinión de Cumplimiento 32-D YA descargada (opinion_path) y
    aplica su sentido (positiva/negativa) + motivos al catálogo — sin volver a
    ir al SAT. Lo usa el botón "Re-analizar opinión".
    """
    from ...cli import config_store
    from ...utils.opinion_parser import parsear_opinion

    try:
        empresa = config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC {rfc}")

    opinion_path = empresa.get("opinion_path") or ""
    if not opinion_path:
        raise HTTPException(
            status_code=409,
            detail="Esta empresa no tiene una opinión 32-D descargada. Descárgala primero.",
        )
    if not os.path.isfile(opinion_path):
        raise HTTPException(
            status_code=409,
            detail="El archivo de la opinión ya no está en el equipo; descárgala de nuevo.",
        )

    try:
        datos = parsear_opinion(opinion_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"No se pudo leer la opinión: {e}")

    if datos.rfc and datos.rfc.upper() != rfc.upper():
        raise HTTPException(
            status_code=409,
            detail=f"La opinión guardada es de otro RFC ({datos.rfc}); descarga la de esta empresa.",
        )

    motivos = [
        {"titulo": m.titulo, "descripcion": m.descripcion, "detalles": m.detalles}
        for m in datos.motivos
    ]
    config_store.aplicar_datos_opinion(rfc, sentido=datos.sentido, motivos=motivos)
    return {
        "ok": True,
        "rfc": rfc,
        "opinion_status": datos.sentido,
        "opinion_motivos": motivos,
    }


@router.get("/empresas/{rfc}/solicitudes")
def empresas_solicitudes(rfc: str):
    """Historial de solicitudes de descarga de la empresa (más recientes primero).

    Aplica el vencimiento local (>72 h pendiente → "vencida") antes de listar,
    para que la UI vea el estado final aunque el poller no haya pasado aún."""
    from ...cli import config_store
    config_store.marcar_solicitudes_vencidas(rfc)
    return {"solicitudes": config_store.list_solicitudes(rfc)}


@router.get("/solicitudes/actividad")
def solicitudes_actividad():
    """Solicitudes WS de TODAS las empresas no archivadas (con rfc + nombre).

    La consume el watcher global del renderer para notificar transiciones
    (lista/descargada/error/vencida) aunque el usuario esté parado en otra
    empresa u otra pantalla. Aplica el vencimiento local antes de listar."""
    from ...cli import config_store

    actividad = []
    for emp in config_store.list_empresas():
        if emp.get("archived_at"):
            continue
        rfc = emp["rfc"]
        config_store.marcar_solicitudes_vencidas(rfc)
        for sol in config_store.list_solicitudes(rfc):
            actividad.append({"rfc": rfc, "nombre": emp.get("nombre") or rfc, **sol})
    return {"solicitudes": actividad}


@router.delete("/empresas/{rfc}/solicitudes/{id_solicitud}")
def empresas_solicitudes_delete(rfc: str, id_solicitud: str):
    """Borra una solicitud del catálogo (solo limpia el registro local, no afecta al SAT)."""
    from ...cli import config_store
    borrada = config_store.delete_solicitud(rfc, id_solicitud)
    if not borrada:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    return {"ok": True}


@router.get("/empresas/{rfc}/historial")
def empresas_historial(rfc: str):
    """Historial de descargas completadas de la empresa (más recientes primero)."""
    from ...cli import config_store
    return {"descargas": config_store.list_descargas(rfc)}


@router.get("/historial")
def historial():
    """Historial de descargas de TODAS las empresas (con rfc + nombre), recientes primero."""
    from ...cli import config_store
    return {"descargas": config_store.list_todas_descargas()}

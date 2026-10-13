"""
Router: Web Service oficial del SAT (e-firma/SOAP) + manejo de la e-firma en sesión.

Endpoints: /auth/cargar-fiel, /auth/fiel, /auth/autocargar-fiel, /solicitar,
/verificar, /descargar, /descarga-completa, /solicitar-folio, /descarga-inteligente.
"""

import functools
import logging
import os
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import List, Optional

import requests
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ...core.fiel import FIEL
from ...webservice.errores import ErrorTransitorioSAT, trae_codestatus
from ...webservice.solicitud import solicitar_descarga
from ...webservice.verificacion import verificar_solicitud, consultar_solicitud
from ...core.config import TIPO_CFDI, TIPO_EMITIDO
from .. import cupo_descargas
from ..uso import rango, tipo_cfdi, tipo_de_solicitud, track
from ..state import (
    _session,
    _get_fiel,
    _renovar_token,
    _limpiar_session,
    _autocargar_empresa_default,
    _descargas_base,
    _registrar_descarga,
    direcciones_de,
    _salida_descarga_ws,
    _iniciar_descarga_ws,
    _terminar_descarga_ws,
    SolicitudRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Segundos que se reutiliza un token del SAT entre solicitudes seguidas (dura ~5 min).
TOKEN_VIGENCIA_S = 240

# ---------------------------------------------------------------------------
# El SAT caído/lento NO es un bug del agente
# ---------------------------------------------------------------------------

_SAT_NO_RESPONDE = (
    "El SAT no respondió (se agotó el tiempo de espera). Suele ocurrir en "
    "horas de alta demanda; la solicitud sigue viva y se reintenta en "
    "automático."
)


def _sat_disponible(fn):
    """Traduce fallos de red contra el SAT (timeout, SSL, conexión) a un 503.

    Los `requests.RequestException` heredan de IOError — el `except RuntimeError`
    de los endpoints nunca los atrapa, así que subían como 500 «unhandled» y
    cada tormenta del SAT generaba eventos de Sentry (TODOCONTA-DESKTOP-13).
    Como HTTPException(503) ya no cuenta como excepción no manejada, y el 503
    está excluido de `failed_request_status_codes` (core/telemetria.py), estos
    fallos transitorios dejan de reportarse. La UI trata el 503 como «el SAT
    está tardando» y sigue reintentando.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except requests.RequestException as e:
            logger.warning("SAT no disponible en %s: %s", fn.__name__, e)
            raise HTTPException(status_code=503, detail=_SAT_NO_RESPONDE) from e
        except ErrorTransitorioSAT as e:
            # El SAT respondió, pero con su error interno genérico
            # (CodEstatus=404 «Error no controlado»): mismo trato que caído.
            logger.warning("SAT con error interno en %s: %s", fn.__name__, e)
            raise HTTPException(status_code=503, detail=str(e)) from e
    return wrapper


# ---------------------------------------------------------------------------
# Modelos de request/response
# ---------------------------------------------------------------------------


class VerificarRequest(BaseModel):
    id_solicitud: str
    poll: bool = False  # True = bloquea hasta que termine


class DescargaCompletaRequest(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    tipo_comprobante: str = TIPO_EMITIDO
    directorio_salida: str = "./cfdi/"
    extraer: bool = True


class SolicitudFolioRequest(BaseModel):
    uuids: List[str]
    tipo_solicitud: str = TIPO_CFDI
    directorio_salida: str = "./cfdi/"
    extraer: bool = True


class DescargaInteligente(BaseModel):
    fecha_inicio: date
    fecha_fin: date
    tipo_comprobante: str = TIPO_EMITIDO
    directorio_salida: str = "./cfdi/"
    ciec: Optional[str] = None  # Si se provee, se puede usar para vol. pequeños
    umbral_ciec: int = 500      # Usar CIEC si el conteo es menor a esto


# ---------------------------------------------------------------------------
# Endpoints: e-firma
# ---------------------------------------------------------------------------

@router.post("/auth/cargar-fiel")
async def cargar_fiel(
    cer_file: UploadFile = File(..., description="Certificado .cer de la e-firma"),
    key_file: UploadFile = File(..., description="Llave privada .key de la e-firma"),
    password: str = Form(..., description="Contraseña de la llave privada"),
):
    """
    Carga la e-firma en memoria del agente local.

    Los archivos se leen en memoria para validar el par certificado/llave.
    Internamente se escriben a archivos temporales del OS (necesario para
    las operaciones criptográficas), pero NUNCA se envían a ningún servidor.

    La e-firma queda disponible para las operaciones de descarga hasta que
    el agente se reinicia o se llama a DELETE /auth/fiel.
    """
    # Leer contenido en memoria
    cer_data = await cer_file.read()
    key_data = await key_file.read()

    # Escribir a temporales para que FIEL pueda cargarlos
    cer_tmp = tempfile.NamedTemporaryFile(suffix=".cer", delete=False)
    key_tmp = tempfile.NamedTemporaryFile(suffix=".key", delete=False)

    try:
        cer_tmp.write(cer_data)
        cer_tmp.flush()
        key_tmp.write(key_data)
        key_tmp.flush()
        cer_tmp.close()
        key_tmp.close()

        fiel = FIEL(cer_tmp.name, key_tmp.name, password)

        # Limpiar sesión anterior si existía
        _limpiar_session()

        _session["fiel"] = fiel
        _session["rfc"] = fiel.rfc
        _session["cer_path"] = cer_tmp.name
        _session["key_path"] = key_tmp.name
        _session["password"] = password
        _session["es_temp"] = True  # archivos temporales → se borran al limpiar

        return {
            "ok": True,
            "rfc": fiel.rfc,
            "numero_serie": fiel.numero_serie,
        }

    except Exception as e:
        # Limpiar temporales si falla la carga
        for path in (cer_tmp.name, key_tmp.name):
            try:
                os.unlink(path)
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=f"Error al cargar e-firma: {e}")


@router.delete("/auth/fiel")
def descargar_fiel():
    """Descarga la e-firma de memoria y elimina los temporales."""
    _limpiar_session()
    return {"ok": True, "mensaje": "E-firma descargada de memoria."}


@router.post("/auth/autocargar-fiel")
def autocargar_fiel_default():
    """
    Carga la FIEL de la empresa activa (si existe) en sesión.

    Reemplazo del autoload que antes corría en el lifespan del agente — ahora
    se invoca explícitamente desde el renderer (post-login) para no bloquear
    el arranque del agente con un `keyring.get_password()` que en Windows
    sin firma puede colgarse esperando un prompt UI.

    Idempotente: si ya hay FIEL en sesión, no hace nada. Si la empresa no
    tiene FIEL o falla la carga, devuelve `ok=false` con detalle — el caller
    NO debe tratar esto como fatal (la app sigue funcional, el usuario solo
    tendrá que cargar la FIEL a mano desde Empresas).
    """
    try:
        _autocargar_empresa_default()
        rfc = _session.get("rfc")
        return {
            "ok": True,
            "cargada": rfc is not None,
            "rfc": rfc,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("autocargar-fiel falló: %s", e)
        return {"ok": False, "cargada": False, "rfc": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Endpoints: Web Service oficial (e-firma)
# ---------------------------------------------------------------------------

@router.post("/solicitar")
@_sat_disponible
def solicitar(req: SolicitudRequest):
    """
    Solicita una descarga masiva al SAT. Devuelve el RequestID.

    El SAT procesa de forma asíncrona:
    - Metadata: responde en segundos/minutos.
    - CFDIs completos: puede tardar 24-72 horas.

    Usa /verificar para consultar el estado y /descargar cuando esté lista.

    Cada solicitud aceptada cuenta como una descarga del mes (plan gratis: 402
    al llegar al tope). Bajar sus paquetes después no vuelve a contar.
    """
    fiel = _get_fiel()
    cupo_descargas.exigir(rfc=fiel.rfc)
    token = _renovar_token()

    try:
        id_solicitud = _pedir_al_sat(fiel, token, req)
        return {"ok": True, "id_solicitud": id_solicitud}
    except ErrorTransitorioSAT:
        raise  # error interno del SAT → lo traduce @_sat_disponible a 503
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _pedir_al_sat(fiel, token: str, req: SolicitudRequest,
                  carpeta_rango: Optional[list] = None) -> str:
    """Lo común de /solicitar y /solicitar/desde-base: pide la descarga al SAT, la
    guarda en el catálogo, cuenta la descarga del mes y registra el uso. Devuelve
    el RequestID; los errores del SAT suben tal cual para que cada endpoint los
    traduzca. `carpeta_rango` ([desde, hasta] ISO): baja a la carpeta de ese rango
    en lugar de la del suyo."""
    id_solicitud = solicitar_descarga(
        fiel=fiel,
        token=token,
        rfc_solicitante=fiel.rfc,
        fecha_inicio=req.fecha_inicio,
        fecha_fin=req.fecha_fin,
        tipo_solicitud=req.tipo_solicitud,
        tipo_comprobante=req.tipo_comprobante,
        rfc_emisor=req.rfc_emisor,
        rfc_receptor=req.rfc_receptor,
        # El SAT rechaza la solicitud (CodEstatus=301 "XML Mal Formado") si no
        # se envía EstadoComprobante — no permite descargar cancelados por WS.
        # Lo forzamos a "Vigente" siempre (E y R por igual): no es una opción
        # del usuario, es un requisito del SAT.
        estado_comprobante="Vigente",
    )
    _guardar_solicitud_ws(fiel.rfc, id_solicitud, req, carpeta_rango=carpeta_rango)
    cupo_descargas.registrar(
        "metadata" if str(req.tipo_solicitud).lower() == "metadata" else "cfdi",
        rfc=fiel.rfc,
    )
    track("descarga_solicitada", canal="web_service", credencial="efirma",
          tipo=tipo_cfdi(req.tipo_comprobante, req.tipo_solicitud))
    return id_solicitud


def _solicitud_viva_igual(rfc: str, desde: date, hasta: date, direccion: str) -> Optional[str]:
    """Id de una solicitud viva (del piloto, o manual sin filtros) con el mismo
    rango, dirección y CFDI, para seguirla en lugar de provocar un 5005."""
    from .. import piloto

    try:
        return piloto._igual(rfc, desde, hasta, direccion, "CFDI", None, manuales=True)
    except Exception:  # noqa: BLE001 - sin catálogo legible, queda el error del SAT
        logger.warning("No se pudo buscar la solicitud viva", exc_info=True)
        return None


@router.post("/solicitar/desde-base")
@_sat_disponible
def solicitar_desde_base(req: SolicitudRequest):
    """
    Como /solicitar, pero lo que el cuadro de control ya tiene `consolidado` se
    sirve de la base local (se guarda en la carpeta de la descarga, sin ir al SAT
    ni gastar descargas del mes) y solo se piden al SAT los días que faltan, en
    rangos contiguos (una solicitud por rango, con tope).

    Solo CFDI con dirección E o R. Si todo el rango está consolidado no se llama
    al SAT, no se exige ni se registra cupo y `id_solicitud` es null. Si un rango
    después del primero falla, se devuelve lo que sí se pidió y el error en
    `errores` (`[{"tipo", "rango": [desde, hasta], "mensaje"}]`, tipo "sat" si un
    hueco no se pudo solicitar, "cupo" si el tope de descargas no deja pedirlo (con
    los `datos` del tope) o "base" si no se pudo guardar lo consolidado; no un 400:
    lo servido y lo pedido ya existen). Lo de la base se sirve primero: si se sirvió
    algo, ningún error del cupo ni del SAT tira la petición, tampoco en el primer
    rango. Un 5005 (ya hay una solicitud igual) se resuelve con la solicitud viva
    sin filtros del mismo rango, si hay una; si no, va a `errores`.

    Con filtros por RFC no se sirve nada de la base, y si el índice falla se
    sigue como /solicitar. Con tope de descargas en el plan se pide un solo
    rango (del primer hueco al último) para que cueste una descarga.
    """
    fiel = _get_fiel()
    if str(req.tipo_solicitud).strip().lower() != "cfdi":
        raise HTTPException(status_code=400, detail="Solo para CFDI")
    direccion = str(req.tipo_comprobante).strip().upper()
    if direccion not in ("E", "R"):
        raise HTTPException(status_code=400, detail="tipo_comprobante debe ser E o R")

    from ...procesador import calendario, servir_base

    if req.fecha_inicio > req.fecha_fin:
        raise HTTPException(status_code=400, detail="La fecha inicial es posterior a la final.")
    if req.fecha_inicio > calendario.hoy():
        raise HTTPException(status_code=400,
                            detail="El periodo empieza después de hoy: todavía no hay CFDI que descargar.")

    rfc = fiel.rfc
    if req.rfc_emisor or req.rfc_receptor:
        # Lo consolidado no está filtrado por RFC: con filtros no se sirve nada de
        # la base y se pide todo el rango, como /solicitar.
        plan = servir_base.plan_sin_base(req.fecha_inicio, req.fecha_fin)
    else:
        try:
            plan = servir_base.plan(rfc, req.fecha_inicio, req.fecha_fin, direccion)
        except Exception:  # noqa: BLE001 - base bloqueada o migración pendiente
            logger.warning("No se pudo leer el índice; se sigue como /solicitar", exc_info=True)
            plan = servir_base.plan_sin_base(req.fecha_inicio, req.fecha_fin)
    huecos = plan["huecos"]
    if len(huecos) > 1 and cupo_descargas.estado().tope is not None:
        # Con tope de descargas cada solicitud cuenta: un solo rango del primer
        # hueco al último (1 descarga, como /solicitar). Los días consolidados que
        # caen dentro de ese rango también se piden, así que ya no se sirven.
        huecos = [(huecos[0][0], huecos[-1][1])]
        a, b = huecos[0]
        plan = {
            **plan,
            "consolidados": [d for d in plan["consolidados"] if not a <= d <= b],
            "uuids": {d: u for d, u in (plan.get("uuids") or {}).items() if not a <= d <= b},
        }

    solicitudes: list[dict] = []
    errores: list[dict] = []
    pedido = [req.fecha_inicio.isoformat(), req.fecha_fin.isoformat()]

    # Primero lo de la base: ya existe y no depende del cupo ni del SAT.
    servidos = {"dias": len(plan["consolidados"]), "cfdis": 0, "ruta": None, "sin_xml": 0}
    try:
        hecho = servir_base.materializar(
            rfc, plan["consolidados"], direccion,
            desde=req.fecha_inicio, hasta=req.fecha_fin,
            uuids_por_dia=plan.get("uuids"),
        )
        servidos.update(cfdis=hecho["cfdis"], ruta=hecho["ruta"], sin_xml=hecho["sin_xml"])
    except Exception as e:  # noqa: BLE001 - los huecos se piden igual
        logger.warning("No se pudo servir lo consolidado desde la base", exc_info=True)
        servidos["dias"] = 0
        errores.append({
            "tipo": "base",
            "rango": pedido,
            "mensaje": f"No se pudo guardar lo consolidado de la base: {e}",
        })
    servido = servidos["dias"] > 0  # con algo servido, ningún error del cupo ni del SAT tira la petición

    if huecos:
        try:
            cupo_descargas.exigir(rfc=rfc)
        except cupo_descargas.TopeDescargasAlcanzado as e:
            if not servido:
                raise
            errores.append({
                "tipo": "cupo",
                "rango": [huecos[0][0].isoformat(), huecos[-1][1].isoformat()],
                "mensaje": e.mensaje,
                "datos": e.datos,
            })
            huecos = []
    token = None
    token_en = 0.0
    for n, (a, b) in enumerate(huecos):
        parte = req.model_copy(update={
            "fecha_inicio": a, "fecha_fin": b, "tipo_comprobante": direccion,
        })
        try:
            # El token dura ~5 min y con reintentos SSL varios huecos pueden pasar de eso.
            if token is None or time.monotonic() - token_en > TOKEN_VIGENCIA_S:
                token = _renovar_token()
                token_en = time.monotonic()
            # Lo que baje va a la carpeta del rango pedido, junto con lo servido.
            id_solicitud = _pedir_al_sat(
                fiel, token, parte,
                carpeta_rango=None if [a.isoformat(), b.isoformat()] == pedido else pedido)
        except Exception as e:  # noqa: BLE001 - tras el primero, lo ya pedido no se pierde
            # 5005: ya hay una solicitud igual (p. ej. la de la descarga
            # automática). Si está viva y sin filtros, esa es la que se sigue.
            ya_pedida = isinstance(e, RuntimeError) and trae_codestatus(str(e), "5005")
            if ya_pedida and not (req.rfc_emisor or req.rfc_receptor):
                existente = _solicitud_viva_igual(rfc, a, b, direccion)
                if existente:
                    solicitudes.append({
                        "id_solicitud": existente,
                        "fecha_inicio": a.isoformat(), "fecha_fin": b.isoformat(),
                    })
                    continue
            if n == 0 and not ya_pedida and not servido:
                # Nada se pidió ni se sirvió: error normal (400 / 503 por el decorador).
                if isinstance(e, (ErrorTransitorioSAT, requests.RequestException)):
                    raise
                if isinstance(e, RuntimeError):
                    raise HTTPException(status_code=400, detail=str(e))
                raise
            logger.warning("Falló el rango %s a %s: %s", a, b, e)
            errores.append({
                "tipo": "sat", "rango": [a.isoformat(), b.isoformat()], "mensaje": str(e),
            })
            continue
        solicitudes.append({
            "id_solicitud": id_solicitud,
            "fecha_inicio": a.isoformat(), "fecha_fin": b.isoformat(),
        })
        try:
            calendario.marcar(rfc, a, b, direccion, "en_proceso", solicitud_id=id_solicitud)
        except Exception:  # noqa: BLE001 - el cuadro de control no rompe la solicitud
            logger.warning("No se pudo marcar el calendario", exc_info=True)

    out = {
        "ok": True,
        "id_solicitud": solicitudes[0]["id_solicitud"] if solicitudes else None,
        "solicitudes": solicitudes,
        "servidos": servidos,
    }
    if errores:
        out["errores"] = errores
    return out


@router.post("/verificar")
@_sat_disponible
def verificar(req: VerificarRequest):
    """
    Consulta el estado de una solicitud de descarga.

    Estados posibles:
    - 1: En cola
    - 2: Procesando
    - 3: Lista (package_ids disponibles para descargar)
    - 4: Error del SAT
    - 5: Rechazada

    Si poll=True, bloquea hasta que la solicitud termine (puede tardar horas).
    Para uso interactivo, usar poll=False y hacer polling periódico desde el cliente.

    Con poll=False los estados de falla (4=error, 5=rechazada, 6=vencida) NO son
    excepción: se persisten en el catálogo y se devuelven al cliente como datos.
    Antes se convertían en HTTP 400 y la solicitud quedaba "Procesando" para
    siempre en el catálogo local.
    """
    fiel = _get_fiel()
    token = _renovar_token()

    try:
        if req.poll:
            estado = verificar_solicitud(
                token=token,
                rfc_solicitante=fiel.rfc,
                id_solicitud=req.id_solicitud,
                fiel=fiel,
                poll=True,
            )
        else:
            estado = consultar_solicitud(
                token=token,
                rfc_solicitante=fiel.rfc,
                id_solicitud=req.id_solicitud,
                fiel=fiel,
            )
        if estado.cod_estado:
            _actualizar_solicitud_ws(
                fiel.rfc, req.id_solicitud, _estado_catalogo(estado.cod_estado),
                package_ids=estado.package_ids if estado.package_ids else None,
                mensaje=estado.mensaje,
                numero_cfdis=estado.numero_cfdis,
                cod_estatus=estado.cod_estatus,
                codigo_estado_solicitud=estado.codigo_estado_solicitud,
            )
        return {
            "cod_estado": estado.cod_estado,
            "mensaje": estado.mensaje,
            "numero_cfdis": estado.numero_cfdis,
            "package_ids": estado.package_ids,
            "terminada": estado.terminada,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/descargar")
@_sat_disponible
def descargar(
    id_solicitud: str,
    directorio_salida: Optional[str] = None,
    extraer: bool = True,
):
    """
    Descarga los paquetes de una solicitud ya terminada (cod_estado=3).

    Llama primero a /verificar para confirmar que la solicitud está lista.
    Si no se pasa `directorio_salida`, se usa la convención por empresa
    (`<descargas>/cfdi/{RFC}/{emitidos|recibidos}/{desde}_a_{hasta}/`), igual que
    las descargas vía CIEC. La carpeta se compone con los datos persistidos al
    crearse la solicitud (`config_store.get_solicitud`); si no hay registro (p. ej.
    flujo legacy), cae al directorio base por RFC.
    """
    from ...webservice.descarga import descargar_todos

    fiel = _get_fiel()

    # Dedup contra el poller en background: si él ya está bajando esta solicitud,
    # no la bajamos doble. La UI trata el 409 como "ya se está resolviendo".
    if not _iniciar_descarga_ws(id_solicitud):
        raise HTTPException(
            status_code=409,
            detail="La descarga de esta solicitud ya está en curso.",
        )

    try:
        token = _renovar_token()

        salida = directorio_salida or _salida_descarga_ws(fiel.rfc, id_solicitud)

        # Verificar estado actual — la petición DEBE ir firmada (xmldsig) con la FIEL,
        # si no, el SAT devuelve un EstadoSolicitud vacío y se ve como "no está lista".
        try:
            estado = verificar_solicitud(
                token=token,
                rfc_solicitante=fiel.rfc,
                id_solicitud=id_solicitud,
                fiel=fiel,
                poll=False,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        if not estado.terminada:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"La solicitud no está lista (cod_estado={estado.cod_estado}). "
                    "Espera a que el SAT termine de procesarla."
                ),
            )

        if not estado.package_ids:
            return {"ok": True, "archivos": [], "total": 0, "mensaje": "Sin CFDIs para el periodo."}

        # Renovar token antes de descargar (puede haber expirado durante el polling)
        token = _renovar_token()

        try:
            zips = descargar_todos(
                token=token,
                rfc_solicitante=fiel.rfc,
                package_ids=estado.package_ids,
                directorio_salida=salida,
                fiel=fiel,
                extraer=extraer,
            )
            # La metadata es un TXT del SAT: va al historial como tal y no se indexa.
            _registrar_descarga(
                fiel.rfc, "ws", "metadata" if _es_metadata_guardada(fiel.rfc, id_solicitud) else "cfdi",
                descripcion=f"Descarga WS · solicitud {id_solicitud[:8]}…",
                ruta=salida, total=estado.numero_cfdis,
                paquetes=estado.package_ids,
            )
            _actualizar_solicitud_ws(
                fiel.rfc, id_solicitud, "descargada", package_ids=estado.package_ids,
            )
            track("descarga_completada", canal="web_service", credencial="efirma",
                  tipo=_tipo_guardado(fiel.rfc, id_solicitud),
                  tamano=rango(estado.numero_cfdis), segundo_plano=False)
            return {
                "ok": True,
                "archivos": [str(z) for z in zips],
                "total": len(zips),
            }
        except HTTPException:
            raise
        except requests.RequestException:
            raise  # red/SSL del SAT → lo traduce @_sat_disponible a 503
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    finally:
        _terminar_descarga_ws(id_solicitud)


@router.post("/descarga-completa")
@_sat_disponible
def descarga_completa(req: DescargaCompletaRequest):
    """
    Flujo completo en un solo endpoint: solicitar → polling → descargar.

    ADVERTENCIA: Bloquea hasta completar. Para CFDIs completos esto puede
    tardar horas (el SAT tarda 24-72 hrs en procesar). Usar solo para
    Metadata o para scripts no interactivos.

    Para uso interactivo en la UI, usar /solicitar + /verificar + /descargar
    de forma separada.
    """
    from ...webservice.client import descargar_cfdi

    cupo_descargas.exigir(rfc=_session["rfc"])
    try:
        zips = descargar_cfdi(
            cer_path=_session["cer_path"],
            key_path=_session["key_path"],
            password=_session["password"],
            fecha_inicio=req.fecha_inicio,
            fecha_fin=req.fecha_fin,
            directorio_salida=req.directorio_salida,
            tipo_solicitud=TIPO_CFDI,
            tipo_comprobante=req.tipo_comprobante,
            extraer=req.extraer,
        )
        _registrar_descarga(
            _session["rfc"], "ws", "cfdi",
            descripcion=f"Descarga WS completa · {req.fecha_inicio} a {req.fecha_fin}",
            ruta=req.directorio_salida,
            rango=(req.fecha_inicio, req.fecha_fin),
            direcciones=direcciones_de(req.tipo_comprobante),
        )
        cupo_descargas.registrar("cfdi", rfc=_session["rfc"])
        # Solicitud y descarga en una sola llamada: cuenta como las dos acciones.
        track("descarga_solicitada", canal="web_service", credencial="efirma",
              tipo=tipo_cfdi(req.tipo_comprobante))
        track("descarga_completada", canal="web_service", credencial="efirma",
              tipo=tipo_cfdi(req.tipo_comprobante), segundo_plano=False)
        return {
            "ok": True,
            "archivos": [str(z) for z in zips],
            "total": len(zips),
        }
    except (requests.RequestException, ErrorTransitorioSAT):
        raise  # red/SSL o error interno del SAT → @_sat_disponible lo hace 503
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoints: Descarga por UUID (SolicitaDescargaFolio)
# ---------------------------------------------------------------------------

@router.post("/solicitar-folio")
@_sat_disponible
def solicitar_folio(req: SolicitudFolioRequest):
    """
    Solicita descarga de CFDIs específicos por UUID.

    Útil para auditorías de folios específicos. Flujo asíncrono igual
    que /solicitar: retorna RequestID → /verificar → /descargar.
    """
    from ...webservice.client import descargar_por_uuid

    _get_fiel()
    cupo_descargas.exigir(rfc=_session["rfc"])

    try:
        zips = descargar_por_uuid(
            cer_path=_session["cer_path"],
            key_path=_session["key_path"],
            password=_session["password"],
            uuids=req.uuids,
            directorio_salida=req.directorio_salida,
            tipo_solicitud=req.tipo_solicitud,
            extraer=req.extraer,
        )
        cupo_descargas.registrar("cfdi", rfc=_session["rfc"])
        track("descarga_solicitada", canal="web_service", credencial="efirma", tipo="por_uuid")
        track("descarga_completada", canal="web_service", credencial="efirma",
              tipo="por_uuid", segundo_plano=False)
        return {
            "ok": True,
            "archivos": [str(z) for z in zips],
            "total": len(zips),
        }
    except (requests.RequestException, ErrorTransitorioSAT):
        raise  # red/SSL o error interno del SAT → @_sat_disponible lo hace 503
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Endpoints: Routing inteligente (CIEC vs Web Service)
# ---------------------------------------------------------------------------

@router.post("/descarga-inteligente")
@_sat_disponible
def descarga_inteligente(req: DescargaInteligente):
    """
    Routing automático según el volumen de CFDIs:

    1. Consulta Metadata del periodo (rápido, <1 min, requiere e-firma).
    2. Si el conteo < umbral_ciec Y se provee ciec → descarga via portal CIEC
       (inmediata, ~2 min).
    3. Si el conteo >= umbral_ciec O no hay ciec → inicia solicitud via Web
       Service (asíncrono, 24-72 hrs).

    Returns:
        {
          "metodo": "ciec" | "web_service",
          "numero_cfdis": int,
          ... (resultado del método elegido)
        }
    """
    from ...webservice.client import descargar_cfdi_inteligente

    _get_fiel()  # Verificar que hay e-firma
    cupo_descargas.exigir(rfc=_session["rfc"])

    try:
        resultado = descargar_cfdi_inteligente(
            cer_path=_session["cer_path"],
            key_path=_session["key_path"],
            password=_session["password"],
            fecha_inicio=req.fecha_inicio,
            fecha_fin=req.fecha_fin,
            tipo_comprobante=req.tipo_comprobante,
            directorio_salida=req.directorio_salida,
            ciec=req.ciec,
            umbral_ciec=req.umbral_ciec,
        )
        cupo_descargas.registrar("cfdi", rfc=_session["rfc"])
        track("descarga_solicitada", tipo=tipo_cfdi(req.tipo_comprobante),
              **_canal_inteligente(resultado))
        return resultado
    except (requests.RequestException, ErrorTransitorioSAT):
        raise  # red/SSL o error interno del SAT → @_sat_disponible lo hace 503
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Helpers: persistencia de solicitudes WS por empresa
# ---------------------------------------------------------------------------


def _es_metadata_guardada(rfc: str, id_solicitud: str) -> bool:
    from ...cli import config_store
    from ..state import es_metadata

    try:
        return es_metadata(config_store.get_solicitud(rfc, id_solicitud))
    except Exception:  # noqa: BLE001
        return False


def _tipo_guardado(rfc: str, id_solicitud: str):
    """emitidos | recibidos | metadata de una solicitud WS guardada (uso por acción)."""
    try:
        from ...cli import config_store
        return tipo_de_solicitud(config_store.get_solicitud(rfc, id_solicitud))
    except Exception:  # noqa: BLE001
        return None


def _canal_inteligente(resultado) -> dict:
    """Canal y credencial que eligió /descarga-inteligente (uso por acción)."""
    if isinstance(resultado, dict) and resultado.get("metodo") == "ciec":
        return {"canal": "rapida", "credencial": "contrasena"}
    return {"canal": "web_service", "credencial": "efirma"}


def _estado_catalogo(cod_estado: str) -> str:
    """Normaliza el EstadoSolicitud del SAT al estado del catálogo local: el 6
    (vencida) se guarda como "vencida" para que la UI lo pinte como terminal."""
    return "vencida" if cod_estado == "6" else cod_estado


def _guardar_solicitud_ws(rfc: str, id_solicitud: str, req: "SolicitudRequest",
                          carpeta_rango: Optional[list] = None) -> None:
    """Guarda la solicitud WS recién creada en el catálogo por empresa. Best-effort.

    Persiste `tipo_comprobante` (E/R) además del tipo humano: lo necesita /descargar
    para ubicar la salida en `{RFC}/{emitidos|recibidos}/{rango}/` (el de
    `carpeta_rango` si viene).
    """
    try:
        from ...cli import config_store
        cuales = {"E": "emitidos", "R": "recibidos"}.get(req.tipo_comprobante, "")
        tipo_humano = f"{req.tipo_solicitud} · {cuales}".rstrip(" ·")
        config_store.save_solicitud(
            rfc, id_solicitud,
            str(req.fecha_inicio), str(req.fecha_fin),
            tipo=tipo_humano,
            tipo_comprobante=req.tipo_comprobante,
            tipo_solicitud=req.tipo_solicitud,
            # Los filtros quedan: una solicitud con contraparte no cubre el día completo
            # (la descarga automática no la toma como suya).
            rfc_emisor=req.rfc_emisor or None,
            rfc_receptor=req.rfc_receptor or None,
            sin_filtros=True if not (req.rfc_emisor or req.rfc_receptor) else None,
            carpeta_rango=carpeta_rango,
        )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo guardar la solicitud en el historial", exc_info=True)


def _actualizar_solicitud_ws(
    rfc: str,
    id_solicitud: str,
    estado: str,
    package_ids=None,
    *,
    mensaje: Optional[str] = None,
    numero_cfdis: Optional[int] = None,
    cod_estatus: Optional[str] = None,
    codigo_estado_solicitud: Optional[str] = None,
) -> None:
    """Actualiza el estado de una solicitud WS guardada. Best-effort.

    También persiste `mensaje`, `numero_cfdis` y `cod_estatus` cuando vienen (los devuelve el SAT
    en /verificar) para mostrarlos en la fila expandida de la UI."""
    try:
        from ...cli import config_store
        config_store.update_solicitud(
            rfc, id_solicitud, estado, package_ids=package_ids,
            mensaje=mensaje, numero_cfdis=numero_cfdis, cod_estatus=cod_estatus,
            codigo_estado_solicitud=codigo_estado_solicitud,
        )
    except Exception:  # noqa: BLE001
        logger.warning("No se pudo actualizar la solicitud en el historial", exc_info=True)



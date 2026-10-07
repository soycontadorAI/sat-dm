"""
Router: Certifica — renovación de e.firma y generación de CSD, de extremo a extremo.

Cada trámite es UN job SSE (la generación local tarda <1 s, así que va dentro del
job y no hay estados huérfanos de .ren/.sdg generados sin enviar):

- POST /renovar            — genera el .ren, lo firma y lo envía a CertiSAT;
                             sustituye la e.firma del catálogo al recuperar el .cer.
- POST /renovar/recuperar  — reintento no destructivo: baja el .cer renovado
                             pendiente y completa la sustitución.
- POST /csd                — genera el .sdg + .key del CSD, lo envía y (si alcanza)
                             recupera el .cer emitido. «Bajar después» es first-class.
- POST /csd/recuperar      — baja el .cer de un CSD pendiente.

FIEL-only: estos trámites NO tienen variante CIEC (CertiSAT solo acepta e.firma;
excepción documentada a la convención dual, ver docs/producto/renovacion-csd-ui-integracion.md).

El progreso se refleja con eventos SSE `{"event": "fase", "fase": ...}` que la UI
mapea a la checklist del wizard: generando → firmando → enviando → numero_operacion
→ acuse → recuperando → guardando.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import jobs
from ..state import _session, _descargas_base, _registrar_descarga, _cargar_fiel_empresa
from ..uso import track
from ...core import paths, secretos
from ...core.fiel import FIEL
from ...cli import config_store

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------------


class RenovarRequest(BaseModel):
    rfc: str
    password: str                      # contraseña de la e.firma VIGENTE (consentimiento)
    confirmar: bool = False            # el trámite es irreversible: la UI debe mandarlo True
    correo: Optional[str] = None       # correo del nuevo requerimiento (default: el del cert)


class RenovarRecuperarRequest(BaseModel):
    rfc: str


class CsdRequest(BaseModel):
    rfc: str
    password: str                      # contraseña de la e.firma (firma y envía)
    password_csd: str = Field(min_length=8)   # contraseña de la .key NUEVA del CSD
    uso: str = "Facturación general"   # nombre/uso del certificado (OU del cert)


class CsdRecuperarRequest(BaseModel):
    rfc: str
    numero_operacion: Optional[str] = None   # default: el último CSD pendiente


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Extensiones que produce el trámite de renovación y que el usuario debe
# resguardar. La .key NUEVA es la crítica: el .cer se puede volver a bajar del
# SAT, la llave privada no.
_EXT_RENOVACION = (".key", ".ren", ".cer", ".pdf")

_LEEME_RESPALDO_RENOVACION = """\
Respaldo de la renovación de tu e.firma — {rfc}

GUARDA ESTA CARPETA EN UN LUGAR SEGURO. Contiene la LLAVE PRIVADA NUEVA de tu
e.firma (el archivo .key).

• El certificado (.cer) siempre lo puedes volver a descargar del SAT, en
  «Recuperación de certificados» de CertiSAT Web.
• La LLAVE PRIVADA NUEVA (.key) NO. Si la pierdes, el certificado que te emitió
  el SAT queda inservible y hay que tramitar una e.firma nueva de forma
  PRESENCIAL, con cita.
• Tu contraseña NO está en este ZIP. Es la misma que usabas en tu e.firma
  anterior. Si la pierdes tampoco se puede recuperar: el .key está cifrado con
  ella.

Contenido:
  .key  — llave privada NUEVA (la crítica)
  .ren  — solicitud de renovación que se envió al SAT
  .cer  — certificado nuevo emitido por el SAT (si el trámite ya concluyó)
  .pdf  — acuse del trámite (si el SAT ya lo entregó)
"""


def _archivos_renovacion(rfc: str) -> list[Path]:
    """Archivos del trámite de renovación de `rfc` que existen hoy en disco.

    La ruta se deriva del RFC (nunca del cliente) y se limita a las extensiones
    del trámite, para que este endpoint no pueda servir nada más.
    """
    carpeta = paths.dir_documento(
        paths.TIPO_RENOVACION, rfc, salida_base=_descargas_base(),
    )
    if not carpeta.is_dir():
        return []
    return sorted(
        f for f in carpeta.iterdir()
        if f.is_file() and f.suffix.lower() in _EXT_RENOVACION
    )


def _empresa_con_fiel(rfc: str) -> dict:
    """Empresa del catálogo con método e.firma, o 404/400."""
    try:
        empresa = config_store.get_empresa(rfc.strip().upper())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No se encontró empresa con RFC {rfc}")
    if "fiel" not in empresa.get("metodos", []):
        raise HTTPException(
            status_code=400,
            detail="Esta empresa no tiene e.firma registrada. Agrégala en Empresas.",
        )
    return empresa


def _credenciales_fiel(rfc: str, password: str) -> tuple[dict, FIEL]:
    """
    Valida la contraseña TECLEADA por el usuario contra la e.firma del catálogo
    (confirmarla es el gesto de consentimiento del trámite; no se toma del keychain).
    """
    empresa = _empresa_con_fiel(rfc)
    try:
        fiel = FIEL(empresa["cer_path"], empresa["key_path"], password)
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Contraseña incorrecta de la e.firma. Verifica e intenta de nuevo.",
        )
    return empresa, fiel


def _credenciales_keychain(rfc: str) -> dict:
    """Credenciales de la e.firma con la contraseña del keychain (reintentos no
    destructivos, sin re-teclear)."""
    empresa = _empresa_con_fiel(rfc)
    if not empresa.get("password"):
        raise HTTPException(
            status_code=400,
            detail="No hay contraseña de e.firma guardada para este RFC.",
        )
    return empresa


def _lanzar_job_certifica(fn_factory, al_completar=None):
    """
    Como `_lanzar_job_portal`, pero la factory recibe `emitir_fase(fase, data)` en
    vez del callback de captcha (la e.firma no pide captcha). Solo un job a la vez.
    """
    if jobs.registry.hay_activo():
        raise HTTPException(
            status_code=409,
            detail="Ya hay una operación en curso. Espera a que termine o cancélala.",
        )
    job = jobs.registry.crear()

    def emitir_fase(fase: str, data: Optional[dict] = None):
        jobs.registry.emitir(job, "fase", fase=fase, **(data or {}))

    fn = fn_factory(emitir_fase)

    def fn_con_navegador():
        from ...portal import setup

        if not setup.navegador_listo():
            jobs.registry.emitir(
                job, "log", nivel="info",
                mensaje=(
                    "Preparando el navegador de trámites (~170 MB, solo la "
                    "primera vez). Esto puede tardar unos minutos…"
                ),
            )
            setup.asegurar_chromium()
            jobs.registry.emitir(job, "log", nivel="ok", mensaje="Navegador listo.")
        return fn()

    jobs.registry.ejecutar(job, fn_con_navegador, al_completar=al_completar)
    return {"job_id": job.id}


def _instalar_efirma_renovada(rfc: str, cer_nuevo: str, key_nueva: str, password: str):
    """
    Paso «guardando»: respalda la e.firma anterior, registra la renovada en el
    catálogo (valida el par, copia a efirma/{RFC}/, keychain, vencimiento) y
    recarga la sesión si esta empresa era la activa.
    """
    config_store.respaldar_efirma_anterior(rfc)
    config_store.add_empresa("", cer_nuevo, key_nueva, password, rfc_esperado=rfc)
    config_store.clear_renovacion_pendiente(rfc)
    if _session.get("rfc") == rfc:
        try:
            _cargar_fiel_empresa(config_store.get_empresa(rfc))
        except Exception as e:  # noqa: BLE001 — la sesión se recarga al reabrir
            logger.warning("No se pudo recargar la sesión con la e.firma renovada: %s", e)


def _verificar_renovacion_procesada(empresa: dict, password: str, salida: str,
                                    key_nueva: str, emitir_fase) -> Optional[str]:
    """
    Tras un envío fallido del `.ren`, verifica si el SAT en realidad YA procesó
    el trámite (glitch del portal después de aceptar la solicitud): busca el
    último certificado del RFC en «Recuperación de certificados» y exige que
    empareje con NUESTRA `.key` nueva. Devuelve la ruta del `.cer` emitido o
    None (incluye cualquier fallo del portal: este chequeo es best-effort y
    nunca debe tapar el error de envío original).

    OJO: el login usa la e.firma vigente del catálogo; si el SAT ya la revocó
    por la renovación, este login puede rebotar mientras propaga — en ese caso
    devolvemos None y el usuario reintenta más tarde (el mismo fallback vuelve
    a correr).
    """
    try:
        from ...portal.renovacion import recuperar_renovacion_fiel

        emitir_fase("recuperando", {"intento": 1, "max": 2})

        def puente(fase, data):
            # Solo las fases de la etapa de descarga: el login del chequeo no
            # debe regresar la checklist del wizard al paso "enviando".
            if fase in ("recuperando", "cer"):
                emitir_fase(fase, data)

        res = recuperar_renovacion_fiel(
            empresa["cer_path"], empresa["key_path"], password,
            directorio_salida=salida, key_nueva_path=key_nueva,
            intentos=2, espera_s=15, on_progreso=puente,
        )
        return str(res["cer"]) if res.get("cer") else None
    except Exception as e:  # noqa: BLE001 — best-effort
        logger.info("[renovar] verificación post-fallo sin resultado: %s", e)
        return None


# ---------------------------------------------------------------------------
# Renovación de e.firma
# ---------------------------------------------------------------------------


@router.post("/renovar")
def renovar_efirma(req: RenovarRequest):
    """
    Renueva la e.firma EN LÍNEA (solo si sigue vigente): genera el `.ren`, lo firma
    con el certificado actual, lo envía a CertiSAT y — si el SAT lo emite a tiempo —
    descarga el `.cer` nuevo y sustituye la e.firma del catálogo. → {job_id}.

    ⚠️ Irreversible: el certificado anterior queda revocado. `confirmar` debe venir
    en true (la UI pide confirmación explícita antes de llamar).
    """
    if not req.confirmar:
        raise HTTPException(
            status_code=400,
            detail="Falta la confirmación explícita del trámite (confirmar=true).",
        )
    rfc = req.rfc.strip().upper()
    empresa, fiel = _credenciales_fiel(rfc, req.password)
    if not fiel.vigente:
        raise HTTPException(
            status_code=400,
            detail=(
                "La renovación en línea ya no es posible: la e.firma está vencida. "
                "Renuévala presencialmente en una oficina del SAT y actualiza aquí "
                "los archivos nuevos."
            ),
        )
    pendiente = config_store.get_renovacion_pendiente(rfc)
    if pendiente and pendiente.get("numero_operacion"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Ya hay una renovación enviada pendiente de descargar. "
                "Usa «Descargar certificado» (POST /renovar/recuperar)."
            ),
        )
    # Pendiente SIN número de operación = el `.ren` se generó pero el envío no se
    # logró (portal del SAT caído). Se REUTILIZA el mismo .ren/.key: si el SAT
    # hubiera alcanzado a procesar el envío sin que leyéramos el número, el cert
    # emitido empareja con ESA .key — regenerar la perdería. Si el usuario borró
    # los archivos del trámite, se limpia y se regenera.
    reusar: Optional[dict] = None
    if pendiente:
        ren_prev, key_prev = pendiente.get("ren_path"), pendiente.get("key_path")
        if ren_prev and key_prev and Path(ren_prev).exists() and Path(key_prev).exists():
            reusar = {"ren": ren_prev, "key": key_prev,
                      "solicitado_en": pendiente.get("solicitado_en")}
        else:
            config_store.clear_renovacion_pendiente(rfc)

    password = req.password
    correo = req.correo
    salida = str(paths.dir_documento(paths.TIPO_RENOVACION, rfc,
                                     salida_base=_descargas_base()))

    def factory(emitir_fase):
        def run():
            from ...certifica import generar_renovacion_fiel
            from ...portal.renovacion import enviar_renovacion_fiel

            emitir_fase("generando")
            if reusar:
                ren_path, key_nueva = str(reusar["ren"]), str(reusar["key"])
            else:
                # La contraseña de la .key nueva = la de la vigente (decisión UX:
                # una sola contraseña que el usuario ya conoce).
                generado = generar_renovacion_fiel(
                    fiel, correo=correo, password=password, salida_dir=salida,
                )
                ren_path, key_nueva = str(generado["ren"]), str(generado["key"])
            # Persistir ANTES de enviar (etapa "generada"): si el portal del SAT
            # falla en el envío, el reintento continúa desde aquí con el MISMO .ren.
            config_store.set_renovacion_pendiente(rfc, {
                "etapa": "generada",
                "numero_operacion": None,
                "acuse_pdf": None,
                "ren_path": ren_path,
                "key_path": key_nueva,
                **({"solicitado_en": reusar["solicitado_en"]}
                   if reusar and reusar.get("solicitado_en") else {}),
            })
            emitir_fase("firmando")     # la firma CMS ocurrió dentro del .ren

            def puente(fase, data):
                emitir_fase(fase, data)
                if fase == "numero_operacion":
                    # El SAT ya tiene el trámite: etapa "enviada". Si la app muere
                    # a media recuperación, la UI retoma con /renovar/recuperar.
                    actual = config_store.get_renovacion_pendiente(rfc) or {}
                    config_store.set_renovacion_pendiente(rfc, {
                        **actual,
                        "etapa": "enviada",
                        "numero_operacion": data.get("numero"),
                    })
                elif fase == "acuse" and data.get("acuse_pdf"):
                    actual = config_store.get_renovacion_pendiente(rfc) or {}
                    if actual:
                        config_store.set_renovacion_pendiente(
                            rfc, {**actual, "acuse_pdf": data["acuse_pdf"]},
                        )

            emitir_fase("enviando")
            try:
                res = enviar_renovacion_fiel(
                    empresa["cer_path"], empresa["key_path"], password,
                    ren_path, directorio_salida=salida,
                    key_nueva_path=key_nueva, recuperar=True,
                    intentos_cert=6, espera_cert_s=30, on_progreso=puente,
                )
            except Exception as e_envio:
                # Fallback: quizá un envío (este o uno previo que quedó en etapa
                # "generada") SÍ fue procesado por el SAT sin que alcanzáramos a
                # leer el número de operación — en ese caso el reenvío rebota.
                # Se busca en «Recuperación de certificados» el último cert del
                # RFC y se verifica que EMPAREJE con nuestra .key (criptográfico,
                # sin falsos positivos): si empareja, la renovación ya ocurrió.
                cer_rescatado = _verificar_renovacion_procesada(
                    empresa, password, salida, key_nueva, emitir_fase,
                )
                if cer_rescatado is None:
                    raise e_envio  # error real de envío: no hay trámite procesado
                logger.info(
                    "[renovar %s] el SAT ya había procesado la renovación; se "
                    "recuperó el certificado emitido.", rfc,
                )
                res = {"numero_operacion": None, "acuse_pdf": None,
                       "estado": "Renovación verificada tras reintento",
                       "cer": cer_rescatado}

            renovada = False
            vencimiento = None
            if res.get("cer"):
                emitir_fase("guardando")
                _instalar_efirma_renovada(rfc, str(res["cer"]), key_nueva, password)
                renovada = True
                vencimiento = config_store.get_empresa(rfc).get("vencimiento")

            return {
                "numero_operacion": res.get("numero_operacion"),
                "acuse_pdf": str(res["acuse_pdf"]) if res.get("acuse_pdf") else None,
                "estado": res.get("estado"),
                "cer": str(res["cer"]) if res.get("cer") else None,
                "vencimiento": vencimiento,
                "renovada": renovada,
                "cer_pendiente": not renovada,
            }
        return run

    def al_completar(resultado):
        if (resultado or {}).get("renovada"):
            _registrar_descarga(
                rfc, "fiel", "renovacion",
                descripcion="Renovación de e.firma en línea",
                ruta=(resultado or {}).get("acuse_pdf") or salida,
            )
        track("efirma_renovada",
              certificado="emitido" if (resultado or {}).get("renovada") else "pendiente")

    return _lanzar_job_certifica(factory, al_completar=al_completar)


@router.get("/renovar/estado")
def renovar_estado(rfc: str):
    """Estado del trámite de renovación de un RFC. → dict, siempre 200.

    Existe para que la UI **nunca** muestre una pantalla muda: si la app se
    cerró a media renovación (o el usuario cambió de máquina), aquí ve en qué
    etapa quedó, si el SAT ya recibió el trámite y si puede bajarse el respaldo.

    Etapas (las persiste `POST /renovar`):
      - `generada` — la .key nueva y el .ren ya existen en disco; el SAT AÚN NO
        recibe nada. Reintentar es seguro.
      - `enviada`  — el SAT ya tiene el trámite (hay número de operación). NO
        se debe regenerar: se completa con `POST /renovar/recuperar`.
    """
    rfc = rfc.strip().upper()
    try:
        config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")

    pendiente = config_store.get_renovacion_pendiente(rfc) or {}
    archivos = _archivos_renovacion(rfc)
    etapa = pendiente.get("etapa")
    return {
        "rfc": rfc,
        "pendiente": bool(pendiente),
        "etapa": etapa,
        "numero_operacion": pendiente.get("numero_operacion"),
        "solicitado_en": pendiente.get("solicitado_en"),
        # El SAT ya recibió: regenerar duplicaría el trámite.
        "reintento_seguro": etapa == "generada",
        "siguiente_paso": (
            "recuperar" if etapa == "enviada"
            else "reintentar" if etapa == "generada"
            else None
        ),
        "respaldo_disponible": bool(archivos),
        "archivos": [p.name for p in archivos],
    }


@router.get("/renovar/respaldo")
def renovar_respaldo(rfc: str):
    """ZIP con lo que exista del trámite de renovación (.key nueva, .ren, acuse, .cer).

    **Es la red de seguridad del trámite.** El `.cer` nuevo siempre se puede
    volver a bajar del SAT («Recuperación de certificados»), pero la **llave
    privada nueva no**: si se pierde, el certificado emitido queda inservible y
    el contribuyente tiene que ir presencialmente al SAT. Por eso este endpoint
    sirve desde la etapa `generada` — antes de que el SAT reciba nada — y no
    espera a que el trámite termine.

    No usa la lista blanca del historial (a esa altura el trámite todavía no
    está registrado): la ruta se deriva del RFC, nunca del cliente.
    """
    rfc = rfc.strip().upper()
    try:
        config_store.get_empresa(rfc)
    except KeyError:
        raise HTTPException(status_code=404, detail="empresa no encontrada")

    archivos = _archivos_renovacion(rfc)
    if not archivos:
        raise HTTPException(
            status_code=404,
            detail="No hay archivos de renovación para este RFC.",
        )

    import tempfile
    import zipfile

    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    try:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in archivos:
                zf.write(f, f.name)
            zf.writestr("LÉEME.txt", _LEEME_RESPALDO_RENOVACION.format(rfc=rfc))
    except Exception:
        os.unlink(tmp.name)
        raise

    return FileResponse(
        tmp.name,
        filename=f"{rfc}_renovacion_efirma.zip",
        media_type="application/zip",
        background=BackgroundTask(os.unlink, tmp.name),
    )


@router.post("/renovar/recuperar")
def renovar_recuperar(req: RenovarRecuperarRequest):
    """
    Reintento NO destructivo: descarga el `.cer` de una renovación ya enviada
    (el SAT tarda minutos en emitirlo) y completa la sustitución. → {job_id}.
    """
    rfc = req.rfc.strip().upper()
    pendiente = config_store.get_renovacion_pendiente(rfc)
    if not pendiente:
        raise HTTPException(
            status_code=404,
            detail="No hay una renovación pendiente de descargar para este RFC.",
        )
    if not pendiente.get("numero_operacion"):
        # Etapa "generada": el .ren nunca llegó al SAT → aquí no hay nada que
        # descargar; el reintento correcto es POST /renovar (reenvía el mismo .ren).
        raise HTTPException(
            status_code=409,
            detail=(
                "La solicitud de renovación aún no se envía al SAT. "
                "Reintenta la renovación: se reenviará la misma solicitud."
            ),
        )
    empresa = _credenciales_keychain(rfc)
    password = empresa["password"]
    key_nueva = pendiente.get("key_path")
    salida = str(paths.dir_documento(paths.TIPO_RENOVACION, rfc,
                                     salida_base=_descargas_base()))

    def factory(emitir_fase):
        def run():
            from ...portal.renovacion import recuperar_renovacion_fiel

            def puente(fase, data):
                emitir_fase(fase, data)

            res = recuperar_renovacion_fiel(
                empresa["cer_path"], empresa["key_path"], password,
                directorio_salida=salida, key_nueva_path=key_nueva,
                intentos=10, espera_s=30, on_progreso=puente,
            )
            renovada = False
            vencimiento = None
            if res.get("cer"):
                emitir_fase("guardando")
                _instalar_efirma_renovada(rfc, str(res["cer"]), key_nueva, password)
                renovada = True
                vencimiento = config_store.get_empresa(rfc).get("vencimiento")
            return {
                "cer": str(res["cer"]) if res.get("cer") else None,
                "vencimiento": vencimiento,
                "renovada": renovada,
                "cer_pendiente": not renovada,
                "numero_operacion": pendiente.get("numero_operacion"),
                "acuse_pdf": pendiente.get("acuse_pdf"),
            }
        return run

    def al_completar(resultado):
        if (resultado or {}).get("renovada"):
            _registrar_descarga(
                rfc, "fiel", "renovacion",
                descripcion="Renovación de e.firma en línea",
                ruta=(resultado or {}).get("acuse_pdf") or salida,
            )

    return _lanzar_job_certifica(factory, al_completar=al_completar)


# ---------------------------------------------------------------------------
# Certificado de Sello Digital (CSD)
# ---------------------------------------------------------------------------

# La contraseña del CSD se necesita para timbrar. Se guarda en el keychain
# (csd:{RFC}) Y en un .txt junto a los archivos del CSD — decisión explícita de
# producto (2026-07-09) que excepciona la regla "contraseñas solo en keychain":
# la app podrá leerla para emitir CFDI/timbrar nómina, y el usuario conserva
# una copia legible con sus archivos. El .txt lo advierte.
_TXT_PASSWORD_CSD = """\
Contraseña de la clave privada (.key) de este CSD — {rfc}

    {password}

• La necesitas para timbrar CFDI con este Certificado de Sello Digital.
• El SAT no puede recuperarla: guarda este archivo (o la contraseña) en un
  lugar seguro. TodoConta también la conserva en el llavero de tu equipo.
• Si la pierdes y no tienes respaldo, genera un nuevo CSD (es gratuito).
"""


@router.post("/csd")
def csd_solicitar(req: CsdRequest):
    """
    Genera un CSD de extremo a extremo: crea la `.key` + `.sdg`, lo firma con la
    e.firma, lo envía a Certifica/CertiSAT y (si alcanza) recupera el `.cer`
    emitido. El certificado puede tardar minutos: si no está listo, queda
    `cert_pendiente` y se descarga después con /csd/recuperar. → {job_id}.
    """
    rfc = req.rfc.strip().upper()
    empresa, fiel = _credenciales_fiel(rfc, req.password)
    uso = req.uso.strip() or "Facturación general"
    password = req.password
    password_csd = req.password_csd
    salida = str(paths.dir_documento(paths.TIPO_CSD, rfc, salida_base=_descargas_base()))

    def factory(emitir_fase):
        def run():
            from ...certifica import generar_solicitud_csd
            from ...portal.csd import enviar_solicitud_csd_fiel

            emitir_fase("generando")
            generado = generar_solicitud_csd(fiel, uso, password_csd, salida_dir=salida)
            key_csd = str(generado["key"])
            emitir_fase("firmando")

            # Contraseña del CSD: keychain + copia .txt junto a la .key (ver nota).
            try:
                secretos.guardar(rfc, secretos.CSD, password_csd)
            except Exception as e:  # noqa: BLE001 — sin keychain igual queda el .txt
                logger.warning("No se pudo guardar la contraseña del CSD en el keychain: %s", e)
            txt = Path(key_csd).with_name(Path(key_csd).stem + "_contraseña.txt")
            txt.write_text(_TXT_PASSWORD_CSD.format(rfc=rfc, password=password_csd),
                           encoding="utf-8")

            def puente(fase, data):
                emitir_fase(fase, data)
                if fase == "numero_operacion":
                    config_store.registrar_csd(rfc, {
                        "uso": uso,
                        "numero_operacion": data.get("numero"),
                        "acuse_pdf": None,
                        "key_path": key_csd,
                    })
                elif fase == "acuse" and data.get("acuse_pdf"):
                    pendiente = config_store.get_csd_pendiente(rfc)
                    if pendiente:
                        config_store.update_csd(
                            rfc, pendiente["numero_operacion"],
                            {"acuse_pdf": data["acuse_pdf"]},
                        )

            emitir_fase("enviando")
            # Intentos cortos a propósito: «bajar después» es first-class; el
            # wizard no debe colgarse minutos esperando al SAT.
            res = enviar_solicitud_csd_fiel(
                empresa["cer_path"], empresa["key_path"], password,
                str(generado["sdg"]), directorio_salida=salida,
                key_nueva_path=key_csd, recuperar=True,
                intentos_cert=3, espera_cert_s=20, on_progreso=puente,
            )

            if res.get("cer") and res.get("numero_operacion"):
                config_store.update_csd(rfc, res["numero_operacion"], {
                    "cer_path": str(res["cer"]),
                    "estado": "emitido",
                    "recuperado_en": datetime.now().isoformat(timespec="seconds"),
                })

            return {
                "numero_operacion": res.get("numero_operacion"),
                "acuse_pdf": str(res["acuse_pdf"]) if res.get("acuse_pdf") else None,
                "estado": res.get("estado"),
                "cer": str(res["cer"]) if res.get("cer") else None,
                "key": key_csd,
                "uso": uso,
                "cert_pendiente": not res.get("cer"),
                "carpeta": salida,
            }
        return run

    def al_completar(resultado):
        _registrar_descarga(
            rfc, "fiel", "csd",
            descripcion=f"Solicitud de CSD «{uso}»",
            ruta=(resultado or {}).get("carpeta") or salida,
        )
        track("csd_solicitado",
              certificado="pendiente" if (resultado or {}).get("cert_pendiente") else "emitido")

    return _lanzar_job_certifica(factory, al_completar=al_completar)


@router.post("/csd/recuperar")
def csd_recuperar(req: CsdRecuperarRequest):
    """
    Descarga el `.cer` de un CSD ya solicitado que quedó pendiente (el SAT tarda
    minutos en emitirlo). Reintentable sin costo. → {job_id}.
    """
    rfc = req.rfc.strip().upper()
    entry = config_store.get_csd_pendiente(rfc, req.numero_operacion)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail="No hay un CSD pendiente de descargar para este RFC.",
        )
    empresa = _credenciales_keychain(rfc)
    password = empresa["password"]
    salida = str(paths.dir_documento(paths.TIPO_CSD, rfc, salida_base=_descargas_base()))

    def factory(emitir_fase):
        def run():
            from ...portal.csd import recuperar_ultimo_csd_fiel

            def puente(fase, data):
                emitir_fase(fase, data)

            res = recuperar_ultimo_csd_fiel(
                empresa["cer_path"], empresa["key_path"], password,
                directorio_salida=salida, key_nueva_path=entry.get("key_path"),
                intentos=10, espera_s=30, on_progreso=puente,
            )
            if res.get("cer"):
                config_store.update_csd(rfc, entry["numero_operacion"], {
                    "cer_path": str(res["cer"]),
                    "estado": "emitido",
                    "recuperado_en": datetime.now().isoformat(timespec="seconds"),
                })
            return {
                "cer": str(res["cer"]) if res.get("cer") else None,
                "numero_operacion": entry.get("numero_operacion"),
                "cert_pendiente": not res.get("cer"),
                "carpeta": salida,
            }
        return run

    return _lanzar_job_certifica(factory)

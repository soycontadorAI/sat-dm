"""
Router: calculadoras fiscales y laborales.

El cálculo vive 100% en el backend (``sat_descarga/calculadoras/``); el
renderer solo captura inputs y renderiza el resultado. Cada request de cálculo
puede llevar ``rfc`` para auto-guardar el estado por empresa (un round-trip =
calcular + persistir); al cambiar de empresa la UI restaura con
``GET /calculadoras/estado/{rfc}/{calculadora}``.

Las calculadoras son de libre acceso — el gating premium (export) es del
frontend; el agente local no valida licencia (patrón existente).
"""

import re
from dataclasses import asdict
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...calculadoras import (
    AguinaldoInput,
    CargaPatronalInput,
    DESCRIPCION_CLASES_RIESGO,
    ESTADOS_ISN,
    EmpresaPTU,
    FiniquitoInput,
    LiquidacionInput,
    PRIMAS_RIESGO,
    SBCInput,
    TIPOS_TERMINACION,
    TrabajadorPTU,
    calcular_aguinaldo,
    calcular_carga_patronal,
    calcular_finiquito,
    calcular_isr_periodo,
    calcular_liquidacion,
    calcular_ptu,
    calcular_sbc,
    get_indicadores,
)
from ...calculadoras import store
from ...calculadoras.isr import validar_salario_minimo
from ..uso import track

router = APIRouter()

# ---------------------------------------------------------------------------
# Modelos de request
# ---------------------------------------------------------------------------


class CalculoBase(BaseModel):
    """Campos comunes: año del ejercicio y RFC para auto-guardar el estado."""

    anio: int = 2026
    rfc: Optional[str] = None


class AguinaldoRequest(CalculoBase):
    salario: float = Field(gt=0)
    tipo_salario: Literal["diario", "mensual"]
    fecha_ingreso: date
    dias_aguinaldo: int = Field(default=15, ge=1)
    fecha_calculo: Optional[date] = None
    ingreso_ordinario_mensual: Optional[float] = None
    metodo_isr: Literal["ley", "reglamento"] = "ley"
    es_zona_fronteriza: bool = False  # ZLFN: salario mínimo mayor al general


class SBCRequest(CalculoBase):
    salario: float = Field(gt=0)
    tipo_salario: Literal["diario", "mensual"]
    antiguedad_anios: int = Field(ge=0)
    dias_aguinaldo: int = Field(default=15, ge=15)
    prima_vacacional: float = Field(default=0.25, ge=0.25, le=1)
    es_zona_fronteriza: bool = False  # ZLFN: salario mínimo mayor al general


class ISRRequest(CalculoBase):
    ingreso_gravado: float = Field(gt=0)
    periodicidad: Literal["diario", "semanal", "decenal", "quincenal", "mensual"] = "mensual"
    es_asimilado: bool = False
    es_zona_fronteriza: bool = False  # ZLFN: salario mínimo mayor al general
    mes: int = Field(default=2, ge=1, le=12)


class FiniquitoRequest(CalculoBase):
    salario: float = Field(gt=0)
    tipo_salario: Literal["diario", "mensual"]
    fecha_ingreso: date
    fecha_baja: date
    dias_aguinaldo: int = Field(default=15, ge=15)
    prima_vacacional: float = Field(default=0.25, ge=0.25, le=1)


class LiquidacionRequest(FiniquitoRequest):
    tipo_terminacion: Literal[
        "DESPIDO_INJUSTIFICADO",
        "RESCISION_ART51",
        "TERMINACION_COLECTIVA",
        "RENUNCIA_VOLUNTARIA",
    ]
    es_zona_fronteriza: bool = False
    ultimo_sueldo_mensual: Optional[float] = None


class PrestacionAdicional(BaseModel):
    nombre: str
    monto: float = Field(ge=0)
    tipo: Literal["mensual", "anual"] = "mensual"


class CargaPatronalRequest(CalculoBase):
    salario: float = Field(gt=0)
    tipo_salario: Literal["diario", "mensual"]
    antiguedad_anios: int = Field(ge=0)
    es_zona_fronteriza: bool = False  # ZLFN: salario mínimo mayor al general
    clase_riesgo: Literal["I", "II", "III", "IV", "V"] = "I"
    prima_riesgo_trabajo: Optional[float] = Field(default=None, ge=0)
    codigo_estado: str = "CDMX"
    tasa_impuesto_estatal: Optional[float] = Field(default=None, ge=0, le=0.1)
    incluir_aguinaldo_mensual: bool = True
    incluir_vacaciones_mensual: bool = True
    prestaciones_adicionales: list[PrestacionAdicional] = Field(default_factory=list)


class TrabajadorPTURequest(BaseModel):
    nombre: str
    salario_diario: float = Field(gt=0)
    dias_trabajados: float = Field(gt=0, le=366)
    percepcion_anual: float = Field(gt=0)
    rfc: str = ""
    curp: str = ""
    nss: str = ""
    fecha_inicio: Optional[date] = None
    es_confianza: bool = False
    ptu_anio_1: float = Field(default=0, ge=0)
    ptu_anio_2: float = Field(default=0, ge=0)
    ptu_anio_3: float = Field(default=0, ge=0)
    ingreso_mensual_ordinario: float = Field(default=0, ge=0)
    isr_mensual_ordinario: float = Field(default=0, ge=0)


class PTURequest(BaseModel):
    rfc: Optional[str] = None  # empresa activa (auto-guardado)
    utilidad_fiscal: float = Field(gt=0)
    ejercicio: int
    nombre: str = ""
    rfc_empresa: str = ""
    ptu_no_cobrada: float = Field(default=0, ge=0)
    tipo_persona: Literal["Moral", "Física"] = "Moral"
    fecha_pago: Optional[date] = None
    criterio_exencion: Literal["UMA", "SMG"] = "UMA"
    trabajadores: list[TrabajadorPTURequest] = Field(min_length=1)


class GuardadoRequest(BaseModel):
    calculadora: str
    nombre: str
    inputs: dict
    resultado: dict
    anio: int = 2026


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _responder(calculadora: str, req: CalculoBase, resultado: dict, anio: int) -> dict:
    """Arma la respuesta estándar y auto-guarda el estado si viene RFC."""
    # Recalcula con cada tecla (debounce de la UI): cuenta una vez cada 30 min.
    track("calculadora_usada", calculadora=calculadora.replace("-", "_"))
    try:
        advertencias = list(get_indicadores(anio).advertencias)
    except ValueError:
        advertencias = []
    inputs = req.model_dump(mode="json", exclude={"rfc"})
    estado = None
    try:
        estado = store.set_estado_calculadora(req.rfc, calculadora, inputs, resultado, anio)
    except ValueError as e:
        # RFC inválido: se calcula igual, solo no se persiste.
        advertencias.append(str(e))
    return {
        "ok": True,
        "resultado": resultado,
        "advertencias": advertencias,
        "guardado_en": estado["actualizado_en"] if estado else None,
    }


# ---------------------------------------------------------------------------
# Ejecutores (compartidos por los endpoints de cálculo y por el export)
# ---------------------------------------------------------------------------


def _run_aguinaldo(req: AguinaldoRequest) -> dict:
    # El aguinaldo se calcula sobre el salario vigente de un trabajador activo:
    # por debajo del mínimo (general o ZLFN) no es base válida. Mismo factor de
    # conversión que la calculadora (mensual / 30.4).
    salario_diario = req.salario / 30.4 if req.tipo_salario == "mensual" else req.salario
    validar_salario_minimo(
        salario_diario,
        req.anio,
        "diario",
        req.es_zona_fronteriza,
        contexto=(
            "Un salario por debajo del mínimo legal (Art. 90 LFT) no es base válida "
            "para calcular el aguinaldo."
        ),
    )
    return calcular_aguinaldo(
        AguinaldoInput(
            salario=req.salario,
            tipo_salario=req.tipo_salario,
            fecha_ingreso=req.fecha_ingreso,
            dias_aguinaldo=req.dias_aguinaldo,
            fecha_calculo=req.fecha_calculo,
            ingreso_ordinario_mensual=req.ingreso_ordinario_mensual,
            metodo_isr=req.metodo_isr,
            anio=req.anio,
        )
    )


def _run_sbc(req: SBCRequest) -> dict:
    # Un salario por debajo del mínimo (general o ZLFN) no es base válida para
    # cotizar. Se valida sobre el salario DIARIO derivado con el mismo factor
    # que usa la calculadora (mensual / 30).
    salario_diario = req.salario / 30 if req.tipo_salario == "mensual" else req.salario
    validar_salario_minimo(
        salario_diario,
        req.anio,
        "diario",
        req.es_zona_fronteriza,
        contexto=(
            "Un salario por debajo del mínimo legal (Art. 90 LFT) no es base válida "
            "para determinar el salario base de cotización."
        ),
    )
    return calcular_sbc(
        SBCInput(
            salario=req.salario,
            tipo_salario=req.tipo_salario,
            antiguedad_anios=req.antiguedad_anios,
            dias_aguinaldo=req.dias_aguinaldo,
            prima_vacacional=req.prima_vacacional,
            anio=req.anio,
        )
    )


def _run_isr(req: ISRRequest) -> dict:
    # Un salario real por debajo del mínimo (general o ZLFN) no es base válida
    # de retención; a los asimilados el salario mínimo no les aplica.
    if not req.es_asimilado:
        validar_salario_minimo(
            req.ingreso_gravado, req.anio, req.periodicidad, req.es_zona_fronteriza
        )
    return calcular_isr_periodo(
        req.ingreso_gravado, req.anio, req.periodicidad, req.es_asimilado, req.mes
    )


def _run_finiquito(req: FiniquitoRequest) -> dict:
    return calcular_finiquito(
        FiniquitoInput(
            salario=req.salario,
            tipo_salario=req.tipo_salario,
            fecha_ingreso=req.fecha_ingreso,
            fecha_baja=req.fecha_baja,
            dias_aguinaldo=req.dias_aguinaldo,
            prima_vacacional=req.prima_vacacional,
            anio=req.anio,
        )
    )


def _run_liquidacion(req: LiquidacionRequest) -> dict:
    return calcular_liquidacion(
        LiquidacionInput(
            salario=req.salario,
            tipo_salario=req.tipo_salario,
            fecha_ingreso=req.fecha_ingreso,
            fecha_baja=req.fecha_baja,
            tipo_terminacion=req.tipo_terminacion,
            es_zona_fronteriza=req.es_zona_fronteriza,
            dias_aguinaldo=req.dias_aguinaldo,
            prima_vacacional=req.prima_vacacional,
            ultimo_sueldo_mensual=req.ultimo_sueldo_mensual,
            anio=req.anio,
        )
    )


def _run_carga_patronal(req: CargaPatronalRequest) -> dict:
    # Un salario por debajo del mínimo (general o ZLFN) no es un costo laboral
    # válido. Mismo factor de conversión que la calculadora (mensual / 30).
    salario_diario = req.salario / 30 if req.tipo_salario == "mensual" else req.salario
    validar_salario_minimo(
        salario_diario,
        req.anio,
        "diario",
        req.es_zona_fronteriza,
        contexto=(
            "Un salario por debajo del mínimo legal (Art. 90 LFT) no es base válida "
            "para calcular la carga patronal."
        ),
    )
    return calcular_carga_patronal(
        CargaPatronalInput(
            salario=req.salario,
            tipo_salario=req.tipo_salario,
            antiguedad_anios=req.antiguedad_anios,
            clase_riesgo=req.clase_riesgo,
            prima_riesgo_trabajo=req.prima_riesgo_trabajo,
            codigo_estado=req.codigo_estado,
            tasa_impuesto_estatal=req.tasa_impuesto_estatal,
            incluir_aguinaldo_mensual=req.incluir_aguinaldo_mensual,
            incluir_vacaciones_mensual=req.incluir_vacaciones_mensual,
            prestaciones_adicionales=[p.model_dump() for p in req.prestaciones_adicionales],
            anio=req.anio,
        )
    )


def _run_ptu(req: "PTURequest") -> dict:
    return calcular_ptu(
        EmpresaPTU(
            utilidad_fiscal=req.utilidad_fiscal,
            ejercicio=req.ejercicio,
            nombre=req.nombre,
            rfc=req.rfc_empresa or (req.rfc or ""),
            ptu_no_cobrada=req.ptu_no_cobrada,
            tipo_persona=req.tipo_persona,
            fecha_pago=req.fecha_pago,
            criterio_exencion=req.criterio_exencion,
        ),
        [
            TrabajadorPTU(
                nombre=t.nombre,
                salario_diario=t.salario_diario,
                dias_trabajados=t.dias_trabajados,
                percepcion_anual=t.percepcion_anual,
                rfc=t.rfc,
                curp=t.curp,
                nss=t.nss,
                fecha_inicio=t.fecha_inicio,
                es_confianza=t.es_confianza,
                ptu_anio_1=t.ptu_anio_1,
                ptu_anio_2=t.ptu_anio_2,
                ptu_anio_3=t.ptu_anio_3,
                ingreso_mensual_ordinario=t.ingreso_mensual_ordinario,
                isr_mensual_ordinario=t.isr_mensual_ordinario,
            )
            for t in req.trabajadores
        ],
    )


# ---------------------------------------------------------------------------
# Endpoints de cálculo
# ---------------------------------------------------------------------------


@router.post("/calculadoras/aguinaldo")
def calcular_aguinaldo_endpoint(req: AguinaldoRequest):
    try:
        resultado = _run_aguinaldo(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _responder("aguinaldo", req, resultado, req.anio)


@router.post("/calculadoras/sbc")
def calcular_sbc_endpoint(req: SBCRequest):
    try:
        resultado = _run_sbc(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _responder("sbc", req, resultado, req.anio)


@router.post("/calculadoras/isr")
def calcular_isr_endpoint(req: ISRRequest):
    try:
        resultado = _run_isr(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _responder("isr", req, resultado, req.anio)


@router.post("/calculadoras/finiquito")
def calcular_finiquito_endpoint(req: FiniquitoRequest):
    if req.fecha_baja <= req.fecha_ingreso:
        raise HTTPException(
            status_code=400, detail="La fecha de baja debe ser posterior a la de ingreso."
        )
    try:
        resultado = _run_finiquito(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _responder("finiquito", req, resultado, req.anio)


@router.post("/calculadoras/liquidacion")
def calcular_liquidacion_endpoint(req: LiquidacionRequest):
    if req.fecha_baja <= req.fecha_ingreso:
        raise HTTPException(
            status_code=400, detail="La fecha de baja debe ser posterior a la de ingreso."
        )
    try:
        resultado = _run_liquidacion(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _responder("liquidacion", req, resultado, req.anio)


@router.post("/calculadoras/carga-patronal")
def calcular_carga_patronal_endpoint(req: CargaPatronalRequest):
    try:
        resultado = _run_carga_patronal(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _responder("carga-patronal", req, resultado, req.anio)


@router.post("/calculadoras/ptu")
def calcular_ptu_endpoint(req: PTURequest):
    try:
        resultado = _run_ptu(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    track("calculadora_usada", calculadora="ptu")
    # El auto-guardado usa el año de PAGO como referencia del estado.
    anio_pago = resultado["config"]["anio_pago"]
    inputs = req.model_dump(mode="json", exclude={"rfc"})
    advertencias = list(resultado.get("advertencias", []))
    estado = None
    try:
        estado = store.set_estado_calculadora(req.rfc, "ptu", inputs, resultado, anio_pago)
    except ValueError as e:
        advertencias.append(str(e))
    return {
        "ok": True,
        "resultado": resultado,
        "advertencias": advertencias,
        "guardado_en": estado["actualizado_en"] if estado else None,
    }


# ---------------------------------------------------------------------------
# Indicadores (para selects de la UI)
# ---------------------------------------------------------------------------


@router.get("/calculadoras/indicadores/{anio}")
def indicadores_endpoint(anio: int):
    try:
        ind = get_indicadores(anio)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {
        "ok": True,
        "anio": ind.anio,
        "uma_diaria": ind.uma_diaria,
        "uma_mensual": ind.uma_mensual,
        "uma_anual": ind.uma_anual,
        "smg_general": ind.smg_general,
        "smg_frontera": ind.smg_frontera,
        "tope_sbc_diario": ind.tope_sbc_diario,
        "tarifa_isr_mensual": (
            [asdict(t) for t in ind.tarifa_isr_mensual] if ind.tarifa_isr_mensual else None
        ),
        "spe": (
            {
                "esquema": ind.spe.esquema,
                "limite_ingresos_mensual": ind.spe.limite_ingresos_mensual,
                "monto_mensual_enero": ind.spe.monto_mensual_enero,
                "monto_mensual_resto": ind.spe.monto_mensual_resto,
                "fuente": ind.spe.fuente,
            }
            if ind.spe
            else None
        ),
        "imss": (
            {
                "infonavit": ind.imss.infonavit,
                "cesantia_vejez": [asdict(r) for r in ind.imss.cesantia_vejez],
            }
            if ind.imss
            else None
        ),
        "estados_isn": ESTADOS_ISN,
        "primas_riesgo": PRIMAS_RIESGO,
        "descripcion_clases_riesgo": DESCRIPCION_CLASES_RIESGO,
        "tipos_terminacion": TIPOS_TERMINACION,
        "advertencias": list(ind.advertencias),
    }


# ---------------------------------------------------------------------------
# Estado por empresa + guardados
# ---------------------------------------------------------------------------


@router.get("/calculadoras/estado/{rfc}")
def estado_empresa_endpoint(rfc: str):
    try:
        data = store.get_estado(rfc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "estados": data["estados"], "guardados": list(reversed(data["guardados"]))}


@router.get("/calculadoras/estado/{rfc}/{calculadora}")
def estado_calculadora_endpoint(rfc: str, calculadora: str):
    try:
        estado = store.get_estado_calculadora(rfc, calculadora)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "estado": estado}


@router.post("/calculadoras/guardados/{rfc}")
def guardar_endpoint(rfc: str, req: GuardadoRequest):
    try:
        guardado = store.add_guardado(
            rfc, req.calculadora, req.nombre, req.inputs, req.resultado, req.anio
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "guardado": guardado}


@router.delete("/calculadoras/guardados/{rfc}/{guardado_id}")
def eliminar_guardado_endpoint(rfc: str, guardado_id: str):
    try:
        eliminado = store.delete_guardado(rfc, guardado_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not eliminado:
        raise HTTPException(status_code=404, detail="Cálculo guardado no encontrado.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Export (Excel / PDF / recibos PTU) — premium; el gating vive en el frontend
# ---------------------------------------------------------------------------

# (modelo de request, ejecutor)
_EXPORTABLES: dict = {
    "aguinaldo": (AguinaldoRequest, _run_aguinaldo),
    "sbc": (SBCRequest, _run_sbc),
    "isr": (ISRRequest, _run_isr),
    "finiquito": (FiniquitoRequest, _run_finiquito),
    "liquidacion": (LiquidacionRequest, _run_liquidacion),
    "carga-patronal": (CargaPatronalRequest, _run_carga_patronal),
    "ptu": (PTURequest, _run_ptu),
}

_MEDIA_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MEDIA_PDF = "application/pdf"


class ExportarRequest(BaseModel):
    calculadora: str
    inputs: dict
    rfc: Optional[str] = None  # empresa activa; entra al nombre del archivo


def _nombre_archivo(rfc: Optional[str], concepto: str, anio: Optional[int], ext: str) -> str:
    """Nomenclatura de archivos exportados: ``{RFC}_{concepto}_{año}.{ext}``.

    El RFC identifica de qué empresa es el archivo sin tener que renombrarlo a
    mano; partes ausentes se omiten. (Pendiente: aplicar la misma convención a
    los exports de los procesadores.)
    """
    rfc_limpio = (rfc or "").strip().upper()
    if not re.fullmatch(r"[A-ZÑ&0-9]{12,13}", rfc_limpio):
        rfc_limpio = ""
    partes = [p for p in (rfc_limpio, concepto, str(anio) if anio else "") if p]
    return "_".join(partes) + f".{ext}"


@router.post("/calculadoras/exportar/{formato}")
def exportar_endpoint(formato: str, req: ExportarRequest):
    """Recalcula server-side desde los inputs (fuente única) y rinde el archivo.

    Formatos: ``xlsx``, ``pdf`` y ``recibos-ptu`` (PDF multi-página, solo PTU).
    """
    from fastapi.responses import StreamingResponse
    from pydantic import ValidationError

    from ...calculadoras import exportar as exportar_mod

    if formato not in ("xlsx", "pdf", "recibos-ptu"):
        raise HTTPException(status_code=404, detail=f"Formato no soportado: {formato!r}.")
    if req.calculadora not in _EXPORTABLES:
        raise HTTPException(
            status_code=400, detail=f"Calculadora desconocida: {req.calculadora!r}."
        )
    if formato == "recibos-ptu" and req.calculadora != "ptu":
        raise HTTPException(status_code=400, detail="Los recibos solo aplican a PTU.")

    inputs = dict(req.inputs)
    rfc_limpio = (req.rfc or "").strip().upper()
    if not re.fullmatch(r"[A-ZÑ&0-9]{12,13}", rfc_limpio):
        rfc_limpio = ""

    # PTU: el documento y los recibos llevan la identidad de la empresa activa
    # (nombre del catálogo + RFC) cuando el formulario no la trae.
    if req.calculadora == "ptu" and rfc_limpio:
        if not inputs.get("rfc_empresa"):
            inputs["rfc_empresa"] = rfc_limpio
        if not inputs.get("nombre"):
            from ...cli.config_store import load_empresas

            empresa = load_empresas().get("empresas", {}).get(rfc_limpio) or {}
            if empresa.get("nombre"):
                inputs["nombre"] = empresa["nombre"]

    modelo_cls, run = _EXPORTABLES[req.calculadora]
    try:
        modelo = modelo_cls(**inputs)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    try:
        resultado = run(modelo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Año del documento y del nombre: en PTU el ejercicio a repartir; en el
    # resto, el del cálculo.
    anio_nombre = modelo.ejercicio if req.calculadora == "ptu" else modelo.anio

    if formato == "recibos-ptu":
        data = exportar_mod.recibos_ptu_pdf(resultado)
        media = _MEDIA_PDF
        filename = _nombre_archivo(req.rfc, "recibos-ptu", anio_nombre, "pdf")
    else:
        doc = exportar_mod.construir_documento(req.calculadora, resultado, anio_nombre)
        if formato == "xlsx":
            data = exportar_mod.a_xlsx(doc)
            media = _MEDIA_XLSX
        else:
            data = exportar_mod.a_pdf(doc)
            media = _MEDIA_PDF
        filename = _nombre_archivo(req.rfc, req.calculadora, anio_nombre, formato)

    track("calculadora_exportada", calculadora=req.calculadora.replace("-", "_"),
          formato=formato.replace("-", "_"))
    return StreamingResponse(
        iter([data]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

"""Indicadores fiscales por año — fuente única de verdad (2021-2026).

Agregar un año nuevo = agregar UNA entrada a ``INDICADORES`` (y correr los tests
de integridad). Ningún módulo de cálculo se toca. Si un dato de un año no está
publicado/verificado, el campo va ``None`` y el año carga una advertencia que la
API propaga a la UI; está prohibido "heredar" silenciosamente el año anterior.

Fuentes primarias (verificadas 2026-07):
- UMA: INEGI (vigente cada 1 de febrero). Histórico 2016-2026.
- Salarios mínimos: CONASAMI (vigentes cada 1 de enero).
- Tarifa ISR mensual: Anexo 8 RMF. La tarifa vigente 2022-2025 se actualizó para
  2026 con factor 1.1321 (DOF 28-12-2025).
- SPE: decretos DOF 01-05-2024 (esquema % UMA), 31-12-2024 (2025) y 31-12-2025
  (2026, nota 5777649).
- IMSS CyV patronal: reforma LSS 2020, tabla progresiva por rango de UMA que sube
  cada año hasta 2030 → SIEMPRE por año.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ── Esquemas ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TramoISR:
    limite_inferior: float
    limite_superior: float | None  # None = último tramo
    cuota_fija: float
    porcentaje_excedente: float  # 0.0192 = 1.92%


@dataclass(frozen=True)
class TramoSPETabla:
    """Rango de la tabla de montos fijos del SPE (esquema 2013, usado hasta 2024)."""

    limite_inferior: float
    limite_superior: float
    subsidio_mensual: float


@dataclass(frozen=True)
class ConfigSPE:
    """Subsidio para el empleo del año.

    - esquema "tabla": montos fijos por rango de ingreso mensual (2021-2024).
    - esquema "uma": monto fijo mensual = porcentaje × UMA mensual, con tope de
      ingreso (2025+). Enero usa un porcentaje distinto SOBRE LA UMA DEL AÑO
      ANTERIOR (la UMA nueva entra en vigor el 1 de febrero — Art. 5 LDVUMA);
      por eso se guarda la base UMA de cada tramo por separado.

    Los montos se calculan sin redondear (uma_diaria × 30.4 × porcentaje) para
    mantener paridad de centavos con la calculadora web.
    """

    esquema: str  # "tabla" | "uma"
    fuente: str
    tabla: tuple[TramoSPETabla, ...] = ()
    limite_ingresos_mensual: float = 0.0
    porcentaje_enero: float = 0.0
    porcentaje_resto: float = 0.0
    uma_diaria_enero: float = 0.0  # UMA vigente en enero (la del año anterior)
    uma_diaria_resto: float = 0.0  # UMA del propio año (vigente feb-dic)

    @property
    def monto_mensual_enero(self) -> float:
        return self.uma_diaria_enero * 30.4 * self.porcentaje_enero

    @property
    def monto_mensual_resto(self) -> float:
        return self.uma_diaria_resto * 30.4 * self.porcentaje_resto


@dataclass(frozen=True)
class RangoCyV:
    """Rango de la tabla patronal de Cesantía en Edad Avanzada y Vejez."""

    min_umas: float
    max_umas: float | None  # None = último rango
    tasa: float


@dataclass(frozen=True)
class CuotasIMSSPatronales:
    """Cuotas patronales IMSS del año (CyV es progresiva y cambia hasta 2030)."""

    enfermedad_maternidad_fija: float      # 20.40% (cuota fija, Art. 106 fr. I LSS)
    enfermedad_maternidad_excedente: float  # 1.10% sobre excedente de 3 UMA
    prestaciones_en_dinero: float          # 0.70%
    gastos_medicos_pensionados: float      # 1.05% (Art. 25 LSS)
    invalidez_vida: float                  # 1.75%
    guarderias: float                      # 1.00%
    retiro: float                          # 2.00% (Art. 168 fr. I LSS)
    infonavit: float                       # 5.00%
    cesantia_vejez: tuple[RangoCyV, ...]


@dataclass(frozen=True)
class IndicadoresAnio:
    anio: int
    uma_diaria: float
    uma_mensual: float  # valor oficial INEGI (diaria × 30.4, publicado redondeado)
    uma_anual: float    # valor oficial INEGI (mensual × 12)
    smg_general: float
    smg_frontera: float
    tarifa_isr_mensual: tuple[TramoISR, ...] | None = None
    spe: ConfigSPE | None = None
    imss: CuotasIMSSPatronales | None = None
    advertencias: tuple[str, ...] = field(default=())

    @property
    def tope_sbc_diario(self) -> float:
        """Tope del salario base de cotización: 25 UMA (Art. 28 LSS)."""
        return self.uma_diaria * 25


# ── Tarifas ISR mensuales (Anexo 8 RMF) ───────────────────────────────────────

# Vigente 2022-2025 (sin actualización intermedia; la inflación acumulada no
# alcanzó 10% hasta el cierre de 2025).
_TARIFA_MENSUAL_2022_2025: tuple[TramoISR, ...] = (
    TramoISR(0.01, 746.04, 0.00, 0.0192),
    TramoISR(746.05, 6332.05, 14.32, 0.0640),
    TramoISR(6332.06, 11128.01, 371.83, 0.1088),
    TramoISR(11128.02, 12935.82, 893.63, 0.1600),
    TramoISR(12935.83, 15487.71, 1182.88, 0.1792),
    TramoISR(15487.72, 31236.49, 1640.18, 0.2136),
    TramoISR(31236.50, 49233.00, 5004.12, 0.2352),
    TramoISR(49233.01, 93993.90, 9236.89, 0.3000),
    TramoISR(93993.91, 125325.20, 22665.17, 0.3200),
    TramoISR(125325.21, 375975.61, 32691.18, 0.3400),
    TramoISR(375975.62, None, 117912.32, 0.3500),
)

# Vigente 2026 (Anexo 8 RMF 2026, DOF 28-12-2025; factor de actualización 1.1321).
_TARIFA_MENSUAL_2026: tuple[TramoISR, ...] = (
    TramoISR(0.01, 844.59, 0.00, 0.0192),
    TramoISR(844.60, 7168.51, 16.22, 0.0640),
    TramoISR(7168.52, 12598.02, 420.95, 0.1088),
    TramoISR(12598.03, 14644.64, 1011.68, 0.1600),
    TramoISR(14644.65, 17533.64, 1339.14, 0.1792),
    TramoISR(17533.65, 35362.83, 1856.84, 0.2136),
    TramoISR(35362.84, 55736.68, 5665.16, 0.2352),
    TramoISR(55736.69, 106410.50, 10457.09, 0.3000),
    TramoISR(106410.51, 141880.66, 25659.23, 0.3200),
    TramoISR(141880.67, 425641.99, 37009.69, 0.3400),
    TramoISR(425642.00, None, 133488.54, 0.3500),
)

# ── SPE ───────────────────────────────────────────────────────────────────────

# Tabla de montos fijos (decreto 2013), usada hasta 2024. El decreto DOF
# 01-05-2024 cambió el esquema a % de UMA a partir de mayo 2024; igual que la
# web, 2024 se modela completo con la tabla (simplificación documentada).
_TABLA_SPE_2020_2024: tuple[TramoSPETabla, ...] = (
    TramoSPETabla(0.01, 1768.96, 407.02),
    TramoSPETabla(1768.97, 2653.38, 406.83),
    TramoSPETabla(2653.39, 3472.84, 406.62),
    TramoSPETabla(3472.85, 3537.87, 392.77),
    TramoSPETabla(3537.88, 4446.15, 382.46),
    TramoSPETabla(4446.16, 4717.18, 354.23),
    TramoSPETabla(4717.19, 5335.42, 324.87),
    TramoSPETabla(5335.43, 6224.67, 294.63),
    TramoSPETabla(6224.68, 7113.90, 253.54),
    TramoSPETabla(7113.91, 7382.33, 217.61),
)

_SPE_TABLA = ConfigSPE(
    esquema="tabla",
    fuente="Decreto DOF 11-12-2013 (tabla de montos fijos, vigente hasta 2024)",
    tabla=_TABLA_SPE_2020_2024,
)

# 2025: 13.8% de la UMA mensual, tope $10,171.00. Enero 2025: 14.39% sobre la
# UMA vigente en enero (la de 2024). DOF 31-12-2024 (nota 5746529).
_SPE_2025 = ConfigSPE(
    esquema="uma",
    fuente="Decreto DOF 31-12-2024 (nota 5746529)",
    limite_ingresos_mensual=10171.00,
    porcentaje_enero=0.1439,
    porcentaje_resto=0.1380,
    uma_diaria_enero=108.57,  # UMA 2024 (vigente en enero 2025) → $474.95
    uma_diaria_resto=113.14,  # UMA 2025 → $474.64
)

# 2026: 15.02% de la UMA mensual, tope $11,492.66. Enero 2026 (Transitorio
# Segundo): 15.59% sobre la UMA vigente en enero (la de 2025, $3,439.46 mensual)
# → $536.21. Feb-dic: 15.02% × $3,566.22 → $535.65. DOF 31-12-2025 (nota
# 5777649). OJO: la web usaba la UMA 2026 también en enero ($556.08) — eso
# contradice el considerando del decreto y aquí se corrige.
_SPE_2026 = ConfigSPE(
    esquema="uma",
    fuente="Decreto DOF 31-12-2025 (nota 5777649), Transitorio Segundo para enero",
    limite_ingresos_mensual=11492.66,
    porcentaje_enero=0.1559,
    porcentaje_resto=0.1502,
    uma_diaria_enero=113.14,  # UMA 2025 (vigente en enero 2026) → $536.21
    uma_diaria_resto=117.31,  # UMA 2026 → $535.65
)

# ── IMSS 2026 ─────────────────────────────────────────────────────────────────

# Tabla patronal de Cesantía y Vejez 2026 (reforma LSS 2020, sube hasta 2030).
# Tasas exactas de la tabla del Art. Cuarto Transitorio (verificadas el
# 2026-10-27 contra IDC, "Factores de las cuotas y aportaciones 2026").
_CYV_2026: tuple[RangoCyV, ...] = (
    RangoCyV(0.00, 1.00, 0.03150),
    RangoCyV(1.01, 1.50, 0.03676),
    RangoCyV(1.51, 2.00, 0.04851),
    RangoCyV(2.01, 2.50, 0.05556),
    RangoCyV(2.51, 3.00, 0.06026),
    RangoCyV(3.01, 3.50, 0.06361),
    RangoCyV(3.51, 4.00, 0.06613),
    RangoCyV(4.01, None, 0.07513),
)

_IMSS_2026 = CuotasIMSSPatronales(
    enfermedad_maternidad_fija=0.204,
    enfermedad_maternidad_excedente=0.011,
    prestaciones_en_dinero=0.007,
    gastos_medicos_pensionados=0.0105,
    invalidez_vida=0.0175,
    guarderias=0.01,
    retiro=0.02,
    infonavit=0.05,
    cesantia_vejez=_CYV_2026,
)

# ── Histórico UMA / SMG (para PTU: exención con valores del año de pago) ─────
# (año, uma_diaria, smg_general, smg_frontera)
UMA_SMG_HISTORICO: dict[int, tuple[float, float, float]] = {
    2016: (73.04, 73.04, 73.04),
    2017: (75.49, 80.04, 80.04),
    2018: (80.60, 88.36, 88.36),
    2019: (84.49, 102.68, 176.72),
    2020: (86.88, 123.22, 185.56),
    2021: (89.62, 141.70, 213.39),
    2022: (96.22, 172.87, 260.34),
    2023: (103.74, 207.44, 312.41),
    2024: (108.57, 248.93, 374.89),
    2025: (113.14, 278.80, 419.88),
    2026: (117.31, 315.04, 440.87),
}

# ── Indicadores por año ───────────────────────────────────────────────────────

INDICADORES: dict[int, IndicadoresAnio] = {
    2021: IndicadoresAnio(
        anio=2021,
        uma_diaria=89.62,
        uma_mensual=2724.45,
        uma_anual=32693.40,
        smg_general=141.70,
        smg_frontera=213.39,
        tarifa_isr_mensual=None,
        spe=_SPE_TABLA,
        imss=None,
        advertencias=(
            "Tarifa ISR mensual 2021 no cargada (verificar Anexo 8 RMF 2021 antes de usar).",
            "Cuotas IMSS 2021 no cargadas.",
        ),
    ),
    2022: IndicadoresAnio(
        anio=2022,
        uma_diaria=96.22,
        uma_mensual=2925.09,
        uma_anual=35101.08,
        smg_general=172.87,
        smg_frontera=260.34,
        tarifa_isr_mensual=_TARIFA_MENSUAL_2022_2025,
        spe=_SPE_TABLA,
        imss=None,
        advertencias=("Cuotas IMSS 2022 no cargadas.",),
    ),
    2023: IndicadoresAnio(
        anio=2023,
        uma_diaria=103.74,
        uma_mensual=3153.70,
        uma_anual=37844.40,
        smg_general=207.44,
        smg_frontera=312.41,
        tarifa_isr_mensual=_TARIFA_MENSUAL_2022_2025,
        spe=_SPE_TABLA,
        imss=None,
        advertencias=("Cuotas IMSS 2023 no cargadas.",),
    ),
    2024: IndicadoresAnio(
        anio=2024,
        uma_diaria=108.57,
        uma_mensual=3300.53,
        uma_anual=39606.36,
        smg_general=248.93,
        smg_frontera=374.89,
        tarifa_isr_mensual=_TARIFA_MENSUAL_2022_2025,
        spe=_SPE_TABLA,
        imss=None,
        advertencias=(
            "SPE 2024: el decreto DOF 01-05-2024 cambió el esquema a % de UMA a "
            "partir de mayo; se usa la tabla de montos fijos para todo el año "
            "(simplificación, igual que la web).",
            "Cuotas IMSS 2024 no cargadas.",
        ),
    ),
    2025: IndicadoresAnio(
        anio=2025,
        uma_diaria=113.14,
        uma_mensual=3439.46,
        uma_anual=41273.52,
        smg_general=278.80,
        smg_frontera=419.88,
        tarifa_isr_mensual=_TARIFA_MENSUAL_2022_2025,
        spe=_SPE_2025,
        imss=None,
        advertencias=("Cuotas IMSS 2025 no cargadas.",),
    ),
    2026: IndicadoresAnio(
        anio=2026,
        uma_diaria=117.31,
        uma_mensual=3566.22,
        uma_anual=42794.64,
        smg_general=315.04,
        smg_frontera=440.87,
        tarifa_isr_mensual=_TARIFA_MENSUAL_2026,
        spe=_SPE_2026,
        imss=_IMSS_2026,
    ),
}


def get_indicadores(anio: int) -> IndicadoresAnio:
    """Indicadores del año, o ``ValueError`` si el año no está soportado."""
    try:
        return INDICADORES[anio]
    except KeyError:
        soportados = ", ".join(str(a) for a in sorted(INDICADORES))
        raise ValueError(
            f"Año {anio} no soportado por las calculadoras (soportados: {soportados})."
        ) from None

"""Carga patronal — cuotas IMSS, Infonavit, ISN y costo total."""

import pytest

from sat_descarga.calculadoras import CargaPatronalInput, calcular_carga_patronal
from sat_descarga.calculadoras.carga_patronal import calcular_cuotas_imss, determinar_tasa_cyv


def test_caso_base_cdmx():
    """$12,000 mensuales, 1 año, clase I, CDMX (ISN 4%)."""
    res = calcular_carga_patronal(
        CargaPatronalInput(
            salario=12000,
            tipo_salario="mensual",
            antiguedad_anios=1,
            clase_riesgo="I",
            codigo_estado="CDMX",
        )
    )
    assert res["salario_diario"] == 400
    assert res["sbc"] == pytest.approx(419.73, abs=0.01)  # 400 × 1.0493
    assert res["impuesto_estatal"] == pytest.approx(504.0)  # 4% × (12,000 + 500 + 100)
    assert res["aguinaldo_prorrateo"] == pytest.approx(500.0)  # 15×400/12
    assert res["vacaciones_prorrateo"] == pytest.approx(100.0)  # 12×0.25×400/12
    assert res["infonavit"] == pytest.approx(638.0, abs=0.05)  # sbc × 5% × 30.4
    assert res["isr_empleado"] == pytest.approx(946.62, abs=0.01)  # sin SPE (>11,492.66)
    assert res["salario_neto"] == pytest.approx(12000 - 946.62, abs=0.01)
    assert res["costo_total_mensual"] == pytest.approx(
        res["salario_mensual"] + res["carga_patronal_mensual"], abs=0.01
    )
    assert res["costo_total_anual"] == pytest.approx(res["costo_total_mensual"] * 12, abs=0.05)


UMA = 117.31
DIAS = 30.4


def test_cuotas_imss_con_excedente_3_uma():
    """SBC arriba de 3 UMA: cuota fija sobre la UMA + 1.10% del excedente + 0.70% del SBC."""
    sbc = 419.726  # > 3 UMA (351.93)
    cuotas = calcular_cuotas_imss(sbc, prima_riesgo_trabajo=0.54355)
    esperado = (UMA * 0.204 + (sbc - 3 * UMA) * 0.011 + sbc * 0.007) * DIAS
    assert cuotas["enfermedad_maternidad"] == pytest.approx(esperado, abs=0.01)


def test_cuotas_imss_sbc_bajo_3_uma():
    """Bajo 3 UMA no hay excedente; la cuota fija sigue siendo sobre la UMA."""
    sbc = 300.0
    cuotas = calcular_cuotas_imss(sbc, prima_riesgo_trabajo=0.54355)
    assert cuotas["enfermedad_maternidad"] == pytest.approx(
        (UMA * 0.204 + 300 * 0.007) * DIAS, abs=0.01
    )


def test_cuotas_imss_son_del_mes_no_del_dia():
    """Regresión 2026-10-27: las cuotas salían por un día y se mostraban como mensuales."""
    sbc = 500.0
    mes = calcular_cuotas_imss(sbc, prima_riesgo_trabajo=0.54355)
    dia = calcular_cuotas_imss(sbc, prima_riesgo_trabajo=0.54355, dias=1)
    assert mes["invalidez_vida"] == pytest.approx(500 * 0.0175 * DIAS, abs=0.01)
    assert mes["retiro"] == pytest.approx(500 * 0.02 * DIAS, abs=0.01)
    assert mes["gastos_medicos_pensionados"] == pytest.approx(500 * 0.0105 * DIAS, abs=0.01)
    assert mes["total"] == pytest.approx(dia["total"] * DIAS, abs=0.5)


def test_caso_reportado_22000_mensual_nuevo_leon():
    """El caso del reporte: $22,000 mensuales, 1 año, clase I, Nuevo León al 3%.

    Calculado a mano con las tasas 2026. SBC = 22,000/30 × 1.0493 = 769.50
    (6.56 UMA, tramo de CyV 7.513%).
    """
    res = calcular_carga_patronal(
        CargaPatronalInput(
            salario=22000,
            tipo_salario="mensual",
            antiguedad_anios=1,
            clase_riesgo="I",
            codigo_estado="NL",
            tasa_impuesto_estatal=0.03,
        )
    )
    sbc = res["sbc"]
    assert sbc == pytest.approx(769.50, abs=0.01)
    c = res["cuotas_imss"]
    assert c["enfermedad_maternidad"] == pytest.approx(
        (UMA * 0.204 + (sbc - 3 * UMA) * 0.011 + sbc * 0.007) * DIAS, abs=0.05
    )  # ≈ 1,031
    assert c["gastos_medicos_pensionados"] == pytest.approx(sbc * 0.0105 * DIAS, abs=0.05)
    assert c["invalidez_vida"] == pytest.approx(sbc * 0.0175 * DIAS, abs=0.05)
    assert c["retiro"] == pytest.approx(sbc * 0.02 * DIAS, abs=0.05)  # ≈ 467.86
    assert c["cesantia_vejez"] == pytest.approx(sbc * 0.07513 * DIAS, abs=0.05)
    assert c["guarderias"] == pytest.approx(sbc * 0.01 * DIAS, abs=0.05)
    assert c["riesgos_trabajo"] == pytest.approx(sbc * 0.0054355 * DIAS, abs=0.05)
    assert res["infonavit"] == pytest.approx(sbc * 0.05 * DIAS, abs=0.05)  # ≈ 1,169.64
    # ISN 3% sobre salario + aguinaldo (916.67) + prima vacacional (183.33)
    assert res["impuesto_estatal"] == pytest.approx(0.03 * (22000 + 916.67 + 183.33), abs=0.01)
    # Carga patronal: entre 25% y 35% del sueldo, no ~9% como antes del arreglo
    assert 0.25 < res["carga_patronal_mensual"] / 22000 < 0.35


@pytest.mark.parametrize(
    "umas,tasa",
    [
        (1.0, 0.03150),
        (1.01, 0.03676),
        (2.0, 0.04851),
        (3.0, 0.06026),
        (4.0, 0.06613),
        (4.01, 0.07513),
        (10.0, 0.07513),
    ],
)
def test_rangos_cyv(umas, tasa):
    assert determinar_tasa_cyv(117.31 * umas) == tasa


def test_isn_por_estado_y_manual():
    jalisco = calcular_carga_patronal(
        CargaPatronalInput(
            salario=10000, tipo_salario="mensual", antiguedad_anios=1, codigo_estado="JAL"
        )
    )
    assert jalisco["tasa_estatal_aplicada"] == 0.03
    manual = calcular_carga_patronal(
        CargaPatronalInput(
            salario=10000,
            tipo_salario="mensual",
            antiguedad_anios=1,
            codigo_estado="JAL",
            tasa_impuesto_estatal=0.025,
        )
    )
    assert manual["tasa_estatal_aplicada"] == 0.025
    assert manual["impuesto_estatal"] == pytest.approx(262.5)  # 2.5% × (10,000 + 416.67 + 83.33)


def test_prima_riesgo_por_clase():
    clase_v = calcular_carga_patronal(
        CargaPatronalInput(
            salario=10000, tipo_salario="mensual", antiguedad_anios=1, clase_riesgo="V"
        )
    )
    assert clase_v["prima_riesgo_aplicada"] == pytest.approx(7.58875)
    assert clase_v["cuotas_imss"]["riesgos_trabajo"] > 0


def test_prestaciones_adicionales():
    res = calcular_carga_patronal(
        CargaPatronalInput(
            salario=10000,
            tipo_salario="mensual",
            antiguedad_anios=1,
            prestaciones_adicionales=[
                {"nombre": "Vales de despensa", "monto": 1000, "tipo": "mensual"},
                {"nombre": "Fondo de ahorro", "monto": 12000, "tipo": "anual"},
            ],
        )
    )
    assert res["prestaciones_adicionales"] == pytest.approx(2000.0)


def test_sin_prorrateos():
    res = calcular_carga_patronal(
        CargaPatronalInput(
            salario=10000,
            tipo_salario="mensual",
            antiguedad_anios=1,
            incluir_aguinaldo_mensual=False,
            incluir_vacaciones_mensual=False,
        )
    )
    assert res["aguinaldo_prorrateo"] == 0
    assert res["vacaciones_prorrateo"] == 0


def test_salario_invalido():
    with pytest.raises(ValueError):
        calcular_carga_patronal(
            CargaPatronalInput(salario=0, tipo_salario="mensual", antiguedad_anios=1)
        )


def test_anio_sin_imss():
    with pytest.raises(ValueError, match="IMSS"):
        calcular_carga_patronal(
            CargaPatronalInput(salario=10000, tipo_salario="mensual", antiguedad_anios=1, anio=2025)
        )

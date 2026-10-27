"""Integridad de los indicadores fiscales por año."""

import pytest

from sat_descarga.calculadoras.indicadores import (
    INDICADORES,
    UMA_SMG_HISTORICO,
    get_indicadores,
)


def test_anios_soportados():
    assert sorted(INDICADORES) == [2021, 2022, 2023, 2024, 2025, 2026]


def test_get_indicadores_anio_no_soportado():
    with pytest.raises(ValueError, match="2019"):
        get_indicadores(2019)


def test_valores_2026():
    ind = get_indicadores(2026)
    assert ind.uma_diaria == 117.31
    assert ind.uma_mensual == 3566.22
    assert ind.uma_anual == 42794.64
    assert ind.smg_general == 315.04
    # CONASAMI 2026: la web traía 474.11 por error; el valor correcto es 440.87
    assert ind.smg_frontera == 440.87
    assert ind.tope_sbc_diario == pytest.approx(2932.75)


def test_valores_2025():
    ind = get_indicadores(2025)
    assert ind.uma_diaria == 113.14
    assert ind.smg_general == 278.80
    assert ind.smg_frontera == 419.88


@pytest.mark.parametrize("anio", [2022, 2023, 2024, 2025, 2026])
def test_tarifa_mensual_integridad(anio):
    """11 tramos, límites contiguos (+0.01), porcentajes crecientes 1.92%→35%."""
    tarifa = get_indicadores(anio).tarifa_isr_mensual
    assert tarifa is not None
    assert len(tarifa) == 11
    assert tarifa[0].limite_inferior == 0.01
    assert tarifa[0].porcentaje_excedente == 0.0192
    assert tarifa[-1].limite_superior is None
    assert tarifa[-1].porcentaje_excedente == 0.35
    for anterior, siguiente in zip(tarifa, tarifa[1:]):
        assert anterior.limite_superior is not None
        assert siguiente.limite_inferior == pytest.approx(
            anterior.limite_superior + 0.01, abs=1e-6
        )


def test_tarifa_2026_valores_anexo8():
    tarifa = get_indicadores(2026).tarifa_isr_mensual
    assert tarifa[0].limite_superior == 844.59
    assert tarifa[1].cuota_fija == 16.22
    assert tarifa[10].limite_inferior == 425642.00
    assert tarifa[10].cuota_fija == 133488.54


def test_tarifa_2021_no_cargada_con_advertencia():
    ind = get_indicadores(2021)
    assert ind.tarifa_isr_mensual is None
    assert any("Tarifa ISR" in a for a in ind.advertencias)


def test_spe_2026_montos_dof():
    """DOF 31-12-2025 (nota 5777649): feb-dic 15.02% × UMA 2026; enero 15.59% ×
    UMA vigente en enero (la de 2025, Transitorio Segundo)."""
    spe = get_indicadores(2026).spe
    assert spe.esquema == "uma"
    assert spe.limite_ingresos_mensual == 11492.66
    assert spe.monto_mensual_resto == pytest.approx(535.65, abs=0.005)
    assert spe.monto_mensual_enero == pytest.approx(536.21, abs=0.005)


def test_spe_2025_montos_dof():
    spe = get_indicadores(2025).spe
    assert spe.esquema == "uma"
    assert spe.limite_ingresos_mensual == 10171.00
    assert spe.monto_mensual_resto == pytest.approx(474.64, abs=0.005)
    assert spe.monto_mensual_enero == pytest.approx(474.95, abs=0.005)


def test_spe_2024_es_tabla():
    spe = get_indicadores(2024).spe
    assert spe.esquema == "tabla"
    assert len(spe.tabla) == 10
    assert spe.tabla[0].subsidio_mensual == 407.02
    assert spe.tabla[-1].limite_superior == 7382.33


def test_imss_2026():
    imss = get_indicadores(2026).imss
    assert imss is not None
    assert imss.infonavit == 0.05
    rangos = imss.cesantia_vejez
    assert len(rangos) == 8
    assert rangos[0].tasa == 0.0315
    assert rangos[-1].tasa == 0.07513
    assert imss.retiro == 0.02
    assert imss.gastos_medicos_pensionados == 0.0105
    assert rangos[-1].max_umas is None


def test_imss_anios_previos_no_cargados():
    for anio in (2021, 2022, 2023, 2024, 2025):
        ind = get_indicadores(anio)
        assert ind.imss is None
        assert any("IMSS" in a for a in ind.advertencias)


def test_historico_uma_smg():
    assert UMA_SMG_HISTORICO[2026] == (117.31, 315.04, 440.87)
    assert UMA_SMG_HISTORICO[2025] == (113.14, 278.80, 419.88)
    assert UMA_SMG_HISTORICO[2016] == (73.04, 73.04, 73.04)
    assert sorted(UMA_SMG_HISTORICO) == list(range(2016, 2027))

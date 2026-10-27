"""Endpoints /calculadoras/* del agente local (TestClient)."""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import server  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402

RFC = "CAUI890921DAA"


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")


@pytest.fixture
def client():
    return TestClient(server.app)


def test_isr_basico(client):
    r = client.post("/calculadoras/isr", json={"ingreso_gravado": 15000})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["resultado"]["isr_final"] == pytest.approx(1402.82, abs=0.01)
    # Sin RFC el estado se persiste bajo "__general__" (no se pierde el trabajo)
    assert body["guardado_en"] is not None
    estado = client.get("/calculadoras/estado/__general__/isr").json()["estado"]
    assert estado["inputs"]["ingreso_gravado"] == 15000


def test_aguinaldo_con_autoguardado(client):
    payload = {
        "salario": 12000,
        "tipo_salario": "mensual",
        "fecha_ingreso": "2025-01-01",
        "fecha_calculo": "2026-12-20",
        "rfc": RFC,
    }
    r = client.post("/calculadoras/aguinaldo", json=payload)
    assert r.status_code == 200
    body = r.json()
    # 12,000 / 30.4 × 15 días (año completo)
    assert body["resultado"]["aguinaldo_bruto"] == pytest.approx(5921.05, abs=0.01)
    assert body["guardado_en"] is not None

    # Round-trip: el estado quedó persistido por RFC
    estado = client.get(f"/calculadoras/estado/{RFC}/aguinaldo").json()["estado"]
    assert estado is not None
    assert estado["inputs"]["salario"] == 12000
    assert estado["resultado"]["aguinaldo_bruto"] == body["resultado"]["aguinaldo_bruto"]

    # Y otra empresa NO ve ese estado
    otro = client.get("/calculadoras/estado/XAXX010101000/aguinaldo").json()["estado"]
    assert otro is None


def test_aguinaldo_debajo_del_salario_minimo_400(client):
    """$8,000 mensuales < SMG mensual 2026 (315.04 × 30.4 = $9,577.22) → 400."""
    r = client.post(
        "/calculadoras/aguinaldo",
        json={
            "salario": 8000,
            "tipo_salario": "mensual",
            "fecha_ingreso": "2025-01-01",
            "fecha_calculo": "2026-12-20",
        },
    )
    assert r.status_code == 400
    assert "salario mínimo" in r.json()["detail"]

    # $400 diarios: pasa en zona general, falla en la frontera ($440.87)
    frontera = client.post(
        "/calculadoras/aguinaldo",
        json={
            "salario": 400,
            "tipo_salario": "diario",
            "fecha_ingreso": "2025-01-01",
            "fecha_calculo": "2026-12-20",
            "es_zona_fronteriza": True,
        },
    )
    assert frontera.status_code == 400


def test_finiquito_endpoint(client):
    r = client.post(
        "/calculadoras/finiquito",
        json={
            "salario": 12000,
            "tipo_salario": "mensual",
            "fecha_ingreso": "2022-03-01",
            "fecha_baja": "2026-07-15",
        },
    )
    assert r.status_code == 200
    assert r.json()["resultado"]["salario_diario"] == 400


def test_finiquito_fechas_invalidas_400(client):
    r = client.post(
        "/calculadoras/finiquito",
        json={
            "salario": 12000,
            "tipo_salario": "mensual",
            "fecha_ingreso": "2026-07-15",
            "fecha_baja": "2026-07-15",
        },
    )
    assert r.status_code == 400


def test_isr_debajo_del_salario_minimo_400(client):
    """$100 diarios < SMG general → 400; en ZLFN el umbral es mayor."""
    r = client.post(
        "/calculadoras/isr", json={"ingreso_gravado": 100, "periodicidad": "diario"}
    )
    assert r.status_code == 400
    assert "salario mínimo" in r.json()["detail"]

    # $400 diarios: pasa en zona general, falla en la frontera ($440.87)
    ok = client.post(
        "/calculadoras/isr", json={"ingreso_gravado": 400, "periodicidad": "diario"}
    )
    assert ok.status_code == 200
    frontera = client.post(
        "/calculadoras/isr",
        json={"ingreso_gravado": 400, "periodicidad": "diario", "es_zona_fronteriza": True},
    )
    assert frontera.status_code == 400

    # A los asimilados el salario mínimo no les aplica
    asimilado = client.post(
        "/calculadoras/isr",
        json={"ingreso_gravado": 100, "periodicidad": "diario", "es_asimilado": True},
    )
    assert asimilado.status_code == 200


def test_sbc_debajo_del_salario_minimo_400(client):
    """El SBC también rechaza salarios por debajo del mínimo (general/ZLFN)."""
    r = client.post(
        "/calculadoras/sbc",
        json={"salario": 300, "tipo_salario": "diario", "antiguedad_anios": 1},
    )
    assert r.status_code == 400
    assert "salario mínimo" in r.json()["detail"]

    # Mensual usa el mismo factor /30 de la calculadora: $9,450 → $315 diarios (< SMG)
    bajo = client.post(
        "/calculadoras/sbc",
        json={"salario": 9450, "tipo_salario": "mensual", "antiguedad_anios": 1},
    )
    assert bajo.status_code == 400
    ok = client.post(
        "/calculadoras/sbc",
        json={"salario": 9452, "tipo_salario": "mensual", "antiguedad_anios": 1},
    )
    assert ok.status_code == 200

    # $400 diarios: pasa en zona general, falla en la frontera ($440.87)
    frontera = client.post(
        "/calculadoras/sbc",
        json={
            "salario": 400,
            "tipo_salario": "diario",
            "antiguedad_anios": 1,
            "es_zona_fronteriza": True,
        },
    )
    assert frontera.status_code == 400


def test_validacion_422(client):
    r = client.post("/calculadoras/isr", json={"ingreso_gravado": -5})
    assert r.status_code == 422
    r2 = client.post(
        "/calculadoras/liquidacion",
        json={
            "salario": 100,
            "tipo_salario": "diario",
            "fecha_ingreso": "2020-01-01",
            "fecha_baja": "2026-01-01",
            "tipo_terminacion": "DESPIDO_IMAGINARIO",
        },
    )
    assert r2.status_code == 422


def test_liquidacion_endpoint(client):
    r = client.post(
        "/calculadoras/liquidacion",
        json={
            "salario": 15000,
            "tipo_salario": "mensual",
            "fecha_ingreso": "2020-03-01",
            "fecha_baja": "2026-07-15",
            "tipo_terminacion": "DESPIDO_INJUSTIFICADO",
            "rfc": RFC,
        },
    )
    assert r.status_code == 200
    res = r.json()["resultado"]
    assert res["aplica_tres_meses"] is True
    assert res["indemnizacion"]["veinte_dias_por_anio"]["monto"] == 0


def test_carga_patronal_endpoint(client):
    r = client.post(
        "/calculadoras/carga-patronal",
        json={
            "salario": 12000,
            "tipo_salario": "mensual",
            "antiguedad_anios": 1,
            "codigo_estado": "CDMX",
        },
    )
    assert r.status_code == 200
    assert r.json()["resultado"]["impuesto_estatal"] == pytest.approx(504.0)


def test_carga_patronal_debajo_del_salario_minimo_400(client):
    """La carga patronal también rechaza salarios por debajo del mínimo."""
    r = client.post(
        "/calculadoras/carga-patronal",
        json={"salario": 300, "tipo_salario": "diario", "antiguedad_anios": 1},
    )
    assert r.status_code == 400
    assert "salario mínimo" in r.json()["detail"]

    # Mensual usa el factor /30: $9,450 → $315 diarios (< SMG general)
    bajo = client.post(
        "/calculadoras/carga-patronal",
        json={"salario": 9450, "tipo_salario": "mensual", "antiguedad_anios": 1},
    )
    assert bajo.status_code == 400

    # $400 diarios: pasa en zona general, falla en la frontera ($440.87)
    frontera = client.post(
        "/calculadoras/carga-patronal",
        json={
            "salario": 400,
            "tipo_salario": "diario",
            "antiguedad_anios": 1,
            "es_zona_fronteriza": True,
        },
    )
    assert frontera.status_code == 400


def test_carga_patronal_anio_sin_imss_400(client):
    r = client.post(
        "/calculadoras/carga-patronal",
        json={"salario": 12000, "tipo_salario": "mensual", "antiguedad_anios": 1, "anio": 2025},
    )
    assert r.status_code == 400


def test_ptu_endpoint(client):
    r = client.post(
        "/calculadoras/ptu",
        json={
            "utilidad_fiscal": 600000,
            "ejercicio": 2025,
            "rfc": RFC,
            "trabajadores": [
                {
                    "nombre": "Trabajador de Prueba",
                    "salario_diario": 15000 / 30.4,
                    "dias_trabajados": 365,
                    "percepcion_anual": 180000,
                    "ptu_anio_1": 40000,
                    "ptu_anio_2": 40000,
                    "ptu_anio_3": 40000,
                    "ingreso_mensual_ordinario": 15000,
                    "isr_mensual_ordinario": 1068.54,
                }
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    t = body["resultado"]["trabajadores"][0]
    assert t["ptu_real"] == pytest.approx(45000.0)
    assert t["comparacion"]["metodo_recomendado"] == "art174"
    # auto-guardado bajo la calculadora "ptu"
    estado = client.get(f"/calculadoras/estado/{RFC}/ptu").json()["estado"]
    assert estado is not None
    assert estado["anio"] == 2026  # año de pago


def test_ptu_ejercicio_no_soportado_400(client):
    r = client.post(
        "/calculadoras/ptu",
        json={
            "utilidad_fiscal": 1000,
            "ejercicio": 2019,
            "trabajadores": [
                {
                    "nombre": "X",
                    "salario_diario": 100,
                    "dias_trabajados": 100,
                    "percepcion_anual": 10000,
                }
            ],
        },
    )
    assert r.status_code == 400


def test_indicadores_endpoint(client):
    r = client.get("/calculadoras/indicadores/2026")
    assert r.status_code == 200
    body = r.json()
    assert body["uma_diaria"] == 117.31
    assert body["smg_frontera"] == 440.87
    assert len(body["tarifa_isr_mensual"]) == 11
    assert len(body["estados_isn"]) == 32
    assert body["spe"]["monto_mensual_resto"] == pytest.approx(535.65, abs=0.005)

    assert client.get("/calculadoras/indicadores/2019").status_code == 404


def test_estado_empresa_completo(client):
    client.post("/calculadoras/isr", json={"ingreso_gravado": 10000, "rfc": RFC})
    client.post(
        "/calculadoras/sbc",
        json={"salario": 400, "tipo_salario": "diario", "antiguedad_anios": 1, "rfc": RFC},
    )
    r = client.get(f"/calculadoras/estado/{RFC}")
    assert r.status_code == 200
    estados = r.json()["estados"]
    assert set(estados) == {"isr", "sbc"}


def test_estado_rfc_invalido_400(client):
    assert client.get("/calculadoras/estado/no-valido").status_code == 400


def test_guardados_crud(client):
    r = client.post(
        f"/calculadoras/guardados/{RFC}",
        json={
            "calculadora": "finiquito",
            "nombre": "Finiquito Juan Pérez",
            "inputs": {"salario": 12000},
            "resultado": {"total_neto": 15000},
            "anio": 2026,
        },
    )
    assert r.status_code == 200
    guardado = r.json()["guardado"]
    assert guardado["nombre"] == "Finiquito Juan Pérez"

    lista = client.get(f"/calculadoras/estado/{RFC}").json()["guardados"]
    assert len(lista) == 1

    assert client.delete(f"/calculadoras/guardados/{RFC}/{guardado['id']}").status_code == 200
    assert client.delete(f"/calculadoras/guardados/{RFC}/{guardado['id']}").status_code == 404

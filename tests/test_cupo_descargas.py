"""Descargas al SAT del mes y su tope en el plan gratis (F1).

Un solo contador para todo lo que se baja del SAT; se hace cumplir solo con
planes v3 vigentes y plan `gratis`, y nunca sin datos de licencia. El SAT, el
portal y la licencia del servicio se simulan; nada toca la red.
"""

from __future__ import annotations

import json
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import cupo_descargas as cd  # noqa: E402
from sat_descarga.api import jobs, server  # noqa: E402
from sat_descarga.api import license_client as lc  # noqa: E402
from sat_descarga.api.routers import webservice  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402

GRATIS = {
    "authenticated": True, "plan": "free", "plan_codigo": "gratis", "plan_nombre": "Gratis",
    "limites": {"empresas": 5, "usuarios": 1}, "legado": False, "planes_v3_activo": True,
}
ESENCIAL = {**GRATIS, "plan": "premium", "plan_codigo": "esencial", "plan_nombre": "Esencial",
            "limites": {"empresas": 10, "usuarios": 1}}
TRIAL = {**GRATIS, "plan": "trial", "plan_codigo": "trial", "plan_nombre": "Prueba",
         "limites": {"empresas": 50, "usuarios": 1}}
LEGADO = {**GRATIS, "plan": "premium", "plan_codigo": "desktop", "plan_nombre": "Anual",
          "limites": {"empresas": None, "usuarios": 1}, "legado": True}


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "registry", jobs.JobRegistry())
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    yield
    server._limpiar_session()


@pytest.fixture
def client():
    return TestClient(server.app)


def _licencia(payload, *, edad_s=3600):
    if payload is None:
        lc.clear_license_cache()
        return
    lc._cache_write({"cached_at": int(time.time()) - edad_s, "payload": payload})


def _usadas(n: int):
    for _ in range(n):
        cd.registrar("cfdi")


def _sin_refresco(monkeypatch):
    def explota(**_):
        raise AssertionError("no debía pedir la licencia al servicio")

    monkeypatch.setattr(lc, "get_license_status", explota)


# ---------------------------------------------------------------------------
# Contador
# ---------------------------------------------------------------------------


def test_cuenta_por_tipo_y_se_reinicia_cada_mes(monkeypatch):
    monkeypatch.setattr(cd, "_mes_actual", lambda: "2026-11")
    cd.registrar("cfdi")
    cd.registrar("constancia")
    cd.registrar("cfdi")
    assert cd.resumen() == {"mes": "2026-11", "usadas": 3,
                            "por_tipo": {"cfdi": 2, "constancia": 1}}
    monkeypatch.setattr(cd, "_mes_actual", lambda: "2026-12")
    assert cd.usadas_del_mes() == 0
    cd.registrar("opinion")
    assert cd.resumen()["usadas"] == 1


def test_archivo_ilegible_cuenta_desde_cero():
    cd._ruta().write_text("{no es json", encoding="utf-8")
    assert cd.usadas_del_mes() == 0
    cd.registrar("cfdi")
    assert cd.usadas_del_mes() == 1


def test_reinicia_el_primero_del_mes_siguiente():
    assert cd.CupoDescargas(10, 0, "2026-11", "gratis", "Gratis").reinicia == "2026-12-01"
    assert cd.CupoDescargas(10, 0, "2026-12", "gratis", "Gratis").reinicia == "2027-01-01"


# ---------------------------------------------------------------------------
# Cuándo aplica el tope
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "licencia, tope",
    [
        (GRATIS, 10),
        ({**GRATIS, "limites": {"empresas": 5, "usuarios": 1, "descargas_mes": 20}}, 20),
        ({**GRATIS, "limites": {"descargas_mes": "muchas"}}, 10),
        ({**GRATIS, "planes_v3_activo": False}, None),
        ({k: v for k, v in GRATIS.items() if k != "planes_v3_activo"}, None),
        (ESENCIAL, None),
        (TRIAL, None),
        (LEGADO, None),
        ({"authenticated": True, "plan": "free"}, None),  # licencia de antes de F0
        (None, None),
    ],
)
def test_tope_de(licencia, tope):
    assert cd.tope_de(licencia) == tope


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


class _FielFalsa:
    rfc = "XAXX010101000"


def _solicitar_ok(monkeypatch):
    monkeypatch.setattr(webservice, "_get_fiel", lambda: _FielFalsa())
    monkeypatch.setattr(webservice, "_renovar_token", lambda: "token")
    monkeypatch.setattr(webservice, "solicitar_descarga", lambda **kw: "id-solicitud-1")
    monkeypatch.setattr(webservice, "_guardar_solicitud_ws", lambda *a, **k: None)


SOLICITUD = {"fecha_inicio": "2026-11-01", "fecha_fin": "2026-11-30", "tipo_comprobante": "R"}


def test_gratis_la_descarga_11_da_402(client, monkeypatch):
    _licencia(GRATIS)
    monkeypatch.setattr(lc, "get_license_status", lambda force_refresh=False: GRATIS)
    _solicitar_ok(monkeypatch)
    _usadas(9)
    assert client.post("/solicitar", json=SOLICITUD).status_code == 200  # la 10 entra
    assert cd.usadas_del_mes() == 10

    r = client.post("/solicitar", json=SOLICITUD)
    assert r.status_code == 402
    body = r.json()
    assert body["codigo"] == "tope_descargas"
    datos = body["tope_descargas"]
    assert datos["tope"] == 10 and datos["usadas"] == 10
    assert datos["plan_codigo"] == "gratis"
    assert datos["siguiente_plan"] == {"codigo": "esencial", "nombre": "Esencial", "descargas": None}
    assert body["detail"].startswith("Tu plan Gratis incluye 10 descargas al mes y ya usaste las 10.")
    assert "cambia a Esencial (descargas sin límite)" in body["detail"]
    assert cd.usadas_del_mes() == 10  # el rechazo no cuenta


@pytest.mark.parametrize("licencia", [ESENCIAL, TRIAL, LEGADO, {**GRATIS, "planes_v3_activo": False}])
def test_otros_planes_o_sin_interruptor_no_tienen_tope(client, monkeypatch, licencia):
    _licencia(licencia)
    _sin_refresco(monkeypatch)
    _solicitar_ok(monkeypatch)
    _usadas(40)
    assert client.post("/solicitar", json=SOLICITUD).status_code == 200
    assert cd.usadas_del_mes() == 41  # se cuenta igual (viaja con la sincronización)


def test_sin_licencia_nunca_bloquea(client, monkeypatch):
    _licencia(None)
    _sin_refresco(monkeypatch)
    _solicitar_ok(monkeypatch)
    _usadas(50)
    assert client.post("/solicitar", json=SOLICITUD).status_code == 200


def test_cache_fuera_de_gracia_no_bloquea(client, monkeypatch):
    _licencia(GRATIS, edad_s=lc.CACHE_GRACE_SECONDS + 60)
    _sin_refresco(monkeypatch)
    _solicitar_ok(monkeypatch)
    _usadas(10)
    assert client.post("/solicitar", json=SOLICITUD).status_code == 200


def test_si_ya_pago_el_refresco_lo_deja_pasar(client, monkeypatch):
    _licencia(GRATIS)
    llamadas = []

    def fresca(force_refresh=False):
        llamadas.append(force_refresh)
        return ESENCIAL

    monkeypatch.setattr(lc, "get_license_status", fresca)
    _solicitar_ok(monkeypatch)
    _usadas(10)
    assert client.post("/solicitar", json=SOLICITUD).status_code == 200
    assert llamadas == [True]


def test_solicitud_que_falla_no_gasta(client, monkeypatch):
    _licencia(GRATIS)
    _solicitar_ok(monkeypatch)

    def rechazo(**kw):
        raise RuntimeError("El SAT rechazó la solicitud")

    monkeypatch.setattr(webservice, "solicitar_descarga", rechazo)
    assert client.post("/solicitar", json=SOLICITUD).status_code == 400
    assert cd.usadas_del_mes() == 0


def test_metadata_cuenta_con_su_tipo(client, monkeypatch):
    _licencia(None)
    _solicitar_ok(monkeypatch)
    client.post("/solicitar", json={**SOLICITUD, "tipo_solicitud": "Metadata"})
    assert cd.resumen()["por_tipo"] == {"metadata": 1}


def test_job_del_portal_cuenta_al_terminar_y_bloquea_antes_de_abrir(client, monkeypatch):
    llamadas = []

    def scrape(**kwargs):
        llamadas.append(kwargs)
        return []

    monkeypatch.setattr("sat_descarga.portal.cfdi.descargar_cfdi_ciec", scrape)
    _licencia(GRATIS)
    monkeypatch.setattr(lc, "get_license_status", lambda force_refresh=False: GRATIS)
    _usadas(9)
    payload = {"rfc": "CAUI890921DAA", "ciec": "x",
               "fecha_inicio": "2026-11-01", "fecha_fin": "2026-11-30"}
    r = client.post("/ciec/cfdi", json=payload)
    assert r.status_code == 200
    job = jobs.registry.get(r.json()["job_id"])
    fin = time.time() + 3
    while time.time() < fin and job.estado not in ("done", "error"):
        time.sleep(0.02)
    assert job.estado == "done"
    assert cd.usadas_del_mes() == 10

    r = client.post("/ciec/cfdi", json=payload)
    assert r.status_code == 402
    assert r.json()["codigo"] == "tope_descargas"
    assert len(llamadas) == 1  # el portal ni se abrió


def test_constancia_con_efirma_cuenta_y_la_que_falla_no(client, monkeypatch, tmp_path):
    from sat_descarga.api import state
    from sat_descarga.api.routers import portal

    _licencia(None)
    monkeypatch.setattr(portal, "_get_fiel", lambda: _FielFalsa())
    state._session.update({"rfc": "XAXX010101000", "cer_path": "c", "key_path": "k", "password": "p"})
    pdf = tmp_path / "csf.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr("sat_descarga.portal.constancia.descargar_constancia_fiel", lambda **kw: pdf)
    assert client.post("/constancia/fiel").status_code == 200
    assert cd.resumen()["por_tipo"] == {"constancia": 1}

    monkeypatch.setattr("sat_descarga.portal.opinion.descargar_opinion_fiel", lambda **kw: None)
    assert client.post("/opinion/fiel").status_code == 502
    assert cd.usadas_del_mes() == 1


def test_endpoint_de_cupo(client, monkeypatch):
    monkeypatch.setattr(cd, "_mes_actual", lambda: "2026-11")
    _licencia(GRATIS)
    _usadas(3)
    assert client.get("/descargas/cupo").json() == {
        "aplica": True, "tope": 10, "usadas": 3, "mes": "2026-11", "reinicia": "2026-12-01",
        "plan_codigo": "gratis", "plan_nombre": "Gratis",
        "siguiente_plan": {"codigo": "esencial", "nombre": "Esencial", "descargas": None},
    }
    _licencia(None)
    cupo = client.get("/descargas/cupo").json()
    assert cupo["aplica"] is False and cupo["tope"] is None and cupo["usadas"] == 3


def test_el_resumen_viaja_con_la_sincronizacion(monkeypatch):
    from sat_descarga.api import sync_empresas

    monkeypatch.setattr(cd, "_mes_actual", lambda: "2026-11")
    lc.save_session(lc.Session(access_token="t", refresh_token=None, user_id="u", email=None))
    _usadas(2)
    enviado = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"empresas": []}

    def fake_put(url, json=None, **kw):
        enviado.update(json)
        return _Resp()

    monkeypatch.setattr(sync_empresas.requests, "put", fake_put)
    assert sync_empresas.sincronizar_catalogo() == 0
    assert enviado["descargas_mes"] == {"mes": "2026-11", "usadas": 2, "por_tipo": {"cfdi": 2}}
    assert "empresas" in enviado
    lc.clear_session()


def test_el_contador_vive_en_un_archivo_legible(monkeypatch):
    monkeypatch.setattr(cd, "_mes_actual", lambda: "2026-11")
    cd.registrar("acuse")
    assert json.loads(cd._ruta().read_text(encoding="utf-8"))["por_tipo"] == {"acuse": 1}

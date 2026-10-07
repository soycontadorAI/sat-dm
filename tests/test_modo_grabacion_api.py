"""Modo de grabación de punta a punta por la API del agente (como la usa la UI).

Siembra la cuenta de grabación en un perfil temporal y recorre las escenas de
los guiones contra los endpoints reales: Web Service, Descarga rápida con
captcha, 32-D/constancia, Validar contra SAT y listas negras. Ninguna llamada
sale al SAT (make_request truena si alguien lo intenta).
"""

from __future__ import annotations

import time
from datetime import datetime

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import jobs, server  # noqa: E402
from sat_descarga.demo import cfdi  # noqa: E402
from sat_descarga.demo import sat as sat_demo  # noqa: E402
from sat_descarga.demo.escenario import EL_ROBLE, MOLINA, NORMA, PANADERIA  # noqa: E402

AHORA = datetime(2026, 10, 19, 9, 30)
SIB = "SIB200117HU9"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from sat_descarga.cli import config_store
    from sat_descarga.demo.siembra import sembrar
    from sat_descarga.procesador import db as db_mod
    from sat_descarga.utils import validacion
    from sat_descarga.webservice import auth, descarga, solicitud, verificacion

    monkeypatch.setenv("SAT_DM_MODO_GRABACION", "1")
    monkeypatch.setenv("SAT_DM_GRABACION_RITMO", "0")
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "0")
    monkeypatch.setattr(cfdi, "_ahora", lambda: AHORA)
    monkeypatch.setattr(sat_demo, "_hoy", lambda: AHORA.date())
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / ".sat-descarga" / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))

    def _no(*a, **k):
        raise AssertionError(f"tocó al SAT: {k.get('operation')}")

    for mod in (auth, solicitud, verificacion, descarga, validacion):
        monkeypatch.setattr(mod, "make_request", _no)

    db_mod.resetear_singleton_para_tests()
    db_mod.abrir_db(tmp_path / "procesador.db")
    sembrar(ahora=AHORA, historial_cfdi=False, avisar=lambda *_: None)
    server._limpiar_session()
    yield TestClient(server.app)
    server._limpiar_session()
    db_mod.resetear_singleton_para_tests()


def _empresas(c):
    return {e["rfc"]: e for e in c.get("/empresas").json()["empresas"]}


def _esperar_job(c, job_id, captcha="K7PQ2X"):
    estados = []
    for _ in range(600):
        e = c.get(f"/jobs/{job_id}").json()
        if not estados or estados[-1] != e["estado"]:
            estados.append(e["estado"])
        if e["estado"] == "captcha":
            c.post(f"/jobs/{job_id}/captcha", json={"solution": captcha})
        if e["estado"] in ("done", "error", "cancelled"):
            return e, estados
        time.sleep(0.02)
    raise AssertionError(f"el job no terminó: {estados}")


def _eventos(job_id):
    job = jobs.registry.get(job_id)
    out = []
    while not job._eventos.empty():
        ev = job._eventos.get_nowait()
        if isinstance(ev, dict):
            out.append(ev)
    return out


def test_health_marca_el_modo(client, monkeypatch):
    assert client.get("/health").json()["modo_grabacion"] is True
    monkeypatch.delenv("SAT_DM_MODO_GRABACION")
    assert client.get("/health").json()["modo_grabacion"] is False


def test_pieza1_descarga_por_web_service(client, monkeypatch):
    assert client.post(f"/empresas/{EL_ROBLE}/activar").json()["efirma_lista"]
    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "3600")
    r = client.post("/solicitar", json={
        "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-30",
        "tipo_solicitud": "CFDI", "tipo_comprobante": "R",
    })
    assert r.status_code == 200, r.text
    id_sol = r.json()["id_solicitud"]
    v = client.post("/verificar", json={"id_solicitud": id_sol, "poll": False}).json()
    assert v["cod_estado"] in ("1", "2") and not v["terminada"]

    monkeypatch.setenv("SAT_DM_GRABACION_ESPERA", "0")
    v = client.post("/verificar", json={"id_solicitud": id_sol, "poll": False}).json()
    assert (v["cod_estado"], v["numero_cfdis"], v["terminada"]) == ("3", 1163, True)
    d = client.post("/descargar", params={"id_solicitud": id_sol}).json()
    assert d["ok"] and d["total"] == 1

    sol = next(s for s in client.get(f"/empresas/{EL_ROBLE}/solicitudes").json()["solicitudes"]
               if s["id_solicitud"] == id_sol)
    assert sol["estado"] == "descargada" and sol["numero_cfdis"] == 1163
    ultima = client.get("/historial").json()["descargas"][0]
    assert ultima["rfc"] == EL_ROBLE and ultima["total"] == 1163
    # No gasta descargas del mes de la cuenta de grabación.
    assert client.get("/descargas/cupo").json()["usadas"] == 0


def test_pieza1_descarga_rapida_con_captcha_y_avance(client):
    r = client.post("/ciec/cfdi", json={
        "rfc": MOLINA, "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-30",
        "tipo_comprobante": "R",
    })
    assert r.status_code == 200, r.text
    fin, estados = _esperar_job(client, r.json()["job_id"])
    assert fin["estado"] == "done" and "captcha" in estados
    esperados = sum(1 for c in cfdi.comprobantes(MOLINA, 2026, 9) if c.direccion == "R")
    assert fin["resultado"]["total"] == esperados
    eventos = _eventos(fin["id"])
    tipos = [e["event"] for e in eventos]
    assert "captcha_required" in tipos and "progreso" in tipos and tipos[-1] == "done"
    captcha = next(e for e in eventos if e["event"] == "captcha_required")
    assert captcha["imagen"].startswith("data:image/")
    ultimo = [e for e in eventos if e["event"] == "progreso"][-1]
    assert ultimo["actual"] == ultimo["total"] == esperados


def test_pieza2_semaforos_y_32d_por_efirma(client):
    emp = _empresas(client)
    assert emp[NORMA]["opinion_status"] == "negativa"
    assert emp[NORMA]["opinion_motivos"][0]["titulo"] == "Cumplimiento de obligaciones"
    assert emp[SIB]["opinion_status"] is None

    client.post(f"/empresas/{SIB}/activar")
    r = client.post("/opinion/fiel")
    assert r.status_code == 200, r.text
    assert _empresas(client)[SIB]["opinion_status"] == "positiva"

    client.post(f"/empresas/{PANADERIA}/activar")
    assert client.post("/constancia/fiel").status_code == 200
    pan = _empresas(client)[PANADERIA]
    assert pan["csf_path"] and pan["nombre"] == "Panadería La Central"


def test_pieza2_constancia_con_contrasena_y_captcha(client):
    r = client.post("/ciec/constancia", json={"rfc": MOLINA})
    fin, estados = _esperar_job(client, r.json()["job_id"])
    assert fin["estado"] == "done" and "captcha" in estados
    assert _empresas(client)[MOLINA]["csf_path"]


def test_pieza3_validar_contra_sat_y_listas_negras(client):
    from sat_descarga.demo.siembra import sembrar

    sembrar(ahora=AHORA, avisar=lambda *_: None)  # ahora sí, con julio y agosto en disco
    client.post(f"/empresas/{EL_ROBLE}/activar")
    cargados = client.post("/procesador/cfdi/cargar-desde-empresa", json={
        "rfc": EL_ROBLE, "desde": "2026-07-01", "hasta": "2026-08-31", "tipo": "R",
    }).json()
    assert cargados["agregados"] > 2000  # julio y agosto, sembrados

    # Septiembre llega por la descarga de la pieza 1.
    id_sol = client.post("/solicitar", json={
        "fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-30",
        "tipo_solicitud": "CFDI", "tipo_comprobante": "R",
    }).json()["id_solicitud"]
    client.post("/verificar", json={"id_solicitud": id_sol, "poll": False})
    client.post("/descargar", params={"id_solicitud": id_sol})
    client.delete("/procesador/cfdi", params={"rfc": EL_ROBLE})
    cargados = client.post("/procesador/cfdi/cargar-desde-empresa", json={
        "rfc": EL_ROBLE, "desde": "2026-09-01", "hasta": "2026-09-30", "tipo": "R",
    }).json()
    assert cargados["agregados"] == 1163

    v = client.post("/procesador/cfdi/validar-sat", json={"rfc": EL_ROBLE}).json()
    assert (v["validados"], v["cancelados"], v["vigentes"]) == (1163, 3, 1160)

    ln = client.post("/procesador/cfdi/validar-listas-negras", json={"rfc": EL_ROBLE}).json()
    assert (ln["efos"], ln["lista_69"]) == (1, 2)
    assert ln["metadata"]["lista_69b_updated_at"]

    pagos = client.get("/procesador/pagos/stats", params={"rfc": EL_ROBLE}).json()
    assert pagos["complementos_extemporaneos"] == 2 and pagos["incidencias_pue"] == 1

    rfcs = client.post("/listas-negras/consultar",
                       json={"rfcs": ["SAG990231KX4", "FMC120431RB7", "TUC120230AB1"]}).json()
    assert [m["risk_level"] for m in rfcs["matches"]] == ["alto", "medio", "limpio"]


def test_empresa_real_en_la_misma_sesion_sigue_al_sat(client, test_cer, test_key, test_password):
    with open(test_cer, "rb") as cer, open(test_key, "rb") as key:
        r = client.post("/auth/cargar-fiel", files={"cer_file": cer, "key_file": key},
                        data={"password": test_password})
    assert r.status_code == 200
    with pytest.raises(AssertionError, match="tocó al SAT"):
        client.post("/solicitar", json={"fecha_inicio": "2026-09-01", "fecha_fin": "2026-09-30"})

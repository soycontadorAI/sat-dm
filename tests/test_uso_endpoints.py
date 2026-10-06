"""Uso por acción de punta a punta: cada endpoint deja su evento en la cola al
salir bien, con propiedades de la lista blanca y sin RFC ni nombres.

TestClient sin `with`: el lifespan (y el hilo de envío) no arranca; la red
nunca se toca.
"""

import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import license_client as lc  # noqa: E402
from sat_descarga.api import poller, server, uso  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402

RFC = "XAXX010101000"
RFC_2 = "CAMY89051862A"


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta"))
    monkeypatch.setattr(poller, "_fiel_cache", {})
    # Encendido (el conftest lo deja apagado) y sin sincronizar nada.
    monkeypatch.delenv("SAT_DM_SIN_USO", raising=False)
    monkeypatch.setenv("SAT_DM_USO", "1")
    monkeypatch.delenv("SAT_DM_MODO", raising=False)
    monkeypatch.setattr("sat_descarga.api.routers.empresas.sincronizar_async", lambda motivo="": None)
    monkeypatch.setattr("sat_descarga.api.routers.tareas.sincronizar_async", lambda motivo="": None)


@pytest.fixture
def client():
    return TestClient(server.app)


def _eventos():
    ruta = uso._ruta()
    if not ruta.exists():
        return []
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines() if linea]


def _resumen():
    return [(e["evento"], e["props"]) for e in _eventos()]


def test_tarea_creada(client):
    assert client.post("/tareas", json={"titulo": "Presentar la DIOT"}).status_code == 200
    r = client.post("/tareas", json={"titulo": "Renovar e.firma", "tipo": "fiscal",
                                     "sugerencia_id": "efirma-por-vencer"})
    assert r.status_code == 200
    assert _resumen() == [
        ("tarea_creada", {"tipo": "manual", "desde_sugerencia": False}),
        ("tarea_creada", {"tipo": "fiscal", "desde_sugerencia": True}),
    ]
    assert "Presentar" not in uso._ruta().read_text(encoding="utf-8")


def test_empresa_agregada_nueva_o_existente_y_archivada(client):
    assert client.post("/empresas/ciec", json={"rfc": RFC, "nombre": "Empresa Uno", "ciec": "x"}).status_code == 200
    assert client.post("/empresas/ciec", json={"rfc": RFC, "ciec": "y"}).status_code == 200
    assert client.post(f"/empresas/{RFC}/archive").status_code == 200
    assert _resumen() == [
        ("empresa_agregada", {"metodo": "contrasena", "nueva": True}),
        ("empresa_agregada", {"metodo": "contrasena", "nueva": False}),
        ("empresa_archivada", {}),
    ]
    texto = uso._ruta().read_text(encoding="utf-8")
    assert RFC not in texto and "Empresa Uno" not in texto


def test_calculadora_usada_una_vez_aunque_recalcule(client):
    cuerpo = {"salario": 15000, "tipo_salario": "mensual", "antiguedad_anios": 2}
    for salario in (15000, 15100, 15200):  # cada tecla recalcula
        r = client.post("/calculadoras/sbc", json={**cuerpo, "salario": salario})
        assert r.status_code == 200
    r = client.post("/calculadoras/carga-patronal", json={**cuerpo, "clase_riesgo": "I",
                                                         "codigo_estado": "CDMX"})
    assert r.status_code == 200, r.text
    assert _resumen() == [
        ("calculadora_usada", {"calculadora": "sbc"}),
        ("calculadora_usada", {"calculadora": "carga_patronal"}),
    ]


def test_app_abierta_al_cargar_y_solo_con_sesion(client, monkeypatch):
    monkeypatch.setattr(lc, "get_license_status", lambda force_refresh=False: {"authenticated": False})
    client.get("/auth/license")
    assert _eventos() == []

    monkeypatch.setattr(lc, "get_license_status",
                        lambda force_refresh=False: {"authenticated": True, "email": "x@y.mx"})
    client.get("/auth/license")
    client.get("/auth/license")              # reconexión del renderer: misma apertura
    client.get("/auth/license?refresh=true")  # intervalo de 6 h: no es apertura
    (evento,) = _eventos()
    assert evento["evento"] == "app_abierta"
    assert set(evento["props"]) <= {"sistema"}


def test_cerrar_sesion_vacia_la_cola(client, monkeypatch):
    uso.track("diot_generada")
    monkeypatch.setattr(lc, "load_session", lambda: None)  # sin sesión: no se puede mandar
    assert client.post("/auth/logout").status_code == 200
    assert _eventos() == []


def test_descarga_completada_por_el_poller(monkeypatch):
    class FielFake:
        rfc = RFC_2

    config_store.add_empresa_ciec(RFC_2, "Empresa Dos", "ciec")
    config_store.save_solicitud(rfc=RFC_2, id_solicitud="sol-1", fecha_inicio="2026-09-01",
                                fecha_fin="2026-09-30", tipo="CFDI · recibidos",
                                tipo_comprobante="R")
    config_store.update_solicitud(RFC_2, "sol-1", "3", package_ids=["PKG-1"], numero_cfdis=42)
    monkeypatch.setattr(poller, "obtener_token", lambda fiel: "token")
    monkeypatch.setattr(poller, "descargar_todos", lambda **kw: [])

    poller._descargar_lista(RFC_2, FielFake(), config_store.get_solicitud(RFC_2, "sol-1"))

    assert _resumen() == [("descarga_completada", {
        "canal": "web_service", "credencial": "efirma", "tipo": "recibidos",
        "tamano": "11_100", "segundo_plano": True,
    })]
    texto = uso._ruta().read_text(encoding="utf-8")
    assert RFC_2 not in texto and "sol-1" not in texto and "PKG-1" not in texto


def test_solicitud_vacia_tambien_cuenta_como_completada(monkeypatch):
    class FielFake:
        rfc = RFC_2

    config_store.add_empresa_ciec(RFC_2, "Empresa Dos", "ciec")
    config_store.save_solicitud(rfc=RFC_2, id_solicitud="sol-2", fecha_inicio="2026-09-01",
                                fecha_fin="2026-09-30", tipo="Metadata · emitidos",
                                tipo_comprobante="E")
    config_store.update_solicitud(RFC_2, "sol-2", "3")
    monkeypatch.setattr(poller, "obtener_token", lambda fiel: "token")
    from types import SimpleNamespace

    monkeypatch.setattr(poller, "consultar_solicitud",
                        lambda *a, **k: SimpleNamespace(package_ids=[], numero_cfdis=0))

    poller._descargar_lista(RFC_2, FielFake(), config_store.get_solicitud(RFC_2, "sol-2"))

    assert _resumen() == [("descarga_completada", {
        "canal": "web_service", "credencial": "efirma", "tipo": "metadata",
        "tamano": "0", "segundo_plano": True,
    })]


def test_apagado_ningun_endpoint_escribe(client, monkeypatch):
    monkeypatch.setenv("SAT_DM_SIN_USO", "1")
    client.post("/tareas", json={"titulo": "Algo"})
    client.post("/empresas/ciec", json={"rfc": RFC, "ciec": "x"})
    assert _eventos() == []

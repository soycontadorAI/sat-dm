"""Tests de /organizar, /renombrar y /deduplicar: rutas inválidas y errores.

Caso real: en un agente Linux, destino "C:/Users/..." es relativo y el mkdir
tronaba con "[400] [Errno 13] Permission denied: 'C:'" sin llegar a Sentry.
"""

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import server  # noqa: E402
from sat_descarga.api.routers import utilidades  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402

from tests.test_organizador import _create_cfdi  # noqa: E402


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.delenv("SAT_DM_MODO", raising=False)


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def capturas(monkeypatch):
    """Excepciones que se habrían mandado a Sentry."""
    from sat_descarga.core import telemetria

    vistas = []
    monkeypatch.setattr(telemetria, "capturar_excepcion", vistas.append)
    return vistas


def test_destino_estilo_windows_en_posix_es_400_legible(client, tmp_path):
    origen = tmp_path / "xmls"
    origen.mkdir()
    _create_cfdi(origen, "a.xml")
    r = client.post(
        "/organizar",
        json={"origen": str(origen), "destino": "C:/Users/x/Desktop/org"},
    )
    if r.status_code == 200:  # en Windows sí es absoluta
        pytest.skip("C:/ es absoluta en Windows")
    assert r.status_code == 400
    assert "carpeta de destino no es una ruta válida" in r.json()["detail"]
    assert "Errno" not in r.json()["detail"]


def test_origen_inexistente_es_400(client, tmp_path):
    r = client.post(
        "/organizar",
        json={"origen": str(tmp_path / "no-existe"), "destino": str(tmp_path)},
    )
    assert r.status_code == 400
    assert "No se encontró la carpeta de origen" in r.json()["detail"]


@pytest.mark.parametrize("ruta", ["/renombrar", "/deduplicar"])
def test_directorio_relativo_es_400(client, ruta):
    r = client.post(ruta, json={"directorio": "xmls"})
    assert r.status_code == 400
    assert "no es una ruta válida" in r.json()["detail"]


def test_organizar_feliz(client, tmp_path):
    origen = tmp_path / "xmls"
    origen.mkdir()
    _create_cfdi(origen, "a.xml")
    r = client.post(
        "/organizar",
        json={"origen": str(origen), "destino": str(tmp_path / "out"), "copiar": True},
    )
    assert r.status_code == 200
    assert r.json()["archivos_movidos"] == 1


def test_oserror_va_a_sentry_y_responde_legible(client, tmp_path, monkeypatch, capturas):
    origen = tmp_path / "xmls"
    origen.mkdir()
    _create_cfdi(origen, "a.xml")

    def falla(*a, **k):
        raise PermissionError(13, "Permission denied", "C:")

    monkeypatch.setattr("sat_descarga.utils.organizador.organizar", falla)
    r = client.post(
        "/organizar", json={"origen": str(origen), "destino": str(tmp_path / "out")}
    )
    assert r.status_code == 400
    assert r.json()["detail"].startswith("No se pudo organizar los archivos")
    assert len(capturas) == 1


def test_value_error_no_va_a_sentry(client, tmp_path, capturas):
    origen = tmp_path / "xmls"
    origen.mkdir()
    r = client.post(
        "/organizar",
        json={"origen": str(origen), "destino": str(tmp_path), "estructura": "nope"},
    )
    assert r.status_code == 400
    assert capturas == []


def test_hosted_rechaza_con_aviso_de_escritorio(client, tmp_path, monkeypatch):
    monkeypatch.setattr(utilidades, "es_modo_hosted", lambda: True)
    r = client.post("/deduplicar", json={"directorio": str(tmp_path)})
    assert r.status_code == 400
    assert "app de escritorio" in r.json()["detail"]

"""Continuidad de credenciales con el espacio en línea (pieza 2)."""

import base64

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sat_descarga.api import server  # noqa: E402
from sat_descarga.api import espacio_online  # noqa: E402
from sat_descarga.cli import config_store  # noqa: E402


@pytest.fixture(autouse=True)
def aislar(tmp_path, monkeypatch):
    monkeypatch.setattr(config_store, "CONFIG_DIR", tmp_path / ".sat-descarga")
    monkeypatch.setattr(config_store, "EFIRMA_DIR", tmp_path / "efirma")
    monkeypatch.setattr(
        config_store, "descargas_dir_default", lambda: str(tmp_path / "TodoConta")
    )


@pytest.fixture
def client():
    return TestClient(server.app)


class TestExportCredenciales:
    def test_en_desktop_no_existe(self, client):
        config_store.add_empresa_ciec("XAXX010101000", "X", "c")
        r = client.get("/empresas/XAXX010101000/credenciales")
        assert r.status_code == 404

    def test_en_hosted_exporta_ciec(self, client, monkeypatch):
        monkeypatch.setenv("SAT_DM_MODO", "hosted")
        config_store.add_empresa_ciec("XAXX010101000", "Prueba SA", "laciec123")
        r = client.get("/empresas/XAXX010101000/credenciales")
        assert r.status_code == 200
        data = r.json()
        assert data["ciec"] == "laciec123"
        assert data["fiel"] is None
        assert data["nombre"] == "Prueba SA"

    def test_en_hosted_rfc_inexistente_404(self, client, monkeypatch):
        monkeypatch.setenv("SAT_DM_MODO", "hosted")
        assert client.get("/empresas/NOEX010101AAA/credenciales").status_code == 404


class TestSincronizarCredenciales:
    def test_sin_ajuste_guardado_viene_apagado(self, monkeypatch):
        """Default apagado: sin `sync_credenciales` en settings no sale nada del equipo."""
        monkeypatch.setattr(config_store, "_load_settings", lambda: {})
        assert config_store.get_sync_credenciales() is False
        llamado = []
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: llamado.append(1)
        )
        assert espacio_online.sincronizar_credenciales() is None
        assert not llamado

    def test_apagado_no_hace_nada(self, monkeypatch):
        config_store.set_sync_credenciales(False)
        llamado = []
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: llamado.append(1)
        )
        assert espacio_online.sincronizar_credenciales() is None
        assert not llamado

    def test_pull_de_ciec_capturada_en_la_web(self, monkeypatch):
        """La web tiene una empresa con CIEC que aquí no existe → alta local."""
        config_store.set_sync_credenciales(True)
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: ("http://esp", "tok")
        )

        class _Resp:
            def __init__(self, data):
                self._data = data
                self.status_code = 200

            def json(self):
                return self._data

        def _get(url, **kwargs):
            if url.endswith("/empresas"):
                return _Resp({
                    "empresas": [
                        {"rfc": "WEB010101AAA", "nombre": "Capturada En Web",
                         "metodos": ["ciec"], "archived_at": None},
                    ]
                })
            if url.endswith("/empresas/WEB010101AAA/credenciales"):
                return _Resp({
                    "rfc": "WEB010101AAA", "nombre": "Capturada En Web",
                    "fiel": None, "ciec": "ciec-desde-web",
                })
            raise AssertionError(f"GET inesperado: {url}")

        monkeypatch.setattr(espacio_online.requests, "get", _get)

        resultado = espacio_online.sincronizar_credenciales()
        assert resultado == {"subidas": [], "bajadas": ["WEB010101AAA:ciec"]}

        e = config_store.get_empresa("WEB010101AAA")
        assert e["ciec"] == "ciec-desde-web"
        assert "ciec" in e["metodos"]

    def test_push_de_lo_que_falta_en_la_web(self, monkeypatch):
        """Local tiene CIEC que la web no conoce → se sube (sin re-conectar)."""
        config_store.set_sync_credenciales(True)
        config_store.add_empresa_ciec("LOC010101AAA", "Local", "laciec")
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: ("http://esp", "tok")
        )

        class _Resp:
            status_code = 200

            def json(self):
                return {"empresas": []}

        monkeypatch.setattr(espacio_online.requests, "get", lambda *a, **k: _Resp())

        subidas = []
        monkeypatch.setattr(
            espacio_online, "subir_credenciales",
            lambda rfc, metodos, conexion=None: subidas.append((rfc, metodos)),
        )
        resultado = espacio_online.sincronizar_credenciales()
        assert resultado["subidas"] == ["LOC010101AAA"]
        assert subidas == [("LOC010101AAA", ["ciec"])]


def test_export_no_incluye_paths_locales(client, monkeypatch):
    """El export expone credenciales, nunca rutas del filesystem del contenedor."""
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    config_store.add_empresa_ciec("XAXX010101000", "X", "c")
    data = client.get("/empresas/XAXX010101000/credenciales").json()
    assert "cer_path" not in data and "key_path" not in data

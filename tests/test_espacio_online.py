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
    monkeypatch.setattr(espacio_online, "_renovadas_aqui", set())
    monkeypatch.setattr(espacio_online, "_revisadas_web", {})


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

    def test_push_de_efirma_renovada_aqui(self, monkeypatch, test_cer, test_key,
                                          test_password, test_rfc):
        """Las dos tienen e.firma, pero la local vence después (se renovó en este
        equipo): la de la web quedó revocada y se reemplaza."""
        config_store.set_sync_credenciales(True)
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: ("http://esp", "tok")
        )

        class _Resp:
            status_code = 200

            def json(self):
                return {"empresas": [
                    {"rfc": test_rfc, "nombre": "Local", "metodos": ["fiel"],
                     "vencimiento": "2001-01-01", "archived_at": None},
                ]}

        monkeypatch.setattr(espacio_online.requests, "get", lambda *a, **k: _Resp())
        subidas = []
        monkeypatch.setattr(
            espacio_online, "subir_credenciales",
            lambda rfc, metodos, conexion=None: subidas.append((rfc, metodos)),
        )
        espacio_online.sincronizar_credenciales()
        assert subidas == [(test_rfc, ["fiel"])]

    def test_misma_efirma_en_los_dos_lados_no_viaja(self, monkeypatch, test_cer, test_key,
                                                    test_password, test_rfc):
        config_store.set_sync_credenciales(True)
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        venc = config_store.get_empresa(test_rfc)["vencimiento"]
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: ("http://esp", "tok")
        )

        class _Resp:
            status_code = 200

            def json(self):
                return {"empresas": [
                    {"rfc": test_rfc, "nombre": "Local", "metodos": ["fiel"],
                     "vencimiento": venc, "archived_at": None},
                ]}

        def _get(url, **kwargs):
            if url.endswith("/empresas"):
                return _Resp()
            raise AssertionError(f"GET inesperado: {url}")

        monkeypatch.setattr(espacio_online.requests, "get", _get)
        monkeypatch.setattr(
            espacio_online, "subir_credenciales",
            lambda *a, **k: pytest.fail("no debía subir nada"),
        )
        assert espacio_online.sincronizar_credenciales() == {"subidas": [], "bajadas": []}

    def test_pull_de_efirma_renovada_en_la_web(self, monkeypatch, tmp_path, test_cer,
                                               test_key, test_password, test_rfc):
        """La web trae una e.firma que vence después que la local: se baja, y la
        local (revocada) queda respaldada antes de reemplazarse."""
        config_store.set_sync_credenciales(True)
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        monkeypatch.setattr(
            espacio_online, "_conectar_espacio", lambda: ("http://esp", "tok")
        )

        class _Resp:
            def __init__(self, data):
                self._data = data
                self.status_code = 200

            def json(self):
                return self._data

        with open(test_cer, "rb") as c, open(test_key, "rb") as k:
            fiel_b64 = {
                "cer_b64": base64.b64encode(c.read()).decode(),
                "key_b64": base64.b64encode(k.read()).decode(),
                "password": test_password,
            }

        def _get(url, **kwargs):
            if url.endswith("/empresas"):
                return _Resp({"empresas": [
                    {"rfc": test_rfc, "nombre": "Local", "metodos": ["fiel"],
                     "vencimiento": "2099-12-31", "archived_at": None},
                ]})
            if url.endswith(f"/empresas/{test_rfc}/credenciales"):
                return _Resp({"rfc": test_rfc, "nombre": "Local",
                              "fiel": fiel_b64, "ciec": None})
            raise AssertionError(f"GET inesperado: {url}")

        monkeypatch.setattr(espacio_online.requests, "get", _get)
        monkeypatch.setattr(
            espacio_online, "subir_credenciales",
            lambda *a, **k: pytest.fail("la local es la vieja: no se sube"),
        )
        resultado = espacio_online.sincronizar_credenciales()
        assert resultado["bajadas"] == [f"{test_rfc}:fiel"]
        assert list((tmp_path / "efirma" / test_rfc).glob("anterior_*"))


class _Resp:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data


class TestRenovadaConSincronizacionApagada:
    """Con el ajuste apagado, una renovación solo cambia la e.firma revocada
    donde el usuario ya la tenía: nada nuevo sube ni baja."""

    @pytest.fixture(autouse=True)
    def apagada(self, monkeypatch):
        config_store.set_sync_credenciales(False)
        self.conexiones = []

        def conectar():
            self.conexiones.append(1)
            return ("http://esp", "tok")

        monkeypatch.setattr(espacio_online, "_conectar_espacio", conectar)
        self.subidas = []
        monkeypatch.setattr(
            espacio_online, "subir_credenciales",
            lambda rfc, metodos, conexion=None: self.subidas.append((rfc, metodos)),
        )

    def test_renovada_aqui_reemplaza_la_de_la_web(self, monkeypatch, test_cer, test_key,
                                                  test_password, test_rfc):
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        config_store.add_empresa_ciec(test_rfc, "Local", "ciec-solo-aqui")
        monkeypatch.setattr(espacio_online.requests, "get", lambda *a, **k: _Resp(
            {"empresas": [{"rfc": test_rfc, "nombre": "Local", "metodos": ["fiel"],
                           "vencimiento": "2001-01-01", "archived_at": None}]}
        ))
        espacio_online.marcar_renovada(test_rfc)

        resultado = espacio_online.sincronizar_credenciales()
        # Solo la e.firma: la CIEC nunca se subió y no se sube ahora.
        assert self.subidas == [(test_rfc, ["fiel"])]
        assert resultado == {"subidas": [test_rfc], "bajadas": []}
        # Ya reemplazada: la siguiente pasada ni se conecta.
        assert espacio_online.sincronizar_credenciales() is None
        assert len(self.conexiones) == 1

    def test_renovada_aqui_no_sube_si_la_web_no_la_tenia(self, monkeypatch, test_cer,
                                                        test_key, test_password, test_rfc):
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        monkeypatch.setattr(
            espacio_online.requests, "get", lambda *a, **k: _Resp({"empresas": []})
        )
        espacio_online.marcar_renovada(test_rfc)

        assert espacio_online.sincronizar_credenciales() == {"subidas": [], "bajadas": []}
        assert self.subidas == []
        assert espacio_online.sincronizar_credenciales() is None

    def test_renovada_aqui_que_no_se_pudo_subir_se_reintenta(
        self, monkeypatch, test_cer, test_key, test_password, test_rfc,
    ):
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        monkeypatch.setattr(espacio_online.requests, "get", lambda *a, **k: _Resp(
            {"empresas": [{"rfc": test_rfc, "metodos": ["fiel"],
                           "vencimiento": "2001-01-01", "archived_at": None}]}
        ))

        def falla(*a, **k):
            raise espacio_online.EspacioOnlineError("sin red")

        monkeypatch.setattr(espacio_online, "subir_credenciales", falla)
        espacio_online.marcar_renovada(test_rfc)
        espacio_online.sincronizar_credenciales()
        assert espacio_online._renovadas_aqui == {test_rfc}

    def test_renovada_en_la_web_reemplaza_la_de_aqui(self, monkeypatch, tmp_path, test_cer,
                                                     test_key, test_password, test_rfc):
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        # El catálogo trae, de la web, una e.firma que vence después.
        config_store.aplicar_sync_remoto([{
            "rfc": test_rfc, "nombre": "Local", "metodos": ["fiel"],
            "vencimiento": "2099-12-31", "updated_at": "2099-01-01T00:00:00+00:00",
        }])
        assert config_store.get_empresa(test_rfc)["vencimiento"] != "2099-12-31"

        with open(test_cer, "rb") as c, open(test_key, "rb") as k:
            fiel_b64 = {
                "cer_b64": base64.b64encode(c.read()).decode(),
                "key_b64": base64.b64encode(k.read()).decode(),
                "password": test_password,
            }

        def _get(url, **kwargs):
            if url.endswith("/empresas"):
                return _Resp({"empresas": [
                    {"rfc": test_rfc, "nombre": "Local", "metodos": ["fiel", "ciec"],
                     "vencimiento": "2099-12-31", "archived_at": None},
                    {"rfc": "WEB010101AAA", "metodos": ["ciec"], "archived_at": None},
                ]})
            if url.endswith(f"/empresas/{test_rfc}/credenciales"):
                return _Resp({"rfc": test_rfc, "nombre": "Local",
                              "fiel": fiel_b64, "ciec": "ciec-solo-en-la-web"})
            raise AssertionError(f"GET inesperado: {url}")

        monkeypatch.setattr(espacio_online.requests, "get", _get)
        resultado = espacio_online.sincronizar_credenciales()
        # Solo la e.firma: ni la CIEC ni la empresa que nada más está en la web.
        assert resultado == {"subidas": [], "bajadas": [f"{test_rfc}:fiel"]}
        assert not config_store.get_empresa(test_rfc).get("ciec")
        assert "WEB010101AAA" not in {e["rfc"] for e in config_store.list_empresas()}
        assert list((tmp_path / "efirma" / test_rfc).glob("anterior_*"))
        # Revisada: el poller no vuelve a conectarse por el mismo vencimiento.
        assert espacio_online.sincronizar_credenciales() is None
        assert len(self.conexiones) == 1

    def test_sin_renovacion_no_se_conecta(self, test_cer, test_key, test_password):
        config_store.add_empresa("Local", test_cer, test_key, test_password)
        assert espacio_online.sincronizar_credenciales() is None
        assert self.conexiones == []


def test_export_no_incluye_paths_locales(client, monkeypatch):
    """El export expone credenciales, nunca rutas del filesystem del contenedor."""
    monkeypatch.setenv("SAT_DM_MODO", "hosted")
    config_store.add_empresa_ciec("XAXX010101000", "X", "c")
    data = client.get("/empresas/XAXX010101000/credenciales").json()
    assert "cer_path" not in data and "key_path" not in data

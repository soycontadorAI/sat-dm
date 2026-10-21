"""Tests del scrubbing de PII de la telemetría (sat_descarga/core/telemetria.py).

Funciones puras: no tocan red ni requieren sentry-sdk ni DSN. Garantizan que NUNCA
salgan RFCs, rutas con nombre de usuario, ni claves sensibles hacia Sentry.
"""

from sat_descarga.core import telemetria


class TestRedactarTexto:
    def test_redacta_rfc_persona_fisica_y_moral(self):
        assert telemetria._redactar_texto("RFC XAXX010101000 aquí") == "RFC <RFC> aquí"
        assert telemetria._redactar_texto("emisor CAUI890921DAA") == "emisor <RFC>"
        assert "<RFC>" in telemetria._redactar_texto("Empresa ABC100101AB1 S.A.")

    def test_redacta_home_windows_mac_linux(self):
        assert telemetria._redactar_texto(r"C:\Users\Israel\efirma") == r"C:\Users\<usuario>\efirma"
        assert telemetria._redactar_texto("/Users/isca/.sat-descarga") == "/Users/<usuario>/.sat-descarga"
        assert telemetria._redactar_texto("/home/bob/x") == "/home/<usuario>/x"

    def test_texto_inofensivo_no_cambia(self):
        assert telemetria._redactar_texto("no hay nada sensible") == "no hay nada sensible"


class TestScrub:
    def test_elimina_claves_sensibles(self):
        limpio = telemetria._scrub({"password": "abc", "ciec": "123", "ok": "visible"})
        assert limpio["password"] == "<redactado>"
        assert limpio["ciec"] == "<redactado>"
        assert limpio["ok"] == "visible"

    def test_recursivo_en_dicts_y_listas(self):
        evento = {
            "extra": {"token": "secreto", "ruta": "/Users/isca/x"},
            "valores": ["RFC XAXX010101000", {"contrasena": "p"}],
        }
        limpio = telemetria._scrub(evento)
        assert limpio["extra"]["token"] == "<redactado>"
        assert limpio["extra"]["ruta"] == "/Users/<usuario>/x"
        assert limpio["valores"][0] == "RFC <RFC>"
        assert limpio["valores"][1]["contrasena"] == "<redactado>"


class TestBeforeSend:
    def test_before_send_scrubbea_y_no_revienta(self):
        evento = {"message": "falló con XAXX010101000", "extra": {"password": "x"}}
        out = telemetria._before_send(evento, {})
        assert out["message"] == "falló con <RFC>"
        assert out["extra"]["password"] == "<redactado>"

    def test_init_sentry_sin_dsn_es_noop(self, monkeypatch):
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        # Reinicia el flag por si otro test lo dejó activo.
        monkeypatch.setattr(telemetria, "_inicializado", False)
        assert telemetria.init_sentry() is False

    def test_capturar_excepcion_sin_init_es_noop(self, monkeypatch):
        monkeypatch.setattr(telemetria, "_inicializado", False)
        # No debe lanzar aunque sentry no esté inicializado.
        telemetria.capturar_excepcion(ValueError("x"))


class TestEntornoYRelease:
    def test_environment_hosted_en_version_web(self, monkeypatch):
        monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
        monkeypatch.setenv("SAT_DM_MODO", "hosted")
        assert telemetria._environment() == "hosted"

    def test_environment_production_en_desktop(self, monkeypatch):
        monkeypatch.delenv("SENTRY_ENVIRONMENT", raising=False)
        monkeypatch.delenv("SAT_DM_MODO", raising=False)
        assert telemetria._environment() == "production"

    def test_environment_explicito_gana(self, monkeypatch):
        monkeypatch.setenv("SENTRY_ENVIRONMENT", "development")
        monkeypatch.setenv("SAT_DM_MODO", "hosted")
        assert telemetria._environment() == "development"

    def test_release_explicito_gana(self, monkeypatch):
        monkeypatch.setenv("SENTRY_RELEASE", "9.9.9")
        assert telemetria._release() == "9.9.9"

    def test_release_cae_a_version_del_paquete(self, monkeypatch):
        from importlib.metadata import version

        monkeypatch.delenv("SENTRY_RELEASE", raising=False)
        assert telemetria._release() == version("sat-descarga-masiva")

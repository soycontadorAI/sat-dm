"""Tests del login e.firma del portal (sin red ni browser).

- `_llave_para_portal`: el JS de login del SAT solo descifra .key PKCS#8 con 3DES;
  una .key AES-256 (caso real: la renovación de la primera versión de Certifica)
  debe entrar al portal como copia temporal en 3DES, sin tocar el archivo.
- `iniciar_sesion_fiel`: si el form muestra el error de la e.firma, se avisa de
  inmediato en vez de esperar los 3 min del timeout.
"""

import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sat_descarga.certifica.generador import cifrar_pkcs8_3des
from sat_descarga.core.errores import ErrorEsperado
from sat_descarga.portal import login
from sat_descarga.portal.login import (
    CredencialFIELInvalida,
    _OID_3DES_DER,
    _llave_para_portal,
    _texto_error_efirma,
)

PWD = "clave-de-prueba"


@pytest.fixture(scope="module")
def llave():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _key_aes(llave, path):
    path.write_bytes(llave.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(PWD.encode()),
    ))
    return str(path)


def _mismo_numero(a, b):
    return a.private_numbers() == b.private_numbers()


# --- _llave_para_portal ----------------------------------------------------

def test_llave_3des_se_usa_tal_cual(llave, tmp_path):
    path = tmp_path / "fiel.key"
    path.write_bytes(cifrar_pkcs8_3des(llave, PWD))
    with _llave_para_portal(str(path), PWD) as ruta:
        assert ruta == str(path)


def test_llave_aes_se_convierte_a_copia_temporal_3des(llave, tmp_path):
    path = tmp_path / "fiel.key"
    original = _key_aes(llave, path)
    bytes_antes = path.read_bytes()
    assert _OID_3DES_DER not in bytes_antes

    with _llave_para_portal(original, PWD) as ruta:
        assert ruta != original
        raw = open(ruta, "rb").read()
        assert _OID_3DES_DER in raw[:128]
        # Misma llave, misma contraseña.
        cargada = serialization.load_der_private_key(raw, PWD.encode())
        assert _mismo_numero(cargada, llave)

    assert not os.path.exists(ruta)              # la copia se borra al salir
    assert path.read_bytes() == bytes_antes      # el archivo del usuario no se toca


def test_llave_aes_con_contrasena_mala_usa_la_original(llave, tmp_path):
    original = _key_aes(llave, tmp_path / "fiel.key")
    with _llave_para_portal(original, "otra") as ruta:
        assert ruta == original


def test_copia_temporal_se_borra_aunque_truene_el_login(llave, tmp_path):
    original = _key_aes(llave, tmp_path / "fiel.key")
    with pytest.raises(RuntimeError):
        with _llave_para_portal(original, PWD) as ruta:
            raise RuntimeError("el login reventó")
    assert not os.path.exists(ruta)


# --- _texto_error_efirma ---------------------------------------------------

class _El:
    def __init__(self, texto, visible=True):
        self.texto, self.visible = texto, visible

    def is_visible(self):
        return self.visible

    def inner_text(self):
        return self.texto


class _PageError:
    def __init__(self, el=None, lanza=False):
        self.el, self.lanza = el, lanza
        self.url = "https://login.siat.sat.gob.mx/nidp/idff/sso?id=fiel_Aviso"

    def query_selector(self, sel):
        if self.lanza:
            raise RuntimeError("Execution context was destroyed")
        return self.el


MSG_SAT = ("Certificado, clave privada o contraseña de clave privada inválidos, "
           "inténtelo nuevamente.")


def test_texto_error_efirma_visible():
    assert _texto_error_efirma(_PageError(_El(f"  {MSG_SAT}\n"))) == MSG_SAT


@pytest.mark.parametrize("page", [
    _PageError(None),
    _PageError(_El(MSG_SAT, visible=False)),
    _PageError(lanza=True),
])
def test_texto_error_efirma_sin_mensaje(page):
    assert _texto_error_efirma(page) == ""


# --- iniciar_sesion_fiel: fail-fast con el error del form -------------------

class _PageLogin(_PageError):
    """No aterriza nunca; `wait_for_url` agota su timeout como Playwright."""

    def __init__(self, el=None):
        super().__init__(el)
        self.esperas = 0

    def wait_for_load_state(self, *a, **k):
        pass

    def wait_for_url(self, exito, timeout):
        from playwright.sync_api import TimeoutError as PWTimeout
        self.esperas += 1
        raise PWTimeout("timeout")


@pytest.fixture
def sin_portal(monkeypatch):
    monkeypatch.setattr(login.demo, "aplica_archivos_fiel", lambda *a: None)
    monkeypatch.setattr(login, "_abrir_entrada", lambda page, url: None)
    monkeypatch.setattr(login, "_login_efirma", lambda page, cer, key, pwd: None)


def test_fiel_rechazada_avisa_de_inmediato(sin_portal, tmp_path):
    page = _PageLogin(_El(MSG_SAT))
    with pytest.raises(CredencialFIELInvalida, match="inválidos") as exc:
        login.iniciar_sesion_fiel(page, "a.cer", str(tmp_path / "x.key"), PWD,
                                  url_entrada="https://sat", exito=lambda u: False)
    assert isinstance(exc.value, ErrorEsperado)
    assert page.esperas == 1  # no esperó el timeout completo


def test_fiel_sin_error_respeta_el_timeout(sin_portal, tmp_path, monkeypatch):
    monkeypatch.setattr(login, "ESPERA_ERROR_FIEL_MS", 1)
    page = _PageLogin(None)
    with pytest.raises(RuntimeError, match="Login e.firma no completado"):
        login.iniciar_sesion_fiel(page, "a.cer", str(tmp_path / "x.key"), PWD,
                                  url_entrada="https://sat", exito=lambda u: False,
                                  timeout_ms=0)

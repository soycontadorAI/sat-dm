"""Recuperación pública de certificados del SAT (portal/recuperacion_publica.py).

Sin red: la sesión HTTP se sustituye por una falsa que imita el formulario JSF
(ViewState + captcha) y la página de resultados.
"""

from pathlib import Path

import pytest

from sat_descarga.core.errores import ErrorEsperado
from sat_descarga.portal import recuperacion_publica as rp

_FORM = """
<form id="consultaCertificados" name="consultaCertificados" method="post"
 action="/RecuperacionDeCertificados/faces/consultaCertificados.xhtml;jsessionid=ABC">
<img src="/RecuperacionDeCertificados/faces/myFacesExtensionResource/org.apache.myfaces.custom.captcha.CAPTCHARenderer/1/;jsessionid=ABC?captchaSessionKeyName=mySessionKeyName&amp;dummyParameter=1" />
<input type="hidden" name="javax.faces.ViewState" id="javax.faces.ViewState" value="-1:2" autocomplete="off" />
</form>
"""

_RESULTADOS = _FORM + """
<table><tr><td>00001000000500000001</td><td>Revocado</td></tr>
<tr><td><a href="https://rdc.sat.gob.mx/rccf/000010/000007/26/39/14/00001000000726391403.cer">00001000000726391403</a></td><td>Activo</td></tr></table>
"""


class _Resp:
    def __init__(self, text="", content=b"", status_code=200):
        self.text = text
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise rp.requests.HTTPError(str(self.status_code))


class _SesionFalsa:
    """GET de la página/captcha y POST que acepta solo `captcha_ok`."""

    def __init__(self, captcha_ok="aBc12"):
        self.captcha_ok = captcha_ok
        self.posts = []

    def get(self, url, timeout=None):
        if "CAPTCHARenderer" in url:
            return _Resp(content=b"\xff\xd8JPEG")
        return _Resp(text=_FORM)

    def post(self, url, data=None, timeout=None):
        self.posts.append(data)
        ok = data["consultaCertificados:verCaptchaRFC"] == self.captcha_ok
        return _Resp(text=_RESULTADOS if ok else _FORM)


@pytest.fixture
def sesion(monkeypatch):
    s = _SesionFalsa()
    monkeypatch.setattr(rp, "_sesion", lambda: s)
    return s


def test_url_cer_por_numero_de_serie():
    assert rp.url_cer("00001000000726391403") == (
        "https://rdc.sat.gob.mx/rccf/000010/000007/26/39/14/00001000000726391403.cer"
    )


def test_series_en_resultados_sin_repetir_y_de_mayor_a_menor():
    assert rp.series_en(_RESULTADOS) == ["00001000000726391403", "00001000000500000001"]
    # El ViewState y los parámetros del captcha no son números de serie.
    assert rp.series_en(_FORM) == []


def test_buscar_series_reintenta_captcha_y_respeta_mayusculas(sesion):
    respuestas = iter(["ABC12", "aBc12"])   # el primero falla: distingue mayúsculas
    pedidos = []

    def pedir(imagen, intento, max_intentos):
        pedidos.append((imagen, intento, max_intentos))
        return next(respuestas)

    series = rp.buscar_series("XAXX010101000", pedir)
    assert series[0] == "00001000000726391403"
    assert [p[1] for p in pedidos] == [1, 2]
    assert sesion.posts[-1]["consultaCertificados:entradaRFC"] == "XAXX010101000"
    assert sesion.posts[-1]["consultaCertificados:todos"] == "todos"
    assert sesion.posts[-1]["javax.faces.ViewState"] == "-1:2"


def test_buscar_series_cancelado(sesion):
    with pytest.raises(RuntimeError, match="(?i)cancel"):
        rp.buscar_series("XAXX010101000", lambda *a: None)


def test_buscar_series_captcha_fallido_tres_veces(sesion):
    with pytest.raises(ErrorEsperado, match="captcha"):
        rp.buscar_series("XAXX010101000", lambda *a: "mal")


def test_recuperar_cert_emparejado_elige_el_que_empareja(
    sesion, monkeypatch, tmp_path, test_cer, test_key, test_password,
):
    cer_bueno = Path(test_cer).read_bytes()
    bajados = []

    def bajar(serie):
        bajados.append(serie)
        # El más reciente es el nuestro; el viejo sería de otra llave.
        return cer_bueno if serie == "00001000000726391403" else b"\x30otro"

    monkeypatch.setattr(rp, "bajar_cer", bajar)
    fases = []
    dest = rp.recuperar_cert_emparejado(
        "XAXX010101000", test_key, test_password, lambda *a: "aBc12", str(tmp_path),
        on_progreso=lambda f, d: fases.append(f),
    )
    assert dest == tmp_path / "00001000000726391403.cer"
    assert dest.read_bytes() == cer_bueno
    assert bajados == ["00001000000726391403"]
    assert fases[:2] == ["consultando", "recuperando"] and "cer" in fases


def test_recuperar_cert_emparejado_sin_cert_nuevo_devuelve_none(
    sesion, monkeypatch, tmp_path, test_key, test_password,
):
    monkeypatch.setattr(rp, "bajar_cer", lambda serie: b"\x30otro")
    assert rp.recuperar_cert_emparejado(
        "XAXX010101000", test_key, test_password, lambda *a: "aBc12", str(tmp_path),
    ) is None

"""
Recuperación PÚBLICA de certificados del SAT: sin iniciar sesión, con captcha.

Para qué: al emitir la e.firma renovada, el SAT revoca la anterior, así que esa
ya no sirve para entrar a CertiSAT a bajar la nueva. Este servicio público
(`portalsat.plataforma.sat.gob.mx/RecuperacionDeCertificados`) busca los
certificados de un RFC sin login; el `.cer` se baja del repositorio público
`rdc.sat.gob.mx` por su número de serie y solo se acepta si empareja con la
`.key` nueva que generamos (criptográfico: nunca se instala un cert ajeno).

Es un formulario JSF simple, así que va con requests (sin navegador):
- El servidor negocia DH de 1024 bits y OpenSSL 3 lo rechaza en su nivel de
  seguridad por default (`DH_KEY_TOO_SMALL`): contexto TLS con `@SECLEVEL=1`
  solo para esta consulta. (Chromium headless recibe un "Service unavailable"
  del gateway.)
- El captcha distingue mayúsculas y minúsculas. Uno mal tecleado regresa el
  formulario con `consultaCertificados:mensajeerrorCaptcha` ("Código incorrecto").
- La respuesta buena es una tabla, una fila por certificado: número de serie
  (liga al `.cer`), estado (Activo/Revocado/Caduco), tipo (FIEL o SELLO) y
  fechas. Validado contra el SAT real el 2026-10-21.
"""

import html
import logging
import re
import ssl
from pathlib import Path
from typing import Callable, Optional

import requests
import urllib3
from requests.adapters import HTTPAdapter

from ..core.errores import ErrorEsperado
from .csd import _mismo_par

logger = logging.getLogger(__name__)

_BASE = "https://portalsat.plataforma.sat.gob.mx"
CONSULTA_URL = f"{_BASE}/RecuperacionDeCertificados/faces/consultaCertificados.xhtml"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_TIMEOUT = 30

# Números de serie de certificados del SAT: 20 dígitos que empiezan con 0000.
_RE_SERIE = re.compile(r"(?<!\d)(0000\d{16})(?!\d)")

_RE_FILA = re.compile(r"<tr\b.*?</tr>", re.S)
_RE_CELDA = re.compile(r"<td\b.*?</td>", re.S)

# Pedir captcha: (imagen, intento, max) → texto, o None para cancelar.
PedirCaptcha = Callable[[bytes, int, int], Optional[str]]


class _TLSHeredado(HTTPAdapter):
    """TLS 1.2+ sin verificar (cert del SAT) y con DH de 1024 bits permitido."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


def _sesion() -> requests.Session:
    urllib3.disable_warnings()
    s = requests.Session()
    s.verify = False
    s.mount("https://", _TLSHeredado())
    s.headers["User-Agent"] = _UA
    return s


def url_cer(serie: str) -> str:
    """URL pública del `.cer` en rdc.sat.gob.mx a partir de su número de serie."""
    return (
        f"https://rdc.sat.gob.mx/rccf/{serie[0:6]}/{serie[6:12]}/"
        f"{serie[12:14]}/{serie[14:16]}/{serie[16:18]}/{serie}.cer"
    )


def bajar_cer(serie: str) -> Optional[bytes]:
    """Descarga el `.cer` (DER) de un número de serie, o None si no existe."""
    try:
        r = _sesion().get(url_cer(serie), timeout=_TIMEOUT)
    except requests.RequestException as e:
        logger.info("[recuperacion] no se pudo bajar %s: %s", serie, e)
        return None
    if r.status_code == 200 and r.content[:1] == b"\x30":  # DER SEQUENCE
        return r.content
    return None


def _formulario(texto: str) -> tuple[str, str, str]:
    """(action, ViewState, src del captcha) del formulario de consulta."""
    action = re.search(r'<form id="consultaCertificados"[^>]*action="([^"]+)"', texto)
    vs = re.search(r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', texto)
    cap = re.search(r'<img src="([^"]*CAPTCHARenderer[^"]*)"', texto)
    if not (action and vs and cap):
        raise ErrorEsperado(
            "La Recuperación de certificados del SAT no respondió como esperábamos. "
            "Intenta de nuevo en unos minutos."
        )
    return html.unescape(action.group(1)), vs.group(1), html.unescape(cap.group(1))


def series_en(texto: str) -> list[str]:
    """Números de serie que aparecen en la página de resultados, sin repetir,
    de mayor a menor (en la práctica, del más reciente al más viejo; de todos
    modos se revisan varios candidatos)."""
    return sorted(set(_RE_SERIE.findall(texto)), reverse=True)


def tipos_en(texto: str) -> dict[str, str]:
    """{número de serie: tipo} de las filas de resultados (FIEL o SELLO)."""
    tipos = {}
    for fila in _RE_FILA.findall(texto):
        serie = _RE_SERIE.search(fila)
        celdas = [
            html.unescape(re.sub(r"<[^>]+>", "", c)).strip()
            for c in _RE_CELDA.findall(fila)
        ]
        if serie and len(celdas) >= 3:
            tipos[serie.group(1)] = celdas[2].upper()
    return tipos


def _captcha_rechazado(texto: str) -> bool:
    return "mensajeerrorCaptcha" in texto or "digo incorrecto" in texto


def buscar_series(
    rfc: str, pedir_captcha: PedirCaptcha, max_intentos: int = 3,
    tipo: Optional[str] = None,
) -> list[str]:
    """
    Consulta «Todos los certificados expedidos» del RFC y devuelve sus números
    de serie (más recientes primero); con `tipo` ("FIEL" o "SELLO"), solo los
    de ese tipo. El captcha lo resuelve una persona vía `pedir_captcha`; uno
    mal tecleado se reintenta con uno nuevo. Sin certificados devuelve [].

    Lanza RuntimeError("Captcha cancelado…") si el usuario cancela (el job lo
    reporta como cancelado) y ErrorEsperado si el servicio no responde.
    """
    s = _sesion()
    try:
        pagina = s.get(CONSULTA_URL, timeout=_TIMEOUT)
        pagina.raise_for_status()
    except requests.RequestException as e:
        raise ErrorEsperado(
            "No pudimos abrir la Recuperación de certificados del SAT. "
            "Intenta de nuevo en unos minutos."
        ) from e
    texto = pagina.text

    for intento in range(1, max_intentos + 1):
        action, viewstate, src_captcha = _formulario(texto)
        imagen = s.get(_BASE + src_captcha, timeout=_TIMEOUT).content
        solucion = pedir_captcha(imagen, intento, max_intentos)
        if not solucion:
            raise RuntimeError("Captcha cancelado por el usuario.")
        try:
            r = s.post(_BASE + action, timeout=60, data={
                "consultaCertificados": "consultaCertificados",
                "consultaCertificados:entradaRFC": rfc,
                "consultaCertificados:todos": "todos",
                "consultaCertificados:numeroDeSerie": "",
                "consultaCertificados:verCaptchaRFC": solucion,
                "consultaCertificados:botonRFC": "Buscar",
                "javax.faces.ViewState": viewstate,
            })
            r.raise_for_status()
        except requests.RequestException as e:
            raise ErrorEsperado(
                "La Recuperación de certificados del SAT no respondió. "
                "Intenta de nuevo en unos minutos."
            ) from e
        if _captcha_rechazado(r.text):
            logger.info("[recuperacion] captcha rechazado (intento %d/%d)", intento, max_intentos)
            texto = r.text
            continue
        series = series_en(r.text)
        tipos = tipos_en(r.text)
        # Si la tabla cambiara de forma y no se leyeran los tipos, van todos:
        # el emparejamiento con la llave descarta los que no son.
        if tipo and tipos:
            series = [s for s in series if tipos.get(s) == tipo]
        return series
    raise ErrorEsperado(
        "El captcha no coincidió. Vuelve a intentarlo: distingue mayúsculas y minúsculas."
    )


def recuperar_cert_emparejado(
    rfc: str,
    key_nueva_path: str,
    password: str,
    pedir_captcha: PedirCaptcha,
    directorio_salida: str,
    on_progreso: Optional[Callable[[str, dict], None]] = None,
    max_candidatos: int = 15,
) -> Optional[Path]:
    """
    Busca entre los certificados públicos del RFC el que empareja con
    `key_nueva_path` y lo guarda como `{serie}.cer` en `directorio_salida`.
    Devuelve la ruta, o None si el SAT todavía no lo publica.
    """
    def emitir(fase: str, **data):
        if on_progreso:
            on_progreso(fase, data)

    key_bytes = Path(key_nueva_path).read_bytes()
    emitir("consultando")
    series = buscar_series(rfc, pedir_captcha, tipo="FIEL")
    logger.info("[recuperacion] %s: %d certificados públicos", rfc, len(series))

    emitir("recuperando", candidatos=min(len(series), max_candidatos))
    for serie in series[:max_candidatos]:
        cer = bajar_cer(serie)
        if cer and _mismo_par(cer, key_bytes, password):
            emitir("cer", serie=serie)
            out = Path(directorio_salida)
            out.mkdir(parents=True, exist_ok=True)
            dest = out / f"{serie}.cer"
            dest.write_bytes(cer)
            logger.info("[recuperacion] ✓ certificado %s empareja con la llave nueva", serie)
            return dest
    return None

"""
Modo de grabación: empresas de demo que nunca tocan al SAT.

Sirve para grabar los tutoriales en la app real con RFC ficticios (el SAT no
responde a esos RFC). Con `SAT_DM_MODO_GRABACION=1` en el entorno del agente,
toda operación contra el SAT de una empresa cuyo RFC está en el set de demo
(`escenario.EMPRESAS`) se responde con datos de ejemplo generados aquí:

- Web Service: la solicitud queda "En proceso" y se resuelve sola tras
  `SAT_DM_GRABACION_ESPERA` segundos (default 20) con un paquete de XML.
- Descarga rápida (portal): captcha dentro de la app (Contraseña) y avance
  XML por XML.
- Constancia y Opinión 32-D: PDF de ejemplo (marcados "Documento de ejemplo")
  que el parser de la app lee igual que los reales.
- Estatus (Validar contra SAT) y listas negras 69/69-B.

Las empresas reales siguen su camino normal en la misma sesión: el desvío se
decide por RFC en cada función que habla con el SAT, nunca por sesión. Con el
modo apagado (default) nada cambia.

Este módulo se importa desde los módulos que hablan con el SAT, así que debe
quedarse LIGERO: solo stdlib y `escenario` (datos puros). Lo pesado (generador
de XML, PDF, simulador) se importa adentro de las funciones.
"""

from __future__ import annotations

import logging
import os

from .escenario import CIEC_DEMO, RFCS_DEMO

logger = logging.getLogger("sat_descarga.demo")

ENV_MODO = "SAT_DM_MODO_GRABACION"
ENV_ESPERA = "SAT_DM_GRABACION_ESPERA"
ENV_RITMO = "SAT_DM_GRABACION_RITMO"

ESPERA_WS_DEFAULT = 20.0

_VERDADERO = {"1", "true", "si", "sí", "yes", "on"}


def activo() -> bool:
    """¿Está prendido el modo de grabación? Se lee del entorno en cada llamada
    (nunca se cachea), así que solo existe si quien arranca el agente lo pide."""
    return os.environ.get(ENV_MODO, "").strip().lower() in _VERDADERO


def es_demo(rfc: object) -> bool:
    """¿El RFC es de una de las empresas de demo? (independiente del modo)."""
    if not isinstance(rfc, str):
        return False
    return rfc.strip().upper() in RFCS_DEMO


def aplica(rfc: object) -> bool:
    """True si esta operación debe responderse con datos de ejemplo:
    modo prendido Y RFC de demo. Es la única pregunta que hacen los módulos
    que hablan con el SAT."""
    return activo() and es_demo(rfc)


def es_ciec_de_ejemplo(rfc: object, ciec: object) -> bool:
    """¿Es la Contraseña de ejemplo que deja la siembra? Con el modo apagado no
    debe llegar al portal: el RFC de demo podría existir y el SAT bloquea la
    contraseña de un tercero tras varios intentos fallidos."""
    return es_demo(rfc) and ciec == CIEC_DEMO


def rfc_de_fiel(fiel) -> str:
    """RFC de una FIEL sin lanzar (las FIEL a medias o mocks devuelven "")."""
    try:
        return str(getattr(fiel, "rfc", "") or "")
    except Exception:  # noqa: BLE001 - un cert ilegible no es asunto del modo
        return ""


def aplica_fiel(fiel) -> bool:
    return activo() and es_demo(rfc_de_fiel(fiel))


def aplica_archivos_fiel(cer_path: str, key_path: str, password: str) -> str:
    """Para las funciones del portal que reciben rutas en vez de FIEL: devuelve
    el RFC si aplica el modo, o "" si no (sin abrir nada con el modo apagado)."""
    if not activo():
        return ""
    try:
        from ..core.fiel import FIEL

        rfc = FIEL(cer_path, key_path, password).rfc
    except Exception:  # noqa: BLE001
        return ""
    return rfc if es_demo(rfc) else ""


def espera_ws() -> float:
    """Segundos que tarda una solicitud del Web Service de demo en quedar lista."""
    try:
        return max(0.0, float(os.environ.get(ENV_ESPERA, ESPERA_WS_DEFAULT)))
    except ValueError:
        return ESPERA_WS_DEFAULT


def ritmo() -> float:
    """Multiplicador de las pausas cortas (login, avance de XML, validación).
    1 = ritmo natural para cámara; 0 = instantáneo (pruebas)."""
    try:
        return max(0.0, float(os.environ.get(ENV_RITMO, "1")))
    except ValueError:
        return 1.0


def anunciar() -> None:
    """Línea en el log al arrancar el agente. Es la marca para quien opera:
    no hay banner en pantalla porque saldría en la grabación."""
    if not activo():
        return
    logger.warning(
        "[modo-grabacion] ACTIVO (%s=1): %d empresas de demo responden con datos "
        "de ejemplo y nunca tocan al SAT; el Web Service de demo tarda %.0f s. "
        "Las empresas reales siguen igual.",
        ENV_MODO, len(RFCS_DEMO), espera_ws(),
    )

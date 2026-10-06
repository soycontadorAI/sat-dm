"""
Validación de estatus de CFDI ante el SAT.

Consulta el endpoint público del SAT para verificar si un CFDI está
Vigente, Cancelado o No Encontrado. NO requiere FIEL — es un servicio
público accesible para cualquiera con los datos del comprobante.

Endpoint: https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc
SOAPAction: http://tempuri.org/IConsultaCFDIService/Consulta

Referencia: port de la implementación TS en todoconta-apps
(apps/web/src/lib/sat/verify-cfdi.ts)
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Optional

from .. import demo
from ..core.http_client import _build_session, make_request

logger = logging.getLogger(__name__)

_SAT_URL = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"
_SOAP_ACTION = "http://tempuri.org/IConsultaCFDIService/Consulta"

# Regex para extraer campos de la respuesta SOAP
_RE_ESTADO = re.compile(r"<a:Estado>([^<]+)</a:Estado>")
_RE_CANCELABLE = re.compile(r"<a:EsCancelable>([^<]+)</a:EsCancelable>")
_RE_ESTATUS_CANCELACION = re.compile(
    r"<a:EstatusCancelacion>([^<]*)</a:EstatusCancelacion>"
)
_RE_VALIDACION_EFOS = re.compile(
    r"<a:ValidacionEFOS>([^<]*)</a:ValidacionEFOS>"
)


@dataclass
class EstadoCFDI:
    """Resultado de la validación de un CFDI ante el SAT."""
    uuid: str
    estado: str                        # "Vigente", "Cancelado", "No Encontrado"
    es_cancelable: Optional[str] = None
    estatus_cancelacion: Optional[str] = None
    validacion_efos: Optional[str] = None
    error: Optional[str] = None


def _build_soap_envelope(
    uuid: str,
    emisor_rfc: str,
    receptor_rfc: str,
    total: float,
) -> bytes:
    """Construye el envelope SOAP para la consulta de estatus."""
    total_fmt = f"{total:.6f}"
    expresion = (
        f"?re={emisor_rfc}"
        f"&amp;rr={receptor_rfc}"
        f"&amp;tt={total_fmt}"
        f"&amp;id={uuid}"
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        "<soap:Body>"
        '<Consulta xmlns="http://tempuri.org/">'
        f"<expresionImpresa>{expresion}</expresionImpresa>"
        "</Consulta>"
        "</soap:Body>"
        "</soap:Envelope>"
    )
    return xml.encode("utf-8")


def _parse_response(resp_xml: bytes) -> dict:
    """Parsea la respuesta SOAP del SAT y extrae los campos relevantes."""
    text = resp_xml.decode("utf-8", errors="replace")

    estado_match = _RE_ESTADO.search(text)
    cancelable_match = _RE_CANCELABLE.search(text)
    estatus_match = _RE_ESTATUS_CANCELACION.search(text)
    efos_match = _RE_VALIDACION_EFOS.search(text)

    raw_estado = estado_match.group(1).strip() if estado_match else ""

    if raw_estado == "Vigente":
        estado = "Vigente"
    elif raw_estado == "Cancelado":
        estado = "Cancelado"
    else:
        estado = "No Encontrado"

    return {
        "estado": estado,
        "es_cancelable": cancelable_match.group(1).strip() if cancelable_match else None,
        "estatus_cancelacion": estatus_match.group(1).strip() if estatus_match else None,
        "validacion_efos": efos_match.group(1).strip() if efos_match else None,
    }


def validar_cfdi(
    uuid: str,
    emisor_rfc: str,
    receptor_rfc: str,
    total: float,
    session=None,
) -> EstadoCFDI:
    """
    Valida el estatus de un CFDI ante el SAT.

    No requiere FIEL — es un endpoint público. Usa el mismo http_client
    con TLS/retry que el resto del proyecto.

    Args:
        uuid: UUID del CFDI (TimbreFiscalDigital).
        emisor_rfc: RFC del emisor.
        receptor_rfc: RFC del receptor.
        total: Total del comprobante.
        session: Sesión HTTP reutilizable (opcional).

    Returns:
        EstadoCFDI con el resultado.
    """
    # Modo de grabación: un CFDI de una empresa de demo (como emisora o
    # receptora) nunca va al SAT; los demás de la misma tanda sí.
    if demo.aplica(emisor_rfc) or demo.aplica(receptor_rfc):
        from ..demo import sat as sat_demo
        return sat_demo.estatus(uuid, emisor_rfc, receptor_rfc, total)

    body = _build_soap_envelope(uuid, emisor_rfc, receptor_rfc, total)
    headers = {
        "Content-Type": "text/xml;charset=UTF-8",
        "SOAPAction": f'"{_SOAP_ACTION}"',
    }

    try:
        resp_xml = make_request(
            url=_SAT_URL,
            body=body,
            headers=headers,
            operation=f"ValidarCFDI({uuid[:8]})",
            session=session,
        )
        result = _parse_response(resp_xml)
        return EstadoCFDI(
            uuid=uuid,
            estado=result["estado"],
            es_cancelable=result["es_cancelable"],
            estatus_cancelacion=result["estatus_cancelacion"],
            validacion_efos=result["validacion_efos"],
        )
    except Exception as e:
        logger.warning("Error validando CFDI %s: %s", uuid[:8], e)
        return EstadoCFDI(uuid=uuid, estado="Error", error=str(e))


def validar_masivo(
    cfdis: List[dict],
    concurrency: int = 10,
) -> List[EstadoCFDI]:
    """
    Valida múltiples CFDIs en paralelo usando ThreadPoolExecutor.

    Más rápido que la versión TS de todoconta-apps (concurrency 5 allá,
    10 aquí por default — Python server-side puede ser más agresivo).

    Args:
        cfdis: Lista de dicts con keys: uuid, emisor_rfc, receptor_rfc, total.
        concurrency: Número de hilos paralelos (default 10).

    Returns:
        Lista de EstadoCFDI en el mismo orden que la entrada.
    """
    if not cfdis:
        return []

    # Una sesión compartida para reutilizar conexiones
    session = _build_session()
    results: dict[int, EstadoCFDI] = {}

    def _validate(idx: int, cfdi: dict) -> tuple[int, EstadoCFDI]:
        resultado = validar_cfdi(
            uuid=cfdi["uuid"],
            emisor_rfc=cfdi["emisor_rfc"],
            receptor_rfc=cfdi["receptor_rfc"],
            total=cfdi["total"],
            session=session,
        )
        return idx, resultado

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_validate, i, cfdi): i
            for i, cfdi in enumerate(cfdis)
        }
        for future in as_completed(futures):
            idx, resultado = future.result()
            results[idx] = resultado

    return [results[i] for i in range(len(cfdis))]

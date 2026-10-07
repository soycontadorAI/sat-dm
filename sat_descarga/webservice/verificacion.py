"""
VerificaSolicitudDescarga: consulta el estado de una solicitud.

API v1.5: mismo patrón que SolicitaDescarga:
- Namespace: http://DescargaMasivaTerceros.sat.gob.mx
- Token WRAP en HTTP header "Authorization: WRAP access_token=..."
- Firma xmldsig enveloped en el cuerpo (elemento VerificaSolicitudDescarga firmado)
- Polling con backoff exponencial hasta estado 3 (terminada)
"""

import time
import hashlib
import base64
import logging
from dataclasses import dataclass
from io import BytesIO
from typing import List
from lxml import etree

from ..core.config import (
    ENDPOINTS, SOAP_ACTIONS,
    POLL_INTERVAL_INITIAL, POLL_INTERVAL_MAX,
    POLL_BACKOFF_FACTOR, POLL_MAX_ATTEMPTS,
)
from .. import demo
from ..core.fiel import FIEL
from ..core.http_client import make_request
from ..core.xml_seguro import parser_seguro
from . import auth as _auth

logger = logging.getLogger(__name__)

_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_DES_NS = "http://DescargaMasivaTerceros.sat.gob.mx"
_XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"

# Estados de la solicitud según el SAT
ESTADO_ACEPTADA = "1"       # En cola
ESTADO_EN_PROCESO = "2"     # Procesando
ESTADO_TERMINADA = "3"      # Lista para descargar
ESTADO_ERROR = "4"          # Error en el servidor del SAT
ESTADO_RECHAZADA = "5"      # Límites excedidos u otro rechazo
ESTADO_VENCIDA = "6"        # La solicitud/paquetes expiraron sin descargarse


@dataclass
class EstadoSolicitud:
    cod_estado: str           # CodEstado: 1-5
    cod_estatus: str          # CodEstatus HTTP-like
    mensaje: str
    numero_cfdis: int
    package_ids: List[str]
    terminada: bool


def verificar_solicitud(
    token: str,
    rfc_solicitante: str,
    id_solicitud: str,
    fiel: FIEL = None,
    poll: bool = True,
) -> EstadoSolicitud:
    """
    Consulta el estado de una solicitud de descarga.

    Args:
        token: Token WRAP obtenido con auth.obtener_token() (URL-encoded).
        rfc_solicitante: RFC del solicitante.
        id_solicitud: RequestID obtenido de SolicitaDescarga.
        fiel: Instancia de FIEL para firmar la solicitud (requerida en v1.5).
        poll: Si True, hace polling hasta que la solicitud termine.

    Returns:
        EstadoSolicitud con los PackageIDs listos para descargar.

    Raises:
        RuntimeError: Si la solicitud es rechazada o hay error del SAT.
    """
    interval = POLL_INTERVAL_INITIAL
    attempt = 0

    while attempt < POLL_MAX_ATTEMPTS:
        estado = _consultar_una_vez(token, rfc_solicitante, id_solicitud, fiel)

        # Token expirado — renovar y reintentar sin consumir intento
        if estado.cod_estatus == "300" and fiel is not None:
            logger.info("[Verificacion] Token expirado, renovando...")
            token = _auth.obtener_token(fiel)
            continue

        attempt += 1
        logger.info(
            "[Verificacion] Intento %d — Estado=%s, Paquetes=%d, Msg=%s",
            attempt, estado.cod_estado, len(estado.package_ids), estado.mensaje,
        )

        if estado.cod_estado == ESTADO_TERMINADA:
            return estado

        if estado.cod_estado in (ESTADO_ERROR, ESTADO_RECHAZADA):
            raise RuntimeError(
                f"La solicitud fue rechazada o falló. "
                f"Estado={estado.cod_estado}, Mensaje={estado.mensaje}"
            )

        if not poll:
            return estado

        logger.info(
            "[Verificacion] Solicitud en proceso. Esperando %ds...", interval,
        )
        time.sleep(interval)
        interval = min(interval * POLL_BACKOFF_FACTOR, POLL_INTERVAL_MAX)

    raise TimeoutError(
        f"La solicitud {id_solicitud} no terminó después de "
        f"{POLL_MAX_ATTEMPTS} intentos."
    )


def consultar_solicitud(
    token: str,
    rfc_solicitante: str,
    id_solicitud: str,
    fiel: FIEL = None,
) -> EstadoSolicitud:
    """
    Una sola consulta de estado que NO lanza en estados 4/5 (error/rechazada):
    devuelve el EstadoSolicitud tal cual para que el caller lo persista.

    A diferencia de `verificar_solicitud` (que hace polling y convierte 4/5 en
    RuntimeError), esta sonda es para los flujos que necesitan REGISTRAR el
    estado final de una solicitud fallida en el catálogo — el endpoint
    /verificar del agente y el poller en background. Renueva el token una vez
    si el SAT reporta que expiró (CodEstatus=300).
    """
    estado = _consultar_una_vez(token, rfc_solicitante, id_solicitud, fiel)
    if estado.cod_estatus == "300" and fiel is not None:
        logger.info("[Verificacion] Token expirado, renovando...")
        token = _auth.obtener_token(fiel)
        estado = _consultar_una_vez(token, rfc_solicitante, id_solicitud, fiel)
    return estado


def _consultar_una_vez(
    token: str, rfc_solicitante: str, id_solicitud: str, fiel: FIEL = None
) -> EstadoSolicitud:
    """Realiza una sola consulta de verificación."""
    if demo.aplica(rfc_solicitante):  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        return sat_demo.verificar(rfc_solicitante, id_solicitud)

    envelope_xml = (
        f'<s:Envelope xmlns:s="{_SOAP_NS}" xmlns:des="{_DES_NS}">'
        f'<s:Header/>'
        f'<s:Body>'
        f'<des:VerificaSolicitudDescarga>'
        f'<des:solicitud'
        f' IdSolicitud="{id_solicitud}"'
        f' RfcSolicitante="{rfc_solicitante}"'
        f'/>'
        f'</des:VerificaSolicitudDescarga>'
        f'</s:Body>'
        f'</s:Envelope>'
    )

    if fiel is not None:
        body = _sign_envelope(envelope_xml, fiel)
    else:
        body = envelope_xml.encode("utf-8")

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": SOAP_ACTIONS["verifica_solicitud"],
        "Authorization": f'WRAP access_token="{token}"',
    }

    resp_xml = make_request(
        url=ENDPOINTS["verifica_solicitud"],
        body=body,
        headers=headers,
        operation="VerificaSolicitud",
    )

    return _parse_estado(resp_xml)


def _sign_envelope(envelope_xml: str, fiel: FIEL) -> bytes:
    """
    Firma el elemento VerificaSolicitudDescarga con xmldsig enveloped.
    La Signature se añade como hijo de solicitud.
    """
    root = etree.fromstring(envelope_xml.encode())
    op_elem = root.find(f'.//{{{_DES_NS}}}VerificaSolicitudDescarga')
    sol_elem = root.find(f'.//{{{_DES_NS}}}solicitud')

    # 1. C14N inclusiva del elemento operación
    op_c14n = _c14n_inclusive(op_elem)

    # 2. DigestValue
    digest = base64.b64encode(hashlib.sha1(op_c14n).digest()).decode()

    # 3. SignedInfo
    signed_info_xml = (
        f'<SignedInfo xmlns="{_XMLDSIG_NS}">'
        f'<CanonicalizationMethod Algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"/>'
        f'<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>'
        f'<Reference URI="">'
        f'<Transforms>'
        f'<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>'
        f'</Transforms>'
        f'<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>'
        f'<DigestValue>{digest}</DigestValue>'
        f'</Reference>'
        f'</SignedInfo>'
    )

    si_elem = etree.fromstring(signed_info_xml.encode())
    si_c14n = _c14n_inclusive(si_elem)
    signature_value = fiel.sign_b64(si_c14n)

    signature_xml = (
        f'<Signature xmlns="{_XMLDSIG_NS}">'
        + signed_info_xml
        + f'<SignatureValue>{signature_value}</SignatureValue>'
        f'<KeyInfo>'
        f'<X509Data>'
        f'<X509IssuerSerial>'
        f'<X509IssuerName>{fiel.issuer_dn}</X509IssuerName>'
        f'<X509SerialNumber>{fiel.numero_serie}</X509SerialNumber>'
        f'</X509IssuerSerial>'
        f'<X509Certificate>{fiel.certificate_b64}</X509Certificate>'
        f'</X509Data>'
        f'</KeyInfo>'
        f'</Signature>'
    )

    # Convertir solicitud a no-self-closing para poder appender
    if sol_elem.text is None and len(sol_elem) == 0:
        sol_elem.text = ""

    sig_elem = etree.fromstring(signature_xml.encode())
    sol_elem.append(sig_elem)

    return etree.tostring(root, encoding="utf-8", xml_declaration=False)


def _c14n_inclusive(elem) -> bytes:
    """C14N inclusiva (W3C Canonical XML) de un elemento."""
    buf = BytesIO()
    etree.ElementTree(elem).write_c14n(buf, exclusive=False, with_comments=False)
    return buf.getvalue()


def _parse_estado(resp_xml: bytes) -> EstadoSolicitud:
    """Parsea la respuesta de VerificaSolicitudDescarga."""
    logger.debug("[Verificacion] Respuesta XML cruda:\n%s", resp_xml.decode(errors="replace"))

    parser = parser_seguro(huge_tree=True)
    root = etree.fromstring(resp_xml, parser=parser)

    result = root.find(f".//{{{_DES_NS}}}VerificaSolicitudDescargaResult")
    if result is None:
        raise RuntimeError(
            f"Respuesta inesperada de VerificaSolicitudDescarga:\n"
            f"{resp_xml.decode()}"
        )

    cod_estado = result.get("EstadoSolicitud", "")
    cod_estatus = result.get("CodEstatus", "")
    mensaje = result.get("Mensaje", "")
    numero_cfdis_str = result.get("NumeroCFDIs", "0")

    try:
        numero_cfdis = int(numero_cfdis_str)
    except ValueError:
        numero_cfdis = 0

    # Extraer PackageIDs — cada <IdsPaquetes> contiene un ID como texto
    package_ids = []
    for paquete_el in result.findall(f"{{{_DES_NS}}}IdsPaquetes"):
        if paquete_el.text and paquete_el.text.strip():
            package_ids.append(paquete_el.text.strip())
    if not package_ids:
        for paquete_el in result.findall("IdsPaquetes"):
            if paquete_el.text and paquete_el.text.strip():
                package_ids.append(paquete_el.text.strip())

    terminada = cod_estado == ESTADO_TERMINADA

    return EstadoSolicitud(
        cod_estado=cod_estado,
        cod_estatus=cod_estatus,
        mensaje=mensaje,
        numero_cfdis=numero_cfdis,
        package_ids=package_ids,
        terminada=terminada,
    )

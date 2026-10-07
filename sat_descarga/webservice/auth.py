"""
Autenticación con el Web Service del SAT.

Construye el mensaje SOAP con WS-Security (xmldsig) y obtiene el token
de sesión (UUID) necesario para las demás operaciones.
"""

import uuid
import base64
import hashlib
from lxml import etree

from .. import demo
from ..core.fiel import FIEL
from ..core.config import ENDPOINTS, SOAP_ACTIONS
from ..core.http_client import make_request
from ..core.xml_seguro import fromstring_seguro


# ---------------------------------------------------------------------------
# Construcción del mensaje SOAP de autenticación
# ---------------------------------------------------------------------------

_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_WSU_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"
_WSSE_NS = "http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"
_XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"
_DES_NS = "http://DescargaMasivaTerceros.gob.mx"

# Value type para el BinarySecurityToken del SAT
_X509_VALUE_TYPE = (
    "http://docs.oasis-open.org/wss/2004/01/"
    "oasis-200401-wss-x509-token-profile-1.0#X509v3"
)


def _build_auth_envelope(fiel: FIEL) -> bytes:
    """
    Construye el envelope SOAP firmado para autenticarse.

    El SAT requiere WS-Security con:
    - BinarySecurityToken (certificado en Base64)
    - Timestamp firmado
    - SignedInfo con referencia al Timestamp (C14N)
    """
    created = fiel.now_utc_str()
    expires = fiel.expires_utc_str(minutes=5)
    token_id = f"uuid-{uuid.uuid4()}-1"
    timestamp_id = f"_0"
    body_id = f"_1"

    # --- Timestamp element (para firmar) ---
    ts_xml = (
        f'<u:Timestamp xmlns:u="{_WSU_NS}" u:Id="{timestamp_id}">'
        f"<u:Created>{created}</u:Created>"
        f"<u:Expires>{expires}</u:Expires>"
        f"</u:Timestamp>"
    )

    # Canonicalizar el Timestamp (C14N exclusivo sin comentarios)
    ts_elem = etree.fromstring(ts_xml.encode())
    ts_c14n = _c14n(ts_elem)

    # DigestValue del Timestamp
    digest = base64.b64encode(hashlib.sha1(ts_c14n).digest()).decode()

    # --- SignedInfo ---
    signed_info_xml = (
        f'<SignedInfo xmlns="{_XMLDSIG_NS}">'
        f'<CanonicalizationMethod Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>'
        f'<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>'
        f'<Reference URI="#{timestamp_id}">'
        f"<Transforms>"
        f'<Transform Algorithm="http://www.w3.org/2001/10/xml-exc-c14n#"/>'
        f"</Transforms>"
        f'<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>'
        f"<DigestValue>{digest}</DigestValue>"
        f"</Reference>"
        f"</SignedInfo>"
    )
    si_elem = etree.fromstring(signed_info_xml.encode())
    si_c14n = _c14n(si_elem)

    # Firma del SignedInfo
    signature_value = fiel.sign_b64(si_c14n)

    # --- Envelope completo ---
    envelope = (
        f'<s:Envelope xmlns:s="{_SOAP_NS}"'
        f' xmlns:u="{_WSU_NS}"'
        f' xmlns:o="{_WSSE_NS}">'
        f"<s:Header>"
        f'<o:Security s:mustUnderstand="1">'
        f'<u:Timestamp u:Id="{timestamp_id}">'
        f"<u:Created>{created}</u:Created>"
        f"<u:Expires>{expires}</u:Expires>"
        f"</u:Timestamp>"
        f'<o:BinarySecurityToken'
        f' u:Id="{token_id}"'
        f' ValueType="{_X509_VALUE_TYPE}"'
        f' EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">'
        f"{fiel.certificate_b64}"
        f"</o:BinarySecurityToken>"
        f'<Signature xmlns="{_XMLDSIG_NS}">'
        + signed_info_xml +
        f"<SignatureValue>{signature_value}</SignatureValue>"
        f"<KeyInfo>"
        f"<o:SecurityTokenReference>"
        f'<o:Reference URI="#{token_id}" ValueType="{_X509_VALUE_TYPE}"/>'
        f"</o:SecurityTokenReference>"
        f"</KeyInfo>"
        f"</Signature>"
        f"</o:Security>"
        f"</s:Header>"
        f"<s:Body>"
        f'<Autentica xmlns="{_DES_NS}"/>'
        f"</s:Body>"
        f"</s:Envelope>"
    )
    return envelope.encode("utf-8")


def _c14n(elem) -> bytes:
    """Serialización C14N exclusiva (Exclusive Canonical XML) de un elemento."""
    from io import BytesIO
    buf = BytesIO()
    elem.getroottree().write_c14n(buf, exclusive=True, with_comments=False)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def obtener_token(fiel: FIEL) -> str:
    """
    Autentica con el SAT y devuelve el token de sesión.

    Args:
        fiel: Instancia de FIEL con certificado y llave privada.

    Returns:
        Token UUID de sesión (dura ~5 minutos).

    Raises:
        RuntimeError: Si la autenticación falla.
    """
    if demo.aplica_fiel(fiel):  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        return sat_demo.token(demo.rfc_de_fiel(fiel))

    body = _build_auth_envelope(fiel)
    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": SOAP_ACTIONS["autenticacion"],
    }

    resp_xml = make_request(
        url=ENDPOINTS["autenticacion"],
        body=body,
        headers=headers,
        operation="autenticacion",
    )

    # Extraer el token del response
    # <AutenticaResult>...</AutenticaResult>
    root = fromstring_seguro(resp_xml)
    ns = {"des": _DES_NS}
    result = root.find(".//{%s}AutenticaResult" % _DES_NS)
    if result is None or not result.text:
        raise RuntimeError(
            f"No se obtuvo token. Respuesta:\n{resp_xml.decode()}"
        )
    # El SAT devuelve un WRAP token URL-encoded: "JWT%26wrap_subject%3dVALOR"
    # Devolvemos la forma URL-encoded tal cual: el servidor de solicitudes
    # espera recibirla así en el SolicitaDescargaHeader SOAP.
    return result.text.strip()

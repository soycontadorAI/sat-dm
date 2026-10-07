"""
DescargaMasiva: descarga los paquetes ZIP con los CFDIs.

API v1.5: mismo patrón que Solicitud y Verificacion:
- Namespace: http://DescargaMasivaTerceros.sat.gob.mx
- Token WRAP en HTTP header "Authorization: WRAP access_token=..."
- Firma xmldsig enveloped en el cuerpo
"""

import io
import base64
import hashlib
import logging
import zipfile
from io import BytesIO
from pathlib import Path
from typing import List
from lxml import etree

from .. import demo
from ..core.config import ENDPOINTS, SOAP_ACTIONS
from ..core.fiel import FIEL
from ..core.http_client import make_request
from ..core.xml_seguro import parser_seguro

logger = logging.getLogger(__name__)

_SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
_DES_NS = "http://DescargaMasivaTerceros.sat.gob.mx"
_XMLDSIG_NS = "http://www.w3.org/2000/09/xmldsig#"


def descargar_paquete(
    token: str,
    rfc_solicitante: str,
    package_id: str,
    directorio_salida: str,
    fiel: FIEL = None,
    extraer: bool = True,
) -> Path:
    """
    Descarga un paquete ZIP y opcionalmente extrae los CFDIs.

    Args:
        token: Token WRAP obtenido con auth.obtener_token() (URL-encoded).
        rfc_solicitante: RFC del solicitante.
        package_id: ID del paquete a descargar.
        directorio_salida: Directorio donde guardar el ZIP / XMLs.
        fiel: Instancia de FIEL para firmar la solicitud (requerida en v1.5).
        extraer: Si True, extrae los XMLs del ZIP.

    Returns:
        Path al archivo ZIP descargado.
    """
    logger.info("[Descarga] Descargando paquete %s ...", package_id)

    if demo.aplica(rfc_solicitante):  # modo de grabación: empresa de demo, sin SAT
        from ..demo import sat as sat_demo
        zip_bytes = sat_demo.paquete_zip(rfc_solicitante, package_id)
    else:
        zip_bytes = _pedir_paquete(token, rfc_solicitante, package_id, fiel)

    out_dir = Path(directorio_salida)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{package_id}.zip"
    zip_path.write_bytes(zip_bytes)
    logger.info("[Descarga] ZIP guardado: %s (%d bytes)", zip_path, len(zip_bytes))

    if extraer:
        _extraer_zip(zip_bytes, out_dir, package_id)

    return zip_path


def _pedir_paquete(token: str, rfc_solicitante: str, package_id: str,
                   fiel: FIEL = None) -> bytes:
    """PeticionDescargaMasivaTercerosEntrada: el ZIP del paquete, del SAT."""
    envelope_xml = (
        f'<s:Envelope xmlns:s="{_SOAP_NS}" xmlns:des="{_DES_NS}">'
        f'<s:Header/>'
        f'<s:Body>'
        f'<des:PeticionDescargaMasivaTercerosEntrada>'
        f'<des:peticionDescarga'
        f' IdPaquete="{package_id}"'
        f' RfcSolicitante="{rfc_solicitante}"'
        f'/>'
        f'</des:PeticionDescargaMasivaTercerosEntrada>'
        f'</s:Body>'
        f'</s:Envelope>'
    )

    if fiel is not None:
        body = _sign_envelope(envelope_xml, fiel)
    else:
        body = envelope_xml.encode("utf-8")

    headers = {
        "Content-Type": "text/xml; charset=utf-8",
        "SOAPAction": SOAP_ACTIONS["descarga_masiva"],
        "Authorization": f'WRAP access_token="{token}"',
    }

    resp_xml = make_request(
        url=ENDPOINTS["descarga_masiva"],
        body=body,
        headers=headers,
        operation="DescargaMasiva",
    )

    return _extraer_zip_del_response(resp_xml, package_id)


def descargar_todos(
    token: str,
    rfc_solicitante: str,
    package_ids: List[str],
    directorio_salida: str,
    fiel: FIEL = None,
    extraer: bool = True,
) -> List[Path]:
    """Descarga todos los paquetes de una solicitud."""
    zips = []
    for i, pkg_id in enumerate(package_ids, start=1):
        logger.info("[Descarga] Paquete %d/%d: %s", i, len(package_ids), pkg_id)
        zip_path = descargar_paquete(
            token=token,
            rfc_solicitante=rfc_solicitante,
            package_id=pkg_id,
            directorio_salida=directorio_salida,
            fiel=fiel,
            extraer=extraer,
        )
        zips.append(zip_path)
    return zips


# ---------------------------------------------------------------------------
# Firma enveloped (xmldsig)
# ---------------------------------------------------------------------------

def _sign_envelope(envelope_xml: str, fiel: FIEL) -> bytes:
    """Firma PeticionDescargaMasivaTercerosEntrada con xmldsig enveloped."""
    root = etree.fromstring(envelope_xml.encode())
    op_elem = root.find(f'.//{{{_DES_NS}}}PeticionDescargaMasivaTercerosEntrada')
    sol_elem = root.find(f'.//{{{_DES_NS}}}peticionDescarga')

    # C14N del elemento operación
    op_c14n = _c14n_inclusive(op_elem)
    digest = base64.b64encode(hashlib.sha1(op_c14n).digest()).decode()

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


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _extraer_zip_del_response(resp_xml: bytes, package_id: str) -> bytes:
    """El SAT devuelve el ZIP en Base64 dentro del XML SOAP."""
    parser = parser_seguro(huge_tree=True)
    try:
        root = etree.fromstring(resp_xml, parser=parser)
    except etree.XMLSyntaxError as e:
        raise RuntimeError(
            f"No se pudo parsear la respuesta del paquete {package_id}: {e}"
        )

    result_el = root.find(f".//{{{_DES_NS}}}respuestaDescarga")
    cod = result_el.get("CodEstatus", "") if result_el is not None else ""
    msg = result_el.get("Mensaje", "") if result_el is not None else ""

    paquete_el = root.find(f".//{{{_DES_NS}}}Paquete")
    if paquete_el is None:
        raise RuntimeError(
            f"No se encontró el paquete {package_id}. "
            f"CodEstatus={cod}, Mensaje={msg}\n"
            f"Respuesta:\n{resp_xml[:500].decode(errors='replace')}"
        )

    # El SAT a veces devuelve <Paquete/> vacío (sin Base64) aunque la solicitud
    # se verificó como terminada: paquete ya consumido, todavía no listo o
    # incidencia transitoria del WS. En ese caso `paquete_el.text` es None y
    # base64.b64decode tronaba con un TypeError cripto ("argument should be a
    # bytes-like object or ASCII string, not 'NoneType'") que se propagaba como
    # un 500 sin contexto. Lo convertimos en un error accionable.
    contenido = (paquete_el.text or "").strip()
    if not contenido:
        raise RuntimeError(
            f"El SAT devolvió el paquete {package_id} vacío "
            f"(CodEstatus={cod or 'N/D'}, Mensaje={msg or 'sin mensaje'}). "
            "Reintenta la descarga en unos minutos; si el paquete ya se había "
            "descargado antes, vuelve a solicitarlo."
        )

    return base64.b64decode(contenido)


def _extraer_zip(zip_bytes: bytes, out_dir: Path, package_id: str) -> int:
    """Extrae los XMLs del ZIP en `out_dir/package_id/`."""
    extract_dir = out_dir / package_id
    extract_dir.mkdir(parents=True, exist_ok=True)
    base = extract_dir.resolve()

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            members = zf.namelist()
            # Anti zip-slip: ningún miembro puede resolver fuera de extract_dir
            # (rutas "../x" o absolutas en un ZIP manipulado).
            for member in members:
                destino = (extract_dir / member).resolve()
                try:
                    destino.relative_to(base)
                except ValueError:
                    raise RuntimeError(
                        f"El ZIP del paquete {package_id} contiene una ruta "
                        f"insegura: {member!r}"
                    )
            zf.extractall(extract_dir)
            logger.info(
                "[Descarga] Extraídos %d archivos en %s", len(members), extract_dir
            )
            return len(members)
    except zipfile.BadZipFile as e:
        raise RuntimeError(
            f"El ZIP del paquete {package_id} está corrupto: {e}"
        )

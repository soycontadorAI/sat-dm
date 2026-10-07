"""
e.firmas de ejemplo para las empresas de demo.

Certificado autofirmado con la forma de los del SAT (RFC en x500UniqueIdentifier,
CURP en serialNumber, razón social en el CN) y su llave .key en PKCS#8 DER
cifrada, como las reales. Así `core.fiel.FIEL` las abre sin ningún caso
especial y el alta (⌘N), el semáforo de vigencia y el poller funcionan igual.

El emisor dice que es de ejemplo: el SAT nunca las aceptaría y, con el modo de
grabación apagado, el alta las rechaza (`exigir_permitida`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .escenario import EMPRESAS, PASSWORD_EFIRMA

EMISOR_CN = "TodoConta Certificado de ejemplo"
EMISOR_OU = "Modo de grabacion - sin validez ante el SAT"


def es_certificado_de_ejemplo(fiel) -> bool:
    """¿La FIEL es una e.firma de ejemplo del modo de grabación?"""
    try:
        emisor = fiel.issuer_dn
    except Exception:  # noqa: BLE001
        return False
    return EMISOR_CN in emisor


def exigir_permitida(fiel) -> None:
    """Con el modo apagado, una e.firma de ejemplo no se da de alta (pasaría las
    validaciones de la app, pero el SAT la rechazaría en cada operación)."""
    from . import activo

    if es_certificado_de_ejemplo(fiel) and not activo():
        raise ValueError(
            "Esta e.firma es de ejemplo (modo de grabación) y no sirve ante el SAT. "
            "Solo se acepta con SAT_DM_MODO_GRABACION=1."
        )


def _serial(rfc: str) -> int:
    # Como los del SAT: 20 dígitos ASCII codificados en el número de serie.
    import hashlib

    n = int(hashlib.sha256(("serie" + rfc).encode()).hexdigest(), 16) % 10**8
    return int.from_bytes(f"300010000005{n:08d}".encode(), "big")


@lru_cache(maxsize=16)
def _llave(rfc: str):
    """Llave RSA de la e.firma de ejemplo (una por empresa y proceso: generarla
    es lo más lento de la siembra y no hay nada que proteger)."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def generar(rfc: str, directorio: Path, hoy: Optional[date] = None,
            password: str = PASSWORD_EFIRMA) -> tuple:
    """Escribe el .cer y la .key en `directorio`, con los nombres que pone el SAT
    (`der180922qx4.cer`, `Claveprivada_FIEL_DER180922QX4_<fecha>_<hora>.key`), para
    que el diálogo de alta se vea como con una e.firma real. Devuelve (cer, key, password).

    La vigencia sale del escenario: vence `vence_en_dias` después de `hoy`
    (Norma en 4 días, Servicios Integrales en 21…), con 4 años de vida."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    emp = EMPRESAS[rfc.upper()]
    hoy = hoy or date.today()
    dias = emp.vence_en_dias if emp.vence_en_dias is not None else 4 * 365
    vence = datetime.combine(hoy + timedelta(days=dias), datetime.min.time()).replace(
        hour=18, tzinfo=timezone.utc)
    emitido = vence - timedelta(days=4 * 365)

    llave = _llave(emp.rfc)
    if emp.tipo == "PM":
        unico = f"{emp.rfc} / {emp.rfc_representante}"
        serie = f" / {emp.curp}"
    else:
        unico = emp.rfc
        serie = emp.curp
    sujeto = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, emp.nombre),
        x509.NameAttribute(x509.ObjectIdentifier("2.5.4.41"), emp.nombre),  # name
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, emp.nombre),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
        x509.NameAttribute(NameOID.X500_UNIQUE_IDENTIFIER, unico),
        x509.NameAttribute(NameOID.SERIAL_NUMBER, serie),
    ])
    emisor = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, EMISOR_CN),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "TodoConta"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, EMISOR_OU),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "MX"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(sujeto)
        .issuer_name(emisor)
        .public_key(llave.public_key())
        .serial_number(_serial(emp.rfc))
        .not_valid_before(emitido)
        .not_valid_after(vence)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True, key_encipherment=False,
            data_encipherment=True, key_agreement=True, key_cert_sign=False,
            crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
        .sign(llave, hashes.SHA256())
    )
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    cer = directorio / f"{emp.rfc.lower()}.cer"
    key = directorio / f"Claveprivada_FIEL_{emp.rfc}_{emitido:%Y%m%d_%H%M%S}.key"
    cer.write_bytes(cert.public_bytes(serialization.Encoding.DER))
    key.write_bytes(llave.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode()),
    ))
    return cer, key, password

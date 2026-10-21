"""
Parser ligero de CFDI XML.

Lee solo los campos necesarios para validación, organización y reportes
fiscales. NO es un parser completo de CFDI — todoconta-apps hace eso
en el browser. Este módulo extrae lo mínimo necesario para las operaciones
server-side de sat-descarga-masiva.

Usa lxml iterparse para eficiencia en memoria con archivos grandes.
"""

import os
from dataclasses import dataclass
from typing import Optional
from lxml import etree

from ..core.xml_seguro import leer_tolerante, nombre_local


# Namespaces comunes en CFDIs — usamos local-name() para ser agnosticos
_CFDI_NS = "http://www.sat.gob.mx/cfd/4"
_CFDI_NS_33 = "http://www.sat.gob.mx/cfd/3"
_TFD_NS = "http://www.sat.gob.mx/TimbreFiscalDigital"


@dataclass
class CfdiHeader:
    """Datos mínimos de un CFDI extraídos del XML."""
    uuid: str
    version: str
    tipo_comprobante: str       # I, E, P, T, N
    fecha_emision: str
    fecha_timbrado: Optional[str]
    emisor_rfc: str
    emisor_nombre: str
    receptor_rfc: str
    receptor_nombre: str
    subtotal: float
    total: float
    moneda: str
    serie: Optional[str] = None
    folio: Optional[str] = None
    archivo: Optional[str] = None


def leer_cfdi(xml_path: str) -> CfdiHeader:
    """
    Lee los datos básicos de un archivo CFDI XML.

    Extrae solo: Comprobante attrs, Emisor, Receptor, TimbreFiscalDigital.
    Rápido y ligero — no parsea conceptos, impuestos ni complementos.

    Args:
        xml_path: Ruta al archivo XML.

    Returns:
        CfdiHeader con los datos extraídos.

    Raises:
        ValueError: Si el archivo no es un CFDI válido.
    """
    # Tolerante como el procesador (core/xml_seguro.py::leer_tolerante), pero solo
    # con lo que se lee completo (namespace mal declarado, codificación): el
    # organizador mueve y renombra con estos datos.
    with open(xml_path, "rb") as f:
        lectura = leer_tolerante(f.read())
    if lectura.avisos and not lectura.sin_perdida:
        raise ValueError(f"XML mal formado: {lectura.avisos[-1]}")
    root = lectura.raiz

    # Usar local-name() para ser namespace-agnostic
    local = nombre_local(root)
    if local != "Comprobante":
        raise ValueError(f"No es un CFDI: elemento raíz es '{local}', esperado 'Comprobante'")

    version = root.get("Version") or root.get("version", "")
    tipo = root.get("TipoDeComprobante") or root.get("tipoDeComprobante", "")
    fecha = root.get("Fecha") or root.get("fecha", "")

    # Emisor y Receptor — buscar sin importar namespace
    emisor = _find_local(root, "Emisor")
    receptor = _find_local(root, "Receptor")

    emisor_rfc = emisor.get("Rfc") or emisor.get("rfc", "") if emisor is not None else ""
    emisor_nombre = emisor.get("Nombre") or emisor.get("nombre", "") if emisor is not None else ""
    receptor_rfc = receptor.get("Rfc") or receptor.get("rfc", "") if receptor is not None else ""
    receptor_nombre = receptor.get("Nombre") or receptor.get("nombre", "") if receptor is not None else ""

    # TimbreFiscalDigital — UUID y fecha timbrado
    tfd = _find_local(root, "TimbreFiscalDigital")
    uuid = tfd.get("UUID") or tfd.get("uuid", "") if tfd is not None else ""
    fecha_timbrado = tfd.get("FechaTimbrado") if tfd is not None else None

    if lectura.avisos and not uuid:
        raise ValueError(f"XML mal formado sin UUID: {lectura.avisos[0]}")

    return CfdiHeader(
        uuid=uuid.upper(),
        version=version,
        tipo_comprobante=tipo,
        fecha_emision=fecha,
        fecha_timbrado=fecha_timbrado,
        emisor_rfc=emisor_rfc,
        emisor_nombre=emisor_nombre,
        receptor_rfc=receptor_rfc,
        receptor_nombre=receptor_nombre,
        subtotal=_safe_float(root.get("SubTotal") or root.get("subTotal", "0")),
        total=_safe_float(root.get("Total") or root.get("total", "0")),
        moneda=root.get("Moneda") or root.get("moneda", "MXN"),
        serie=root.get("Serie") or root.get("serie"),
        folio=root.get("Folio") or root.get("folio"),
        archivo=os.path.basename(xml_path),
    )


def leer_directorio(directorio: str, recursive: bool = True) -> list[CfdiHeader]:
    """
    Lee todos los XMLs de un directorio y retorna sus headers.

    Args:
        directorio: Ruta al directorio.
        recursive: Si True, busca en subdirectorios.

    Returns:
        Lista de CfdiHeader (omite archivos que no son CFDI válidos).
    """
    headers = []
    for root_dir, _dirs, files in os.walk(directorio):
        for f in files:
            if not f.lower().endswith(".xml"):
                continue
            path = os.path.join(root_dir, f)
            try:
                header = leer_cfdi(path)
                headers.append(header)
            except (ValueError, etree.XMLSyntaxError):
                continue
        if not recursive:
            break
    return headers


def _find_local(elem, local_name: str):
    """Busca un descendiente por nombre local, ignorando namespace y prefijo
    (también el prefijo sin declarar de la lectura tolerante). Comentarios e
    instrucciones de proceso no son elementos: `nombre_local` les da ""."""
    for child in elem.iter():
        if nombre_local(child) == local_name:
            return child
    return None


def _safe_float(val: str) -> float:
    """Convierte string a float, retorna 0.0 si falla."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0

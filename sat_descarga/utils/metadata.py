"""
Parser de metadata CSV del SAT.

Cuando se solicita una descarga con tipo_solicitud="Metadata", el SAT
retorna un ZIP que contiene un archivo CSV (no XMLs). Este módulo parsea
ese CSV y lo convierte en una lista de diccionarios.

Columnas del CSV del SAT (encabezados reales del archivo):
  Uuid, RfcEmisor, NombreEmisor, RfcReceptor, NombreReceptor,
  RfcPac, FechaEmision, FechaCertificacionSat, Monto,
  EfectoComprobante, Estatus, FechaCancelacion
"""

import csv
import io
import logging
import zipfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Mapeo de nombres de columna del SAT → nombres internos normalizados.
# El SAT puede variar mayúsculas/minúsculas; normalizamos a minúsculas para comparar.
_COLUMN_MAP = {
    "uuid": "uuid",
    "rfcemisor": "rfc_emisor",
    "nombreemisor": "nombre_emisor",
    "rfcreceptor": "rfc_receptor",
    "nombrereceptor": "nombre_receptor",
    "rfcpac": "rfc_pac",
    "fechaemision": "fecha_emision",
    "fechacertificacionsat": "fecha_certificacion",
    "monto": "monto",
    "efectocomprobante": "efecto_comprobante",
    "estatus": "estatus",
    "fechacancelacion": "fecha_cancelacion",
}


@dataclass
class MetadataCFDI:
    """Un registro de metadata de CFDI tal como lo devuelve el SAT."""
    uuid: str = ""
    rfc_emisor: str = ""
    nombre_emisor: str = ""
    rfc_receptor: str = ""
    nombre_receptor: str = ""
    rfc_pac: str = ""
    fecha_emision: str = ""
    fecha_certificacion: str = ""
    monto: str = ""
    efecto_comprobante: str = ""
    estatus: str = ""
    fecha_cancelacion: str = ""


def parse_metadata_csv(csv_text: str) -> List[MetadataCFDI]:
    """
    Parsea el contenido CSV de metadata del SAT.

    Args:
        csv_text: Contenido del archivo CSV como string.

    Returns:
        Lista de MetadataCFDI.
    """
    records = []

    # El SAT puede usar diferentes separadores (~ o ,)
    # Detectar automáticamente
    first_line = csv_text.split("\n", 1)[0]
    delimiter = "~" if "~" in first_line else ","

    reader = csv.reader(io.StringIO(csv_text), delimiter=delimiter)

    # Primera fila = encabezados
    try:
        raw_headers = next(reader)
    except StopIteration:
        return records

    # Normalizar encabezados y mapear a nombres internos
    col_indices = {}
    for i, h in enumerate(raw_headers):
        normalized = h.strip().lower().replace(" ", "").replace("_", "")
        if normalized in _COLUMN_MAP:
            col_indices[_COLUMN_MAP[normalized]] = i

    # Parsear filas
    for row in reader:
        if not row or all(cell.strip() == "" for cell in row):
            continue

        record = MetadataCFDI()
        for field_name, col_idx in col_indices.items():
            if col_idx < len(row):
                setattr(record, field_name, row[col_idx].strip())

        if record.uuid:
            records.append(record)

    logger.info("[Metadata] Parseados %d registros del CSV", len(records))
    return records


def extraer_metadata_de_zip(zip_path: str) -> List[MetadataCFDI]:
    """
    Extrae y parsea el CSV de metadata de un archivo ZIP del SAT.

    Args:
        zip_path: Ruta al archivo ZIP descargado.

    Returns:
        Lista de MetadataCFDI.
    """
    path = Path(zip_path)

    with zipfile.ZipFile(path) as zf:
        # Buscar el archivo CSV dentro del ZIP
        csv_files = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not csv_files:
            # Si no hay CSV, intentar con el primer archivo
            csv_files = zf.namelist()

        if not csv_files:
            logger.warning("[Metadata] ZIP vacío: %s", zip_path)
            return []

        csv_name = csv_files[0]
        csv_bytes = zf.read(csv_name)

        # Intentar decodificar (SAT usa diferentes encodings)
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                csv_text = csv_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            csv_text = csv_bytes.decode("latin-1", errors="replace")

    return parse_metadata_csv(csv_text)


def extraer_metadata_de_directorio(directorio: str,
                                   errores: Optional[list] = None) -> List[MetadataCFDI]:
    """
    Busca archivos ZIP o CSV en un directorio y extrae la metadata.

    Args:
        directorio: Ruta al directorio con ZIPs de metadata.
        errores: si se pasa, recibe la ruta de cada archivo que no se pudo leer.

    Returns:
        Lista combinada de MetadataCFDI de todos los archivos.
    """
    records = []
    path = Path(directorio)

    # Buscar ZIPs (solo en raíz, no en subdirectorios donde ya están extraídos)
    for zip_file in sorted(path.glob("*.zip")):
        try:
            records.extend(extraer_metadata_de_zip(str(zip_file)))
        except (zipfile.BadZipFile, Exception) as e:
            logger.warning("[Metadata] Error leyendo %s: %s", zip_file, e)
            if errores is not None:
                errores.append(str(zip_file))

    # Si no hubo ZIPs, buscar TXTs/CSVs sueltos
    if not records:
        for pattern in ("**/*.csv", "**/*.txt"):
            for text_file in sorted(path.glob(pattern)):
                try:
                    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
                        try:
                            csv_text = text_file.read_text(encoding=encoding)
                            break
                        except UnicodeDecodeError:
                            continue
                    else:
                        csv_text = text_file.read_text(encoding="latin-1")

                    if csv_text.startswith("Uuid") or csv_text.startswith("uuid"):
                        records.extend(parse_metadata_csv(csv_text))
                except Exception as e:
                    logger.warning("[Metadata] Error leyendo %s: %s", text_file, e)
                    if errores is not None:
                        errores.append(str(text_file))

    # Deduplicar por UUID (múltiples solicitudes pueden tener los mismos registros)
    seen = set()
    unique = []
    for r in records:
        if r.uuid not in seen:
            seen.add(r.uuid)
            unique.append(r)

    if len(unique) < len(records):
        logger.info("[Metadata] Deduplicados: %d → %d registros", len(records), len(unique))

    return unique


def metadata_to_dicts(records: List[MetadataCFDI]) -> List[dict]:
    """Convierte lista de MetadataCFDI a lista de dicts (para JSON/API)."""
    return [asdict(r) for r in records]

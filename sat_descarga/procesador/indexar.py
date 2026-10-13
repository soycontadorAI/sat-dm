"""
Indexado de XMLs al procesador (el índice permanente de cada empresa).

Una sola tubería para todas las entradas: parsea, descarta lo que no es de la
empresa, valida y guarda las tres capas (columnas planas, XML original y
`nodos`) vía `ProcesadorDB.agregar`. La usan:

- las descargas de CFDI del SAT (Web Service, portal con contraseña o
  e.firma), en segundo plano al terminar cada una (`api/state.py`);
- el indexado inicial de la carpeta de descargas, una vez por empresa al
  arrancar el agente;
- los endpoints de carga del procesador (subir XMLs y "cargar desde empresa").

Kill switch del indexado automático: `SAT_DM_SIN_INDEXADO=1`.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from lxml import etree

from ..core.xml_seguro import fromstring_seguro
from .cfdi_parser import CfdiParseError, parse_cfdi
from .db import abrir_db, normalizar_mi_rfc
from .validaciones import validar_y_anotar

logger = logging.getLogger(__name__)

# Canal del historial de descargas → `cfdis.origen` (migración 010).
ORIGEN_POR_CANAL = {"ws": "sat_ws", "ciec": "sat_portal", "fiel": "sat_portal"}

# CFDIs por transacción: acota la memoria con carpetas de decenas de miles.
LOTE = 500

# Versión del indexado inicial de la carpeta de cada empresa. La 2 trae la
# lectura tolerante: una carpeta indexada con la 1 se recorre otra vez, una sola
# vez, solo por los XML que la 1 rechazaba (los que no se leen en modo estricto,
# `solo_mal_formados`); lo demás ya está en el índice.
INDEXADO_CARPETA_VERSION = "2"

# Un indexado en segundo plano a la vez: comparten CPU y el candado de la DB.
_en_curso = threading.Lock()

Contenido = Union[bytes, Path]


def pertenece_a(cfdi, mi_rfc: str) -> bool:
    """¿El CFDI menciona a la empresa como emisor O receptor? strip+upper
    porque hay XMLs con el RFC en minúsculas."""
    lados = {
        (cfdi.emisor_rfc or "").strip().upper(),
        (cfdi.receptor_rfc or "").strip().upper(),
    }
    return mi_rfc in lados


def indexar(
    mi_rfc: str,
    archivos: Iterable[tuple[str, Contenido]],
    *,
    origen: Optional[str],
    direccion_fija: Optional[str] = None,
    desde: str = "",
    hasta: str = "",
    solo_mal_formados: bool = False,
) -> dict:
    """Indexa `(nombre, bytes o ruta)` bajo la empresa `mi_rfc`.

    `desde`/`hasta` (ISO, opcionales) filtran por fecha de emisión. Con
    `solo_mal_formados`, un XML que se lee en modo estricto se salta (cuenta como
    duplicado): lo usa el reindexado de la carpeta al subir de versión, porque
    esos ya los indexó la versión anterior y solo faltan los que rechazaba.
    Devuelve `{agregados, duplicados, omitidos_rfc, errores, archivos_encontrados}`.
    """
    mi_rfc = normalizar_mi_rfc(mi_rfc)
    db = abrir_db()
    total = {"agregados": 0, "duplicados": 0, "omitidos_rfc": 0,
             "errores": [], "archivos_encontrados": 0}
    lote: list = []
    xmls: dict[str, bytes] = {}

    def _vaciar() -> None:
        if not lote:
            return
        r = db.agregar(lote, mi_rfc=mi_rfc, direccion_fija=direccion_fija,
                       xmls=xmls, origen=origen)
        total["agregados"] += r["agregados"]
        total["duplicados"] += r["duplicados"]
        lote.clear()
        xmls.clear()

    for nombre, contenido in archivos:
        total["archivos_encontrados"] += 1
        try:
            xml = contenido.read_bytes() if isinstance(contenido, Path) else contenido
            if solo_mal_formados and _lee_estricto(xml):
                total["duplicados"] += 1
                continue
            cfdi = parse_cfdi(xml, file_name=nombre)
            if desde and cfdi.fecha_emision and cfdi.fecha_emision < desde:
                continue
            if hasta and cfdi.fecha_emision and cfdi.fecha_emision > hasta:
                continue
            # La carpeta de descargas puede tener XMLs movidos a mano que no
            # son de esta empresa.
            if not pertenece_a(cfdi, mi_rfc):
                total["omitidos_rfc"] += 1
                continue
            validar_y_anotar(cfdi)
        except CfdiParseError as e:
            total["errores"].append({"filename": nombre, "mensaje": str(e)})
            continue
        except Exception as e:  # noqa: BLE001
            logger.exception("[indexar] error parseando %s", nombre)
            total["errores"].append({"filename": nombre, "mensaje": str(e)})
            continue
        lote.append(cfdi)
        if cfdi.uuid:
            xmls[cfdi.uuid] = xml
        if len(lote) >= LOTE:
            _vaciar()
    _vaciar()
    return total


def _lee_estricto(xml: bytes) -> bool:
    try:
        fromstring_seguro(xml)
        return True
    except etree.XMLSyntaxError:
        return False


def xmls_de_carpeta(carpeta: Union[str, Path]) -> Iterator[tuple[str, Path]]:
    """`(nombre, ruta)` de cada `.xml` bajo `carpeta` (recursivo)."""
    base = Path(carpeta)
    if not base.is_dir():
        return
    for ruta in sorted(base.rglob("*")):
        if ruta.is_file() and ruta.suffix.lower() == ".xml":
            yield ruta.name, ruta


def indexar_carpeta(mi_rfc: str, carpeta: Union[str, Path], *, origen: Optional[str],
                    **kwargs) -> dict:
    return indexar(mi_rfc, xmls_de_carpeta(carpeta), origen=origen, **kwargs)


def automatico_activo() -> bool:
    return os.environ.get("SAT_DM_SIN_INDEXADO") != "1"


def indexar_descarga(rfc: str, ruta: str, canal: str) -> Optional[threading.Thread]:
    """Indexa en segundo plano lo que acaba de bajar una descarga de CFDI.
    Best-effort: un fallo aquí nunca afecta la descarga."""
    if not (automatico_activo() and rfc and ruta):
        return None
    origen = ORIGEN_POR_CANAL.get(canal, canal)
    return _en_hilo(f"indexar-{rfc}", _indexar_registrando, rfc, ruta, origen)


def indexar_descargas_existentes(base: Union[str, Path]) -> Optional[threading.Thread]:
    """Una vez por empresa: indexa lo que ya está en `{base}/cfdi/{RFC}/`
    (descargas previas al índice permanente). Corre en segundo plano."""
    if not automatico_activo():
        return None
    return _en_hilo("indexar-existentes", _indexar_existentes, Path(base))


def _en_hilo(nombre: str, fn, *args) -> threading.Thread:
    def _correr():
        with _en_curso:
            try:
                fn(*args)
            except Exception:  # noqa: BLE001 — el indexado nunca tumba al agente
                logger.exception("[indexar] falló %s", nombre)

    hilo = threading.Thread(target=_correr, name=nombre, daemon=True)
    hilo.start()
    return hilo


def _indexar_registrando(rfc: str, ruta: str, origen: str) -> None:
    r = indexar_carpeta(rfc, ruta, origen=origen)
    logger.info(
        "[indexar] %s: %d nuevos, %d ya estaban, %d errores (%s)",
        rfc, r["agregados"], r["duplicados"], len(r["errores"]), ruta,
    )


def _indexar_existentes(base: Path) -> None:
    from ..cli import config_store
    from ..core import paths

    db = abrir_db()
    for emp in config_store.list_empresas():
        if emp.get("archived_at"):
            continue
        rfc = emp["rfc"]
        llave = f"indexado_carpeta:{normalizar_mi_rfc(rfc)}"
        previa = db.meta_get(llave)
        if previa == INDEXADO_CARPETA_VERSION:
            continue
        carpeta = paths.dir_cfdi_base(rfc, salida_base=base)
        r = indexar_carpeta(rfc, carpeta, origen="carpeta", solo_mal_formados=previa == "1")
        db.meta_set(llave, INDEXADO_CARPETA_VERSION)
        logger.info(
            "[indexar] %s: carpeta de descargas indexada — %d nuevos, %d ya estaban",
            rfc, r["agregados"], r["duplicados"],
        )

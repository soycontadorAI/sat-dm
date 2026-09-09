"""
Composición centralizada de las rutas de salida LOCAL de las descargas.

Única fuente de verdad del layout `descargas/`, agrupado por **tipo de documento → RFC**
(no por método de autenticación: al usuario no le importa si bajó por CIEC o e.firma).

    descargas/
      cfdi/{RFC}/{emitidos|recibidos}/{desde}_a_{hasta}/...
      constancia/{RFC}/constancia_{RFC}_{YYYYMMDD}.pdf
      opinion/{RFC}/opinion32d_{RFC}_{YYYYMMDD}.pdf

Vive en `core/` (sumidero de dependencias: lo pueden importar `cli/`, `portal/`,
`webservice/`, `api/` sin ciclos). Solo usa stdlib.

Cambiar singular↔plural de las carpetas de tipo, o apagar la agrupación por solicitud,
es un único edit aquí (las constantes de abajo).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional, Union

# --- Punto único para nombrar las carpetas (singular ↔ plural) -------------
BASE_DIR = "descargas"          # wrapper raíz (plural, estilo "Descargas/Documentos")
TIPO_CFDI = "cfdi"              # categoría en singular; → "cfdis" para plural
TIPO_CONSTANCIA = "constancia"  # → "constancias"
TIPO_OPINION = "opinion"        # → "opiniones"
TIPO_RENOVACION = "renovacion"  # e.firma: .ren/.key/acuse/cer del trámite de renovación
TIPO_CSD = "csd"                # CSD: .sdg/.key/acuse/cer por solicitud de sello
TIPO_CE = "ce"                  # contabilidad electrónica: acuses AR_/AP_ por envío
TIPO_DECLARACION = "declaracion"  # declaraciones presentadas + acuses, por periodo YYYY-MM

SUB_EMITIDOS = "emitidos"       # colecciones en plural
SUB_RECIBIDOS = "recibidos"
_SUB_POR_TIPO = {"E": SUB_EMITIDOS, "R": SUB_RECIBIDOS}

# True  = una carpeta por solicitud, nombrada por rango ({desde}_a_{hasta}/).
# False = plano: todos los XML juntos bajo emitidos/recibidos (reorganizar luego
#         con `sat-dm organizar`).
AGRUPAR_POR_EVENTO = True


def base() -> Path:
    """Raíz `descargas/` (relativa al cwd)."""
    return Path(BASE_DIR)


def _raiz(salida_base: Optional[Union[str, Path]]) -> Path:
    """Base efectiva: el `--salida` del usuario si lo dio, si no `descargas/`."""
    return Path(salida_base) if salida_base else base()


def etiqueta_rango(desde: date, hasta: date) -> str:
    """Nombre de la carpeta de solicitud: ``2026-01-01_a_2026-03-31``."""
    return f"{desde.isoformat()}_a_{hasta.isoformat()}"


def dir_cfdi(
    rfc: str,
    tipo: str,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    *,
    salida_base: Optional[Union[str, Path]] = None,
) -> Path:
    """
    ``descargas/cfdi/{RFC}/{emitidos|recibidos}/[{desde}_a_{hasta}]/``

    El nivel de carpeta por solicitud se omite si `AGRUPAR_POR_EVENTO` es False o si
    no se pasan ambas fechas.

    Args:
        tipo: "E" (emitidos) o "R" (recibidos).
    """
    d = _raiz(salida_base) / TIPO_CFDI / rfc.strip().upper() / _SUB_POR_TIPO[tipo.strip().upper()]
    if AGRUPAR_POR_EVENTO and desde is not None and hasta is not None:
        d = d / etiqueta_rango(desde, hasta)
    return d


def dir_cfdi_base(rfc: str, *, salida_base: Optional[Union[str, Path]] = None) -> Path:
    """``descargas/cfdi/{RFC}/`` — usado por `retomar` (sin tipo ni fechas conocidos)."""
    return _raiz(salida_base) / TIPO_CFDI / rfc.strip().upper()


def dir_documento(
    tipo_doc: str,
    rfc: str,
    *,
    salida_base: Optional[Union[str, Path]] = None,
) -> Path:
    """
    ``descargas/{tipo_doc}/{RFC}/`` para documentos PDF (constancia, opinión).

    Args:
        tipo_doc: una de las constantes `TIPO_CONSTANCIA` / `TIPO_OPINION`.
        rfc: si viene vacío (p. ej. FIEL sin resolver aún), usa ``sin_rfc``.
    """
    rfc_seg = rfc.strip().upper() if rfc and rfc.strip() else "sin_rfc"
    return _raiz(salida_base) / tipo_doc / rfc_seg


def dir_ce(
    rfc: str,
    ejercicio: Union[int, str],
    *,
    salida_base: Optional[Union[str, Path]] = None,
) -> Path:
    """``descargas/ce/{RFC}/{ejercicio}/`` — acuses de contabilidad electrónica.

    El nivel {ejercicio} espeja ``diot/presentaciones/{RFC}/{ejercicio}/`` y evita
    mezclar años (hasta 13 periodos x 2 acuses AR_/AP_ por año).
    """
    return dir_documento(TIPO_CE, rfc, salida_base=salida_base) / str(ejercicio)


def dir_declaraciones(
    rfc: str,
    *,
    salida_base: Optional[Union[str, Path]] = None,
) -> Path:
    """``descargas/declaracion/{RFC}/`` — el scraper anida ``{YYYY-MM}/`` por periodo
    con la declaración y su acuse (normal y complementarias)."""
    return dir_documento(TIPO_DECLARACION, rfc, salida_base=salida_base)


def dir_diot_consultas(
    rfc: str,
    *,
    salida_base: Optional[Union[str, Path]] = None,
) -> Path:
    """``descargas/diot/consultas/{RFC}/`` — DIOT presentadas (PDF, Excel) y acuses,
    anidadas por ``{YYYY-MM}/``. Hermana de ``diot/presentaciones/{RFC}/``."""
    return _raiz(salida_base) / "diot" / "consultas" / (rfc.strip().upper() if rfc and rfc.strip() else "sin_rfc")

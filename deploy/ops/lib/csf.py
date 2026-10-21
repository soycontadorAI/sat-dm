"""Lectura LOCAL de la Constancia de Situación Fiscal (CSF) para los agentes de ops.

Sin LLM y sin red: pdfplumber lee el PDF y reglas fijas sacan RFC, nombre o razón
social, tipo de persona, regímenes activos y código postal fiscal. Costo cero,
resultado determinista, y los datos fiscales del cliente no salen del contenedor.

Vive aparte de `sat_descarga/utils/csf_parser.py` porque la imagen de ops se
construye con el contexto `deploy/ops` y no lleva el paquete `sat_descarga`.
`tests/test_ops_csf_adjuntos.py` compara los dos parsers sobre las mismas tablas
para que no se desfasen. Misma calibración que el parser del núcleo: el SAT
comprime el espaciado de las celdas, así que se lee con `text_x_tolerance=1`.

Dos capas, como en el núcleo:
  - `extraer_de_pdf()` — única que toca pdfplumber: bytes → (texto, tablas).
  - `parsear_contenido()` — pura (texto + tablas → DatosCsf), testeable sin PDFs
    reales (las constancias contienen datos personales y no se commitean).
"""

from __future__ import annotations

import io
import re
import signal
import threading
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Optional

# Un PDF que llega por correo viene de afuera: topes para que uno raro no
# cuelgue ni infle la corrida (una CSF real tiene 2-3 páginas).
MAX_PAGINAS = 8
SEGUNDOS_MAX = 20

_TABLE_SETTINGS = {"text_x_tolerance": 1}

_RE_TITULO = re.compile(r"CONSTANCIA\s*DE\s*SITUACI[OÓ]N\s*FISCAL", re.I)
_RE_CEDULA = re.compile(r"C[EÉ]DULA\s*DE\s*IDENTIFICACI[OÓ]N\s*FISCAL", re.I)
_RE_RFC_LINEA = re.compile(r"^\s*RFC:?\s*([A-ZÑ&0-9]{12,13})\s*$", re.M)
_RE_CP = re.compile(r"C[oó]digo\s*Postal:?\s*(\d{5})", re.I)
_RE_FILA_REGIMEN = re.compile(
    r"^(.+?)\s+(\d{2}/\d{2}/\d{4})(?:\s+(\d{2}/\d{2}/\d{4}))?$"
)


@dataclass
class DatosCsf:
    rfc: str
    nombre: str  # tal cual el SAT, sin el régimen de capital (S.A. de C.V., etc.)
    tipo_persona: str  # "PM" | "PF" | "" si no se pudo determinar
    regimenes: list[str] = field(default_factory=list)  # solo los activos
    codigo_postal: str = ""  # CP del domicilio fiscal

    def faltantes(self) -> list[str]:
        """Lo que la lectura no pudo obtener (vacío = datos completos)."""
        falta = []
        if not self.rfc:
            falta.append("RFC")
        if not self.nombre:
            falta.append("nombre o razón social")
        if not self.regimenes:
            falta.append("régimen fiscal")
        if not self.codigo_postal:
            falta.append("código postal fiscal")
        return falta

    @property
    def completa(self) -> bool:
        return not self.faltantes()


def _celda(valor) -> str:
    """Celda cruda de pdfplumber → texto en una línea (None → "")."""
    return " ".join((valor or "").split())


def _plano(texto: str) -> str:
    """Clave de comparación tolerante a espacios perdidos y a acentos."""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", "", sin_acentos).lower()


def _valor_fila(tablas: list, *etiquetas: str) -> Optional[str]:
    """Valor de una fila etiqueta→valor (p. ej. la tabla de identificación)."""
    planas = [_plano(e) for e in etiquetas]
    for tabla in tablas:
        for fila in tabla:
            if len(fila) >= 2 and _plano(_celda(fila[0])) in planas:
                valor = _celda(fila[1])
                if valor:
                    return valor
    return None


def _valor_linea(texto: str, patron: str) -> Optional[str]:
    """Primer grupo de `patron` buscado línea por línea en el texto plano."""
    m = re.search(patron, texto, re.I | re.M)
    return _celda(m.group(1)) if m and _celda(m.group(1)) else None


def _nombre_desde_cedula(tablas: list) -> str:
    """Nombre desde el bloque de la cédula (QR): líneas entre "Registro Federal
    de Contribuyentes" y "Nombre, denominación o razón social". Es la fuente con
    espacios más confiables, y ya excluye el régimen de capital."""
    for tabla in tablas:
        for fila in tabla:
            for celda in fila:
                if not celda or "Registro Federal de Contribuyentes" not in celda:
                    continue
                lineas = [" ".join(l.split()) for l in celda.splitlines()]
                inicio = fin = None
                for i, linea in enumerate(lineas):
                    plano = _plano(linea)
                    if plano == "registrofederaldecontribuyentes":
                        inicio = i
                    elif inicio is not None and plano.startswith("nombre,denominaci"):
                        fin = i
                        break
                if inicio is not None and fin is not None and fin > inicio + 1:
                    nombre = " ".join(l for l in lineas[inicio + 1:fin] if l)
                    if nombre:
                        return nombre
    return ""


def _filas_de_seccion(tablas: list, *encabezados: str) -> list[list[str]]:
    """Filas de datos de las tablas cuyo encabezado contenga TODOS los
    `encabezados` (las tablas que continúan en otra página repiten el suyo)."""
    planos = [_plano(e) for e in encabezados]
    filas: list[list[str]] = []
    for tabla in tablas:
        idx = None
        for i, fila in enumerate(tabla):
            if all(p in _plano(" ".join(_celda(c) for c in fila)) for p in planos):
                idx = i
                break
        if idx is None:
            continue
        for fila in tabla[idx + 1:]:
            normalizada = [_celda(c) for c in fila]
            if any(normalizada):
                filas.append(normalizada)
    return filas


def _regimenes(texto: str, tablas: list) -> list[str]:
    """Regímenes activos (sin Fecha Fin). Por tabla; si la tabla no salió, por
    las líneas de texto bajo el encabezado "Régimen Fecha Inicio Fecha Fin"."""
    activos = []
    for fila in _filas_de_seccion(tablas, "Régimen", "Fecha Inicio"):
        if len(fila) < 2 or not fila[0]:
            continue
        fecha_fin = fila[2] if len(fila) >= 3 else ""
        if not fecha_fin:
            activos.append(fila[0])
    if activos:
        return activos
    lineas = texto.splitlines()
    for i, linea in enumerate(lineas):
        if _plano(linea) == _plano("Régimen Fecha Inicio Fecha Fin"):
            for siguiente in lineas[i + 1:]:
                m = _RE_FILA_REGIMEN.match(siguiente.strip())
                if not m:
                    break
                if not m.group(3):
                    activos.append(m.group(1))
            break
    return activos


def _codigo_postal(texto: str, tablas: list) -> str:
    m = _RE_CP.search(texto)
    if m:
        return m.group(1)
    for tabla in tablas:
        for fila in tabla:
            for celda in fila:
                m = _RE_CP.search(celda or "")
                if m:
                    return m.group(1)
    return ""


def parsear_contenido(texto: str, tablas: list) -> Optional[DatosCsf]:
    """Capa pura: texto + tablas crudas de pdfplumber → DatosCsf.

    None si el documento no parece una CSF. Si lo parece pero la lectura quedó
    incompleta, devuelve lo que alcanzó (`faltantes()` dice qué no).
    """
    if not (_RE_TITULO.search(texto) or _RE_CEDULA.search(texto)):
        return None

    rfc = _valor_fila(tablas, "RFC:")
    if not rfc:
        m = _RE_RFC_LINEA.search(texto)
        rfc = m.group(1) if m else ""

    razon_social = _valor_fila(tablas, "Denominación/Razón Social:") or _valor_linea(
        texto, r"Denominaci[oó]n\s*/\s*Raz[oó]n\s*Social:?\s*(.+)$"
    )
    nombre_pf = [
        _valor_fila(tablas, "Nombre (s):", "Nombre(s):")
        or _valor_linea(texto, r"^\s*Nombre\s*\(s\):?\s*(.+)$"),
        _valor_fila(tablas, "Primer Apellido:", "PrimerApellido:")
        or _valor_linea(texto, r"^\s*Primer\s*Apellido:?\s*(.+)$"),
        _valor_fila(tablas, "Segundo Apellido:", "SegundoApellido:")
        or _valor_linea(texto, r"^\s*Segundo\s*Apellido:?\s*(.+)$"),
    ]

    if razon_social:
        tipo = "PM"
    elif nombre_pf[0]:
        tipo = "PF"
    elif len(rfc) in (12, 13):
        tipo = "PM" if len(rfc) == 12 else "PF"
    else:
        tipo = ""

    nombre = _nombre_desde_cedula(tablas)
    if not nombre:
        nombre = (razon_social or "") if tipo == "PM" else " ".join(p for p in nombre_pf if p)

    return DatosCsf(
        rfc=rfc,
        nombre=nombre.strip(),
        tipo_persona=tipo,
        regimenes=_regimenes(texto, tablas),
        codigo_postal=_codigo_postal(texto, tablas),
    )


@contextmanager
def _limite_tiempo(segundos: int):
    """Corta la lectura si un PDF raro se atora (solo hilo principal, Linux/mac)."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(
        signal, "SIGALRM"
    ):
        yield
        return

    def _alarma(*_):
        raise TimeoutError(f"lectura de PDF excedió {segundos}s")

    previo = signal.signal(signal.SIGALRM, _alarma)
    signal.alarm(segundos)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previo)


def _extraer_pdf(contenido: bytes) -> tuple[str, list]:
    """Única capa que toca pdfplumber: bytes del PDF → (texto, tablas crudas)."""
    import pdfplumber

    textos: list[str] = []
    tablas: list = []
    with pdfplumber.open(io.BytesIO(contenido)) as pdf:
        for pagina in pdf.pages[:MAX_PAGINAS]:
            textos.append(
                pagina.extract_text(x_tolerance=_TABLE_SETTINGS["text_x_tolerance"]) or ""
            )
            tablas.extend(pagina.extract_tables(_TABLE_SETTINGS) or [])
    return "\n".join(textos), tablas


def extraer_de_pdf(contenido: bytes) -> Optional[DatosCsf]:
    """Bytes de un PDF → DatosCsf, o None si no es una CSF.

    Si el PDF no se puede leer (corrupto, cifrado, demasiado lento) la excepción
    sube: quien llama distingue "no es una CSF" de "no se pudo leer".
    """
    with _limite_tiempo(SEGUNDOS_MAX):
        texto, tablas = _extraer_pdf(contenido)
    return parsear_contenido(texto, tablas)

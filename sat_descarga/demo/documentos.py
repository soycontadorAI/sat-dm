"""
Documentos de ejemplo del modo de grabación: Constancia de Situación Fiscal,
Opinión de Cumplimiento 32-D y la imagen del captcha del portal.

Los PDF siguen la forma de los del SAT lo suficiente para que los parsers de la
app (`utils/csf_parser.py` y `utils/opinion_parser.py`) los lean igual que a
los reales: así el semáforo, los regímenes y los motivos de una negativa salen
del mismo camino de código. Cada PDF lleva la franja "DOCUMENTO DE EJEMPLO" por
si llega a abrirse en cuadro (lo piden los guiones).

El captcha es un PNG armado a mano (sin Pillow, que no viaja en el binario del
agente): seis caracteres con una fuente de 5×7 y algo de ruido.
"""

from __future__ import annotations

import hashlib
import random
import struct
import zlib
from datetime import date
from pathlib import Path
from typing import Optional

from .escenario import EMPRESAS, MOTIVOS_32D

MARCA = "DOCUMENTO DE EJEMPLO  ·  Modo de grabación de TodoConta  ·  Sin validez fiscal"

_MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO",
          "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE")

_REGIMEN_CAPITAL = "SOCIEDAD ANONIMA DE CAPITAL VARIABLE"

_OBLIGACIONES_PM = (
    ("Declaración anual de ISR del ejercicio Personas morales.",
     "A más tardar el 31 de marzo del ejercicio siguiente."),
    ("Pago definitivo mensual de IVA.",
     "A más tardar el día 17 del mes inmediato posterior al periodo que corresponda."),
    ("Pago provisional mensual de ISR personas morales régimen general",
     "A más tardar el día 17 del mes inmediato posterior al periodo que corresponda."),
    ("Declaración informativa de IVA con la anual de ISR",
     "A más tardar el 31 de marzo del ejercicio siguiente."),
)
_OBLIGACIONES_PF = (
    ("Declaración anual de ISR. Personas Físicas.",
     "A más tardar el 30 de abril del ejercicio siguiente."),
    ("Pago definitivo mensual de IVA.",
     "A más tardar el día 17 del mes inmediato posterior al periodo que corresponda."),
)


def _pdf():
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="Letter")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(14, 12, 14)
    pdf.add_page()
    return pdf


def _franja(pdf) -> None:
    pdf.set_fill_color(236, 236, 236)
    pdf.set_text_color(70, 70, 70)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 6, MARCA, border=0, align="C", fill=True,
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)


def _sello(texto: str, n: int = 172) -> str:
    import base64

    crudo = b""
    i = 0
    while len(crudo) < n:
        crudo += hashlib.sha512(f"{texto}|{i}".encode()).digest()
        i += 1
    return base64.b64encode(crudo[:n]).decode()


def _fecha_larga(d: date) -> str:
    return f"{d.day:02d} DE {_MESES[d.month - 1]} DE {d.year}"


def _tabla(pdf, filas, anchos, encabezado: bool = True, tam: float = 8) -> None:
    """Tabla con bordes (pdfplumber la reconoce como tabla por las líneas)."""
    from fpdf.fonts import FontFace

    pdf.set_font("Helvetica", "", tam)
    with pdf.table(col_widths=anchos, text_align="LEFT", line_height=4.6,
                   first_row_as_headings=encabezado,
                   headings_style=FontFace(emphasis="BOLD")) as tabla:
        for fila in filas:
            renglon = tabla.row()
            for celda in fila:
                renglon.cell(str(celda))
    pdf.ln(3)


def _titulo_seccion(pdf, texto: str) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, texto, new_x="LMARGIN", new_y="NEXT")


# ---------------------------------------------------------------------------
# Constancia de Situación Fiscal
# ---------------------------------------------------------------------------

def constancia_pdf(rfc: str, destino: Path, hoy: Optional[date] = None) -> Path:
    """Escribe la CSF de ejemplo de la empresa de demo `rfc` en `destino`."""
    emp = EMPRESAS[rfc.upper()]
    hoy = hoy or date.today()
    id_cif = f"{int(hashlib.sha256(('idcif' + emp.rfc).encode()).hexdigest(), 16) % 10**11:011d}"
    pdf = _pdf()
    _franja(pdf)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "CONSTANCIA DE SITUACIÓN FISCAL", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, "CÉDULA DE IDENTIFICACIÓN FISCAL", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # Bloque de la cédula: el parser toma el nombre de las líneas entre
    # "Registro Federal de Contribuyentes" y "Nombre, denominación o razón social".
    cedula = "\n".join((
        emp.rfc,
        "Registro Federal de Contribuyentes",
        emp.nombre,
        "Nombre, denominación o razón social",
        f"idCIF: {id_cif}",
        "VALIDA TU INFORMACIÓN FISCAL",
    ))
    lugar = (f"Lugar y Fecha de Emisión\n{emp.municipio} , {emp.estado} A "
             f"{_fecha_larga(hoy)}")
    _tabla(pdf, [(cedula, lugar)], (95, 93), encabezado=False, tam=9)

    _titulo_seccion(pdf, "Datos de Identificación del Contribuyente:")
    if emp.tipo == "PM":
        identificacion = [
            ("RFC:", emp.rfc),
            ("Denominación/Razón Social:", emp.nombre),
            ("Régimen Capital:", _REGIMEN_CAPITAL),
            ("Nombre Comercial:", emp.nombre),
            ("Fecha inicio de operaciones:", emp.inicio_operaciones),
            ("Estatus en el padrón:", "ACTIVO"),
            ("Fecha de último cambio de estado:", emp.inicio_operaciones),
        ]
    else:
        partes = emp.nombre.split()
        identificacion = [
            ("RFC:", emp.rfc),
            ("CURP:", emp.curp),
            ("Nombre (s):", " ".join(partes[:-2])),
            ("Primer Apellido:", partes[-2]),
            ("Segundo Apellido:", partes[-1]),
            ("Fecha inicio de operaciones:", emp.inicio_operaciones),
            ("Estatus en el padrón:", "ACTIVO"),
            ("Fecha de último cambio de estado:", emp.inicio_operaciones),
        ]
    _tabla(pdf, identificacion, (70, 118), encabezado=False)

    _titulo_seccion(pdf, "Datos del domicilio registrado")
    calle, _, numero = emp.calle.rpartition(" ")
    _tabla(pdf, [
        ("Código Postal:", emp.cp),
        ("Nombre de Vialidad:", calle or emp.calle),
        ("Número Exterior:", numero),
        ("Nombre de la Colonia:", emp.colonia),
        ("Nombre del Municipio o Demarcación Territorial:", emp.municipio),
        ("Nombre de la Entidad Federativa:", emp.estado),
    ], (70, 118), encabezado=False)

    _titulo_seccion(pdf, "Actividades Económicas:")
    _tabla(pdf, [("Orden", "Actividad Económica", "Porcentaje", "Fecha Inicio", "Fecha Fin")]
           + [(str(i + 1), desc, str(pct), inicio, "")
              for i, (desc, pct, inicio) in enumerate(emp.actividades)],
           (14, 104, 22, 26, 22))

    _titulo_seccion(pdf, "Regímenes:")
    _tabla(pdf, [("Régimen", "Fecha Inicio", "Fecha Fin")]
           + [(desc, inicio, "") for _clave, desc, inicio in emp.regimenes],
           (124, 32, 32))

    _titulo_seccion(pdf, "Obligaciones:")
    obligaciones = _OBLIGACIONES_PM if emp.tipo == "PM" else _OBLIGACIONES_PF
    _tabla(pdf, [("Descripción de la Obligación", "Descripción Vencimiento", "Fecha Inicio", "Fecha Fin")]
           + [(o, v, emp.inicio_operaciones, "") for o, v in obligaciones],
           (66, 78, 24, 20), tam=7)

    pdf.set_font("Helvetica", "", 7)
    cadena = (f"||{hoy.strftime('%Y/%m/%d')}|{emp.rfc}|CONSTANCIA DE SITUACIÓN FISCAL|"
              f"{id_cif}|{hoy.strftime('%Y%m%d')}||")
    pdf.multi_cell(0, 3.5, f"Cadena Original Sello: {cadena}", align="L",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 3.5, f"Sello Digital: {_sello('csf' + emp.rfc + hoy.isoformat())}",
                   align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _franja(pdf)

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(destino))
    return destino


# ---------------------------------------------------------------------------
# Opinión de Cumplimiento 32-D
# ---------------------------------------------------------------------------

_TEXTO_POSITIVA = (
    "En atención a su consulta, se le informa que en los controles electrónicos",
    "institucionales del SAT, y con base en la información proporcionada por el",
    "contribuyente, se encuentra al corriente en el cumplimiento de sus obligaciones",
    "fiscales, por lo que se emite esta opinión del cumplimiento en sentido POSITIVO.",
)
_TEXTO_NEGATIVA = (
    "En atención a su consulta, se le informa que en los controles electrónicos",
    "institucionales del SAT se detectó que no se encuentra al corriente en el",
    "cumplimiento de sus obligaciones fiscales, por lo que se emite esta opinión",
    "del cumplimiento en sentido NEGATIVO.",
    "Los motivos por los que se emite la opinión en sentido negativo se detallan a continuación:",
)
_INFO_IMPORTANTE = (
    "Información importante",
    "La presente opinión se emite con base en la información con que cuenta el SAT",
    "a la fecha de su emisión y no constituye resolución en sentido favorable al contribuyente.",
    "Opinión de ejemplo generada por el modo de grabación de TodoConta: no es un documento del SAT.",
)


def folio_opinion(rfc: str, hoy: date) -> str:
    h = int(hashlib.sha256(f"folio32d|{rfc}|{hoy.isoformat()}".encode()).hexdigest(), 16)
    return f"26NA{h % 10**7:07d}"


def opinion_pdf(rfc: str, destino: Path, hoy: Optional[date] = None,
                sentido: Optional[str] = None) -> Path:
    """Escribe la Opinión 32-D de ejemplo (positiva o negativa con motivos)."""
    emp = EMPRESAS[rfc.upper()]
    hoy = hoy or date.today()
    sentido = sentido or emp.opinion
    negativa = sentido == "negativa"
    folio = folio_opinion(emp.rfc, hoy)
    pdf = _pdf()
    _franja(pdf)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, "Opinión del cumplimiento de obligaciones fiscales", align="C",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 9)
    for linea in (
        f"Folio: {folio}",
        f"Clave de R.F.C.: {emp.rfc}",
        f"Nombre, denominación o razón social: {emp.nombre}",
        f"Fecha: {hoy.day:02d} de {_MESES[hoy.month - 1].lower()} de {hoy.year}",
        f"Sentido: {'NEGATIVO' if negativa else 'POSITIVO'}",
    ):
        pdf.cell(0, 5, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    for linea in (_TEXTO_NEGATIVA if negativa else _TEXTO_POSITIVA):
        pdf.cell(0, 5, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if negativa:
        for motivo in MOTIVOS_32D.get(emp.rfc, ()):
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 5, motivo.titulo, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8.5)
            pdf.cell(0, 4.6, motivo.descripcion, new_x="LMARGIN", new_y="NEXT")
            for detalle in motivo.detalles:
                tam = 8.0
                pdf.set_font("Helvetica", "", tam)
                while pdf.get_string_width(detalle) > 186 and tam > 5.5:
                    tam -= 0.5
                    pdf.set_font("Helvetica", "", tam)
                pdf.cell(0, 4.4, detalle, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1.5)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, _INFO_IMPORTANTE[0], new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    for linea in _INFO_IMPORTANTE[1:]:
        pdf.cell(0, 4.4, linea, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    letra = "N" if negativa else "P"
    pdf.set_font("Helvetica", "", 7)
    cadena = f"||{emp.rfc}|{folio}|{hoy.strftime('%d-%m-%Y')}|{letra}||00001088888800000031||"
    pdf.cell(0, 4, f"Cadena Original: {cadena}", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 3.5, f"Sello Digital: {_sello('32d' + emp.rfc + hoy.isoformat())}",
                   align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    _franja(pdf)

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(destino))
    return destino


# ---------------------------------------------------------------------------
# Captcha (PNG en escala de grises, sin dependencias)
# ---------------------------------------------------------------------------

_FUENTE = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "10101", "01010"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
}


def _png_gris(ancho: int, alto: int, pixeles: bytearray) -> bytes:
    def chunk(tipo: bytes, datos: bytes) -> bytes:
        return (struct.pack(">I", len(datos)) + tipo + datos
                + struct.pack(">I", zlib.crc32(tipo + datos) & 0xFFFFFFFF))

    crudo = b"".join(b"\x00" + bytes(pixeles[y * ancho:(y + 1) * ancho]) for y in range(alto))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", ancho, alto, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(crudo, 9))
            + chunk(b"IEND", b""))


def captcha_png(texto: Optional[str] = None, semilla: Optional[int] = None) -> tuple:
    """Devuelve (texto, png_bytes) de un captcha con aspecto del portal."""
    rng = random.Random(semilla)
    letras = "".join(sorted(_FUENTE))
    texto = (texto or "".join(rng.choice(letras) for _ in range(6))).upper()
    escala, ancho, alto = 4, 220, 60
    pix = bytearray([238] * (ancho * alto))
    for _ in range(ancho * alto // 9):  # moteado de fondo
        pix[rng.randrange(ancho * alto)] = rng.randint(150, 215)
    x = 14
    for ch in texto:
        glifo = _FUENTE.get(ch)
        if glifo is None:
            continue
        dy = rng.randint(12, 20)
        tono = rng.randint(30, 80)
        for fila, bits in enumerate(glifo):
            for col, bit in enumerate(bits):
                if bit != "1":
                    continue
                inclinacion = (6 - fila) // 2
                for sy in range(escala):
                    for sx in range(escala):
                        px = x + col * escala + sx + inclinacion
                        py = dy + fila * escala + sy
                        if 0 <= px < ancho and 0 <= py < alto:
                            pix[py * ancho + px] = tono
        x += 5 * escala + rng.randint(9, 13)
    for _ in range(3):  # líneas que cruzan el texto
        y0, y1 = rng.randint(8, alto - 8), rng.randint(8, alto - 8)
        for px in range(ancho):
            py = y0 + (y1 - y0) * px // ancho
            for grosor in (0, 1):
                if 0 <= py + grosor < alto:
                    pix[(py + grosor) * ancho + px] = 110
    return texto, _png_gris(ancho, alto, pix)

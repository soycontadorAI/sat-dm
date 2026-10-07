"""
Catálogo de contrapartes y conceptos del escenario de grabación.

Proveedores, clientes y empleados de las 7 empresas de demo, con los conceptos
que facturan. Todo inventado. Los RFC/CURP se derivan del nombre con una fecha
IMPOSIBLE (31 de febrero, 31 de abril…): pasan el formato que valida la app,
pero nunca coinciden con un contribuyente real (los guiones lo piden así).

Lo usa `cfdi.py` para armar los comprobantes. Datos puros + dos helpers.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from typing import Optional

from .escenario import EL_ROBLE, LISTAS_NEGRAS, MOLINA, NORMA, PANADERIA

# ---------------------------------------------------------------------------
# RFC / CURP ficticios
# ---------------------------------------------------------------------------

_FECHAS_IMPOSIBLES = (("02", "30"), ("02", "31"), ("04", "31"), ("06", "31"),
                      ("09", "31"), ("11", "31"))
_HOMO = "ABCDEFGHJKLMNPRSTUVWXYZ123456789"
_IGNORAR = {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "E", "EN", "SA", "CV",
            "S", "A", "C", "V", "RL", "SAPI", "SC", "SPR"}
_VOCALES = "AEIOU"


def _plano(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFD", texto.upper())
    return "".join(c for c in sin_acentos if c.isalnum() or c == " ")


def _h(texto: str) -> int:
    return int(hashlib.sha256(texto.encode("utf-8")).hexdigest(), 16)


def _fecha_imposible(semilla: str, persona: str) -> str:
    h = _h(semilla)
    yy = (h % 22) if persona == "PM" else (55 + h % 45) % 100
    mm, dd = _FECHAS_IMPOSIBLES[(h >> 8) % len(_FECHAS_IMPOSIBLES)]
    return f"{yy:02d}{mm}{dd}"


def _homoclave(semilla: str) -> str:
    h = _h("homo:" + semilla)
    return _HOMO[h % 32] + _HOMO[(h >> 5) % 32] + "0123456789A"[(h >> 10) % 11]


def _letras_pf(nombre: str) -> str:
    """Nombre(s) Apellido1 Apellido2 → 4 letras del RFC de persona física."""
    partes = [p for p in _plano(nombre).split() if p not in _IGNORAR]
    nombre_pila, ap1, ap2 = partes[0], partes[-2], partes[-1]
    vocal = next((c for c in ap1[1:] if c in _VOCALES), "X")
    return ap1[0] + vocal + ap2[0] + nombre_pila[0]


def rfc_ficticio(nombre: str, persona: str = "PM") -> str:
    """RFC con formato válido y fecha imposible (no puede existir en el SAT)."""
    if persona == "PF":
        letras = _letras_pf(nombre)
    else:
        palabras = [p for p in _plano(nombre).split() if p not in _IGNORAR]
        letras = "".join(p[0] for p in palabras[:3])
        if len(letras) < 3:
            letras = (letras + palabras[0][1:] + "XXX")[:3]
    return letras + _fecha_imposible(nombre, persona) + _homoclave(nombre)


def curp_ficticia(nombre: str, sexo: str) -> str:
    """CURP de 18 posiciones con la misma fecha imposible que su RFC."""
    partes = [p for p in _plano(nombre).split() if p not in _IGNORAR]
    nombre_pila, ap1, ap2 = partes[0], partes[-2], partes[-1]

    def consonante(p: str) -> str:
        return next((c for c in p[1:] if c not in _VOCALES), "X")

    base = _letras_pf(nombre) + _fecha_imposible(nombre, "PF")
    h = _h("curp:" + nombre)
    return (base + sexo + "GT" + consonante(ap1) + consonante(ap2)
            + consonante(nombre_pila) + "0" + str(h % 10))


def nss_ficticio(nombre: str) -> str:
    return f"{_h('nss:' + nombre) % 10**11:011d}"


# ---------------------------------------------------------------------------
# Conceptos por giro: (ClaveProdServ, descripción, ClaveUnidad, unidad,
# (precio mín, precio máx), tasa IVA "16"|"0"|"exento", (cant mín, cant máx))
# ---------------------------------------------------------------------------

GIROS: dict = {
    "abarrotes": (
        ("50161509", "Azúcar estándar bulto 50 kg", "H87", "Pieza", (980, 1150), "0", (5, 60)),
        ("50151513", "Aceite vegetal comestible caja 12 pzas 1 L", "XBX", "Caja", (420, 560), "0", (5, 80)),
        ("50221102", "Arroz súper extra bulto 25 kg", "H87", "Pieza", (520, 690), "0", (4, 40)),
        ("50221101", "Frijol pinto bulto 25 kg", "H87", "Pieza", (780, 980), "0", (4, 40)),
        ("50131702", "Leche ultrapasteurizada caja 12 pzas 1 L", "XBX", "Caja", (250, 320), "0", (10, 120)),
        ("50171830", "Atún en agua caja 24 latas", "XBX", "Caja", (540, 690), "0", (5, 60)),
        ("50201706", "Café soluble caja 12 frascos 200 g", "XBX", "Caja", (980, 1350), "0", (2, 30)),
        ("50192902", "Pasta para sopa caja 20 pzas", "XBX", "Caja", (160, 230), "0", (10, 100)),
        ("50221201", "Avena en hojuelas caja 12 pzas", "XBX", "Caja", (310, 420), "0", (5, 50)),
        ("50131601", "Huevo blanco caja 360 pzas", "XBX", "Caja", (780, 960), "0", (5, 40)),
        ("50171551", "Sal refinada caja 24 pzas 1 kg", "XBX", "Caja", (190, 260), "0", (5, 40)),
        ("50112004", "Chiles en vinagre caja 24 latas", "XBX", "Caja", (380, 520), "0", (4, 40)),
    ),
    "harinas": (
        ("50221101", "Harina de trigo bulto 44 kg", "H87", "Pieza", (690, 820), "0", (10, 60)),
        ("50192902", "Pasta para sopa caja 20 pzas", "XBX", "Caja", (160, 230), "0", (10, 100)),
        ("50221201", "Harina de maíz bulto 20 kg", "H87", "Pieza", (360, 450), "0", (10, 60)),
    ),
    "lacteos": (
        ("50131702", "Leche ultrapasteurizada caja 12 pzas 1 L", "XBX", "Caja", (250, 320), "0", (10, 120)),
        ("50131800", "Queso fresco caja 10 kg", "XBX", "Caja", (980, 1260), "0", (2, 20)),
        ("50131700", "Mantequilla sin sal caja 20 kg", "XBX", "Caja", (2100, 2600), "0", (1, 10)),
    ),
    "limpieza": (
        ("47131807", "Cloro blanqueador caja 12 pzas 1 L", "XBX", "Caja", (190, 260), "16", (10, 80)),
        ("47131811", "Detergente en polvo bulto 10 kg", "H87", "Pieza", (420, 560), "16", (5, 40)),
        ("53131608", "Jabón de tocador caja 72 pzas", "XBX", "Caja", (620, 780), "16", (3, 30)),
        ("47131805", "Limpiador multiusos caja 12 pzas", "XBX", "Caja", (280, 360), "16", (5, 40)),
        ("14111704", "Papel higiénico caja 48 rollos", "XBX", "Caja", (390, 520), "16", (5, 60)),
        ("14111703", "Toalla de papel caja 12 rollos", "XBX", "Caja", (310, 420), "16", (5, 40)),
    ),
    "desechables": (
        ("52151502", "Vaso desechable caja 1000 pzas", "XBX", "Caja", (380, 480), "16", (3, 30)),
        ("24111503", "Bolsa de plástico rollo 10 kg", "H87", "Pieza", (410, 530), "16", (3, 30)),
        ("52151504", "Plato desechable caja 500 pzas", "XBX", "Caja", (290, 380), "16", (3, 30)),
    ),
    "empaque": (
        ("24112404", "Caja de cartón corrugado 40x30x30", "H87", "Pieza", (9.5, 18), "16", (200, 2000)),
        ("24141501", "Película estirable rollo 18 pulgadas", "H87", "Pieza", (240, 330), "16", (10, 80)),
        ("24112100", "Tarima de madera 1.20 x 1.00", "H87", "Pieza", (140, 210), "16", (20, 120)),
    ),
    "agua": (
        ("50202301", "Agua purificada garrafón 20 L", "H87", "Pieza", (38, 45), "0", (20, 80)),
    ),
    "combustible": (
        ("15101505", "Diésel", "LTR", "Litro", (25.4, 26.9), "16", (60, 320)),
        ("15101514", "Gasolina regular menor a 91 octanos", "LTR", "Litro", (23.6, 24.6), "16", (25, 60)),
    ),
    "gaslp": (
        ("15111510", "Gas LP para horno industrial", "LTR", "Litro", (10.9, 12.4), "16", (300, 1200)),
    ),
    "refacciones": (
        ("25174004", "Filtro de aceite para motor diésel", "H87", "Pieza", (180, 690), "16", (1, 6)),
        ("15121501", "Aceite para motor 15W40 cubeta 19 L", "H87", "Pieza", (1450, 1890), "16", (1, 6)),
        ("25174800", "Juego de balatas para camión", "H87", "Pieza", (980, 2600), "16", (1, 4)),
        ("26111702", "Batería 12 V para camión", "H87", "Pieza", (2900, 4600), "16", (1, 2)),
        ("25174300", "Banda de distribución", "H87", "Pieza", (420, 980), "16", (1, 3)),
    ),
    "taller": (
        ("78181507", "Servicio de mantenimiento preventivo a camión", "E48", "Unidad de servicio", (2800, 9800), "16", (1, 1)),
        ("78181505", "Reparación de sistema de frenos", "E48", "Unidad de servicio", (1800, 7400), "16", (1, 1)),
        ("78181506", "Alineación y balanceo", "E48", "Unidad de servicio", (650, 1400), "16", (1, 1)),
    ),
    "llantas": (
        ("25172504", "Llanta 11R22.5 para camión", "H87", "Pieza", (6200, 8900), "16", (2, 8)),
        ("25172504", "Llanta 225/75R16 para camioneta", "H87", "Pieza", (2900, 3900), "16", (2, 4)),
    ),
    "fletes": (
        ("78101802", "Servicio de flete León-Querétaro", "E48", "Unidad de servicio", (6800, 9800), "16", (1, 1)),
        ("78101802", "Servicio de flete Celaya-León", "E48", "Unidad de servicio", (4200, 6500), "16", (1, 1)),
        ("78101802", "Servicio de flete León-Guadalajara", "E48", "Unidad de servicio", (9800, 14500), "16", (1, 1)),
        ("78101802", "Servicio de flete Irapuato-San Luis Potosí", "E48", "Unidad de servicio", (8900, 12800), "16", (1, 1)),
    ),
    "arrendamiento": (
        ("80131502", "Arrendamiento de bodega comercial", "E48", "Unidad de servicio", (48000, 48000), "16", (1, 1)),
    ),
    "arrendamiento_local": (
        ("80131502", "Arrendamiento de local comercial", "E48", "Unidad de servicio", (22000, 22000), "16", (1, 1)),
    ),
    "arrendamiento_oficina": (
        ("80131502", "Arrendamiento de oficina", "E48", "Unidad de servicio", (16500, 16500), "16", (1, 1)),
    ),
    "consultoria": (
        ("80101500", "Servicios de consultoría en procesos comerciales", "E48", "Unidad de servicio", (12000, 28000), "16", (1, 1)),
    ),
    "honorarios_contables": (
        ("84111500", "Honorarios por servicios contables", "E48", "Unidad de servicio", (9500, 9500), "16", (1, 1)),
    ),
    "honorarios_ingenieria": (
        ("81101500", "Honorarios por supervisión de obra", "E48", "Unidad de servicio", (18000, 32000), "16", (1, 1)),
    ),
    "vigilancia": (
        ("92121504", "Servicio de vigilancia en bodega", "E48", "Unidad de servicio", (18500, 18500), "16", (1, 1)),
    ),
    "limpieza_srv": (
        ("76111501", "Servicio de limpieza de oficinas y bodega", "E48", "Unidad de servicio", (9800, 9800), "16", (1, 1)),
    ),
    "internet": (
        ("81112101", "Servicio de internet empresarial 200 Mbps", "E48", "Unidad de servicio", (1299, 1299), "16", (1, 1)),
    ),
    "software": (
        ("81112501", "Licencia mensual de sistema administrativo", "E48", "Unidad de servicio", (3480, 3480), "16", (1, 1)),
    ),
    "telefonia": (
        ("83111603", "Servicio de telefonía celular, plan empresarial", "E48", "Unidad de servicio", (4850, 4850), "16", (1, 1)),
    ),
    "fumigacion": (
        ("70141605", "Servicio de fumigación de bodega", "E48", "Unidad de servicio", (3200, 4500), "16", (1, 1)),
    ),
    "montacargas": (
        ("78181800", "Mantenimiento preventivo a montacargas", "E48", "Unidad de servicio", (4500, 8900), "16", (1, 1)),
    ),
    "seguros": (
        ("84131503", "Prima de seguro de flotilla, parcialidad mensual", "E48", "Unidad de servicio", (12800, 12800), "16", (1, 1)),
    ),
    "uniformes": (
        ("53102710", "Camisa tipo polo bordada", "H87", "Pieza", (240, 320), "16", (10, 40)),
        ("53111600", "Calzado industrial con casquillo", "H87", "Pieza", (690, 980), "16", (4, 20)),
    ),
    "restaurante": (
        ("90101501", "Consumo de alimentos", "E48", "Unidad de servicio", (180, 2400), "16", (1, 1)),
    ),
    "hotel": (
        ("90111501", "Hospedaje, habitación sencilla", "E48", "Unidad de servicio", (950, 1890), "16", (1, 2)),
    ),
    "papeleria": (
        ("14111507", "Papel bond carta caja 5000 hojas", "XBX", "Caja", (780, 980), "16", (1, 6)),
        ("44121704", "Bolígrafo tinta azul caja 12 pzas", "XBX", "Caja", (55, 90), "16", (1, 10)),
        ("44103103", "Tóner para impresora láser", "H87", "Pieza", (890, 1690), "16", (1, 3)),
        ("44122003", "Folder tamaño carta caja 100 pzas", "XBX", "Caja", (120, 190), "16", (1, 6)),
    ),
    "ferreteria": (
        ("31161500", "Tornillería surtida", "H87", "Pieza", (45, 380), "16", (1, 20)),
        ("31201500", "Cinta de aislar", "H87", "Pieza", (18, 35), "16", (5, 30)),
        ("27111700", "Desarmador plano", "H87", "Pieza", (65, 180), "16", (1, 5)),
        ("31211500", "Pintura vinílica cubeta 19 L", "H87", "Pieza", (1450, 2300), "16", (1, 4)),
    ),
    "electrico": (
        ("39101600", "Lámpara LED 18 W", "H87", "Pieza", (85, 160), "16", (5, 40)),
        ("26121600", "Cable THW calibre 12 caja 100 m", "XBX", "Caja", (1450, 1890), "16", (1, 4)),
    ),
    "computo": (
        ("43211507", "Computadora de escritorio", "H87", "Pieza", (11500, 16900), "16", (1, 2)),
        ("43211706", "Teclado y mouse inalámbrico", "H87", "Pieza", (390, 690), "16", (1, 6)),
    ),
    "imprenta": (
        ("82121500", "Impresión de notas de remisión, block de 100", "H87", "Pieza", (45, 90), "16", (20, 100)),
    ),
    "pension": (
        ("78181700", "Pensión mensual para camiones", "E48", "Unidad de servicio", (6800, 6800), "16", (1, 1)),
    ),
    "mensajeria": (
        ("78102203", "Servicio de mensajería", "E48", "Unidad de servicio", (180, 890), "16", (1, 1)),
    ),
    "clinica": (
        ("85121600", "Examen médico de ingreso", "E48", "Unidad de servicio", (450, 850), "16", (1, 6)),
    ),
    "capacitacion": (
        ("86101700", "Curso de manejo defensivo", "E48", "Unidad de servicio", (9800, 14500), "16", (1, 1)),
    ),
    "viajes": (
        ("90121502", "Boleto de autobús", "E48", "Unidad de servicio", (450, 1250), "16", (1, 4)),
    ),
    "basculas": (
        ("41111500", "Calibración de báscula de piso", "E48", "Unidad de servicio", (1800, 2900), "16", (1, 1)),
    ),
    "refrigeracion": (
        ("72101500", "Mantenimiento a cámara de refrigeración", "E48", "Unidad de servicio", (5800, 9800), "16", (1, 1)),
    ),
    "hornos": (
        ("72101500", "Mantenimiento a horno de piso", "E48", "Unidad de servicio", (3800, 7200), "16", (1, 1)),
    ),
    "rastreo": (
        ("81161700", "Servicio de rastreo satelital GPS por unidad", "E48", "Unidad de servicio", (390, 390), "16", (8, 14)),
    ),
    "lavado": (
        ("76111800", "Lavado de tractocamión", "E48", "Unidad de servicio", (380, 650), "16", (1, 3)),
    ),
    "cemento": (
        ("30111601", "Cemento gris bulto 50 kg", "H87", "Pieza", (230, 270), "16", (50, 600)),
    ),
    "acero": (
        ("30102304", "Varilla corrugada 3/8 pieza 12 m", "H87", "Pieza", (165, 210), "16", (50, 800)),
        ("30102304", "Alambrón 1/4 rollo", "KGM", "Kilogramo", (24, 31), "16", (100, 1500)),
    ),
    "block": (
        ("30131502", "Block de concreto 15x20x40", "H87", "Pieza", (14, 19), "16", (500, 5000)),
    ),
    "concreto": (
        ("30111505", "Concreto premezclado f'c 250 kg/cm2", "MTQ", "Metro cúbico", (2450, 2900), "16", (3, 40)),
    ),
    "maquinaria": (
        ("72141101", "Renta de retroexcavadora por hora", "HUR", "Hora", (850, 1200), "16", (8, 60)),
    ),
    "diseno": (
        ("81112501", "Licencia mensual de software de diseño", "E48", "Unidad de servicio", (1450, 1450), "16", (1, 1)),
        ("82121500", "Impresión de planos tamaño doble carta", "H87", "Pieza", (35, 60), "16", (10, 80)),
    ),
    "medico": (
        ("85121800", "Honorarios por consulta médica", "E48", "Unidad de servicio", (800, 1500), "exento", (1, 1)),
    ),
    "colegiatura": (
        ("86121500", "Colegiatura primaria, mes en curso", "E48", "Unidad de servicio", (5600, 5600), "exento", (1, 1)),
    ),
    "seguro_gmm": (
        ("84131600", "Prima de seguro de gastos médicos, parcialidad", "E48", "Unidad de servicio", (2350, 2350), "16", (1, 1)),
    ),
    # --- Lo que venden las empresas de demo (emitidos) ---
    "venta_abarrotes": (
        ("50161509", "Azúcar estándar bulto 50 kg", "H87", "Pieza", (1180, 1290), "0", (2, 30)),
        ("50151513", "Aceite vegetal comestible caja 12 pzas 1 L", "XBX", "Caja", (520, 620), "0", (2, 40)),
        ("50221101", "Frijol pinto bulto 25 kg", "H87", "Pieza", (930, 1090), "0", (2, 20)),
        ("50131702", "Leche ultrapasteurizada caja 12 pzas 1 L", "XBX", "Caja", (295, 340), "0", (5, 60)),
        ("47131807", "Cloro blanqueador caja 12 pzas 1 L", "XBX", "Caja", (240, 290), "16", (5, 40)),
        ("14111704", "Papel higiénico caja 48 rollos", "XBX", "Caja", (470, 560), "16", (5, 30)),
    ),
    "venta_pan": (
        ("50181902", "Pan blanco: bolillo y telera", "H87", "Pieza", (2.8, 3.5), "0", (200, 1500)),
        ("50181905", "Pan dulce surtido", "H87", "Pieza", (9, 14), "0", (100, 600)),
        ("50181900", "Pastel de tres leches 20 porciones", "H87", "Pieza", (420, 680), "0", (1, 6)),
    ),
    "venta_flete": (
        ("78101802", "Servicio de transporte de carga León-Monterrey", "E48", "Unidad de servicio", (24000, 31000), "16", (1, 1)),
        ("78101802", "Servicio de transporte de carga Irapuato-CDMX", "E48", "Unidad de servicio", (16500, 21000), "16", (1, 1)),
        ("78101802", "Servicio de transporte de carga Silao-Manzanillo", "E48", "Unidad de servicio", (32000, 41000), "16", (1, 1)),
    ),
    "venta_limpieza_industrial": (
        ("76111501", "Servicio de limpieza industrial, mes en curso", "E48", "Unidad de servicio", (38000, 96000), "16", (1, 1)),
        ("72101500", "Mantenimiento a instalaciones", "E48", "Unidad de servicio", (12000, 45000), "16", (1, 1)),
    ),
    "venta_obra": (
        ("72111000", "Estimación de obra, avance de edificación", "E48", "Unidad de servicio", (380000, 1800000), "16", (1, 1)),
    ),
    "venta_diseno": (
        ("81101500", "Proyecto de diseño de interiores, avance", "E48", "Unidad de servicio", (12000, 48000), "16", (1, 1)),
    ),
    "venta_renta_casa": (
        ("80131501", "Arrendamiento de casa habitación", "E48", "Unidad de servicio", (14500, 14500), "exento", (1, 1)),
    ),
}


# ---------------------------------------------------------------------------
# Contrapartes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Contraparte:
    nombre: str                 # como va en el XML (MAYÚSCULAS, como la CSF)
    persona: str                # "PM" | "PF"
    regimen: str
    giro: str
    peso: float                 # frecuencia relativa en el mes
    credito: bool = False       # factura a crédito (PPD + complementos)
    retencion: Optional[str] = None  # flete | arrendamiento | honorarios | resico
    mensual: Optional[int] = None    # factura fija una vez al mes, ese día
    rfc_fijo: Optional[str] = None

    @property
    def rfc(self) -> str:
        return self.rfc_fijo or rfc_ficticio(self.nombre, self.persona)


def _pm(nombre, giro, peso, **kw):
    return Contraparte(nombre, "PM", kw.pop("regimen", "601"), giro, peso, **kw)


def _pf(nombre, giro, peso, regimen="612", **kw):
    return Contraparte(nombre, "PF", regimen, giro, peso, **kw)


def _lista(rfc):
    e = LISTAS_NEGRAS[rfc]
    return e.nombre, rfc


_ALAMO = _lista("SAG990231KX4")
_CARDENAS = _lista("FMC120431RB7")
_OLMO = _lista("COR140230FN2")

# Gasolineras que comparten varias empresas (misma contraparte, mismo RFC).
_GAS = (
    _pm("SERVICIO LOS FRESNOS", "combustible", 120),
    _pm("ESTACION DE SERVICIO PASEO DEL MOLINO", "combustible", 110),
    _pm("COMBUSTIBLES DEL ALTIPLANO", "combustible", 105),
    _pm("GASOLINERA LA LOMA", "combustible", 95),
    _pm("GASOLINERA SAN PEDRO", "combustible", 70),
    _pm("SERVICIO EL MIRADOR", "combustible", 40),
)

# El Roble: 87 emisores en septiembre (guiones, pieza 1 F6.1). 15 a crédito.
_PROV_EL_ROBLE = (
    # Mercancía a crédito (PPD + complementos)
    _pm("COMERCIALIZADORA DEL VALLE", "abarrotes", 6, credito=True),
    _pm("DISTRIBUIDORA DE BEBIDAS LA FUENTE", "agua", 3, credito=True),
    _pm("ALIMENTOS PROCESADOS DEL CENTRO", "abarrotes", 5, credito=True),
    _pm("LACTEOS SANTA ROSALIA", "lacteos", 5, credito=True),
    _pm("MOLINO DE TRIGO EL MOLINO", "harinas", 4, credito=True),
    _pm("ABARROTES MAYORISTAS DEL BAJIO", "abarrotes", 5, credito=True),
    _pm("PRODUCTOS DE LIMPIEZA AZAHAR", "limpieza", 4, credito=True),
    _pm("CONSERVAS Y ENLATADOS SIERRA GORDA", "abarrotes", 4, credito=True),
    _pm("SEMILLAS Y LEGUMBRES LA CANASTA", "abarrotes", 3, credito=True),
    _pm("EMPAQUES Y CARTON DEL BAJIO", "empaque", 3, credito=True),
    _pm("ACEITES COMESTIBLES EL GIRASOL", "abarrotes", 3, credito=True),
    _pm("CAFE Y DERIVADOS LOS ALTOS", "abarrotes", 3, credito=True),
    _pm("HARINAS Y PASTAS SAN MIGUEL", "harinas", 3, credito=True),
    _pm("PAPEL TISSUE DEL NORTE", "limpieza", 4, credito=True),
    _pm("HIGIENE PERSONAL ALBA", "limpieza", 3, credito=True),
    # Mercancía de contado
    _pm(_OLMO[0], "abarrotes", 12, rfc_fijo=_OLMO[1]),
    _pm("GRANOS SELECTOS RAMIREZ", "abarrotes", 14),
    _pm("HUEVO FRESCO SAN JUAN", "abarrotes", 16),
    _pm("ABARROTES LA PALOMA", "abarrotes", 14),
    _pm(_ALAMO[0], "limpieza", 4, rfc_fijo=_ALAMO[1]),
    _pm("FRUTAS SECAS DEL SUR", "abarrotes", 10),
    _pm("DETERGENTES BRISA", "limpieza", 12),
    _pm("SAL Y ESPECIAS LA HACIENDA", "abarrotes", 10),
    _pm("PRODUCTOS DESECHABLES EL PALMAR", "desechables", 14),
    _pm("PURIFICADORA MANANTIAL", "agua", 8),
    # Combustible (el grueso del volumen)
    *_GAS,
    # Refacciones, taller y llantas
    _pm("REFACCIONARIA DIESEL DEL CENTRO", "refacciones", 14),
    _pf("JOSE LUIS HERNANDEZ PRIETO", "refacciones", 8, regimen="626", retencion="resico"),
    _pm("SERVICIO AUTOMOTRIZ HERMANOS ORTIZ", "taller", 9),
    _pm("FRENOS Y CLUTCH EL ARCO", "taller", 6),
    _pm("LUBRICANTES DEL BAJIO", "refacciones", 8),
    _pf("ARTURO RUIZ MEDINA", "taller", 5, regimen="626", retencion="resico"),
    _pm("LLANTERA LA RUEDA", "llantas", 5),
    _pm("NEUMATICOS Y SERVICIOS DEL CENTRO", "llantas", 4),
    # Fletes (retención de IVA del 4 %)
    _pm("TRANSPORTES UNIDOS DEL CENTRO", "fletes", 12, retencion="flete"),
    _pm("GRUPO LOGISTICO DEL NORTE", "fletes", 9, retencion="flete"),
    _pm(_CARDENAS[0], "fletes", 8, retencion="flete", rfc_fijo=_CARDENAS[1]),
    _pm("AUTOTRANSPORTES RIO LERMA", "fletes", 6, retencion="flete"),
    # Servicios fijos del mes
    _pm("CONSULTORES ASOCIADOS DEL PACIFICO", "consultoria", 1, mensual=3),
    _pf("ROBERTO SALAZAR JIMENEZ", "arrendamiento", 1, regimen="606", retencion="arrendamiento", mensual=1),
    _pf("MARGARITA CRUZ CASTRO", "honorarios_contables", 1, retencion="honorarios", mensual=2),
    _pm("VIGILANCIA INTEGRAL DEL BAJIO", "vigilancia", 1, mensual=1),
    _pm("LIMPIEZA PROFESIONAL BRILLO", "limpieza_srv", 1, mensual=1),
    _pm("TELECOMUNICACIONES ENLACE BAJIO", "internet", 1, mensual=5),
    _pm("SOFTWARE ADMINISTRATIVO NUBE", "software", 1, mensual=7),
    _pm("TELEFONIA CORPORATIVA DEL CENTRO", "telefonia", 1, mensual=10),
    _pm("FUMIGACIONES EL PINO", "fumigacion", 1, mensual=18),
    _pm("MONTACARGAS Y EQUIPOS DEL CENTRO", "montacargas", 2),
    _pm("ASEGURADORA PROTECCION DEL BAJIO", "seguros", 1, mensual=15),
    _pm("UNIFORMES INDUSTRIALES LUNA", "uniformes", 2),
    _pm("PENSION LA ALAMEDA", "pension", 1, mensual=1),
    # Comidas y viáticos
    _pm("RESTAURANTE EL FOGON", "restaurante", 16),
    _pf("JUAN CARLOS MORALES ESPINOZA", "restaurante", 14, regimen="626", retencion="resico"),
    _pm("CAFETERIA EL PORTAL", "restaurante", 12),
    _pm("HOTEL POSADA DEL CAMINO", "hotel", 8),
    _pm("HOTEL PLAZA DEL SOL", "hotel", 6),
    _pm("MARISCOS EL PUERTO", "restaurante", 8),
    _pf("GUADALUPE TORRES NAVA", "restaurante", 10, regimen="626", retencion="resico"),
    _pm("BIRRIERIA LA TRADICION", "restaurante", 9),
    _pm("POLLOS ASADOS EL GALLO", "restaurante", 9),
    _pm("CAFE DE OLLA LA ESQUINA", "restaurante", 7),
    _pm("PIZZERIA NAPOLITANA DEL CENTRO", "restaurante", 6),
    _pm("RESTAURANTE LOS ARCOS", "restaurante", 7),
    _pm("HOTEL VILLA DEL ANGEL", "hotel", 5),
    _pm("FONDA SANTA CLARA", "restaurante", 8),
    _pm("TAQUERIA EL PASTOR DE ORO", "restaurante", 8),
    _pm("TAQUERIA LOS COMPADRES", "restaurante", 6),
    # Papelería, ferretería, mantenimiento
    _pm("AUTOPARTES EL CHAPARRAL", "refacciones", 5),
    _pm("PAPELERIA Y EQUIPOS DEL SUR", "papeleria", 12),
    _pm("FERRETERIA EL TORNILLO", "ferreteria", 12),
    _pm("MATERIALES ELECTRICOS VOLTA", "electrico", 7),
    _pm("OFICINA Y COMPUTO DIGITAL", "computo", 3),
    _pm("IMPRENTA LA PLUMA", "imprenta", 4),
    _pf("JOSEFINA AVILA PEREZ", "ferreteria", 7, regimen="626", retencion="resico"),
    _pf("RAMON CASTILLO LUGO", "ferreteria", 5, regimen="626", retencion="resico"),
    _pm("PINTURAS Y RECUBRIMIENTOS COLOR", "ferreteria", 4),
    # Varios
    _pm("MENSAJERIA EXPRES DEL CENTRO", "mensajeria", 6),
    _pm("CLINICA DE MEDICINA DEL TRABAJO VITAL", "clinica", 2),
    _pm("CAPACITACION EMPRESARIAL AGORA", "capacitacion", 1),
    _pm("AGENCIA DE VIAJES RUMBO", "viajes", 3),
    _pm("BASCULAS Y BALANZAS PRECISION", "basculas", 1),
    _pm("REFRIGERACION INDUSTRIAL POLAR", "refrigeracion", 1),
)

_CLI_EL_ROBLE = (
    _pm("MINISUPER LA ESQUINA", "venta_abarrotes", 10, credito=True),
    _pm("TIENDAS DE CONVENIENCIA EL PASO", "venta_abarrotes", 12, credito=True),
    _pm("COMERCIAL LOS PINOS", "venta_abarrotes", 8, credito=True),
    _pm("SUPER ABARROTES DON TOÑO", "venta_abarrotes", 9, credito=True),
    _pm("CADENA COMERCIAL LA ECONOMICA", "venta_abarrotes", 11, credito=True),
    _pm("ABASTECEDORA DE COMEDORES INDUSTRIALES", "venta_abarrotes", 6, credito=True),
    _pf("MARIA ELENA SOTO RAMIREZ", "venta_abarrotes", 8, regimen="626"),
    _pf("FRANCISCO JAVIER LUNA OCHOA", "venta_abarrotes", 7, regimen="612"),
    _pf("ROSA MARIA GALVAN TREJO", "venta_abarrotes", 6, regimen="626"),
    _pf("PEDRO ALBERTO RIOS CAMACHO", "venta_abarrotes", 6, regimen="612"),
    _pf("SILVIA PATRICIA MENDEZ OROZCO", "venta_abarrotes", 5, regimen="626"),
    _pm("ABARROTES Y CREMERIA LA LUPITA", "venta_abarrotes", 7),
    _pm("MISCELANEA EL SOL", "venta_abarrotes", 6),
    _pm("COMERCIALIZADORA SAN JUDAS", "venta_abarrotes", 5),
    _pm("TIENDA ESCOLAR COLEGIO ARBOLEDAS", "venta_abarrotes", 3),
    _pm("COMEDOR INDUSTRIAL EL BUEN SAZON", "venta_abarrotes", 4, credito=True),
)

_PROV_PANADERIA = (
    _pm("MOLINO DE TRIGO EL MOLINO", "harinas", 14, credito=True),
    _pm("HARINAS Y PASTAS SAN MIGUEL", "harinas", 8, credito=True),
    _pm("LACTEOS SANTA ROSALIA", "lacteos", 10, credito=True),
    _pm("HUEVO FRESCO SAN JUAN", "abarrotes", 12),
    _pm("GRANOS SELECTOS RAMIREZ", "abarrotes", 6),
    _pm("GAS DEL BAJIO HORNOS Y COCINAS", "gaslp", 9),
    _pm("PRODUCTOS DESECHABLES EL PALMAR", "desechables", 8),
    _pm("PURIFICADORA MANANTIAL", "agua", 6),
    _pm("PRODUCTOS DE LIMPIEZA AZAHAR", "limpieza", 4),
    _pm("PAPELERIA Y EQUIPOS DEL SUR", "papeleria", 3),
    _pm("MANTENIMIENTO DE HORNOS EL TAHONERO", "hornos", 2),
    _pf("ELENA BRISEÑO VARGAS", "arrendamiento_local", 1, regimen="606", retencion="arrendamiento", mensual=1),
    _pf("MARGARITA CRUZ CASTRO", "honorarios_contables", 1, retencion="honorarios", mensual=2),
    _pm("TELECOMUNICACIONES ENLACE BAJIO", "internet", 1, mensual=5),
    _pm("SOFTWARE ADMINISTRATIVO NUBE", "software", 1, mensual=7),
    _pm("FUMIGACIONES EL PINO", "fumigacion", 1, mensual=20),
    _pm("UNIFORMES INDUSTRIALES LUNA", "uniformes", 1),
    _GAS[3],
    _pm("FERRETERIA EL TORNILLO", "ferreteria", 3),
    _pm("RESTAURANTE EL FOGON", "restaurante", 3),
)

_CLI_PANADERIA = (
    _pm("CAFETERIA EL PORTAL", "venta_pan", 8),
    _pm("RESTAURANTE LOS ARCOS", "venta_pan", 7),
    _pm("HOTEL PLAZA DEL SOL", "venta_pan", 6, credito=True),
    _pm("HOTEL POSADA DEL CAMINO", "venta_pan", 5, credito=True),
    _pm("COMEDOR INDUSTRIAL EL BUEN SAZON", "venta_pan", 6, credito=True),
    _pm("FONDA SANTA CLARA", "venta_pan", 4),
    _pm("COLEGIO ARBOLEDAS", "venta_pan", 3),
    _pf("ADRIANA FLORES QUINTERO", "venta_pan", 3, regimen="626"),
    _pm("BANQUETES Y EVENTOS LA HACIENDA", "venta_pan", 4),
    _pm("CAFE DE OLLA LA ESQUINA", "venta_pan", 4),
)

_PROV_MOLINA = (
    *_GAS[:5],
    _pm("REFACCIONARIA DIESEL DEL CENTRO", "refacciones", 10),
    _pm("LUBRICANTES DEL BAJIO", "refacciones", 6),
    _pm("LLANTERA LA RUEDA", "llantas", 4),
    _pm("NEUMATICOS Y SERVICIOS DEL CENTRO", "llantas", 3),
    _pm("SERVICIO AUTOMOTRIZ HERMANOS ORTIZ", "taller", 6),
    _pm("FRENOS Y CLUTCH EL ARCO", "taller", 4),
    _pm("ASEGURADORA PROTECCION DEL BAJIO", "seguros", 1, mensual=15),
    _pm("RASTREO SATELITAL CENTINELA", "rastreo", 1, mensual=3),
    _pm("AUTOLAVADO TRAILERO EL GUERO", "lavado", 6),
    _pm("HOTEL POSADA DEL CAMINO", "hotel", 4),
    _pm("RESTAURANTE EL FOGON", "restaurante", 6),
    _pf("GUADALUPE TORRES NAVA", "restaurante", 5, regimen="626", retencion="resico"),
    _pm("PAPELERIA Y EQUIPOS DEL SUR", "papeleria", 2),
)

_CLI_MOLINA = (
    _pm("INDUSTRIAS QUIMICAS DEL BAJIO", "venta_flete", 8, credito=True),
    _pm("AGROINDUSTRIAS SAN FRANCISCO", "venta_flete", 7, credito=True),
    _pm("AUTOPARTES Y FORJAS DE SILAO", "venta_flete", 6, credito=True),
    _pm("CALZADO FINO DE LEON", "venta_flete", 5),
    _pm("EMPACADORA DE HORTALIZAS EL CAMPO", "venta_flete", 5),
    _pm("COMERCIALIZADORA DEL VALLE", "venta_flete", 4),
)

_PROV_SERVICIOS = (
    _pm("PRODUCTOS DE LIMPIEZA AZAHAR", "limpieza", 12, credito=True),
    _pm("DETERGENTES BRISA", "limpieza", 8),
    _pm("UNIFORMES INDUSTRIALES LUNA", "uniformes", 4),
    _pm("FERRETERIA EL TORNILLO", "ferreteria", 6),
    _pm("MATERIALES ELECTRICOS VOLTA", "electrico", 4),
    _GAS[0], _GAS[2],
    _pm("PAPELERIA Y EQUIPOS DEL SUR", "papeleria", 3),
    _pm("SOFTWARE ADMINISTRATIVO NUBE", "software", 1, mensual=7),
    _pm("TELEFONIA CORPORATIVA DEL CENTRO", "telefonia", 1, mensual=10),
    _pm("INMOBILIARIA CORREGIDORA PLAZA", "arrendamiento_oficina", 1, mensual=1),
    _pm("CAPACITACION EMPRESARIAL AGORA", "capacitacion", 1),
    _pm("RESTAURANTE LOS ARCOS", "restaurante", 4),
)

_CLI_SERVICIOS = (
    _pm("AUTOPARTES Y FORJAS DE SILAO", "venta_limpieza_industrial", 4, credito=True),
    _pm("INDUSTRIAS QUIMICAS DEL BAJIO", "venta_limpieza_industrial", 4, credito=True),
    _pm("PLAZA COMERCIAL LOS ALAMOS", "venta_limpieza_industrial", 3, credito=True),
    _pm("HOSPITAL SAN LUCAS DEL BAJIO", "venta_limpieza_industrial", 3, credito=True),
    _pm("CORPORATIVO TORRE QUERETARO", "venta_limpieza_industrial", 2),
)

_PROV_CONSTRUCTORA = (
    _pm("CEMENTOS Y AGREGADOS DEL BAJIO", "cemento", 12, credito=True),
    _pm("ACEROS Y VARILLAS DEL CENTRO", "acero", 10, credito=True),
    _pm("BLOQUERA LA PIEDRA", "block", 8, credito=True),
    _pm("CONCRETOS PREMEZCLADOS LEON", "concreto", 9, credito=True),
    _pm("RENTA DE MAQUINARIA EL TITAN", "maquinaria", 6),
    _pm("TRANSPORTES UNIDOS DEL CENTRO", "fletes", 5, retencion="flete"),
    _pm("FERRETERIA EL TORNILLO", "ferreteria", 10),
    _pm("MATERIALES ELECTRICOS VOLTA", "electrico", 6),
    _pm("PINTURAS Y RECUBRIMIENTOS COLOR", "ferreteria", 5),
    *_GAS[:3],
    _pf("HECTOR MANUEL DIAZ ROBLES", "honorarios_ingenieria", 1, retencion="honorarios", mensual=28),
    _pm("ASEGURADORA PROTECCION DEL BAJIO", "seguros", 1, mensual=15),
    _pm("INMOBILIARIA CAMPESTRE TORRE B", "arrendamiento_oficina", 1, mensual=1),
    _pm("PAPELERIA Y EQUIPOS DEL SUR", "papeleria", 3),
    _pm("RESTAURANTE EL FOGON", "restaurante", 5),
    _pm("UNIFORMES INDUSTRIALES LUNA", "uniformes", 2),
)

_CLI_CONSTRUCTORA = (
    _pm("DESARROLLOS HABITACIONALES LOS OLIVOS", "venta_obra", 3, credito=True),
    _pm("INMOBILIARIA PUERTA DEL BAJIO", "venta_obra", 2, credito=True),
    _pm("PLAZA COMERCIAL LOS ALAMOS", "venta_obra", 1, credito=True),
)

_PROV_NORMA = (
    _GAS[1], _GAS[3],
    _pm("PAPELERIA Y EQUIPOS DEL SUR", "papeleria", 4),
    _pm("OFICINA Y COMPUTO DIGITAL", "computo", 1),
    _pm("ESTUDIO DIGITAL TRAZO", "diseno", 3),
    _pm("INMOBILIARIA CAMPESTRE TORRE B", "arrendamiento_oficina", 1, mensual=1),
    _pm("TELECOMUNICACIONES ENLACE BAJIO", "internet", 1, mensual=5),
    _pm("TELEFONIA CORPORATIVA DEL CENTRO", "telefonia", 1, mensual=10),
    _pm("CAFETERIA EL PORTAL", "restaurante", 5),
    _pm("RESTAURANTE LOS ARCOS", "restaurante", 3),
)

_CLI_NORMA = (
    _pm("DESARROLLOS HABITACIONALES LOS OLIVOS", "venta_diseno", 3),
    _pm("CORPORATIVO TORRE QUERETARO", "venta_diseno", 2),
    _pm("HOTEL VILLA DEL ANGEL", "venta_diseno", 2),
    _pf("CLAUDIA JIMENEZ MORALES", "venta_diseno", 2, regimen="605"),
    _pf("FERNANDO PEÑA NAVARRO", "venta_diseno", 1, regimen="605"),
)

_PROV_LAURA = (
    _GAS[0],
    _pf("ALEJANDRO VEGA SALINAS", "medico", 2, regimen="612"),
    _pm("COLEGIO ARBOLEDAS", "colegiatura", 1, mensual=5),
    _pm("SEGUROS MEDICOS DEL BAJIO", "seguro_gmm", 1, mensual=12),
    _pm("CAFETERIA EL PORTAL", "restaurante", 3),
    _pm("PIZZERIA NAPOLITANA DEL CENTRO", "restaurante", 2),
)

_CLI_LAURA = (
    _pf("RICARDO SANTOS TORRES", "venta_renta_casa", 1, regimen="605", mensual=1),
)


@dataclass(frozen=True)
class Perfil:
    """Volumen y contrapartes de una empresa por mes."""
    proveedores: tuple
    clientes: tuple
    recibidos_mes: int      # facturas de proveedores por mes (aprox.)
    emitidos_mes: int       # facturas a clientes por mes (aprox.)
    global_publico: bool = False   # factura global semanal a público en general


PERFILES: dict = {
    EL_ROBLE: Perfil(_PROV_EL_ROBLE, _CLI_EL_ROBLE, recibidos_mes=1060, emitidos_mes=170),
    PANADERIA: Perfil(_PROV_PANADERIA, _CLI_PANADERIA, recibidos_mes=120, emitidos_mes=48,
                      global_publico=True),
    MOLINA: Perfil(_PROV_MOLINA, _CLI_MOLINA, recibidos_mes=140, emitidos_mes=38),
    "SIB200117HU9": Perfil(_PROV_SERVICIOS, _CLI_SERVICIOS, recibidos_mes=70, emitidos_mes=16),
    "COV110714AB2": Perfil(_PROV_CONSTRUCTORA, _CLI_CONSTRUCTORA, recibidos_mes=200, emitidos_mes=6),
    NORMA: Perfil(_PROV_NORMA, _CLI_NORMA, recibidos_mes=34, emitidos_mes=8),
    "GACL850312H40": Perfil(_PROV_LAURA, _CLI_LAURA, recibidos_mes=14, emitidos_mes=1),
}


# ---------------------------------------------------------------------------
# Nómina: empleados de Panadería La Central (quincenal, 14 personas) y el
# patrón de Laura García Cervantes (recibe su nómina).
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Empleado:
    num: str
    nombre: str
    sexo: str            # H | M
    puesto: str
    departamento: str
    salario_diario: float
    ingreso: str         # AAAA-MM-DD
    jornada: str = "01"  # 01 diurna, 02 nocturna
    premio_puntualidad: bool = False
    horas_extra: float = 0.0  # importe por quincena (mitad exenta)
    infonavit: float = 0.0    # descuento por quincena

    @property
    def rfc(self) -> str:
        return rfc_ficticio(self.nombre, "PF")

    @property
    def curp(self) -> str:
        return curp_ficticia(self.nombre, self.sexo)

    @property
    def nss(self) -> str:
        return nss_ficticio(self.nombre)


EMPLEADOS: dict = {
    PANADERIA: (
        Empleado("001", "Martín Olvera Sánchez", "H", "Maestro panadero", "Producción", 585.00, "2015-04-06", "02", True, 640.0),
        Empleado("002", "José Antonio Ramírez Luna", "H", "Panadero", "Producción", 452.00, "2016-02-15", "02", True, 420.0),
        Empleado("003", "Ricardo Méndez Pacheco", "H", "Panadero", "Producción", 452.00, "2018-09-03", "02", False, 380.0, 612.40),
        Empleado("004", "Luis Fernando Aguilar Ríos", "H", "Panadero", "Producción", 438.00, "2020-01-13", "02", True),
        Empleado("005", "Ernesto Salgado Villa", "H", "Ayudante de panadero", "Producción", 395.00, "2022-06-01", "02"),
        Empleado("006", "Brenda Ivonne Cárdenas Mora", "M", "Repostera", "Producción", 470.00, "2017-08-21", "01", True),
        Empleado("007", "Alejandra Campos Rivera", "M", "Repostera", "Producción", 455.00, "2021-03-08", "01"),
        Empleado("008", "Diana Laura Torres Becerra", "M", "Cajera", "Ventas", 392.00, "2019-11-04", "01", True),
        Empleado("009", "Mónica Herrera Solís", "M", "Cajera", "Ventas", 388.00, "2023-02-20", "01"),
        Empleado("010", "Juan Pablo Ortega Núñez", "H", "Repartidor", "Distribución", 410.00, "2018-05-14", "01", True, 0.0, 535.80),
        Empleado("011", "Héctor Gallardo Peña", "H", "Repartidor", "Distribución", 405.00, "2024-01-08", "01"),
        Empleado("012", "Patricia Delgado Fuentes", "M", "Encargada de tienda", "Ventas", 520.00, "2015-03-09", "01", True),
        Empleado("013", "Verónica Ibarra Lozano", "M", "Auxiliar administrativa", "Administración", 465.00, "2020-10-19", "01", True),
        Empleado("014", "Gerardo Velázquez Rojas", "H", "Intendente", "Administración", 386.00, "2025-04-07", "01"),
    ),
    "GACL850312H40": (
        Empleado("2417", "Laura García Cervantes", "M", "Coordinadora académica", "Dirección académica",
                 1150.00, "2009-08-15", "01"),
    ),
}

# Número de empleado cuya retención de ISR queda corta a propósito: el reporte
# "ISR teórico contra retenido" de la pieza 4 enseña una diferencia real.
EMPLEADO_CON_DIFERENCIA_ISR = (PANADERIA, "004")

PATRONES: dict = {
    PANADERIA: {"registro_patronal": "G1263548102", "riesgo": "2", "entidad": "GUA"},
    # Laura recibe su nómina de un patrón ficticio (no es empresa de demo).
    "GACL850312H40": {
        "registro_patronal": "G1270931105", "riesgo": "1", "entidad": "GUA",
        "patron": _pm("COLEGIO ARBOLEDAS", "colegiatura", 1),
    },
}

# Proveedores de certificación (PAC) ficticios para el timbre.
PACS = (
    rfc_ficticio("TIMBRADO DIGITAL DEL NORTE", "PM"),
    rfc_ficticio("CERTIFICACION FISCAL EXPRES", "PM"),
    rfc_ficticio("SELLO DIGITAL DEL PACIFICO", "PM"),
)

# Códigos postales de la región para los lugares de expedición.
CPS = ("37000", "37150", "37290", "37530", "38000", "38010", "36500", "36660",
       "76000", "76090", "36100", "44100", "78000", "37800", "38300")


def contraparte_por_rfc(rfc: str) -> Optional[Contraparte]:
    """Busca una contraparte del escenario por RFC (para nombres en listas)."""
    rfc = (rfc or "").strip().upper()
    for perfil in PERFILES.values():
        for c in (*perfil.proveedores, *perfil.clientes):
            if c.rfc == rfc:
                return c
    return None


def rfcs_del_escenario() -> frozenset:
    """Todos los RFC que inventa el escenario (empresas, contrapartes,
    empleados): los que la consulta de listas negras de demo contesta sin red."""
    from .escenario import RFCS_DEMO

    rfcs = set(RFCS_DEMO) | set(LISTAS_NEGRAS)
    for perfil in PERFILES.values():
        rfcs.update(c.rfc for c in (*perfil.proveedores, *perfil.clientes))
    for empleados in EMPLEADOS.values():
        rfcs.update(e.rfc for e in empleados)
    rfcs.update(PACS)
    return frozenset(rfcs)

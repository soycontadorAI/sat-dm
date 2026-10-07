"""
Escenario de la cuenta de grabación: las 7 empresas de demo y los hechos que
cada pieza de los tutoriales necesita ver en pantalla.

Fuente: docs/negocio/guiones-ventana-2026-11.md (todoconta-apps), tabla
"Empresas y datos de la cuenta de grabación". Nombres y RFC inventados; los RFC
de las contrapartes (proveedores, clientes, empleados) se generan con fechas
imposibles (31 de febrero, 31 de abril…) para que nunca coincidan con un
contribuyente real (ver `catalogo.rfc_ficticio`).

Solo datos puros: este módulo lo importa `demo/__init__`, que a su vez cargan
los módulos que hablan con el SAT. Nada de imports pesados aquí.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EmpresaDemo:
    rfc: str
    nombre: str                 # como se ve en la app (catálogo, CSF de ejemplo)
    nombre_sat: str             # como va en los XML (receptor/emisor)
    tipo: str                   # "PM" | "PF"
    regimen: str                # clave principal (c_RegimenFiscal)
    cp: str                     # domicilio fiscal (código postal)
    municipio: str
    estado: str
    colonia: str
    calle: str
    accesos: tuple              # ("fiel",), ("ciec",) o ambos
    vence_en_dias: Optional[int]  # vigencia de la e.firma al sembrar
    opinion: str                # sentido de la 32-D que "devuelve el SAT"
    inicio_operaciones: str     # dd/mm/aaaa (CSF)
    regimenes: tuple = ()       # ((clave, descripción, fecha inicio), ...)
    actividades: tuple = ()     # ((descripción, porcentaje, fecha inicio), ...)
    curp: str = ""              # PF: su CURP; PM: la del representante legal
    rfc_representante: str = ""  # PM: va en el certificado ("RFC / RFC_REP")
    papel: str = ""             # para qué sirve en los guiones


EMPRESAS: dict = {
    e.rfc: e
    for e in (
        EmpresaDemo(
            rfc="DER180922QX4",
            nombre="Distribuidora El Roble",
            nombre_sat="DISTRIBUIDORA EL ROBLE",
            tipo="PM", regimen="601", cp="37290",
            municipio="LEON", estado="GUANAJUATO",
            colonia="CIUDAD INDUSTRIAL", calle="BOULEVARD LA LUZ 1520",
            accesos=("fiel",), vence_en_dias=712, opinion="positiva",
            inicio_operaciones="22/09/2018",
            regimenes=(("601", "Régimen General de Ley Personas Morales", "22/09/2018"),),
            actividades=(
                ("Comercio al por mayor de abarrotes", 85, "22/09/2018"),
                ("Comercio al por mayor de artículos de limpieza", 15, "22/09/2018"),
            ),
            curp="ROMJ780431HGTBRN09", rfc_representante="ROMJ780431JD4",
            papel="Protagonista: descarga de recibidos de septiembre (pieza 1), "
                  "Excel de CFDI y Pagos (4), estatus y listas negras (3).",
        ),
        EmpresaDemo(
            rfc="PCE150308MT7",
            nombre="Panadería La Central",
            nombre_sat="PANADERIA LA CENTRAL",
            tipo="PM", regimen="601", cp="38000",
            municipio="CELAYA", estado="GUANAJUATO",
            colonia="ZONA CENTRO", calle="CALLE BENITO JUAREZ 214",
            accesos=("fiel",), vence_en_dias=198, opinion="positiva",
            inicio_operaciones="08/03/2015",
            regimenes=(("601", "Régimen General de Ley Personas Morales", "08/03/2015"),),
            actividades=(
                ("Panificación tradicional", 100, "08/03/2015"),
            ),
            curp="LOCA690231MGTPSN02", rfc_representante="LOCA690231QW1",
            papel="Constancia por ⌘K (pieza 2), nómina quincenal (4), orden de ejemplo (5).",
        ),
        EmpresaDemo(
            rfc="SIB200117HU9",
            nombre="Servicios Integrales del Bajío",
            nombre_sat="SERVICIOS INTEGRALES DEL BAJIO",
            tipo="PM", regimen="601", cp="76000",
            municipio="QUERETARO", estado="QUERETARO",
            colonia="CENTRO", calle="AVENIDA CORREGIDORA 88",
            accesos=("fiel",), vence_en_dias=21, opinion="positiva",
            inicio_operaciones="17/01/2020",
            regimenes=(("601", "Régimen General de Ley Personas Morales", "17/01/2020"),),
            actividades=(
                ("Servicios de limpieza de inmuebles", 70, "17/01/2020"),
                ("Servicios de mantenimiento a instalaciones", 30, "17/01/2020"),
            ),
            curp="BAPE810231HQTRRD06", rfc_representante="BAPE810231R72",
            papel="32-D positiva por ⌘K (pieza 2). e.firma por vencer.",
        ),
        EmpresaDemo(
            rfc="TML160923KP8",
            nombre="Transportes Molina",
            nombre_sat="TRANSPORTES MOLINA",
            tipo="PM", regimen="601", cp="36500",
            municipio="IRAPUATO", estado="GUANAJUATO",
            colonia="LAS HUERTAS", calle="CARRETERA IRAPUATO SILAO KM 5.5",
            accesos=("ciec",), vence_en_dias=None, opinion="positiva",
            inicio_operaciones="23/09/2016",
            regimenes=(("601", "Régimen General de Ley Personas Morales", "23/09/2016"),),
            actividades=(
                ("Autotransporte foráneo de carga general", 100, "23/09/2016"),
            ),
            curp="MOCR750631HGTLRB08", rfc_representante="MOCR750631KL3",
            papel="Solo Contraseña: Descarga rápida con captcha (pieza 1), "
                  "constancia con captcha (2).",
        ),
        EmpresaDemo(
            rfc="REAN741122K85",
            nombre="Norma Reyes Aguilar",
            nombre_sat="NORMA REYES AGUILAR",
            tipo="PF", regimen="612", cp="37150",
            municipio="LEON", estado="GUANAJUATO",
            colonia="JARDINES DEL MORAL", calle="CALLE MONTE ALBAN 305",
            accesos=("fiel",), vence_en_dias=4, opinion="negativa",
            inicio_operaciones="01/02/2012",
            regimenes=(
                ("612", "Régimen de las Personas Físicas con Actividades Empresariales y Profesionales",
                 "01/02/2012"),
            ),
            actividades=(
                ("Servicios de arquitectura y diseño de interiores", 100, "01/02/2012"),
            ),
            curp="REAN741122MGTYGR05",
            papel="32-D negativa con motivos (pieza 2). e.firma vence en 4 días.",
        ),
        EmpresaDemo(
            rfc="GACL850312H40",
            nombre="Laura García Cervantes",
            nombre_sat="LAURA GARCIA CERVANTES",
            tipo="PF", regimen="605", cp="37000",
            municipio="LEON", estado="GUANAJUATO",
            colonia="ZONA CENTRO", calle="CALLE MADERO 410 INT 3",
            accesos=("fiel",), vence_en_dias=480, opinion="positiva",
            inicio_operaciones="15/08/2009",
            regimenes=(
                ("605", "Régimen de Sueldos y Salarios e Ingresos Asimilados a Salarios",
                 "15/08/2009"),
                ("606", "Régimen de Arrendamiento", "01/03/2019"),
            ),
            actividades=(
                ("Asalariado", 70, "15/08/2009"),
                ("Alquiler de viviendas no amuebladas", 30, "01/03/2019"),
            ),
            curp="GACL850312MGTRRR08",
            papel="32-D sin descargar, semáforo gris (pieza 2).",
        ),
        EmpresaDemo(
            rfc="COV110714AB2",
            nombre="Constructora del Valle",
            nombre_sat="CONSTRUCTORA DEL VALLE",
            tipo="PM", regimen="601", cp="37530",
            municipio="LEON", estado="GUANAJUATO",
            colonia="VALLE DEL CAMPESTRE", calle="BOULEVARD CAMPESTRE 2401 PISO 3",
            accesos=("fiel",), vence_en_dias=540, opinion="positiva",
            inicio_operaciones="14/07/2011",
            regimenes=(("601", "Régimen General de Ley Personas Morales", "14/07/2011"),),
            actividades=(
                ("Edificación de vivienda unifamiliar", 60, "14/07/2011"),
                ("Edificación de inmuebles comerciales", 40, "14/07/2011"),
            ),
            curp="VAGE700931HGTLMN03", rfc_representante="VAGE700931TT2",
            papel="32-D positiva en la lista (pieza 2).",
        ),
    )
}

RFCS_DEMO: frozenset = frozenset(EMPRESAS)

# Empresa que protagoniza la historia de punta a punta (piezas 1, 3 y 4).
EL_ROBLE = "DER180922QX4"
PANADERIA = "PCE150308MT7"
MOLINA = "TML160923KP8"
NORMA = "REAN741122K85"

# Contraseña de las e.firmas de ejemplo (la .key va cifrada con ella). No es un
# secreto: los certificados son autofirmados y no sirven ante el SAT.
PASSWORD_EFIRMA = "TodoConta2026"
# Contraseña del SAT (antes CIEC) de ejemplo para las empresas con Contraseña.
CIEC_DEMO = "Grabacion26"


# ---------------------------------------------------------------------------
# Listas negras de ejemplo (art. 69 y 69-B del CFF). Solo RFC ficticios de
# proveedores de El Roble; todo lo demás del escenario sale "limpio".
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EntradaLista:
    rfc: str
    nombre: str
    situacion_69b: Optional[str] = None       # Definitivo | Presunto | Desvirtuado…
    fecha_publicacion_69b: Optional[str] = None
    supuestos_69: tuple = ()                  # Firmes | No localizados | …
    fecha_publicacion_69: Optional[str] = None

    @property
    def risk_level(self) -> str:
        if self.situacion_69b in ("Definitivo", "Presunto"):
            return "alto"
        if self.situacion_69b or self.supuestos_69:
            return "medio"
        return "limpio"


# El RFC de Álamo Gris es inválido a propósito (31 de febrero), como piden los
# guiones; los otros dos también llevan fecha imposible.
LISTAS_NEGRAS: dict = {
    e.rfc: e
    for e in (
        EntradaLista(
            rfc="SAG990231KX4", nombre="SUMINISTROS ÁLAMO GRIS",
            situacion_69b="Definitivo", fecha_publicacion_69b="2026-08-14",
        ),
        EntradaLista(
            rfc="FMC120431RB7", nombre="FLETES Y MANIOBRAS CÁRDENAS",
            supuestos_69=("Firmes",), fecha_publicacion_69="2026-06-12",
        ),
        EntradaLista(
            rfc="COR140230FN2", nombre="COMERCIALIZADORA OLMO ROJO",
            supuestos_69=("No localizados",), fecha_publicacion_69="2026-07-10",
        ),
    )
}


# ---------------------------------------------------------------------------
# Opinión 32-D negativa de Norma Reyes Aguilar (pieza 2, escena 8): los motivos
# que la app lee del PDF y muestra sin abrirlo. Formato del SAT: encabezado de
# sección + frase "Se …:" + renglones de detalle.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MotivoDemo:
    titulo: str
    descripcion: str
    detalles: tuple = field(default_factory=tuple)


MOTIVOS_32D: dict = {
    NORMA: (
        MotivoDemo(
            titulo="Cumplimiento de obligaciones",
            descripcion="Se detectan omisiones en la presentación de las siguientes declaraciones:",
            detalles=(
                "2026 Julio Pago provisional mensual de ISR personas físicas. Actividad empresarial y profesional",
                "2026 Julio Pago definitivo mensual de IVA",
                "2026 Agosto Pago definitivo mensual de IVA",
            ),
        ),
        MotivoDemo(
            titulo="Créditos fiscales",
            descripcion="Se ubican créditos fiscales firmes a su cargo:",
            detalles=(
                "Número de crédito 2025-118342 Autoridad: ADR Guanajuato \"1\" Estado: Firme",
            ),
        ),
    ),
}

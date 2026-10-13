"""
Catálogos del SAT y constantes del procesador.

Portado fielmente de todoconta-apps `lib/procesador-cfdi/constants.ts`. Mantener
los valores idénticos para que los reportes sean consistentes entre proyectos.
"""

# Límites operativos
MAX_FILE_SIZE = 5 * 1024 * 1024     # 5 MB por archivo
MAX_BATCH_SIZE = 500                # Máximo archivos en un batch
INTEGRIDAD_TOLERANCE = 0.02         # Tolerancia ±2 centavos en validación de montos


FORMAS_PAGO: dict[str, str] = {
    "01": "Efectivo",
    "02": "Cheque nominativo",
    "03": "Transferencia electrónica de fondos",
    "04": "Tarjeta de crédito",
    "05": "Moneda electrónica",
    "06": "Dinero electrónico",
    "08": "Vales de despensa",
    "12": "Dación en pago",
    "13": "Pago por subrogación",
    "14": "Pago por consignación",
    "15": "Condonación",
    "17": "Compensación",
    "23": "Novación",
    "24": "Confusión",
    "25": "Remisión de deuda",
    "26": "Prescripción o caducidad",
    "27": "A plazos",
    "28": "Tarjeta de débito",
    "29": "Tarjeta de servicios",
    "30": "Aplicación de anticipos",
    "31": "Intermediario pagos",
    "32": "Criptomonedas",
    "99": "Por definir",
}


METODOS_PAGO: dict[str, str] = {
    "PUE": "Pago en una sola exhibición",
    "PPD": "Pago en parcialidades o diferido",
}


USOS_CFDI: dict[str, str] = {
    "G01": "Adquisición de mercancías",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "G04": "Construcciones",
    "G05": "Mobiliario y equipo de oficina por inversiones",
    "G06": "Diferencia entre precio estimado y real del bien o servicio recibido",
    "G07": "Readecuación y refuncionalización de espacios",
    "G08": "Mantenimiento o reparaciones",
    "G09": "Servicios profesionales",
    "G10": "Instalación",
    "G11": "Reparación",
    "G12": "Otras reparaciones",
    "G13": "Flete y acarreos",
    "G14": "Almacenes y empaques",
    "G15": "Carga, descarga y manipulación",
    "G16": "Comisiones sobre ventas",
    "G17": "Comisiones por cobro",
    "G18": "Reembolsos",
    "G19": "Devoluciones por falta de especificación",
    "G20": "Cifras y claves",
    "G21": "Servicios de factoraje",
    "I01": "Construcciones",
    "I02": "Mobiliario y equipo de oficina por inversiones",
    "I03": "Equipo de transporte",
    "I04": "Equipo de computo y accesorios",
    "I05": "Dados, troqueles, moldes, matrices y herramental",
    "I06": "Adaptaciones",
    "I07": "Mejoras al inmueble",
    "I08": (
        "Depósitos en garantía y pólizas por coberturas de seguros, "
        "de pensiones y de jubilaciones, derivados de la entrega de bienes "
        "o adquisición de servicios"
    ),
    "D01": "Honorarios médicos",
    "D02": "Honorarios dentales",
    "D03": "Honorarios de enfermería",
    "D04": "Gastos médicos",
    "D05": "Gastos de hospital",
    "D06": "Gastos farmacéuticos",
    "D07": "Gastos de servicios auxiliares de diagnóstico y tratamiento",
    "D08": "Medicinas y productos relacionados",
    "D09": "Gastos de transportación relacionados con servicios médicos",
    "D10": "Primas de seguros de vida",
    "P01": "Por definir",
    "S01": "Sin efectos fiscales",
    "CP01": "Contribuciones al Sistema de Seguridad Social",
    "CN01": "Contribuciones de mejoras",
    "CF01": "Contribuciones federales",
    "CE01": "Contribuciones estatales",
    "CT01": "Contribuciones municipales",
}


TIPOS_COMPROBANTE: dict[str, str] = {
    "I": "Ingreso",
    "E": "Egreso",
    "T": "Traslado",
    "N": "Nómina",
    "P": "Pago",
}


# c_ObjetoImp (Anexo 20, CFDI 4.0). Una clave fuera de esta lista se muestra
# sola, sin descripción.
OBJETOS_IMPUESTO: dict[str, str] = {
    "01": "No objeto de impuesto",
    "02": "Sí objeto de impuesto",
    "03": "Sí objeto del impuesto y no obligado al desglose",
    "04": "Sí objeto del impuesto y no causa impuesto",
    "05": "Sí objeto del impuesto, IVA crédito PODEBI",
}


# c_TipoRelacion (CfdiRelacionados).
TIPOS_RELACION: dict[str, str] = {
    "01": "Nota de crédito de los documentos relacionados",
    "02": "Nota de débito de los documentos relacionados",
    "03": "Devolución de mercancía sobre facturas o traslados previos",
    "04": "Sustitución de los CFDI previos",
    "05": "Traslados de mercancías facturados previamente",
    "06": "Factura generada por los traslados previos",
    "07": "CFDI por aplicación de anticipo",
}


MONEDAS: dict[str, str] = {
    "MXN": "Peso mexicano",
    "USD": "Dólar estadounidense",
    "EUR": "Euro",
    "GBP": "Libra esterlina",
    "JPY": "Yen japonés",
    "CAD": "Dólar canadiense",
    "CHF": "Franco suizo",
    "AUD": "Dólar australiano",
    "XXX": "Sin especificar",
}


# ---------------------------------------------------------------------------
# Catálogos de Nómina (Complemento de Nómina 1.2)
# Portados de todoconta-apps lib/procesador-nomina/catalogs.ts (idénticos en
# claves y descripciones para que los reportes sean comparables).
# ---------------------------------------------------------------------------


TIPO_NOMINA: dict[str, str] = {
    "O": "Ordinaria",
    "E": "Extraordinaria",
}


PERIODICIDAD_PAGO: dict[str, str] = {
    "01": "Diario",
    "02": "Semanal",
    "03": "Catorcenal",
    "04": "Quincenal",
    "05": "Mensual",
    "06": "Bimestral",
    "07": "Unidad de obra",
    "08": "Comisión",
    "09": "Precio alzado",
    "10": "Decenal",
    "99": "Otra periodicidad",
}


TIPO_CONTRATO: dict[str, str] = {
    "01": "Contrato de trabajo por tiempo indeterminado",
    "02": "Contrato de trabajo para obra determinada",
    "03": "Contrato de trabajo por tiempo determinado",
    "04": "Contrato de trabajo por temporada",
    "05": "Contrato de trabajo sujeto a prueba",
    "06": "Contrato de trabajo con capacitación inicial",
    "07": "Modalidad de contratación por pago de hora laborada",
    "08": "Modalidad de contratación por comisión laboral",
    "09": "Modalidades de contratación donde no existe relación de trabajo",
    "10": "Jubilación, pensión, retiro",
    "99": "Otro contrato",
}


TIPO_REGIMEN: dict[str, str] = {
    "02": "Sueldos (Salarios e Ingresos Asimilados)",
    "03": "Jubilados",
    "04": "Pensionados",
    "05": "Asimilados Miembros Sociedades Cooperativas",
    "06": "Asimilados Integrantes Sociedades y Asociaciones",
    "07": "Asimilados Miembros Consejos",
    "08": "Asimilados Comisionistas",
    "09": "Asimilados Honorarios",
    "10": "Asimilados Acciones",
    "11": "Asimilados Otros",
    "12": "Jubilados o Pensionados",
    "13": "Indemnización o Separación",
    "99": "Otro Régimen",
}


TIPO_JORNADA: dict[str, str] = {
    "01": "Diurna",
    "02": "Nocturna",
    "03": "Mixta",
    "04": "Por hora",
    "05": "Reducida",
    "06": "Continuada",
    "07": "Partida",
    "08": "Por turnos",
    "99": "Otra jornada",
}


RIESGO_TRABAJO: dict[str, str] = {
    "1": "Clase I",
    "2": "Clase II",
    "3": "Clase III",
    "4": "Clase IV",
    "5": "Clase V",
    "99": "No aplica",
}


TIPO_PERCEPCION: dict[str, str] = {
    "001": "Sueldos, Salarios, Rayas y Jornales",
    "002": "Gratificación Anual (Aguinaldo)",
    "003": "Participación de los Trabajadores en las Utilidades (PTU)",
    "004": "Reembolso de Gastos Médicos Dentales y Hospitalarios",
    "005": "Fondo de Ahorro",
    "006": "Caja de ahorro",
    "009": "Contribuciones a Cargo del Trabajador Pagadas por el Patrón",
    "010": "Premios por puntualidad",
    "011": "Prima de Seguro de vida",
    "012": "Seguro de Gastos Médicos Mayores",
    "013": "Cuotas Sindicales Pagadas por el Patrón",
    "014": "Subsidios por incapacidad",
    "015": "Becas para trabajadores y/o hijos",
    "016": "Otros",
    "017": "Subsidio para el empleo",
    "019": "Horas extra",
    "020": "Prima dominical",
    "021": "Prima vacacional",
    "022": "Prima por antigüedad",
    "023": "Pagos por separación",
    "024": "Seguro de retiro",
    "025": "Indemnizaciones",
    "026": "Reembolso por funeral",
    "027": "Cuotas de seguridad social pagadas por el patrón",
    "028": "Comisiones",
    "029": "Vales de despensa",
    "030": "Vales de restaurante",
    "031": "Vales de gasolina",
    "032": "Vales de ropa",
    "033": "Ayuda para renta",
    "034": "Ayuda para artículos escolares",
    "035": "Ayuda para anteojos",
    "036": "Ayuda para transporte",
    "037": "Ayuda para gastos de funeral",
    "038": "Otros ingresos por salarios (100% gravado 2026)",
    "039": "Jubilaciones, pensiones o haberes de retiro",
    "044": "Jubilaciones, pensiones o haberes de retiro en parcialidades",
    "045": "Ingresos en acciones o títulos valor",
    "046": "Ingresos asimilados a salarios",
    "047": "Alimentación",
    "048": "Habitación",
    "049": "Premios por asistencia",
    "050": "Viáticos",
    "051": "Pagos por fallecimiento",
    "052": "Pagos a expatriados",
    "053": "Pagos a terceros",
    "054": "Día de descanso obligatorio laborado (Nuevo 2026)",
    "055": "Día de descanso no obligatorio laborado (Nuevo 2026)",
    "056": "Previsión social (Nuevo 2026)",
}


TIPO_DEDUCCION: dict[str, str] = {
    "001": "Seguridad social",
    "002": "ISR",
    "003": "Aportaciones a retiro, cesantía y vejez",
    "004": "Otros",
    "005": "Aportaciones a Fondo de vivienda",
    "006": "Descuento por incapacidad",
    "007": "Pensión alimenticia",
    "008": "Renta",
    "009": "Préstamos provenientes del Fondo Nacional de la Vivienda",
    "010": "Pago por crédito de vivienda",
    "011": "Pago de abonos INFONACOT",
    "012": "Anticipo de salarios",
    "013": "Pagos hechos con exceso al trabajador",
    "014": "Errores",
    "015": "Pérdidas",
    "016": "Averías",
    "017": "Adquisición de artículos producidos por la empresa",
    "018": "Cuotas para la constitución de cooperativas",
    "019": "Cuotas sindicales",
    "020": "Ausencia (Ausentismo)",
    "021": "Cuotas obrero patronales",
    "100": "Ajuste en Gratificación Anual (Aguinaldo) Exento",
    "101": "Ajuste en Gratificación Anual (Aguinaldo) Gravado",
    "102": "Ajuste en Participación de los Trabajadores (PTU) Exento",
    "103": "Ajuste en Participación de los Trabajadores (PTU) Gravado",
    "104": "Ajuste en Reembolso de Gastos Médicos Dentales y Hospitalarios Exento",
    "105": "Ajuste en Fondo de ahorro Exento",
    "106": "Ajuste en Caja de ahorro Exento",
    "107": "Ajuste en Contribuciones a Cargo del Trabajador Pagadas por el Patrón Gravado",
    "108": "Ajuste a día de descanso obligatorio laborado exento (Nuevo 2026)",
    "109": "Ajuste a día de descanso obligatorio laborado gravado (Nuevo 2026)",
    "110": "Ajuste a día de descanso no obligatorio laborado exento (Nuevo 2026)",
    "111": "Ajuste a día de descanso no obligatorio laborado gravado (Nuevo 2026)",
}


TIPO_OTRO_PAGO: dict[str, str] = {
    "001": "Reintegro de ISR pagado en exceso (siempre que no haya sido enterado al SAT)",
    "002": "Subsidio para el empleo (efectivamente entregado al trabajador)",
    "003": "Viáticos (entregados al trabajador)",
    "004": "Aplicación de saldo a favor por compensación anual",
    "005": "Reintegro de ISR retenido en exceso de ejercicio anterior",
    "006": "Alimentos en bienes (Servicios de comedor y comida)",
    "007": "ISR ajustado por subsidio",
    "008": "Subsidio efectivamente entregado que no correspondía",
    "009": "Pago en parcialidades derivado de resolución judicial o laudo",
    "999": "Reintegro de ISR retenido en exceso cuando no fue enterado al SAT",
}


TIPO_INCAPACIDAD: dict[str, str] = {
    "01": "Riesgo de trabajo",
    "02": "Enfermedad en general",
    "03": "Maternidad",
    "04": "Licencia por cuidados médicos de hijos",
}


ESTADO: dict[str, str] = {
    "01": "Aguascalientes",
    "02": "Baja California",
    "03": "Baja California Sur",
    "04": "Campeche",
    "05": "Coahuila de Zaragoza",
    "06": "Colima",
    "07": "Chiapas",
    "08": "Chihuahua",
    "09": "Ciudad de México",
    "10": "Durango",
    "11": "Guanajuato",
    "12": "Guerrero",
    "13": "Hidalgo",
    "14": "Jalisco",
    "15": "México",
    "16": "Michoacán de Ocampo",
    "17": "Morelos",
    "18": "Nayarit",
    "19": "Nuevo León",
    "20": "Oaxaca",
    "21": "Puebla",
    "22": "Querétaro",
    "23": "Quintana Roo",
    "24": "San Luis Potosí",
    "25": "Sinaloa",
    "26": "Sonora",
    "27": "Tabasco",
    "28": "Tamaulipas",
    "29": "Tlaxcala",
    "30": "Veracruz de Ignacio de la Llave",
    "31": "Yucatán",
    "32": "Zacatecas",
}


BANCO: dict[str, str] = {
    "002": "Banamex",
    "006": "Bancomext",
    "009": "Banobras",
    "012": "BBVA Bancomer",
    "014": "Santander",
    "019": "Banjército",
    "021": "HSBC",
    "030": "Bajío",
    "032": "IXE",
    "036": "Inbursa",
    "037": "Interacciones",
    "042": "Mifel",
    "044": "Scotiabank",
    "058": "Banregio",
    "059": "Invex",
    "060": "Bansi",
    "062": "Afirme",
    "072": "Banorte",
    "102": "The Royal Bank",
    "103": "American Express",
    "106": "Bank of America",
    "108": "Bank of Tokyo",
    "110": "JP Morgan",
    "112": "Bmonex",
    "113": "Ve Por Mas",
    "116": "ING",
    "124": "Deutsche",
    "126": "Crédit Suisse",
    "127": "Azteca",
    "128": "Autofin",
    "129": "Barclays",
    "130": "Compartamos",
    "131": "Banco Famsa",
    "132": "BMULTIVA",
    "133": "Actinver",
    "134": "WAL-MART",
    "135": "Nafin",
    "136": "Interbanco",
    "137": "Bancoppel",
    "138": "ABC Capital",
    "139": "UBS Bank",
    "140": "Confia",
    "141": "Volkswagen",
    "143": "CiBanco",
    "145": "Bbase",
    "147": "Bankaool",
    "148": "PagaTodo",
    "150": "Inmobiliario",
    "152": "Bancrea",
    "154": "Banco Finterra",
    "155": "ICBC",
    "156": "Sabadell",
    "157": "Shinhan",
    "158": "Banco S3",
    "159": "Banco Covalto",
    "160": "Mizuho Bank",
    "166": "Bank of China",
    "168": "Banco del Bienestar",
}


def descripcion_catalogo(catalogo: dict[str, str], code: str) -> str:
    """Auxiliar para obtener descripción con fallback explícito."""
    return catalogo.get(code, f"Código desconocido: {code}")

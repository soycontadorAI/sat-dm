"""
sat_descarga — Descarga masiva de CFDIs y documentos del SAT (México).

Organizado por canal de acceso:
- ``webservice/`` : Web Service oficial (FIEL/SOAP, asíncrono) — CFDIs.
- ``portal/``     : scraping del portal (CIEC o e.firma) — CFDIs y documentos
                    (constancia de situación fiscal, opinión 32-D, ...).
- ``core/``       : base compartida (config, FIEL, http_client).
- ``utils/``      : parseo XML, metadata, organización, validación.
- ``api/``        : servidores FastAPI (local y hosted).
- ``cli/``        : interfaz de línea de comandos (``sat-dm``).

API pública estable:
    from sat_descarga import descargar_cfdi, FIEL                       # Web Service
    from sat_descarga import descargar_cfdi_ciec, descargar_cfdi_fiel   # portal (CFDIs)
    from sat_descarga import descargar_constancia_ciec, descargar_constancia_fiel
    from sat_descarga import descargar_opinion_ciec, descargar_opinion_fiel
"""

from .webservice.client import descargar_cfdi, verificar_solicitud_existente
from .core.fiel import FIEL
from .webservice.auth import obtener_token
from .webservice.solicitud import solicitar_descarga
from .webservice.verificacion import verificar_solicitud
from .webservice.descarga import descargar_paquete, descargar_todos

# Portal (scraping). Playwright se importa de forma lazy dentro de estas funciones,
# así que re-exportarlas aquí NO requiere el extra `ciec`.
from .portal.cfdi import descargar_cfdi_ciec, descargar_cfdi_fiel
from .portal.constancia import descargar_constancia_ciec, descargar_constancia_fiel
from .portal.opinion import descargar_opinion_ciec, descargar_opinion_fiel
from .portal.declaraciones import descargar_declaraciones_ciec, descargar_declaraciones_fiel
from .portal.diot_consulta import descargar_diot_ciec, descargar_diot_fiel
from .portal.csd import enviar_solicitud_csd_fiel, recuperar_ultimo_csd_fiel
from .portal.renovacion import enviar_renovacion_fiel, recuperar_renovacion_fiel

# Parser de la Constancia de Situación Fiscal (nombre, regímenes, actividades).
from .utils.csf_parser import DatosCsf, parsear_csf

# Parser de la Opinión de Cumplimiento 32-D (sentido positiva/negativa + motivos).
from .utils.opinion_parser import DatosOpinion, parsear_opinion

# Listas negras del SAT (Art. 69 y 69-B). Cliente HTTP hacia todoconta-apps.
from .utils.listas_negras import (
    MatchListaNegra,
    ListasMetadata,
    consultar_rfcs,
    consultar_metadata,
    detectar_edos,
)

# Calculadoras fiscales y laborales (cálculo puro, sin dependencias extra).
from .calculadoras import (
    AguinaldoInput,
    CargaPatronalInput,
    EmpresaPTU,
    FiniquitoInput,
    LiquidacionInput,
    SBCInput,
    TrabajadorPTU,
    calcular_aguinaldo,
    calcular_carga_patronal,
    calcular_finiquito,
    calcular_isr_periodo,
    calcular_liquidacion,
    calcular_ptu,
    calcular_sbc,
)

# DIOT 2025: prellenado desde el procesador + export del TXT de carga masiva.
from .diot import (
    DiotInvalida,
    exportar_txt as exportar_diot_txt,
    prellenar_desde_procesador as prellenar_diot,
    validar_filas as validar_filas_diot,
)

# Certifica: generación de solicitudes de e.firma (.req/.ren) y CSD (.sdg),
# equivalente a la app oficial del SAT. Solo depende de `cryptography`.
from .certifica import (
    generar_requerimiento_fiel,
    generar_renovacion_fiel,
    generar_renovacion_fiel_moral,
    generar_solicitud_csd,
)

__all__ = [
    "descargar_cfdi",
    "verificar_solicitud_existente",
    "FIEL",
    "obtener_token",
    "solicitar_descarga",
    "verificar_solicitud",
    "descargar_paquete",
    "descargar_todos",
    "descargar_cfdi_ciec",
    "descargar_cfdi_fiel",
    "descargar_constancia_ciec",
    "descargar_constancia_fiel",
    "descargar_opinion_ciec",
    "descargar_opinion_fiel",
    "descargar_declaraciones_ciec",
    "descargar_declaraciones_fiel",
    "descargar_diot_ciec",
    "descargar_diot_fiel",
    "DatosCsf",
    "parsear_csf",
    "DatosOpinion",
    "parsear_opinion",
    "MatchListaNegra",
    "ListasMetadata",
    "consultar_rfcs",
    "consultar_metadata",
    "detectar_edos",
    "AguinaldoInput",
    "calcular_aguinaldo",
    "CargaPatronalInput",
    "calcular_carga_patronal",
    "EmpresaPTU",
    "TrabajadorPTU",
    "calcular_ptu",
    "FiniquitoInput",
    "calcular_finiquito",
    "LiquidacionInput",
    "calcular_liquidacion",
    "SBCInput",
    "calcular_sbc",
    "calcular_isr_periodo",
    "DiotInvalida",
    "exportar_diot_txt",
    "prellenar_diot",
    "validar_filas_diot",
    "generar_requerimiento_fiel",
    "generar_renovacion_fiel",
    "generar_renovacion_fiel_moral",
    "generar_solicitud_csd",
    "enviar_solicitud_csd_fiel",
    "recuperar_ultimo_csd_fiel",
    "enviar_renovacion_fiel",
    "recuperar_renovacion_fiel",
]

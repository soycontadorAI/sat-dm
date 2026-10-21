"""
Errores del Web Service del SAT que NO son culpa de la solicitud del usuario.

`CodEstatus=404 «Error no controlado»` es el error interno genérico del SAT:
llega en una respuesta SOAP exitosa (no es un fallo de red, así que el manejo
de timeouts/SSL no lo ve) pero significa "el servicio del SAT está fallando,
reintenta más tarde" — típico en fines de semana y ventanas de mantenimiento.
Verificado en vivo (2026-07-12): la misma solicitud falla igual desde
cualquier red, y minutos u horas después vuelve a funcionar sin cambios.
"""

import re

from sat_descarga.core.errores import ErrorEsperado

_CODESTATUS = re.compile(r"CodEstatus=(\d+)")


def codestatus(mensaje: str) -> str:
    """El `CodEstatus` que trae el texto de un error del WS ('' si no trae)."""
    m = _CODESTATUS.search(mensaje or "")
    return m.group(1) if m else ""


def trae_codestatus(mensaje: str, codigo: str) -> bool:
    """¿El texto trae ese `CodEstatus` en cualquier parte (un error puede encadenar
    varios)?"""
    return codigo in _CODESTATUS.findall(mensaje or "")

# Códigos de estatus del WS que indican fallo interno transitorio del SAT
# (no un rechazo de la solicitud). Hoy solo el 404; si aparecen otros se
# agregan aquí.
CODIGOS_TRANSITORIOS = {"404"}


class ErrorTransitorioSAT(ErrorEsperado):
    """El SAT respondió con un error interno transitorio (p. ej. CodEstatus=404).

    Los routers lo traducen a HTTP 503 («el SAT está fallando, reintenta»),
    igual que los fallos de red — no a 400, que la UI pinta como rechazo
    definitivo de la solicitud.
    """


# ---------------------------------------------------------------------------
# Traducción de los CodEstatus a algo que el contador pueda accionar
#
# El SAT devuelve etiquetas de tres palabras ("Certificado Inválido") que no le
# dicen al usuario qué hacer. La tabla oficial está transcrita en
# docs/producto/protocolo-sat.md; aquí solo van los códigos donde hay una
# acción concreta que sugerir.
# ---------------------------------------------------------------------------

# El caso de los certs de la CA del SAT de mayo 2023: la observación oficial del
# 305 dice "codificación incorrecta", y esos certificados traen un
# PrintableString con bytes UTF-8. El WS de descarga masiva los rechaza, pero el
# portal (login por e.firma, CSF, 32-D y la descarga de comprobantes) SÍ los
# acepta — verificado en vivo. Por eso el mensaje manda a Descarga rápida antes
# que a renovar: para la mayoría, renovar no hace falta.
_AYUDA_CODESTATUS = {
    "300": (
        "El SAT no reconoce al usuario de esta solicitud. Revisa que el RFC y la "
        "e.firma cargada sean del mismo contribuyente."
    ),
    "302": (
        "El SAT no pudo validar la firma de la solicitud. Vuelve a intentar; si "
        "sigue igual, recarga la e.firma de la empresa."
    ),
    "303": (
        "La firma de la solicitud no corresponde al RFC solicitante. Revisa que la "
        "e.firma cargada sea la de esta empresa."
    ),
    "304": (
        "El SAT reporta esta e.firma como revocada o vencida. Hay que renovarla "
        "para poder seguir descargando."
    ),
    "305": (
        "El SAT no acepta este certificado para la descarga masiva por Web "
        "Service. Usa Descarga rápida, que funciona con la misma e.firma; si "
        "necesitas la masiva, hay que renovar la e.firma."
    ),
    "5001": (
        "Este RFC no te tiene autorizado como tercero para descargar sus "
        "comprobantes. El contribuyente debe autorizarte en el portal del SAT."
    ),
    "5005": (
        "Ya tienes una solicitud activa con exactamente los mismos criterios. "
        "Espera a que termine o cambia el rango de fechas."
    ),
}


def mensaje_rechazo(cod: str, msg: str) -> str:
    """Mensaje de rechazo del WS listo para mostrarle al usuario.

    Conserva SIEMPRE `CodEstatus=<cod>` en el texto: hay lógica que ramifica por
    el código leyendo el string del error (p. ej. el reintento del 5002 en
    `solicitud.py`), y soporte necesita el código para diagnosticar.
    """
    base = f"SAT rechazó la solicitud. CodEstatus={cod}, Mensaje={msg}"
    ayuda = _AYUDA_CODESTATUS.get(cod)
    return f"{ayuda} ({base})" if ayuda else base

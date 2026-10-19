"""Adjuntos PDF de un correo, leídos en local (sin LLM) para los agentes de ops.

Hasta ahora `soporte.py` se quedaba solo con el texto del correo: un cliente que
mandaba su Constancia de Situación Fiscal adjunta recibía un borrador pidiéndole
RFC, razón social y domicilio que ya venían en el PDF. Aquí se extraen los PDF,
se identifican las CSF con `lib/csf.py` y se arman dos resúmenes:

  - `para_llm()`: SOLO qué se leyó y si quedó completo. Los datos fiscales del
    cliente (RFC, nombre, CP) no se mandan al modelo: no los necesita para
    redactar y así no salen del contenedor ni suman tokens.
  - `para_israel()`: los datos extraídos, listos para capturar la factura.

Solo lectura: nada de esto toca el buzón ni escribe en ningún lado.
"""

from __future__ import annotations

import email.message
import re
from dataclasses import dataclass
from email.header import decode_header
from typing import Optional

from lib import csf

MAX_BYTES = 8 * 1024 * 1024  # una CSF pesa ~100-300 KB
MAX_PDFS = 3  # por correo; el resto se ignora


@dataclass
class Adjunto:
    nombre: str
    # "csf" (leída) | "pdf_otro" (PDF que no es CSF) | "ilegible" | "omitido" (tamaño)
    estado: str
    csf: Optional[csf.DatosCsf] = None


def _nombre_archivo(parte: email.message.Message) -> str:
    """Nombre del adjunto, decodificado y saneado: viene del remitente y termina
    dentro del prompt, así que solo se deja un nombre de archivo plano."""
    crudo = parte.get_filename() or "(sin nombre)"
    partes = []
    for texto, charset in decode_header(crudo):
        partes.append(
            texto.decode(charset or "utf-8", errors="replace")
            if isinstance(texto, bytes)
            else texto
        )
    return re.sub(r"[^\w .()\-]", "_", "".join(partes)).strip()[:80] or "(sin nombre)"


def _es_pdf(parte: email.message.Message) -> bool:
    nombre = (parte.get_filename() or "").lower()
    return parte.get_content_type() == "application/pdf" or (
        parte.get_content_type() == "application/octet-stream" and nombre.endswith(".pdf")
    )


def analizar(msg: email.message.Message) -> list[Adjunto]:
    """Los PDF adjuntos del correo, ya identificados (máximo MAX_PDFS)."""
    resultado: list[Adjunto] = []
    for parte in msg.walk():
        if parte.is_multipart() or not _es_pdf(parte):
            continue
        if len(resultado) >= MAX_PDFS:
            break
        nombre = _nombre_archivo(parte)
        contenido = parte.get_payload(decode=True) or b""
        if len(contenido) > MAX_BYTES:
            resultado.append(Adjunto(nombre, "omitido"))
            continue
        try:
            datos = csf.extraer_de_pdf(contenido)
        except Exception as e:  # noqa: BLE001 — PDF corrupto/cifrado/lento: no rompe la corrida
            print(f"[adjuntos] no pude leer {nombre}: {type(e).__name__}: {e}")
            resultado.append(Adjunto(nombre, "ilegible"))
            continue
        resultado.append(
            Adjunto(nombre, "csf", datos) if datos else Adjunto(nombre, "pdf_otro")
        )
    return resultado


def para_llm(adjuntos: list[Adjunto]) -> str:
    """Bloque para el prompt del modelo ("" si no hay PDF adjuntos). Sin datos
    fiscales: solo qué se leyó y qué falta. Tampoco lleva los nombres de archivo
    (suelen traer el RFC, p. ej. "Csf_ABC010101XXX.pdf"): van como "Adjunto N"."""
    if not adjuntos:
        return ""
    lineas = ["\n\nADJUNTOS (los leyó el sistema; tú no ves el archivo):"]
    for n, a in enumerate(adjuntos, 1):
        if a.estado == "csf" and a.csf is not None:
            falta = a.csf.faltantes()
            if not falta:
                lineas.append(
                    f'- Adjunto {n}: Constancia de Situación Fiscal LEÍDA con éxito '
                    "(RFC, nombre o razón social, régimen y CP fiscal completos). "
                    "Ya tenemos esos datos: NO los pidas."
                )
            else:
                lineas.append(
                    f'- Adjunto {n}: Constancia de Situación Fiscal leída, pero no se '
                    f"pudo obtener: {', '.join(falta)}. Pide SOLO eso."
                )
        elif a.estado == "pdf_otro":
            lineas.append(f'- Adjunto {n}: PDF que no es una Constancia de Situación Fiscal.')
        elif a.estado == "omitido":
            lineas.append(f'- Adjunto {n}: archivo demasiado grande, no se revisó.')
        else:
            lineas.append(
                f'- Adjunto {n}: PDF que no se pudo leer; si hace falta, pide que lo reenvíen.'
            )
    return "\n".join(lineas)


def para_israel(adjuntos: list[Adjunto]) -> str:
    """Resumen en texto plano para el aviso a Israel ("" si no hay PDF adjuntos),
    con los datos extraídos listos para capturar la factura."""
    if not adjuntos:
        return ""
    lineas = ["ADJUNTOS"]
    for a in adjuntos:
        if a.estado == "csf" and a.csf is not None:
            d = a.csf
            persona = {"PM": "persona moral", "PF": "persona física"}.get(d.tipo_persona, "")
            partes = [
                f"RFC {d.rfc or '—'}",
                d.nombre or "nombre —",
                persona,
                f"régimen: {'; '.join(d.regimenes) if d.regimenes else '—'}",
                f"CP fiscal {d.codigo_postal or '—'}",
            ]
            lineas.append(f"• {a.nombre} — CSF leída: " + " · ".join(p for p in partes if p))
            if d.faltantes():
                lineas.append(f"  Ojo, no se pudo leer: {', '.join(d.faltantes())}. Revisa el PDF.")
        elif a.estado == "pdf_otro":
            lineas.append(f"• {a.nombre} — PDF que no es una CSF.")
        elif a.estado == "omitido":
            lineas.append(f"• {a.nombre} — demasiado grande, no se revisó.")
        else:
            lineas.append(f"• {a.nombre} — no se pudo leer el PDF.")
    return "\n".join(lineas)

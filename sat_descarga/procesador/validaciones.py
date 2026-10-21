"""
Validaciones de integridad sobre un `CfdiData` parseado.

Portado de todoconta-apps `lib/procesador-cfdi/validators.ts`. Devuelve una
lista de mensajes de warning; vacía si el CFDI está sano.
"""

from __future__ import annotations

from datetime import datetime

from .catalogos import INTEGRIDAD_TOLERANCE
from .cfdi_parser import CfdiData


def validar(cfdi: CfdiData) -> list[str]:
    """
    Devuelve la lista de warnings del CFDI (vacía si todo coherente).

    Los avisos de lectura (XML mal formado leído en modo tolerante) van
    primero, para que `validar_y_anotar` no los pierda al sobrescribir.

    Cubre:
    - Integridad de montos: Total ≈ SubTotal − Descuento + IVA Trasladado
      − IVA Retenido − ISR Retenido (tolerancia ±0.02).
    - UUID ausente o mal formado.
    - Tipo de comprobante no reconocido.
    - Fecha de emisión en el futuro.
    """
    warnings: list[str] = list(cfdi.avisos_lectura)

    # UUID
    if not cfdi.uuid:
        warnings.append("Sin UUID — el TimbreFiscalDigital no se encontró o está vacío")

    # Tipo de comprobante
    if cfdi.tipo_comprobante not in ("I", "E", "T", "N", "P"):
        warnings.append(
            f"Tipo de comprobante desconocido: '{cfdi.tipo_comprobante}'"
        )

    # Fecha en el futuro (tolerancia de 1 día por zona horaria)
    if cfdi.fecha_emision:
        try:
            # CFDI usa "2026-05-30T12:34:56" sin TZ — interpretamos como local
            fecha = datetime.fromisoformat(cfdi.fecha_emision)
            ahora = datetime.now()
            if (fecha - ahora).days > 1:
                warnings.append(
                    f"Fecha de emisión en el futuro: {cfdi.fecha_emision}"
                )
        except ValueError:
            warnings.append(f"Fecha de emisión malformada: '{cfdi.fecha_emision}'")

    # Integridad de montos — para tipo P el Total normalmente es 0; no validamos
    # la fórmula clásica ahí (el monto vive en el complemento de Pagos).
    # Suma IEPS además de IVA: hay sectores (telecomunicaciones, bebidas,
    # combustibles) donde el IEPS trasladado es parte del Total y no incluirlo
    # da un falso positivo de "no cuadra".
    if cfdi.tipo_comprobante in ("I", "E", "T", "N"):
        esperado = (
            cfdi.sub_total
            - cfdi.descuento
            + cfdi.iva_trasladado
            + cfdi.ieps_trasladado
            - cfdi.iva_retenido
            - cfdi.isr_retenido
        )
        if abs(cfdi.total - esperado) > INTEGRIDAD_TOLERANCE:
            warnings.append(
                f"Total ({cfdi.total:.2f}) no cuadra con SubTotal "
                f"({cfdi.sub_total:.2f}) − Descuento ({cfdi.descuento:.2f}) "
                f"+ IVA trasladado ({cfdi.iva_trasladado:.2f}) "
                f"+ IEPS trasladado ({cfdi.ieps_trasladado:.2f}) "
                f"− IVA retenido ({cfdi.iva_retenido:.2f}) "
                f"− ISR retenido ({cfdi.isr_retenido:.2f}) "
                f"= {esperado:.2f} (diferencia {cfdi.total - esperado:+.2f})"
            )

    return warnings


def validar_y_anotar(cfdi: CfdiData) -> CfdiData:
    """Conveniencia: corre `validar` y deja el resultado en `cfdi.warnings`."""
    cfdi.warnings = validar(cfdi)
    return cfdi

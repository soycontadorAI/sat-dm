// ---------------------------------------------------------------------------
// Identidad visual de una empresa en la UI (badge PF/PM del sidebar, detalle).
// ---------------------------------------------------------------------------

export type TipoPersona = 'PF' | 'PM';

/** Persona Física (RFC de 13) vs Persona Moral (RFC de 12). */
export function tipoPersona(rfc: string | null | undefined): TipoPersona {
  return (rfc || '').trim().length >= 13 ? 'PF' : 'PM';
}

/**
 * Fondo del cuadro de identidad de una empresa. Señal no tiene colores de
 * identidad: todas van en tinta (el texto encima va en `text-background`). Se
 * queda la firma por RFC para no tocar a quien lo llama.
 */
export function colorEmpresa(_rfc?: string | null): string {
  return 'var(--foreground)';
}

/** Iniciales para avatares (p. ej. del email de la cuenta o del nombre). */
export function iniciales(texto: string | null | undefined): string {
  const limpio = (texto || '').split('@')[0].trim();
  if (!limpio) return '?';
  const partes = limpio.split(/[\s._-]+/).filter(Boolean);
  if (partes.length >= 2) {
    return (partes[0][0] + partes[1][0]).toUpperCase();
  }
  return limpio.slice(0, 2).toUpperCase();
}

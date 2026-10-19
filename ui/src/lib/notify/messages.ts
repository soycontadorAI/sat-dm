/**
 * Pools de mensajes para toasts. Patrón replicado de
 * `todoconta-apps/apps/web/src/lib/toasts/long-running.ts`:
 * mensajes cálidos, en tono mexicano profesional, 3-5 variantes
 * por contexto/timing. Se elige una al azar por evento.
 *
 * Interpolación: {count}, {rfc}, {motivo}, {n}, {dias}.
 */

export type DescargaCanal = 'ws' | 'ciec' | 'fiel';

interface Pool {
  success: string[];
  error: string[];
}

const POOLS_DESCARGA: Record<DescargaCanal, Pool> = {
  ws: {
    success: [
      'Listo: {count} CFDIs descargados para {rfc}.',
      'El SAT respondió. Tienes {count} comprobantes nuevos en {rfc}.',
      'Descarga WS completa: {count} XMLs guardados.',
      'Solicitud lista, {count} CFDIs disponibles para {rfc}.',
    ],
    error: [
      'La descarga WS de {rfc} falló. {motivo}',
      'El SAT rechazó la solicitud de {rfc}. Revisa el detalle.',
      'No pudimos terminar la descarga WS. {motivo}',
    ],
  },
  ciec: {
    success: [
      'Descargamos {count} CFDIs con tu Contraseña del SAT para {rfc}.',
      'Listo, {count} XMLs guardados desde el portal.',
      'Descarga con Contraseña completa: {count} comprobantes para {rfc}.',
    ],
    error: [
      'La descarga con Contraseña del SAT de {rfc} falló. {motivo}',
      'No pudimos completar la descarga del portal. {motivo}',
    ],
  },
  fiel: {
    success: [
      'Listo: terminó el trámite con la e.firma de {rfc}.',
      'El portal del SAT respondió. Operación de {rfc} completada.',
      'Trámite con e.firma completado para {rfc}.',
    ],
    error: [
      'El trámite con la e.firma de {rfc} falló. {motivo}',
      'No pudimos completar la operación en el portal. {motivo}',
    ],
  },
};

const POOL_EFIRMA_AVISO = [
  'Tienes {n} e.firmas por vencer. La más próxima: {rfc} en {dias} días.',
  'Recordatorio: la e.firma de {rfc} vence en {dias} días ({n} en total).',
  '{n} e.firmas necesitan renovación. La que urge: {rfc} a {dias} días.',
];

// Cuando la más urgente YA venció ({dias} llega negativo desde el semáforo).
const POOL_EFIRMA_VENCIDA = [
  'La e.firma de {rfc} venció hace {dias} días. Renuévala o quítala y sigue con la Contraseña del SAT.',
  'Tienes una e.firma vencida: {rfc} (hace {dias} días). Puedes renovarla o quitarla en Empresas.',
];

interface Vars {
  count?: number;
  rfc?: string;
  motivo?: string;
  n?: number;
  dias?: number;
}

function interpolate(template: string, vars: Vars): string {
  return template
    .replace(/\{count\}/g, vars.count != null ? String(vars.count) : '')
    .replace(/\{rfc\}/g, vars.rfc ?? '')
    .replace(/\{motivo\}/g, vars.motivo ?? '')
    .replace(/\{n\}/g, vars.n != null ? String(vars.n) : '')
    .replace(/\{dias\}/g, vars.dias != null ? String(vars.dias) : '');
}

function pick<T>(pool: T[]): T {
  return pool[Math.floor(Math.random() * pool.length)];
}

export function mensajeDescargaSuccess(canal: DescargaCanal, vars: Vars): string {
  return interpolate(pick(POOLS_DESCARGA[canal].success), vars);
}

export function mensajeDescargaError(canal: DescargaCanal, vars: Vars): string {
  return interpolate(pick(POOLS_DESCARGA[canal].error), vars);
}

export function mensajeEfirmaAviso(vars: Vars): string {
  // Vencida (días negativos): otro copy, con los días en positivo.
  if (vars.dias != null && vars.dias < 0) {
    return interpolate(pick(POOL_EFIRMA_VENCIDA), {
      ...vars,
      dias: Math.abs(vars.dias),
    });
  }
  if (vars.dias === 0) {
    return interpolate('La e.firma de {rfc} vence HOY. Renuévala cuanto antes.', vars);
  }
  return interpolate(pick(POOL_EFIRMA_AVISO), vars);
}

/** Renovación de e.firma a medias: 'enviada' falta bajar el cert; si no, falta enviarla. */
export function mensajeRenovacionPendiente(enviada: boolean, rfc: string): string {
  return enviada
    ? interpolate(
        'La renovación de la e.firma de {rfc} ya está en el SAT: falta descargar tu certificado nuevo.',
        { rfc },
      )
    : interpolate(
        'La renovación de la e.firma de {rfc} quedó a medias: tu solicitud está lista para enviarse.',
        { rfc },
      );
}

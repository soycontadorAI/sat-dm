// Lógica pura de la pantalla de Enviar DIOT: leer el periodo de la URL, entender
// el resultado del trámite y comparar totales. Sin React ni fetch para poder
// probarla con `pnpm test`.

import { MESES } from './contabilidad-electronica.ts';
import type { DiotPresentacionResultado, DiotTotales } from './types.ts';

/** Igual que `TOLERANCIA_PESOS` de portal/diot_presentacion.py: el portal redondea. */
export const TOLERANCIA_PESOS = 3;

/** Portal DIOT del SAT: donde se presenta a mano cuando la app no alcanza. */
export const URL_PORTAL_DIOT = 'https://pstcdi.clouda.sat.gob.mx/';

/** "2026-08" */
export function periodoClave(ejercicio: number, mes: number): string {
  return `${ejercicio}-${String(mes).padStart(2, '0')}`;
}

/** "Agosto 2026" */
export function etiquetaPeriodoDiot(ejercicio: number, mes: number): string {
  return `${MESES[mes - 1] ?? mes} ${ejercicio}`;
}

/** Lee `?periodo=YYYY-MM`; null si falta o no es un mes válido. */
export function leerPeriodoParam(valor: string | null): { ejercicio: number; mes: number } | null {
  const m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(valor ?? '');
  return m ? { ejercicio: Number(m[1]), mes: Number(m[2]) } : null;
}

/** Los ejercicios 2025+ usan el TXT de 54 campos; 2024 y anteriores, el de 23. */
export function layoutEsperado(ejercicio: number): '2025' | 'v24' {
  return ejercicio >= 2025 ? '2025' : 'v24';
}

export function etiquetaLayout(layout?: string): string {
  if (layout === '2025') return 'formato 2025 (54 campos)';
  if (layout === 'v24') return 'formato 2024 y anteriores (23 campos)';
  return 'formato desconocido';
}

/**
 * Aviso (no bloquea) si el TXT subido es de un formato distinto al del ejercicio:
 * el portal lo rechazaría. La validación contra el SAT lo confirmaría sin riesgo,
 * así que no se impide avanzar.
 */
export function avisoLayout(ejercicio: number, layout?: string): string | null {
  if (!layout || layout === layoutEsperado(ejercicio)) return null;
  return `Este TXT es del ${etiquetaLayout(layout)}, pero el ejercicio ${ejercicio} usa el ${etiquetaLayout(layoutEsperado(ejercicio))}. El SAT probablemente lo rechace.`;
}

export type VeredictoPresentacion =
  | 'discrepancias'
  | 'validado'
  | 'presentado'
  | 'no_presentada'
  | 'desconocido';

/**
 * Qué le pasó al trámite. Con discrepancias de totales NUNCA se envió nada, y
 * el agente las manda con estado `validado` (el job termina bien): hay que
 * mirarlas antes que el estado.
 */
export function veredictoPresentacion(r: DiotPresentacionResultado | null): VeredictoPresentacion | null {
  if (!r) return null;
  if (r.discrepancias && r.discrepancias.length > 0) return 'discrepancias';
  switch (r.estado) {
    case 'presentado': return 'presentado';
    case 'no_presentada': return 'no_presentada';
    case 'desconocido': return 'desconocido';
    default: return 'validado';
  }
}

export interface FilaTotales {
  etiqueta: string;
  txt: number;
  portal: number;
  /** Operaciones exactas; los montos admiten ±TOLERANCIA_PESOS (redondeo del portal). */
  coincide: boolean;
  diferencia: number;
}

/** TXT vs portal, renglón por renglón; vacío si falta alguno de los dos. */
export function compararTotales(txt: DiotTotales | null, portal: DiotTotales | null): FilaTotales[] {
  if (!txt || !portal) return [];
  const fila = (etiqueta: string, a: number, b: number, tolerancia: number): FilaTotales => ({
    etiqueta,
    txt: a,
    portal: b,
    diferencia: b - a,
    coincide: Math.abs(a - b) <= tolerancia,
  });
  return [
    fila('Operaciones', txt.operaciones, portal.operaciones, 0),
    fila('IVA acreditable', txt.iva_acreditable, portal.iva_acreditable, TOLERANCIA_PESOS),
    fila('IVA retenido', txt.iva_retenido, portal.iva_retenido, TOLERANCIA_PESOS),
  ];
}

export type TonoEstatusDiot = 'success' | 'warning' | 'error' | 'neutral';

/**
 * Tono del estatus que muestra el portal en "Consultar declaración". El
 * vocabulario exacto lo define el SAT, así que se muestra TAL CUAL y el color
 * solo es una ayuda: rechazo en rojo, presentada/aceptada en verde, el resto neutro.
 */
export function tonoEstatusDiot(estado?: string): TonoEstatusDiot {
  const t = (estado ?? '').toLowerCase();
  if (/rechaz|error|inv[aá]lid|cancel/.test(t)) return 'error';
  if (/proces|pendiente|recib/.test(t)) return 'warning';
  if (/presentad|acept|correct|exitos/.test(t)) return 'success';
  return 'neutral';
}

/** Mes (1-12) del selector de Presentadas → rango que se manda al agente. */
export function rangoMeses(mes: number | 'todos'): { mesIni: number; mesFin: number } {
  return mes === 'todos' ? { mesIni: 1, mesFin: 12 } : { mesIni: mes, mesFin: mes };
}

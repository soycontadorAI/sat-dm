// Lógica pura de la pantalla de Contabilidad electrónica (Anexo 24): revisar el
// lote antes de enviarlo y leer los estatus del SAT. Sin React ni fetch para
// poder probarla con `pnpm test`.

import type { CeAcuseFila, CeFicha } from './types.ts';

export const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
];

/** "Enero 2026"; el periodo 13 es el ajuste al cierre del ejercicio. */
export function etiquetaPeriodo(anio?: string, mes?: string): string {
  if (!anio) return '';
  const n = Number(mes);
  if (n === 13) return `Ajuste al cierre ${anio}`;
  if (n >= 1 && n <= 12) return `${MESES[n - 1]} ${anio}`;
  return anio;
}

/** CT es el catálogo de cuentas; BN/BC, la balanza de comprobación. */
export function etiquetaTipo(tipo?: string): string {
  switch (tipo) {
    case 'CT': return 'Catálogo de cuentas';
    case 'BN': return 'Balanza de comprobación';
    case 'BC': return 'Balanza complementaria';
    case 'PL': return 'Pólizas';
    case 'XF': return 'Auxiliar de folios';
    case 'XC': return 'Auxiliar de cuentas';
    default: return tipo ?? '';
  }
}

export interface RevisionLote {
  /** Se puede pasar al siguiente paso. */
  ok: boolean;
  /** Motivos por los que no (lo que la UI muestra en rojo). */
  errores: string[];
}

/**
 * ¿El lote se puede enviar con la empresa activa? El agente repite estas
 * revisiones, pero decirlo aquí evita ir al portal para enterarse: un ZIP con
 * problemas, ZIPs de varios RFC, o de un RFC que no es el de la empresa (el
 * portal entra con la e.firma de UNA empresa).
 */
export function revisarLote(fichas: CeFicha[], rfcEmpresa: string | null): RevisionLote {
  const errores: string[] = [];
  if (fichas.length === 0) return { ok: false, errores: ['Elige al menos un ZIP.'] };

  const conProblemas = fichas.filter((f) => f.problemas.length > 0);
  if (conProblemas.length > 0) {
    errores.push(
      `${conProblemas.length} de ${fichas.length} no pasan la revisión; corrígelos en tu software contable y vuelve a generarlos.`,
    );
  }

  const rfcs = [...new Set(fichas.map((f) => f.rfc).filter((r): r is string => !!r))];
  if (rfcs.length > 1) {
    errores.push(`Los ZIP son de varios RFC (${rfcs.join(', ')}); envía una empresa a la vez.`);
  } else if (rfcs.length === 1 && rfcEmpresa && rfcs[0] !== rfcEmpresa.toUpperCase()) {
    errores.push(
      `Los ZIP son de ${rfcs[0]}, pero la empresa activa es ${rfcEmpresa}. Cambia de empresa o elige otros archivos.`,
    );
  }
  return { ok: errores.length === 0, errores };
}

export type TonoEstatus = 'success' | 'warning' | 'error' | 'neutral';

/** Solo "Aceptado" ampara el cumplimiento; "Recibido" aún lo valida el SAT. */
export function tonoEstatus(estatus?: string): TonoEstatus {
  switch (estatus) {
    case 'Aceptado': return 'success';
    case 'Rechazado': return 'error';
    case 'Recibido': return 'warning';
    default: return 'neutral';
  }
}

export interface ResumenAcuses {
  total: number;
  aceptados: number;
  rechazados: number;
  recibidos: number;
}

export function resumenAcuses(filas: CeAcuseFila[]): ResumenAcuses {
  const cuenta = (e: string) => filas.filter((f) => f.estatus === e).length;
  return {
    total: filas.length,
    aceptados: cuenta('Aceptado'),
    rechazados: cuenta('Rechazado'),
    recibidos: cuenta('Recibido'),
  };
}

/** Ejercicios que ofrece el selector: el actual y los 4 anteriores. */
export function ejerciciosDisponibles(hoy: Date = new Date()): number[] {
  const actual = hoy.getFullYear();
  return Array.from({ length: 5 }, (_, i) => actual - i);
}

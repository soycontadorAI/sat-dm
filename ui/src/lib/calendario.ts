// Lógica pura del cuadro de control (sin React): fechas, lectura de celdas,
// textos y colores por estado. La pantalla vive en app/descarga/calendario.

import type {
  CalendarioAnio,
  CalendarioCelda,
  DireccionCfdi,
  EstadoDia,
} from './types';

export type FiltroDireccion = 'E' | 'R' | 'A';

export const ESTADOS: readonly EstadoDia[] = [
  'pendiente',
  'en_proceso',
  'provisional',
  'consolidado',
  'diferencia',
  'error',
];

export const MESES = [
  'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
  'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
] as const;

export const MESES_CORTO = [
  'ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic',
] as const;

const TEXTO_ESTADO: Record<EstadoDia, string> = {
  pendiente: 'Por descargar',
  en_proceso: 'En proceso',
  provisional: 'Provisional',
  consolidado: 'Consolidado',
  diferencia: 'Diferencia',
  error: 'Error',
};

const NOMBRE_DIRECCION: Record<DireccionCfdi, string> = { E: 'Emitidos', R: 'Recibidos' };

const pad = (n: number) => String(n).padStart(2, '0');

export function textoEstado(estado: EstadoDia): string {
  return TEXTO_ESTADO[estado];
}

export function nombreDireccion(d: DireccionCfdi): string {
  return NOMBRE_DIRECCION[d];
}

/** Estados que muestran el total de la base en la celda. */
export function llevaTotal(estado: EstadoDia): boolean {
  return estado === 'provisional' || estado === 'consolidado' || estado === 'diferencia';
}

/** Días del mes (mes 1-12), con febrero bisiesto. */
export function diasDelMes(anio: number, mes: number): number {
  return new Date(Date.UTC(anio, mes, 0)).getUTCDate();
}

export function fechaIso(anio: number, mes: number, dia: number): string {
  return `${anio}-${pad(mes)}-${pad(dia)}`;
}

/** ¿Existe esa fecha en el calendario (30 de febrero no)? */
export function fechaValida(anio: number, mes: number, dia: number): boolean {
  return mes >= 1 && mes <= 12 && dia >= 1 && dia <= diasDelMes(anio, mes);
}

/** Frente a `hoy` (YYYY-MM-DD): las ISO se comparan como texto. */
export function esFutura(fecha: string, hoy: string): boolean {
  return fecha > hoy;
}

export function rangoMes(anio: number, mes: number): { desde: string; hasta: string } {
  return { desde: fechaIso(anio, mes, 1), hasta: fechaIso(anio, mes, diasDelMes(anio, mes)) };
}

/** "2026-03-04" -> "4 mar 2026". */
export function fechaCorta(fecha: string): string {
  const [a, m, d] = fecha.split('-').map(Number);
  return `${d} ${MESES_CORTO[m - 1]} ${a}`;
}

/** Celda de una dirección; lo ausente es pendiente con 0. */
export function celdaDireccion(
  cal: Pick<CalendarioAnio, 'dias'>,
  fecha: string,
  dir: DireccionCfdi,
): CalendarioCelda {
  return cal.dias[fecha]?.[dir] ?? { estado: 'pendiente', total_bd: 0 };
}

export function direccionesDe(filtro: FiltroDireccion): DireccionCfdi[] {
  return filtro === 'A' ? ['E', 'R'] : [filtro];
}

export type ContenidoCelda =
  | { tipo: 'total'; valor: number }
  | { tipo: 'punto' }
  | { tipo: 'error' }
  | { tipo: 'vacio' };

export interface LecturaCelda {
  fecha: string;
  /** Estado por dirección visible (una con filtro E/R, dos con Ambos). */
  estados: { dir: DireccionCfdi; estado: EstadoDia }[];
  contenido: ContenidoCelda;
  tooltip: string;
}

/**
 * Lee una celda del calendario. En Ambos el número es E+R y el tooltip separa
 * las dos direcciones. `sinPiloto` añade la invitación a Pro en días pasados
 * que nadie ha pedido.
 */
export function celda(
  cal: Pick<CalendarioAnio, 'dias' | 'hoy'>,
  fecha: string,
  filtro: FiltroDireccion,
  opciones: { sinPiloto?: boolean } = {},
): LecturaCelda {
  const dirs = direccionesDe(filtro);
  const lecturas = dirs.map((dir) => ({ dir, c: celdaDireccion(cal, fecha, dir) }));
  const estados = lecturas.map(({ dir, c }) => ({ dir, estado: c.estado }));

  let contenido: ContenidoCelda = { tipo: 'vacio' };
  const conTotal = lecturas.filter(({ c }) => llevaTotal(c.estado));
  if (conTotal.length > 0) {
    contenido = { tipo: 'total', valor: conTotal.reduce((s, { c }) => s + c.total_bd, 0) };
  } else if (lecturas.some(({ c }) => c.estado === 'error')) {
    contenido = { tipo: 'error' };
  } else if (lecturas.some(({ c }) => c.estado === 'en_proceso')) {
    contenido = { tipo: 'punto' };
  }

  const partes = lecturas.map(({ dir, c }) => {
    const base = textoEstado(c.estado);
    const detalle = llevaTotal(c.estado) ? ` (${c.total_bd})` : '';
    // Con filtro E/R el nombre de la dirección va en el encabezado de la pantalla.
    return `${nombreDireccion(dir)}: ${base}${detalle}`;
  });
  let tooltip = `${fechaCorta(fecha)} · ${partes.join(' · ')}`;
  if (opciones.sinPiloto && fecha < cal.hoy && estados.every((e) => e.estado === 'pendiente')) {
    tooltip += ' · Con Pro se descarga solo.';
  }
  return { fecha, estados, contenido, tooltip };
}

/** Fondo de la celda (o de su mitad) por estado, con variante dark. */
export function claseEstado(estado: EstadoDia): string {
  switch (estado) {
    case 'pendiente':
      return 'bg-transparent';
    case 'en_proceso':
      return 'bg-sky-200 dark:bg-sky-800/70';
    case 'provisional':
      return 'bg-emerald-200 dark:bg-emerald-800/60';
    case 'consolidado':
      return 'bg-emerald-600 dark:bg-emerald-600';
    case 'diferencia':
      return 'bg-amber-300 dark:bg-amber-600/80';
    case 'error':
      return 'bg-red-600 dark:bg-red-600';
  }
}

const OSCUROS: ReadonlySet<EstadoDia> = new Set(['consolidado', 'error']);

/** Color del número según el fondo; si las mitades chocan, un chip legible. */
export function claseTexto(estados: EstadoDia[]): string {
  const oscuros = estados.filter((e) => OSCUROS.has(e)).length;
  if (oscuros === 0) return 'text-foreground';
  if (oscuros === estados.length) return 'text-white';
  return 'rounded-sm bg-background/90 px-0.5 text-foreground';
}

/** Punto de la leyenda y de los chips del resumen. */
export function clasePunto(estado: EstadoDia): string {
  return estado === 'pendiente'
    ? 'border border-border bg-transparent'
    : `${claseEstado(estado)} border border-black/10 dark:border-white/10`;
}

/** Conteos del año para el filtro; en Ambos suma E y R. */
export function resumenAnio(
  cal: Pick<CalendarioAnio, 'resumen'>,
  filtro: FiltroDireccion,
): Record<EstadoDia, number> {
  const out = {} as Record<EstadoDia, number>;
  for (const e of ESTADOS) out[e] = 0;
  for (const dir of direccionesDe(filtro)) {
    const r = cal.resumen?.[dir];
    if (!r) continue;
    for (const e of ESTADOS) out[e] += r[e] ?? 0;
  }
  return out;
}

/** Texto humano del estado de una solicitud al SAT. */
export function textoSolicitud(estado: string): string {
  switch (String(estado)) {
    case 'solicitada':
    case '1':
      return 'En cola';
    case '2':
      return 'Procesando';
    case '3':
      return 'Lista';
    case 'descargada':
      return 'Descargada';
    case '4':
      return 'Error del SAT';
    case '5':
      return 'Rechazada';
    case 'vencida':
      return 'Vencida';
    default:
      return String(estado);
  }
}

/** El piloto automático lo da el plan; sin `capacidades`, el flag premium. */
export function tienePiloto(
  license:
    | { capacidades?: { piloto?: boolean } | null; premium_features_unlocked?: boolean }
    | null
    | undefined,
): boolean {
  return license?.capacidades?.piloto ?? (license?.premium_features_unlocked === true);
}

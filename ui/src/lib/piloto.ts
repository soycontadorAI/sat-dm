// Lógica pura de la descarga automática (piloto), sin React.
// La pantalla vive en components/calendario/piloto-panel.tsx.

import { MESES, MESES_CORTO } from './calendario.ts';
import type {
  PilotoAviso,
  PilotoEmpresa,
  PilotoEstado,
  PilotoHistorial,
  PilotoPausadoPor,
  PilotoTipoAviso,
} from './types.ts';

const pad = (n: number) => String(n).padStart(2, '0');

function mismoDia(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
  );
}

/** "1:13" (24 h, sin cero a la izquierda en la hora). */
function horaCorta(d: Date): string {
  return `${d.getHours()}:${pad(d.getMinutes())}`;
}

/**
 * Cuándo es la próxima pasada, relativo a `ahora`: "hoy 1:13", "mañana 1:13",
 * "en curso" (ya venció el plazo) o "13 oct. 1:13" si es más lejos.
 */
export function textoProximaPasada(iso: string | null | undefined, ahora: Date): string {
  if (!iso) return 'sin programar';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 'sin programar';
  if (d.getTime() <= ahora.getTime()) return 'en curso';
  if (mismoDia(d, ahora)) return `hoy ${horaCorta(d)}`;
  const manana = new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate() + 1);
  if (mismoDia(d, manana)) return `mañana ${horaCorta(d)}`;
  return `${d.getDate()} ${MESES_CORTO[d.getMonth()]}. ${horaCorta(d)}`;
}

/** "Cierre de septiembre: 5 oct." a partir de `{periodo: '2026-09', fecha: '2026-10-05'}`. */
export function textoCierre(
  cierre: { periodo: string; fecha: string } | null | undefined,
): string | null {
  if (!cierre) return null;
  const mes = Number(cierre.periodo.slice(5, 7));
  const [, m, d] = cierre.fecha.split('-').map(Number);
  if (!(mes >= 1 && mes <= 12) || !(m >= 1 && m <= 12) || !d) return null;
  return `Cierre de ${MESES[mes - 1].toLowerCase()}: ${d} ${MESES_CORTO[m - 1]}.`;
}

export interface InfoAviso {
  icon: string;
  etiqueta: string;
  /** Clase de color del icono. */
  tono: string;
}

const INFO_AVISO: Record<PilotoTipoAviso, InfoAviso> = {
  resumen: { icon: 'ph:check-circle-light', etiqueta: 'Resumen', tono: 'text-success' },
  cancelacion: { icon: 'ph:receipt-x-light', etiqueta: 'Cancelación', tono: 'text-warning' },
  efirma: { icon: 'ph:shield-check-light', etiqueta: 'e.firma', tono: 'text-warning' },
  error: { icon: 'ph:warning-circle-light', etiqueta: 'Error', tono: 'text-destructive' },
};

export function infoAviso(tipo: PilotoTipoAviso): InfoAviso {
  return INFO_AVISO[tipo] ?? INFO_AVISO.resumen;
}

/** Texto del motivo de pausa; null cuando corre. */
export function textoPausa(p: PilotoPausadoPor): string | null {
  switch (p) {
    case 'sesion':
      return 'Pausada: otra instalación tiene abierta tu cuenta.';
    case 'licencia':
      return 'Tu plan ya no incluye la descarga automática.';
    default:
      return null;
  }
}

export type EtiquetaEstado = 'Activa' | 'Pausada' | 'Apagada';

/** Activa (corriendo), Pausada (encendida pero detenida por sesión/licencia) o Apagada. */
export function etiquetaEstado(e: Pick<PilotoEstado, 'activo' | 'pausado_por'>): EtiquetaEstado {
  if (!e.activo) return 'Apagada';
  return e.pausado_por === 'sesion' || e.pausado_por === 'licencia' ? 'Pausada' : 'Activa';
}

/** Empresas visibles en la lista (sin archivadas). */
export function empresasVisibles(empresas: PilotoEmpresa[]): PilotoEmpresa[] {
  return empresas.filter((e) => e.motivo !== 'Archivada');
}

export function conteoIncluidas(empresas: PilotoEmpresa[]): { incluidas: number; total: number } {
  const vis = empresasVisibles(empresas);
  return { incluidas: vis.filter((e) => e.incluida).length, total: vis.length };
}

export function textoIncluidas(empresas: PilotoEmpresa[]): string {
  const { incluidas, total } = conteoIncluidas(empresas);
  return `${incluidas} de ${total} ${total === 1 ? 'empresa incluida' : 'empresas incluidas'}`;
}

/** Avisos sin leer, del más nuevo al más viejo. */
export function avisosSinLeer(avisos: PilotoAviso[]): PilotoAviso[] {
  return avisos.filter((a) => !a.leido).sort((a, b) => b.creado_en.localeCompare(a.creado_en));
}

/** Tipos que además salen como toast global. */
export function esAvisoDeToast(a: PilotoAviso): boolean {
  return a.tipo === 'resumen' || a.tipo === 'cancelacion' || a.tipo === 'efirma';
}

export type TipoToastPiloto = 'resumen' | 'cancelacion' | 'efirma';

export interface ToastPiloto {
  id: number;
  tipo: TipoToastPiloto;
  mensaje: string;
}

/** Más avisos nuevos que esto a la vez se juntan en uno solo. */
export const MAX_TOASTS_PILOTO = 3;

/**
 * Qué avisar de los avisos nuevos: uno por aviso o, si son más de `max`, uno
 * solo que manda al cuadro de control (un despacho con muchas empresas no debe
 * recibir decenas de notificaciones de golpe).
 */
export function toastsDeAvisos(nuevos: PilotoAviso[], max = MAX_TOASTS_PILOTO): ToastPiloto[] {
  const deToast = nuevos.filter(esAvisoDeToast);
  if (deToast.length <= max) {
    return deToast.map((a) => ({ id: a.id, tipo: a.tipo as TipoToastPiloto, mensaje: a.mensaje }));
  }
  // Un solo tipo: ese. Mezclados: de advertencia si alguno lo es.
  const tipos = new Set(deToast.map((a) => a.tipo));
  let tipo: TipoToastPiloto = 'resumen';
  if (tipos.size === 1) tipo = deToast[0].tipo as TipoToastPiloto;
  else if (tipos.has('cancelacion') || tipos.has('efirma')) tipo = 'cancelacion';
  return [
    {
      id: Math.max(...deToast.map((a) => a.id)),
      tipo,
      mensaje: `${deToast.length} avisos nuevos de la descarga automática. Revísalos en el cuadro de control.`,
    },
  ];
}

// ---------------------------------------------------------------------------
// Historial ("Llenar historial desde…")
// ---------------------------------------------------------------------------

export interface OpcionMes {
  /** "YYYY-MM-01": lo que se manda al agente. */
  valor: string;
  /** "ene 2025". */
  etiqueta: string;
}

function partesMes(s: string | null | undefined): { a: number; m: number } | null {
  const r = /^(\d{4})-(\d{2})/.exec(s ?? '');
  if (!r) return null;
  const a = Number(r[1]);
  const m = Number(r[2]);
  return m >= 1 && m <= 12 ? { a, m } : null;
}

/** "ene 2025" a partir de "2025-01" o "2025-01-01"; '' si no es válido. */
export function etiquetaMes(s: string | null | undefined): string {
  const p = partesMes(s);
  return p ? `${MESES_CORTO[p.m - 1]} ${p.a}` : '';
}

/** "julio de 2026" a partir de "2026-07" o "2026-07-01"; '' si no es válido. */
export function nombreMes(s: string | null | undefined): string {
  const p = partesMes(s);
  return p ? `${MESES[p.m - 1].toLowerCase()} de ${p.a}` : '';
}

/** Meses entre `minimo` y `maximo` (inclusive), del más reciente al más antiguo. */
export function mesesDisponibles(minimo: string, maximo: string): OpcionMes[] {
  const a = partesMes(minimo);
  const b = partesMes(maximo);
  if (!a || !b) return [];
  const out: OpcionMes[] = [];
  let y = b.a;
  let m = b.m;
  while (y > a.a || (y === a.a && m >= a.m)) {
    const valor = `${y}-${pad(m)}-01`;
    out.push({ valor, etiqueta: etiquetaMes(valor) });
    m -= 1;
    if (m === 0) {
      m = 12;
      y -= 1;
    }
  }
  return out;
}

/** Cierres que siguen con trabajo pese a haber detenido el historial; "" si no hay. */
export function textoEmpezados(h: PilotoHistorial): string {
  const n = h.empezados ?? 0;
  if (h.desde || n <= 0) return '';
  return n === 1 ? 'Se termina 1 mes que ya había empezado.' : `Se terminan ${n} meses que ya habían empezado.`;
}

/** Ya no queda mes por pedir (todos en la base o en error sin reintento). */
export function historialTerminado(h: PilotoHistorial): boolean {
  return !!h.desde && h.siguiente === null && h.meses_total > 0;
}

/** 0 a 100. */
export function porcentajeHistorial(h: PilotoHistorial): number {
  if (!h.meses_total) return 0;
  // Los que fallaron sin reintento ya no tienen trabajo: cuentan como hechos.
  const hechos = h.meses_completos + (h.meses_con_error ?? 0);
  return Math.max(0, Math.min(100, Math.round((hechos / h.meses_total) * 100)));
}

/** Mes con que arranca el selector al activar: el guardado, o el mínimo si ya no está en la lista. */
export function desdeInicial(h: PilotoHistorial | undefined): string {
  if (!h?.desde) return '';
  return h.desde < h.minimo ? h.minimo : h.desde;
}

function detallesHistorial(h: PilotoHistorial): string[] {
  const out: string[] = [];
  if (h.meses_con_diferencia > 0) out.push(`${h.meses_con_diferencia} con diferencia`);
  const err = h.meses_con_error ?? 0;
  if (err > 0) out.push(`${err} no se ${err === 1 ? 'pudo' : 'pudieron'} cerrar`);
  return out;
}

/** "3 de 20 meses en la base, 1 con diferencia; va en julio de 2026" o "Terminado". */
export function textoHistorial(h: PilotoHistorial): string {
  if (!h.desde) return '';
  const detalles = detallesHistorial(h);
  // Con varias empresas el total cuenta cierres (empresa x mes).
  const empresas = h.empresas ?? 1;
  const varias = empresas > 1;
  const unidad = varias ? 'cierre' : 'mes';
  const plural = (n: number) => `${n} ${n === 1 ? unidad : unidad === 'mes' ? 'meses' : 'cierres'}`;
  const cuenta = `${h.meses_completos} de ${plural(h.meses_total)}`;
  const prefijo = varias && h.meses
    ? `${empresas} empresas, ${h.meses} ${h.meses === 1 ? 'mes' : 'meses'}: `
    : '';
  if (historialTerminado(h)) {
    const extra = detalles.length ? ` (${detalles.join('; ')})` : '';
    return `Terminado: ${cuenta} en la base${extra}.`;
  }
  let t = `${prefijo}${cuenta} en la base`;
  if (detalles.length) t += `, ${detalles.join(', ')}`;
  const va = nombreMes(h.siguiente);
  if (va) t += `; va en ${va}`;
  return t;
}

/** "Historial: 3/20"; null si la empresa no tiene historial pedido. */
export function textoHistorialEmpresa(e: PilotoEmpresa): string | null {
  const total = e.historial_total ?? 0;
  if (total <= 0) return null;
  return `Historial: ${e.historial_completos ?? 0}/${total}`;
}

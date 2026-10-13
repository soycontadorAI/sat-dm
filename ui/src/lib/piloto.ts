// Lógica pura de la descarga automática (piloto), sin React.
// La pantalla vive en components/calendario/piloto-panel.tsx.

import { MESES, MESES_CORTO } from './calendario.ts';
import type {
  PilotoAviso,
  PilotoEmpresa,
  PilotoEstado,
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

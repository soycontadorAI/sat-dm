// ---------------------------------------------------------------------------
// Dominio de tareas: etiquetas, fechas límite y sugerencias derivadas.
//
// Las sugerencias NO viven en el agente: se derivan aquí de datos que la UI
// ya tiene (catálogo de empresas + calendario). El agente solo persiste los
// descartes y — vía `sugerencia_id` en la tarea — las aceptadas; ambos
// suprimen la sugerencia al re-derivar. Los ids son deterministas para que
// la supresión sobreviva entre sesiones.
// ---------------------------------------------------------------------------

import type {
  Empresa,
  Tarea,
  TareaPrioridad,
  TareaTipo,
} from '@/lib/types';
import { semaforoVencimiento } from '@/lib/vencimiento';

export const TIPO_TAREA_META: Record<TareaTipo, { label: string; icon: string }> = {
  fiscal: { label: 'Fiscal', icon: 'ph:file-text-light' },
  manual: { label: 'Manual', icon: 'ph:user-light' },
  recurrente: { label: 'Recurrente', icon: 'ph:arrows-clockwise-light' },
};

export const PRIORIDADES: { valor: TareaPrioridad; label: string }[] = [
  { valor: 'baja', label: 'Baja' },
  { valor: 'media', label: 'Media' },
  { valor: 'alta', label: 'Alta' },
];

/** Días enteros desde hoy (medianoche local) hasta la fecha "YYYY-MM-DD". */
export function diasDesdeHoy(fecha: string, hoy = new Date()): number {
  const [y, m, d] = fecha.split('-').map(Number);
  const objetivo = new Date(y, (m ?? 1) - 1, d ?? 1);
  const base = new Date(hoy);
  base.setHours(0, 0, 0, 0);
  objetivo.setHours(0, 0, 0, 0);
  return Math.round((objetivo.getTime() - base.getTime()) / 86_400_000);
}

export interface InfoVence {
  texto: string;
  tono: 'rojo' | 'ambar' | 'normal';
  icono: string;
}

/** Etiqueta corta de la fecha límite ("Venció hace 2 días", "Hoy", "mié 15"…). */
export function infoVence(fecha: string | null, hoy = new Date()): InfoVence {
  if (!fecha) return { texto: 'Sin fecha', tono: 'normal', icono: 'ph:clock-light' };
  const dias = diasDesdeHoy(fecha, hoy);
  if (dias < 0) {
    const d = -dias;
    return {
      texto: d === 1 ? 'Venció ayer' : `Venció hace ${d} días`,
      tono: 'rojo',
      icono: 'ph:warning-circle-light',
    };
  }
  if (dias === 0) return { texto: 'Hoy', tono: 'ambar', icono: 'ph:clock-light' };
  if (dias === 1) return { texto: 'Mañana', tono: 'normal', icono: 'ph:clock-light' };
  const f = new Date(fecha + 'T00:00:00');
  const texto =
    dias <= 7
      ? f.toLocaleDateString('es-MX', { weekday: 'short', day: '2-digit' })
      : f.toLocaleDateString('es-MX', { day: '2-digit', month: 'short' });
  return { texto: texto.replace('.', ''), tono: 'normal', icono: 'ph:clock-light' };
}

/** Nombre corto de empresa para chips (primera parte, máx. 24 chars). */
export function nombreCortoEmpresa(nombre: string): string {
  const primero = nombre.split(',')[0];
  return primero.length > 24 ? `${primero.slice(0, 23)}…` : primero;
}

// ---------------------------------------------------------------------------
// Sugerencias derivadas
// ---------------------------------------------------------------------------

export interface Sugerencia {
  /** Determinista: "efirma-{rfc}-{vencimiento}" | "diot-{YYYY-MM}". */
  id: string;
  titulo: string;
  motivo: string;
  rfc: string | null;
  tipo: TareaTipo;
  prioridad: TareaPrioridad;
  fecha: string | null;
}

function fechaIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
    d.getDate(),
  ).padStart(2, '0')}`;
}

/**
 * Deriva las sugerencias vigentes:
 * - Renovar e.firma por empresa activa con vencimiento a ≤ 30 días (aún
 *   vigente: la renovación en línea requiere e.firma viva).
 * - Generar la DIOT del mes anterior (obligación mensual, vence el 17).
 *
 * Suprime las descartadas y las ya aceptadas (tarea con ese `sugerencia_id`).
 */
export function derivarSugerencias(
  empresas: Empresa[],
  tareas: Tarea[],
  descartadas: string[],
  hoy = new Date(),
): Sugerencia[] {
  const suprimidas = new Set([
    ...descartadas,
    ...tareas.map((t) => t.sugerencia_id).filter(Boolean),
  ]);
  const sugerencias: Sugerencia[] = [];

  for (const e of empresas) {
    if (e.archived_at || !e.metodos.includes('fiel')) continue;
    const semaforo = semaforoVencimiento(e.vencimiento);
    if (!semaforo || semaforo.estado === 'verde' || semaforo.vencida) continue;
    sugerencias.push({
      id: `efirma-${e.rfc}-${semaforo.fecha}`,
      titulo: `Renovar la e.firma de ${e.nombre}`,
      motivo:
        semaforo.dias === 0
          ? 'La e.firma vence hoy'
          : `La e.firma vence en ${semaforo.dias} ${semaforo.dias === 1 ? 'día' : 'días'}`,
      rfc: e.rfc,
      tipo: 'fiscal',
      prioridad: 'alta',
      fecha: semaforo.fecha,
    });
  }

  // DIOT del mes anterior: se presenta a más tardar el 17 del mes en curso.
  const mesAnterior = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
  const clave = `${mesAnterior.getFullYear()}-${String(mesAnterior.getMonth() + 1).padStart(2, '0')}`;
  const nombreMes = mesAnterior.toLocaleDateString('es-MX', {
    month: 'long',
    year: 'numeric',
  });
  sugerencias.push({
    id: `diot-${clave}`,
    titulo: `Generar la DIOT de ${nombreMes}`,
    motivo: 'Obligación mensual: vence el 17',
    rfc: null,
    tipo: 'recurrente',
    prioridad: 'media',
    fecha: fechaIso(new Date(hoy.getFullYear(), hoy.getMonth(), 17)),
  });

  const pesoPrioridad: Record<TareaPrioridad, number> = { alta: 0, media: 1, baja: 2 };
  return sugerencias
    .filter((s) => !suprimidas.has(s.id))
    .sort(
      (a, b) =>
        pesoPrioridad[a.prioridad] - pesoPrioridad[b.prioridad] ||
        (a.fecha ?? '9999').localeCompare(b.fecha ?? '9999'),
    );
}

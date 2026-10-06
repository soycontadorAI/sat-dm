// ---------------------------------------------------------------------------
// Semáforo de la Opinión de Cumplimiento 32-D:
//   🟢 verde     → positiva (al corriente)
//   🔴 rojo      → negativa (créditos, omisiones, buzón, 69-B, …)
//   🟡 amarillo  → descargada pero sin analizar, o sentido "otro"
//                  ("sin obligaciones", "no inscrito")
//   ⚪ gris       → aún no se ha descargado
// El sentido lo determina el agente al parsear el PDF (opinion_status).
// ---------------------------------------------------------------------------

import type { Empresa, OpinionStatus } from '@/lib/types';

export type TonoOpinion = 'verde' | 'amarillo' | 'rojo' | 'gris';

export interface SemaforoOpinion {
  tono: TonoOpinion;
  /** Etiqueta corta lista para mostrar. */
  label: string;
  /** True cuando hay motivos que mostrar (negativa). */
  negativa: boolean;
}

export function semaforoOpinion(empresa: Empresa): SemaforoOpinion {
  const status = empresa.opinion_status ?? null;
  if (status === 'positiva') {
    return { tono: 'verde', label: 'Positiva', negativa: false };
  }
  if (status === 'negativa') {
    return { tono: 'rojo', label: 'Negativa', negativa: true };
  }
  if (status === 'otro') {
    return { tono: 'amarillo', label: 'Sin determinar', negativa: false };
  }
  // Sin status: distingue "descargada pero no analizada" de "no descargada".
  if (empresa.opinion_path) {
    return { tono: 'amarillo', label: 'Sin analizar', negativa: false };
  }
  return { tono: 'gris', label: 'No descargada', negativa: false };
}

/** Etiqueta larga para el `title` del semáforo en la lista. */
export function tituloOpinion(status: OpinionStatus | null | undefined): string {
  switch (status) {
    case 'positiva':
      return 'Opinión 32-D: positiva (al corriente)';
    case 'negativa':
      return 'Opinión 32-D negativa: revisa el detalle de la empresa';
    case 'otro':
      return 'Opinión 32-D: sentido sin determinar';
    default:
      return 'Opinión 32-D pendiente';
  }
}

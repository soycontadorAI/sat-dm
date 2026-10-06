// ---------------------------------------------------------------------------
// Qué navegación ve esta instalación: la clásica (sidebar plano) o la de
// espacios (F3). Lógica pura; el estado vive en providers/navegacion-provider.
//
// Orden de decisión (gana la primera que aplique):
//   1. `NAV_ESPACIOS = false` (kill switch) → clásica para todos.
//   2. Preferencia de la instalación (`tc:navegacion`): la fija `?labs=espacios`
//      / `?labs=clasica` o el selector de Ajustes > Apariencia > Navegación.
//   3. Licencia: si el backend manda `navegacion: 'espacios' | 'clasica'`
//      (campo aditivo opcional), manda él. Sirve para encenderla por segmento
//      sin sacar versión.
//   4. `NAV_ESPACIOS_PARA_TODOS` (fase 2) → espacios.
//   5. Desde `NAV_ESPACIOS_DEFAULT_DESDE` (2 de noviembre): las cuentas en
//      prueba (incluidas las reabiertas y las nuevas, que arrancan en prueba)
//      → espacios. Esa decisión se recuerda en la instalación
//      (`tc:navegacion-default`) para que no regresen a la clásica al terminar
//      la prueba o al pagar.
//   6. Lo demás → clásica.
// ---------------------------------------------------------------------------

export type ModoNavegacion = 'clasica' | 'espacios';

export type OrigenModo =
  | 'apagado'
  | 'preferencia'
  | 'licencia'
  | 'para-todos'
  | 'prueba'
  | 'recordado'
  | 'default';

/** Preferencia explícita de la instalación (labs o Ajustes). */
export const LLAVE_PREFERENCIA = 'tc:navegacion';
/** La instalación ya recibió espacios por default (regla del 2 de noviembre). */
export const LLAVE_DEFAULT_RECORDADO = 'tc:navegacion-default';
/** La instalación entró por `?labs=espacios` (muestra el selector antes de tiempo). */
export const LLAVE_LABS = 'tc:labs-espacios';

export interface EntradaModo {
  disponible: boolean;
  preferencia: ModoNavegacion | null;
  /** Campo opcional de la licencia (`license.navegacion`). */
  licencia: ModoNavegacion | null;
  paraTodos: boolean;
  /** La cuenta está en prueba (plan 'trial' o plan_codigo 'trial'). */
  enPrueba: boolean;
  /** La instalación ya había recibido espacios por default. */
  recordado: boolean;
  ahora: Date;
  desde: Date;
}

export function resolverModoNavegacion(e: EntradaModo): {
  modo: ModoNavegacion;
  origen: OrigenModo;
} {
  if (!e.disponible) return { modo: 'clasica', origen: 'apagado' };
  if (e.preferencia) return { modo: e.preferencia, origen: 'preferencia' };
  if (e.licencia) return { modo: e.licencia, origen: 'licencia' };
  if (e.paraTodos) return { modo: 'espacios', origen: 'para-todos' };
  if (e.recordado) return { modo: 'espacios', origen: 'recordado' };
  if (e.enPrueba && e.ahora.getTime() >= e.desde.getTime()) {
    return { modo: 'espacios', origen: 'prueba' };
  }
  return { modo: 'clasica', origen: 'default' };
}

export function esModo(v: unknown): v is ModoNavegacion {
  return v === 'clasica' || v === 'espacios';
}

/**
 * Lee `?labs=` de la URL: 'espacios' enciende, 'clasica' (u 'off') apaga.
 * Acepta listas separadas por coma (`?labs=csd,espacios`), como el `?labs=csd`
 * que ya existe en el detalle de empresa.
 */
export function modoDeLabs(search: string): ModoNavegacion | null {
  const params = new URLSearchParams(search);
  const valores = params
    .getAll('labs')
    .flatMap((v) => v.split(','))
    .map((v) => v.trim().toLowerCase());
  if (valores.includes('espacios')) return 'espacios';
  if (valores.includes('clasica') || valores.includes('off')) return 'clasica';
  return null;
}

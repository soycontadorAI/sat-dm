// Atajos de teclado de la app: detección de plataforma, formato de hints
// (⌘K vs Ctrl+K) y la tabla de referencia que consumen la card de /ayuda y
// los CommandShortcut del palette. La captura real de teclas vive en
// hooks/use-atajos-globales.ts; el cableado de acciones en
// components/layout/global-shortcuts.tsx.

// Eventos window de los atajos (mismo patrón que 'empresas:refresh'):
// desacoplan GlobalShortcuts del Sidebar sin levantar un context.
export const EVENTO_PALETTE_OPEN = 'tc:palette-open';
export const EVENTO_SIDEBAR_TOGGLE = 'tc:sidebar-toggle';

export interface Plataforma {
  desktop: boolean;
  mac: boolean;
  win: boolean;
}

/**
 * Detecta si corremos dentro de Electron y en qué SO. El preload expone la
 * plataforma real (`window.satDesktop.platform`); user-agent solo como
 * fallback (preloads viejos / navegador dev). Llamar solo post-mount: en el
 * primer render (prerender del export estático) devuelve todo false.
 */
export function detectarPlataforma(): Plataforma {
  if (typeof window === 'undefined') return { desktop: false, mac: false, win: false };
  const w = window as unknown as {
    satAgent?: { isDesktop?: boolean };
    satDesktop?: { platform?: string };
  };
  const desktop = !!w.satAgent?.isDesktop;
  const platform = w.satDesktop?.platform;
  if (platform) {
    return { desktop, mac: platform === 'darwin', win: platform === 'win32' };
  }
  const ua = navigator.platform || navigator.userAgent || '';
  return { desktop, mac: /Mac/i.test(ua), win: /Win/i.test(ua) };
}

export function esMac(): boolean {
  return detectarPlataforma().mac;
}

/** Un atajo de la tabla de referencia (solo presentación, no captura). */
export interface Atajo {
  id: string;
  /** Tecla legible: 'K', 'E', '1…7', ',', 'F1'. */
  tecla: string;
  shift?: boolean;
  /** false = sin modificador (teclas de función como F1). */
  mod?: boolean;
  descripcion: string;
  grupo: 'Navegación' | 'Acciones' | 'Vista';
}

/**
 * Formatea un atajo para mostrarlo: mac '⇧⌘L', win/linux 'Ctrl+Shift+L';
 * sin modificador queda la tecla sola ('F1'). Como `esMac()` depende de
 * window, llamar post-mount (patrón de /ajustes).
 */
export function formatearAtajo(
  atajo: Pick<Atajo, 'tecla' | 'shift' | 'mod'>,
  mac: boolean,
): string {
  if (atajo.mod === false) return `${atajo.shift ? (mac ? '⇧' : 'Shift+') : ''}${atajo.tecla}`;
  if (mac) return `${atajo.shift ? '⇧' : ''}⌘${atajo.tecla}`;
  return `Ctrl+${atajo.shift ? 'Shift+' : ''}${atajo.tecla}`;
}

// Tabla de referencia (card "Atajos de teclado" en /ayuda) de la navegación
// clásica. Los ⌘1..⌘9 se asignan por el ORDEN de NAV_ITEMS en
// lib/navegacion.ts — ver nota ahí (a partir de la 10.ª página ya no hay
// dígito; se llega por ⌘K).
export const ATAJOS: readonly Atajo[] = [
  { id: 'palette', tecla: 'K', descripcion: 'Buscar página o acción', grupo: 'Navegación' },
  { id: 'empresas', tecla: 'E', descripcion: 'Cambiar de empresa activa', grupo: 'Navegación' },
  { id: 'paginas', tecla: '1…9', descripcion: 'Ir a la página N del menú (en su orden)', grupo: 'Navegación' },
  { id: 'descarga-rapida', tecla: 'D', shift: true, descripcion: 'Ir a Descarga rápida', grupo: 'Navegación' },
  { id: 'ajustes', tecla: ',', descripcion: 'Abrir Ajustes', grupo: 'Navegación' },
  { id: 'ayuda', tecla: 'F1', mod: false, descripcion: 'Abrir Ayuda', grupo: 'Navegación' },
  { id: 'alta-empresa', tecla: 'N', descripcion: 'Agregar empresa', grupo: 'Acciones' },
  { id: 'tema', tecla: 'L', shift: true, descripcion: 'Alternar tema claro/oscuro', grupo: 'Vista' },
  { id: 'sidebar', tecla: 'B', descripcion: 'Colapsar o expandir el menú lateral', grupo: 'Vista' },
] as const;

// Navegación por espacios (F3): ⌘1..⌘5 son los 5 espacios, en el orden del
// riel (ESPACIOS en lib/navegacion.ts), y ⌘B esconde el panel del espacio.
// Los demás atajos no cambian.
export const ATAJOS_ESPACIOS: readonly Atajo[] = [
  { id: 'palette', tecla: 'K', descripcion: 'Busca o pide algo: pantallas, empresas y órdenes', grupo: 'Navegación' },
  { id: 'espacios', tecla: '1…5', descripcion: 'Ir a Despacho, SAT, Revisar, Cumplimiento o Herramientas', grupo: 'Navegación' },
  { id: 'empresas', tecla: 'E', descripcion: 'Cambiar de empresa activa', grupo: 'Navegación' },
  { id: 'descarga-rapida', tecla: 'D', shift: true, descripcion: 'Ir a Descarga rápida', grupo: 'Navegación' },
  { id: 'ajustes', tecla: ',', descripcion: 'Abrir Ajustes', grupo: 'Navegación' },
  { id: 'ayuda', tecla: 'F1', mod: false, descripcion: 'Abrir Ayuda', grupo: 'Navegación' },
  { id: 'alta-empresa', tecla: 'N', descripcion: 'Agregar empresa', grupo: 'Acciones' },
  { id: 'tema', tecla: 'L', shift: true, descripcion: 'Alternar tema claro/oscuro', grupo: 'Vista' },
  { id: 'panel', tecla: 'B', descripcion: 'Mostrar u ocultar el panel del espacio', grupo: 'Vista' },
] as const;

/** La tabla de atajos que aplica a la navegación que ve esta instalación. */
export function atajosDe(modo: 'clasica' | 'espacios'): readonly Atajo[] {
  return modo === 'espacios' ? ATAJOS_ESPACIOS : ATAJOS;
}

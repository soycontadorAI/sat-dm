// ---------------------------------------------------------------------------
// Una sesión activa a la vez (F1.1): gana la sesión más reciente.
//
// Al abrir la app o iniciar sesión, esta instalación reclama la cuenta y las
// demás se cierran. En la web la instalación es el NAVEGADOR (id en
// localStorage); en escritorio la pone el agente (id en su directorio de datos)
// y lo que se mande desde aquí se ignora.
//
// Lo usa `components/auth/sesion-unica.tsx` (reclamo, latidos y pantalla de
// cierre). Lógica del agente: `sat_descarga/api/sesion_unica.py`.
// ---------------------------------------------------------------------------

/** Latido de la web si el agente no dice otra cosa. */
export const LATIDO_WEB_MS = 60_000;
/** Escritorio: cada cuánto se lee el estado LOCAL del agente (sin red). */
export const ESTADO_ESCRITORIO_MS = 15_000;

const STORAGE_KEY = 'todoconta.instalacion';

let idEnMemoria: string | null = null;

function nuevoId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

/**
 * Id estable de este navegador (web). Si el localStorage está bloqueado vive
 * solo en memoria: cada recarga sería "un navegador nuevo", que con "gana la
 * más reciente" solo significa que reclama al abrir, como siempre.
 */
export function instalacionNavegador(): string {
  if (idEnMemoria) return idEnMemoria;
  try {
    const guardado = window.localStorage.getItem(STORAGE_KEY);
    if (guardado && /^[A-Za-z0-9_-]{8,64}$/.test(guardado)) {
      idEnMemoria = guardado;
      return guardado;
    }
    const nuevo = nuevoId();
    window.localStorage.setItem(STORAGE_KEY, nuevo);
    idEnMemoria = nuevo;
    return nuevo;
  } catch {
    idEnMemoria = nuevoId();
    return idEnMemoria;
  }
}

/** "Chrome en Windows", "Safari en macOS"… a partir del user agent. */
export function etiquetaNavegador(ua: string = typeof navigator !== 'undefined' ? navigator.userAgent : ''): string {
  const navegador = /Edg\//.test(ua)
    ? 'Edge'
    : /OPR\/|Opera/.test(ua)
      ? 'Opera'
      : /Firefox\//.test(ua)
        ? 'Firefox'
        : /Chrome\/|CriOS\//.test(ua)
          ? 'Chrome'
          : /Safari\//.test(ua)
            ? 'Safari'
            : 'Navegador';
  const so = /Windows/.test(ua)
    ? 'Windows'
    : /iPhone|iPad|iPod/.test(ua)
      ? 'iOS'
      : /Mac OS X|Macintosh/.test(ua)
        ? 'macOS'
        : /Android/.test(ua)
          ? 'Android'
          : /Linux/.test(ua)
            ? 'Linux'
            : '';
  return so ? `${navegador} en ${so}` : navegador;
}

/** "hace un momento", "hace 5 min", "hace 2 h", "hace 3 días". */
export function haceCuanto(iso: string | null | undefined, ahora: number = Date.now()): string | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  const min = Math.max(0, Math.floor((ahora - t) / 60_000));
  if (min < 1) return 'hace un momento';
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `hace ${h} h`;
  const d = Math.floor(h / 24);
  return d === 1 ? 'hace 1 día' : `hace ${d} días`;
}

// ---------------------------------------------------------------------------
// Interacción del usuario (para medir uso simultáneo en modo observar)
// ---------------------------------------------------------------------------

let ultimaInteraccion: number | null = null;

/** Marca interacción ahora (teclado, ratón, toque o foco). */
export function marcarInteraccion(): void {
  ultimaInteraccion = Date.now();
}

/** Segundos desde la última interacción, o null si no ha habido. */
export function interaccionHaceS(): number | null {
  if (ultimaInteraccion === null) return null;
  return Math.max(0, Math.floor((Date.now() - ultimaInteraccion) / 1000));
}

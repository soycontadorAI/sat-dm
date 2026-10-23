// Telemetría de errores del renderer (Sentry).
//
// - Desktop: vía @sentry/electron/renderer. El SDK reenvía los eventos al proceso
//   main por IPC; el DSN y el envío real viven en main (ver desktop/main.js).
// - Versión web (esWeb()): vía @sentry/browser, directo al mismo proyecto que la
//   desktop con environment `hosted` (el agente web reporta igual, ver
//   sat_descarga/core/telemetria.py), así un fallo cae en un solo issue.
//
// Fuera de esos dos casos (dev en navegador) todo es no-op. Privacidad: un
// beforeSend redacta RFCs, rutas con nombre de usuario y tokens en URLs antes de
// enviar; nunca se envían e.firma, contraseñas ni datos fiscales.

import { esWeb } from '@/lib/modo';

// La API que usan los helpers de abajo; ambos SDK la exportan igual (@sentry/core).
type SentryRenderer = Pick<
  typeof import('@sentry/browser'),
  'captureException' | 'setUser' | 'addBreadcrumb' | 'captureMessage' | 'captureFeedback'
>;

let sentry: SentryRenderer | null = null;
let activo = false;
// identificarUsuario() puede llegar antes de que termine el import dinámico del
// SDK; se guarda y se aplica al inicializar.
let usuarioPendiente: { id?: string; email?: string } | null = null;

// DSN de la versión web: el mismo que hornea la desktop (no es secreto, va en el
// cliente). NEXT_PUBLIC_SENTRY_DSN lo sobreescribe por si algún día se separa.
const SENTRY_DSN_WEB =
  process.env.NEXT_PUBLIC_SENTRY_DSN ||
  'https://577a136e71f0ab4f39f71123b8a4d3d6@o4511587133947904.ingest.us.sentry.io/4511587138863104';

// Solo inicializamos si el proceso main de Electron habilitó Sentry (window.satAgent
// .sentry === true). En el navegador/dev sin DSN es false → no se inicializa el SDK
// del renderer (evita el "failed to establish connection with the Electron main
// process", porque sin Sentry en main no hay con quién conectarse).
function sentryHabilitado(): boolean {
  if (typeof window === 'undefined') return false;
  return (window as unknown as { satAgent?: { sentry?: boolean } }).satAgent?.sentry === true;
}

const RFC_RE = /\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{2,3}\b/g;
const HOME_RES: Array<[RegExp, string]> = [
  [/([A-Za-z]:\\Users\\)[^\\/]+/gi, '$1<usuario>'],
  [/(\/Users\/)[^/]+/g, '$1<usuario>'],
  [/(\/home\/)[^/]+/g, '$1<usuario>'],
];
// El agente escucha en un puerto efímero distinto en cada arranque; si el puerto
// viaja en el mensaje ("Failed to fetch (127.0.0.1:65005)"), Sentry crea un
// issue NUEVO por puerto y el mismo fallo queda regado en decenas de issues.
// Normalizarlo hace que agrupen en uno solo.
const PUERTO_LOCAL_RE = /(127\.0\.0\.1|localhost):\d+/g;
// El SSE del agente lleva el token en la URL (`/events/{id}?token=…`) y el
// regreso de OAuth trae `access_token=…`; las migas de fetch/navegación copian
// esas URLs tal cual.
const TOKEN_URL_RE = /([?&#](?:token|access_token|refresh_token|code)=)[^&#\s]+/gi;

function redactarTexto(s: string): string {
  let out = s.replace(RFC_RE, '<RFC>');
  for (const [re, rep] of HOME_RES) out = out.replace(re, rep);
  out = out.replace(TOKEN_URL_RE, '$1<redactado>');
  return out.replace(PUERTO_LOCAL_RE, '$1:<puerto>');
}

function scrub(value: unknown): unknown {
  if (typeof value === 'string') return redactarTexto(value);
  if (Array.isArray(value)) return value.map(scrub);
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>;
    for (const k of Object.keys(obj)) {
      if (/(password|contrase|ciec|secreto|secret|token|api[_-]?key)/i.test(k)) {
        obj[k] = '<redactado>';
      } else {
        obj[k] = scrub(obj[k]);
      }
    }
  }
  return value;
}

/** Inicializa Sentry en el renderer (Electron o versión web; idempotente). */
export async function initTelemetria(): Promise<void> {
  if (activo) return;
  try {
    if (sentryHabilitado()) {
      const mod = await import('@sentry/electron/renderer');
      mod.init({
        // El DSN/transport los pone el proceso main; aquí solo el scrub local.
        beforeSend: (event) => scrub(event) as typeof event,
      });
      sentry = mod;
    } else if (esWeb() && SENTRY_DSN_WEB) {
      const mod = await import('@sentry/browser');
      mod.init({
        dsn: SENTRY_DSN_WEB,
        release: process.env.NEXT_PUBLIC_APP_VERSION,
        // Previews de Vercel aparte, para no mezclarlas con producción.
        environment: process.env.NEXT_PUBLIC_VERCEL_ENV === 'preview' ? 'hosted-preview' : 'hosted',
        sendDefaultPii: false,
        // Solo errores de nuestros scripts (no de extensiones del navegador).
        allowUrls: [window.location.origin],
        beforeSend: (event) => scrub(event) as typeof event,
        beforeBreadcrumb: (crumb) => scrub(crumb) as typeof crumb,
      });
      sentry = mod;
    } else {
      return;
    }
    activo = true;
    if (usuarioPendiente) sentry.setUser(usuarioPendiente);
  } catch {
    // best-effort: la telemetría nunca debe romper el arranque del renderer.
  }
}

/** Reporta una excepción si la telemetría está activa; no-op si no. */
export function capturarExcepcion(error: unknown, contexto?: Record<string, unknown>): void {
  if (!activo || !sentry) return;
  sentry.captureException(error, contexto ? { extra: contexto } : undefined);
}

/**
 * Asocia (o desliga) el usuario autenticado a los eventos de Sentry. La app es
 * solo para usuarios registrados, así que el `id`/`email` identifican de quién
 * viene cada reporte — sin exponer nada sensible: la e.firma, las contraseñas y
 * los datos fiscales se siguen redactando en `beforeSend`. Pasa `null` (o un
 * usuario vacío) al cerrar sesión para desligar.
 *
 * `@sentry/electron` sincroniza el scope del renderer hacia el proceso main, así
 * que este `setUser` también queda en los eventos del main (p. ej. los errores
 * del auto-update, que ocurren fuera del renderer).
 */
export function identificarUsuario(
  user: { id?: string | null; email?: string | null } | null,
): void {
  usuarioPendiente =
    user && (user.id || user.email)
      ? { id: user.id ?? undefined, email: user.email ?? undefined }
      : null;
  if (!activo || !sentry) return;
  sentry.setUser(usuarioPendiente);
}

/** Deja una miga (breadcrumb) si la telemetría está activa; no-op si no. */
export function agregarBreadcrumb(crumb: { category?: string; message?: string; level?: 'info' | 'warning' | 'error'; data?: Record<string, unknown> }): void {
  if (!activo || !sentry) return;
  sentry.addBreadcrumb(crumb);
}

/**
 * Envía el reporte del usuario (botón "Reportar un problema"). Devuelve true si se
 * envió, false si la telemetría no está activa (navegador/dev sin DSN).
 *
 * Manda DOS cosas:
 *  - `captureMessage` → crea un **Issue** en Sentry, así dispara la alerta de
 *    "nuevo issue" por correo y aparece en la lista de Issues (donde uno mira).
 *  - `captureFeedback` → además queda en la bandeja "User Feedback", vinculado al
 *    issue anterior (vista más rica con el correo de contacto).
 * Sin esto, un feedback suelto NO aparece en Issues ni dispara alertas de issue.
 */
export function reportarProblema(input: { mensaje: string; email?: string; nombre?: string }): boolean {
  if (!activo || !sentry) return false;
  const eventId = sentry.captureMessage(`Reporte del usuario: ${input.mensaje}`, {
    level: 'info',
    tags: { tipo: 'reporte_usuario' },
    user: input.email ? { email: input.email } : undefined,
    extra: { mensaje: input.mensaje },
  });
  try {
    sentry.captureFeedback({
      message: input.mensaje,
      email: input.email,
      name: input.nombre,
      associatedEventId: eventId,
    });
  } catch {
    /* el feedback es secundario; el issue ya quedó */
  }
  return true;
}

/** ¿La telemetría quedó activa? (para decidir si mostrar el botón de reporte). */
export function telemetriaActiva(): boolean {
  return activo;
}

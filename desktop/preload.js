'use strict';
/*
 * Preload de Electron: puente mínimo y seguro entre el proceso main y el renderer.
 *
 * Por ahora solo expone el base URL del agente (que el main pasó como argumento)
 * para que el renderer (ui/) apunte sus llamadas HTTP al puerto efímero correcto.
 * Aquí se irán agregando, detrás de contextBridge, los file pickers nativos
 * (.cer/.key), revelar archivos en el explorador, etc. El renderer NUNCA toca Node.
 */

const { contextBridge, ipcRenderer } = require('electron');

function leerArg(prefijo) {
  const arg = process.argv.find((a) => a.startsWith(prefijo));
  if (!arg) return null;
  return arg.slice(prefijo.length) || null;
}

// ¿El proceso main inicializó Sentry? (lo decide main según haya DSN). Solo
// entonces montamos el puente IPC del renderer y dejamos que el SDK del renderer
// se conecte. Si lo montáramos sin Sentry en main, el SDK del renderer lanza
// "failed to establish connection with the Electron main process" (p. ej. en
// `pnpm dev` sin DSN). La telemetría JAMÁS debe romper el preload (try/catch).
const SENTRY_HABILITADO = leerArg('--sentry-enabled=') === '1';
if (SENTRY_HABILITADO) {
  try {
    require('@sentry/electron/preload');
  } catch {
    /* best-effort: seguimos sin telemetría del renderer */
  }
}

contextBridge.exposeInMainWorld('satAgent', {
  /** Base URL del agente Python local (http://127.0.0.1:<puerto efímero>). */
  baseUrl: leerArg('--sat-agent-url='),
  /**
   * Token efímero de autenticación con el agente (uno nuevo por arranque).
   * El agente rechaza requests sin él; va como header X-Agent-Token
   * (o ?token= en SSE, porque EventSource no acepta headers).
   */
  token: leerArg('--sat-agent-token='),
  /** Marca para que el renderer sepa que corre dentro de Electron. */
  isDesktop: true,
  /**
   * ¿La telemetría de Sentry está activa en el main? El renderer solo inicializa
   * su SDK si esto es true (si no, el SDK del renderer no encuentra el main y
   * tira un error en consola). Activo en el build de release; en dev, solo si se
   * exportó SENTRY_DSN.
   */
  sentry: SENTRY_HABILITADO,
});

contextBridge.exposeInMainWorld('satDesktop', {
  /**
   * Plataforma del SO ('darwin' | 'win32' | 'linux'). El renderer la usa para
   * decidir el chrome del titlebar (traffic lights de macOS vs controles
   * custom de Windows) sin adivinar por user-agent.
   */
  platform: process.platform,
  /**
   * Controles de ventana custom (Windows corre con titleBarStyle 'hidden';
   * la UI dibuja min/max/cerrar y los conecta aquí). En macOS no se usan
   * (traffic lights nativos).
   */
  windowControls: {
    minimize: () => ipcRenderer.invoke('window-minimize'),
    /** Maximiza o restaura; devuelve el estado resultante (true = maximizada). */
    toggleMaximize: () => ipcRenderer.invoke('window-maximize-toggle'),
    close: () => ipcRenderer.invoke('window-close'),
    isMaximized: () => ipcRenderer.invoke('window-is-maximized'),
    /** Suscribe a cambios de maximizado; devuelve dispose() para limpiar. */
    onMaximizedChanged: (cb) => {
      const handler = (_event, maximized) => cb(maximized);
      ipcRenderer.on('window-maximized-changed', handler);
      return () => ipcRenderer.removeListener('window-maximized-changed', handler);
    },
  },
  /** Abre el selector de carpeta nativo del SO; devuelve la ruta o null. */
  elegirCarpeta: () => ipcRenderer.invoke('elegir-carpeta'),
  /** Selector nativo de archivos .zip (multi-selección); devuelve rutas o []. */
  elegirZips: () => ipcRenderer.invoke('elegir-zips'),
  /**
   * Dispara una notificación nativa del SO (Windows Action Center / macOS
   * Notification Center). Click en la toast → enfoca la ventana de la app.
   * Devuelve true si el SO soporta y se envió, false si no.
   */
  notify: (payload) => ipcRenderer.invoke('notify-native', payload),
  /**
   * Enfoca y trae al frente la ventana de la app (sale de minimizado, sube
   * al frente del SO, hace flash en Windows). Lo usa el flow de login
   * device-code: cuando el usuario completa la activación en el browser,
   * la desktop "se vuelve a poner adelante" sin que el usuario tenga que
   * cambiar de ventana — estilo Notion / 1Password.
   */
  focusWindow: () => ipcRenderer.invoke('focus-window'),
  /**
   * Suscribe un callback al evento "deep link recibido". El SO lanza/enfoca
   * la app con una URL `todoconta://activated?code=XXX` cuando el usuario
   * completa el activate en el browser; el main process la parsea y envía
   * por IPC. El renderer (LoginPage) usa esto para poll inmediato con el
   * code recibido.
   *
   * Devuelve una función `dispose()` para quitar el listener (cleanup).
   */
  onProtocolActivated: (cb) => {
    const handler = (_event, payload) => cb(payload);
    ipcRenderer.on('protocol-activated', handler);
    return () => ipcRenderer.removeListener('protocol-activated', handler);
  },
  /**
   * Actualizaciones de la app (electron-updater contra GitHub Releases).
   * Estado: { estado: 'idle'|'buscando'|'al-dia'|'descargando'|'lista'|'error',
   *           version, progreso, mensaje, disponible }.
   * `disponible: false` = updater inoperante (dev sin empaquetar) → la UI
   * oculta el botón. Lo usa Ajustes → "Buscar actualizaciones".
   */
  updates: {
    /** Dispara una búsqueda manual; devuelve el estado al momento. */
    check: () => ipcRenderer.invoke('updates-check'),
    /** Estado actual sin disparar nada. */
    getState: () => ipcRenderer.invoke('updates-get-state'),
    /** Reinicia e instala el update ya descargado (estado 'lista'). */
    install: () => ipcRenderer.invoke('updates-install'),
    /** Suscribe a cambios de estado; devuelve dispose() para limpiar. */
    onChanged: (cb) => {
      const handler = (_event, state) => cb(state);
      ipcRenderer.on('updates-changed', handler);
      return () => ipcRenderer.removeListener('updates-changed', handler);
    },
  },
});

'use strict';
/*
 * Proceso principal de Electron (TodoConta Desktop).
 *
 * Responsabilidades:
 *   1. Levantar el AGENTE Python (FastAPI) en un puerto efímero local.
 *   2. Esperar a que responda /health.
 *   3. Abrir la ventana y cargar el renderer (ui/), inyectándole el base URL del
 *      agente vía el preload (window.satAgent.baseUrl).
 *   4. Cerrar el agente al salir.
 *
 * Dev:  el agente se levanta con `uv run uvicorn ...` desde la raíz del repo, y el
 *       renderer se sirve con `next dev` (puerto 3001). En producción el agente será
 *       el binario congelado (PyInstaller) y el renderer un export estático (se
 *       ajustará al empaquetar con electron-builder).
 *
 * Variables de entorno (overrides):
 *   SAT_AGENT_URL      Si ya tienes el agente corriendo, úsalo (no se spawnea).
 *   SAT_AGENT_CMD      Comando para levantar el agente (usa el puerto en SAT_AGENT_PORT).
 *   SAT_RENDERER_URL   URL del renderer (default http://localhost:3001).
 */

const { app, BrowserWindow, Notification, nativeImage, shell, dialog, ipcMain, protocol, net: electronNet } = require('electron');
const { spawn } = require('child_process');
const crypto = require('crypto');
const path = require('path');
const net = require('net');
const http = require('http');
const fs = require('fs');
const { pathToFileURL } = require('url');
const { autoUpdater } = require('electron-updater');
const log = require('electron-log');

const REPO_ROOT = path.resolve(__dirname, '..');
const APP_ICON = path.join(__dirname, 'assets', 'icon.png');

// ---------------------------------------------------------------------------
// Telemetría de errores (Sentry) — apagada salvo que haya DSN configurado.
// ---------------------------------------------------------------------------
// El DSN no es secreto (va embebido en el cliente) y un solo proyecto de Sentry
// cubre el shell y el agente (el mismo DSN se inyecta al agente Python al
// spawnearlo, ver spawnAgent). Política de activación:
//   - Release empaquetado → usa el DSN horneado (telemetría siempre activa).
//   - Dev → APAGADA salvo que exportes SENTRY_DSN a mano (para no spamear el
//     proyecto en cada `pnpm dev`; env SENTRY_DSN siempre gana).
// Privacidad: esta app maneja datos fiscales — `scrubEventoSentry` redacta RFCs y
// rutas con nombre de usuario antes de enviar, y adjunta solo la cola del log.
const SENTRY_DSN_HORNEADO =
  'https://577a136e71f0ab4f39f71123b8a4d3d6@o4511587133947904.ingest.us.sentry.io/4511587138863104';
const SENTRY_DSN = process.env.SENTRY_DSN || (app.isPackaged ? SENTRY_DSN_HORNEADO : '');
const SENTRY_ENVIRONMENT = app.isPackaged ? 'production' : 'development';

const _RFC_RE = /\b[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{2,3}\b/g;
const _HOME_RES = [
  [/([A-Za-z]:\\Users\\)[^\\/]+/gi, '$1<usuario>'],
  [/(\/Users\/)[^/]+/g, '$1<usuario>'],
  [/(\/home\/)[^/]+/g, '$1<usuario>'],
];

// El agente escucha en un puerto efímero distinto por arranque: si el puerto
// viaja en un mensaje de error, Sentry agrupa el mismo fallo en un issue por
// puerto. Se normaliza para que agrupen en uno solo.
const _PUERTO_LOCAL_RE = /(127\.0\.0\.1|localhost):\d+/g;

function _redactarTexto(s) {
  let out = s.replace(_RFC_RE, '<RFC>');
  for (const [re, rep] of _HOME_RES) out = out.replace(re, rep);
  return out.replace(_PUERTO_LOCAL_RE, '$1:<puerto>');
}

function _scrub(value) {
  if (typeof value === 'string') return _redactarTexto(value);
  if (Array.isArray(value)) return value.map(_scrub);
  if (value && typeof value === 'object') {
    for (const k of Object.keys(value)) {
      if (/(password|contrase|ciec|secreto|secret|token|api[_-]?key)/i.test(k)) {
        value[k] = '<redactado>';
      } else {
        value[k] = _scrub(value[k]);
      }
    }
  }
  return value;
}

function _colaDelLog(maxBytes = 50 * 1024) {
  try {
    const p = log.transports.file.getFile().path;
    const buf = fs.readFileSync(p);
    const slice = buf.length > maxBytes ? buf.subarray(buf.length - maxBytes) : buf;
    return _redactarTexto(slice.toString('utf8'));
  } catch {
    return null;
  }
}

function scrubEventoSentry(event, hint) {
  // Rechazo de firma del auto-updater: esperado en instalaciones previas a la
  // firma de código (se atiende con un aviso de reinstalación manual, ver
  // manejarErrorUpdater). Ya lo atrapamos para que no sea unhandledRejection;
  // este guard es defensa en profundidad por si electron-updater lo emite por
  // otra vía. No es un bug accionable → no se reporta.
  if (esErrorDeFirmaDeUpdate(hint && hint.originalException)) return null;
  const limpio = _scrub(event);
  const cola = _colaDelLog();
  if (cola) {
    hint.attachments = [
      { filename: 'main.log', data: cola, contentType: 'text/plain' },
      ...(hint.attachments || []),
    ];
  }
  return limpio;
}

if (SENTRY_DSN) {
  try {
    const Sentry = require('@sentry/electron/main');
    Sentry.init({
      dsn: SENTRY_DSN,
      release: app.getVersion(),
      environment: SENTRY_ENVIRONMENT,
      sendDefaultPii: false,
      beforeSend: scrubEventoSentry,
    });
    log.info('[sentry] telemetría activada (%s)', SENTRY_ENVIRONMENT);
  } catch (e) {
    log.warn('[sentry] no se pudo inicializar:', e.message);
  }
}

// Esquema propio para servir el renderer empacado (ui/out) con un ORIGEN real
// (app://-/...) en lugar de file://. Necesario porque sobre file:// los paths
// absolutos que emite Next (`/_next/...`, `/icon.png`) y la navegación del
// router (`/empresas`, ...) resuelven contra la raíz del disco (`file:///C:/...`)
// y fallan con ERR_FILE_NOT_FOUND. Con un origen `app://` resuelven contra la
// raíz del bundle. DEBE registrarse antes de `app.whenReady()`.
const APP_SCHEME = 'app';

// Modo debug del renderer: abre DevTools y loguea cada request del handler
// `app://` (qué archivo sirve / cuándo cae al fallback SPA). Se activa con
// `SAT_DEBUG_RENDERER=1` — pensado para reproducir el bundle empacado en Mac
// vía `pnpm debug:packaged` (ver desktop/CLAUDE.md). Inofensivo en prod.
const DEBUG_RENDERER = process.env.SAT_DEBUG_RENDERER === '1';
protocol.registerSchemesAsPrivileged([
  {
    scheme: APP_SCHEME,
    privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
  },
]);

// Nombre visible en el menú de la app de macOS (About / Hide / Quit) y en
// `app.getName()`. El tooltip del dock y el source de las notificaciones
// nativas siguen viniendo del bundle (Electron.app en dev) — eso solo
// cambia cuando empaquetemos con electron-builder. Debe llamarse antes
// de app.whenReady() para que surta efecto en el menú inicial.
app.setName('TodoConta');

// AppUserModelId: obligatorio en Windows 10/11 para que las notificaciones
// nativas aparezcan con el nombre correcto en el Action Center y se agrupen
// bien en el taskbar. DEBE setearse antes de app.whenReady() o no surte
// efecto. Mismo id que usaremos para el appId de electron-builder cuando
// empaquetemos para producción.
if (process.platform === 'win32') {
  app.setAppUserModelId('com.todoconta.desktop');
}

// Protocol handler para `todoconta://...` (deep links estilo Notion).
//
// Flujo:
//   1. La app desktop genera un device_code.
//   2. El user completa el activate en la web.
//   3. La página `/desktop/activate` de todoconta-apps redirige a
//      `todoconta://activated?code=XXXXXXXX` al éxito.
//   4. El SO lanza esta app (o trae al frente si ya está corriendo).
//   5. Aquí parseamos la URL, enfocamos la ventana y le decimos al renderer
//      "hay un device_code listo — poll inmediato".
//
// En dev (electron .) el registro puede fallar silenciosamente porque el
// app no está realmente instalada — la prueba real es post-`pnpm build`.
// Sí funciona en dev para el escenario "app corriendo + URL via second-instance".
if (process.defaultApp) {
  // dev: argv[1] es el script
  if (process.argv.length >= 2) {
    app.setAsDefaultProtocolClient('todoconta', process.execPath, [path.resolve(process.argv[1])]);
  }
} else {
  app.setAsDefaultProtocolClient('todoconta');
}

// Single-instance lock: si el usuario lanza la app un segundo tiempo (vía
// protocolo o doble-click en el ícono), no spawneamos un proceso nuevo —
// fire del evento `second-instance` en la primera instancia y la traemos
// al frente.
const gotInstanceLock = app.requestSingleInstanceLock();
if (!gotInstanceLock) {
  app.quit();
}

// Pendiente: la URL de protocolo capturada al startup ANTES de que la ventana
// exista. Se enviará al renderer cuando esté lista.
let pendingProtocolUrl = null;

/**
 * Extrae el code de una URL `todoconta://<action>?code=XXX`.
 *   - `activated`     → device-code flow legado.
 *   - `auth-callback` → OAuth con Google (PKCE): el `code` es el auth_code que
 *     el agente canjea por la sesión. Si el usuario cancela, Supabase regresa
 *     `?error=...` en vez de `code`.
 */
function parseProtocolUrl(url) {
  if (!url || typeof url !== 'string') return null;
  if (!url.startsWith('todoconta://')) return null;
  try {
    const u = new URL(url);
    const action = u.host || u.pathname.replace(/^\/+/, '');  // "activated" | "auth-callback"
    const code = u.searchParams.get('code');
    // Defensa en profundidad: el code (device-flow o auth_code PKCE) es corto y
    // url-safe; nada con otra pinta cruza al renderer.
    if (code && !/^[A-Za-z0-9_-]{1,256}$/.test(code)) return null;
    // OAuth fallido (p. ej. el usuario canceló en Google): solo dejamos pasar
    // un código de error corto y conocido, no el texto crudo de Supabase.
    let error = u.searchParams.get('error');
    if (error && !/^[A-Za-z0-9_-]{1,64}$/.test(error)) error = 'oauth_error';
    return { action, code, error: error || null };
  } catch {
    return null;
  }
}

/** Busca una URL `todoconta://...` dentro de un argv. */
function protocolUrlFromArgv(argv) {
  return argv.find((a) => typeof a === 'string' && a.startsWith('todoconta://')) || null;
}

/**
 * Aplica el evento de deep link: enfoca la ventana y, si el renderer ya
 * está vivo, le manda el code para que polleé de inmediato. Si no hay
 * ventana todavía, deja la URL pendiente.
 */
function handleProtocolUrl(url) {
  const parsed = parseProtocolUrl(url);
  if (!parsed) return;

  const wins = BrowserWindow.getAllWindows();
  const win = wins[0];
  if (!win) {
    pendingProtocolUrl = url;
    return;
  }

  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  win.moveTop();
  if (process.platform === 'darwin' && app.dock) {
    try { app.dock.show(); } catch (_) { /* noop */ }
    app.focus({ steal: true });
  }
  if (process.platform === 'win32') {
    try { win.flashFrame(true); setTimeout(() => win.flashFrame(false), 600); } catch (_) { /* noop */ }
  }

  // Notificar al renderer (LoginPage escucha esto y dispara un poll inmediato
  // con el code recibido).
  try {
    win.webContents.send('protocol-activated', parsed);
  } catch (_) { /* noop */ }
}

// Captura inicial de URL de protocolo cuando la app se LANZA por primera
// vez con `todoconta://...`. En Windows/Linux viene en argv; en macOS, vía
// evento `open-url`.
const initialUrl = protocolUrlFromArgv(process.argv);
if (initialUrl) pendingProtocolUrl = initialUrl;

app.on('second-instance', (_event, argv) => {
  const url = protocolUrlFromArgv(argv);
  if (url) handleProtocolUrl(url);
  else {
    // Segundo launch sin URL: solo traer al frente.
    const win = BrowserWindow.getAllWindows()[0];
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  }
});

// macOS: cuando el SO abre la app con `todoconta://...`, esto se dispara
// (no llega vía argv como en otros SO).
app.on('open-url', (event, url) => {
  event.preventDefault();
  if (BrowserWindow.getAllWindows().length === 0) {
    // App aún no terminó de arrancar; guardamos para más tarde.
    pendingProtocolUrl = url;
  } else {
    handleProtocolUrl(url);
  }
});

// ---------------------------------------------------------------------------
// Auto-update (electron-updater)
// ---------------------------------------------------------------------------
//
// Flujo:
//   1. 30s después de que la ventana esté lista, autoUpdater consulta el
//      GitHub Release más reciente (configurado vía electron-builder.yml), y
//      lo re-consulta cada 4 horas (sesiones largas + checks fallidos por red
//      lenta/antivirus ya no se quedan sin update — antes era UN solo intento
//      silencioso por sesión).
//   2. Si hay versión nueva, descarga el .exe + delta en background SIN
//      molestar al usuario (no popups intermedios).
//   3. Cuando termina la descarga (`update-downloaded`), muestra UN solo
//      dialog: "Reiniciar ahora / Más tarde".
//   4. Si el user elige "Más tarde", el update se aplica en el próximo
//      arranque (electron-updater lo deja stageado).
//
// Además, Ajustes tiene un botón "Buscar actualizaciones": el renderer dispara
// `updates-check` por IPC y sigue el progreso con `updates-changed`. En ese
// caso el dialog nativo del paso 3 se omite (la UI muestra "Reiniciar ahora"
// en su lugar, justo donde el usuario está mirando).
//
// En dev (NO empaquetado) NO arranca: electron-updater requiere
// `app-update.yml` que solo existe en el bundle. Si se invoca en dev,
// loguea warning y sale.

log.transports.file.level = 'info';
log.transports.console.level = 'warn';
autoUpdater.logger = log;
autoUpdater.autoDownload = true;
autoUpdater.autoInstallOnAppQuit = true;

const UPDATE_RECHECK_INTERVAL_MS = 4 * 60 * 60 * 1000; // 4 horas

// Estado del updater que consume el renderer (Ajustes → "Buscar actualizaciones").
//   estado: 'idle' | 'buscando' | 'al-dia' | 'descargando' | 'lista' | 'error'
const updaterState = {
  estado: 'idle',
  version: null, // versión nueva detectada (si hay)
  progreso: null, // % de descarga (0-100)
  mensaje: null, // detalle del error (si estado === 'error')
  requiereReinstalar: false, // true si el error exige reinstalar a mano (firma)
};
// true mientras el check en curso lo pidió el usuario desde Ajustes: el dialog
// nativo de "update listo" se omite y la UI muestra el botón de reiniciar.
let busquedaManual = false;

function setUpdaterState(patch) {
  Object.assign(updaterState, patch);
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('updates-changed', { ...updaterState });
  }
}

// Página pública de descarga (para la reinstalación manual descrita abajo).
const URL_DESCARGA = 'https://todoconta.com/descargar';

// ¿El error del updater es un rechazo de FIRMA del instalador?
// Pasa en instalaciones previas a la firma de código (v1.4.0 y anteriores, cuyo
// app-update.yml tiene grabado publisherName "TodoConta"): al descargar un update
// firmado con el nuevo certificado IV (CN "Israel Castro Urieta") electron-updater
// lo rechaza por mismatch de publisher ("...is not signed by the application
// owner"), o falla al verificar la firma con Get-AuthenticodeSignature. No hay
// arreglo por auto-update: el usuario debe reinstalar a mano por única vez. Se
// detecta para (1) no dejar que el rechazo se vuelva unhandledRejection → Sentry
// y (2) mostrar un mensaje accionable en lugar de un error genérico.
function esErrorDeFirmaDeUpdate(err) {
  const msg = (err && err.message) || (typeof err === 'string' ? err : '');
  return /not signed by the application owner|is not signed|Get-AuthenticodeSignature/i.test(msg);
}

// El dialog de "reinstala a mano" se muestra UNA vez por sesión (el re-check es
// cada 4h; no queremos repetirlo).
let avisoReinstalarMostrado = false;

// Handler unificado de errores del updater (check, descarga automática y manual).
function manejarErrorUpdater(err) {
  busquedaManual = false;
  if (esErrorDeFirmaDeUpdate(err)) {
    log.warn('[updater] update rechazado por firma (instalación previa a la firma de código):', err && err.message);
    setUpdaterState({
      estado: 'error',
      requiereReinstalar: true,
      mensaje: `No se pudo actualizar automáticamente esta instalación. Descarga la última versión desde ${URL_DESCARGA} e instálala encima (tus datos y empresas se conservan).`,
    });
    mostrarAvisoReinstalar();
    return;
  }
  log.warn('[updater] error (silencioso):', err && err.message);
  setUpdaterState({
    estado: 'error',
    requiereReinstalar: false,
    mensaje: (err && err.message) || 'Error desconocido',
  });
}

function mostrarAvisoReinstalar() {
  if (avisoReinstalarMostrado) return;
  avisoReinstalarMostrado = true;
  const parent = BrowserWindow.getAllWindows()[0] || null;
  dialog
    .showMessageBox(parent, {
      type: 'info',
      buttons: ['Ir a la descarga', 'Más tarde'],
      defaultId: 0,
      cancelId: 1,
      title: 'Actualización manual requerida',
      message: 'Hay una versión nueva de TodoConta, pero esta instalación necesita actualizarse a mano por única vez.',
      detail: `Descarga la última versión desde ${URL_DESCARGA} e instálala encima. Tus datos y empresas se conservan.`,
      noLink: true,
    })
    .then((choice) => {
      if (choice.response === 0) shell.openExternal(URL_DESCARGA);
    })
    .catch(() => {});
}

// Con autoDownload=true, la descarga arranca sola tras `update-available` y su
// promesa vive en `result.downloadPromise`. Si no la enganchamos, un rechazo
// (p. ej. la verificación de firma) se vuelve unhandledRejection → Sentry. La
// atrapamos y la enrutamos al handler unificado.
function engancharDescarga(result) {
  if (result && result.downloadPromise) {
    result.downloadPromise.catch((err) => manejarErrorUpdater(err));
  }
  return result;
}

function setupAutoUpdaterListeners() {
  autoUpdater.on('checking-for-update', () => {
    log.info('[updater] buscando update...');
    setUpdaterState({ estado: 'buscando', mensaje: null });
  });
  autoUpdater.on('update-available', (info) => {
    log.info('[updater] update disponible:', info.version);
    // autoDownload=true: la descarga arranca sola en cuanto se detecta.
    setUpdaterState({ estado: 'descargando', version: info.version, progreso: 0 });
  });
  autoUpdater.on('update-not-available', () => {
    log.info('[updater] no hay update');
    busquedaManual = false;
    setUpdaterState({ estado: 'al-dia', version: null, progreso: null });
  });
  autoUpdater.on('error', (err) => {
    manejarErrorUpdater(err);
  });
  autoUpdater.on('download-progress', (p) => {
    log.info(`[updater] descargando ${Math.round(p.percent)}%`);
    setUpdaterState({ estado: 'descargando', progreso: Math.round(p.percent) });
  });

  autoUpdater.on('update-downloaded', async (info) => {
    log.info('[updater] update descargado:', info.version);
    const manual = busquedaManual;
    busquedaManual = false;
    setUpdaterState({ estado: 'lista', version: info.version, progreso: 100 });
    if (manual) return; // la UI de Ajustes ofrece "Reiniciar ahora"; sin doble prompt.

    const wins = BrowserWindow.getAllWindows();
    const parent = wins[0] || null;
    const choice = await dialog.showMessageBox(parent, {
      type: 'info',
      buttons: ['Reiniciar ahora', 'Más tarde'],
      defaultId: 0,
      cancelId: 1,
      title: 'Actualización lista',
      message: `TodoConta ${info.version} está lista para instalarse.`,
      detail: 'Se aplicará al reiniciar la aplicación. Tus datos y empresas se conservan.',
      noLink: true,
    });
    if (choice.response === 0) {
      // quitAndInstall(isSilent=false, isForceRunAfter=true)
      autoUpdater.quitAndInstall(false, true);
    }
    // "Más tarde" → autoInstallOnAppQuit lo aplica cuando el user cierre.
  });
}

function checkForUpdatesSilencioso() {
  autoUpdater
    .checkForUpdates()
    .then(engancharDescarga)
    .catch((err) => manejarErrorUpdater(err));
}

function scheduleUpdateCheck() {
  if (!app.isPackaged) {
    log.info('[updater] skip en dev (app no empacada).');
    return;
  }
  setTimeout(checkForUpdatesSilencioso, 30_000);
  setInterval(() => {
    // Con un update ya descargado/stageado no hay nada que re-consultar.
    if (updaterState.estado === 'lista' || updaterState.estado === 'descargando') return;
    checkForUpdatesSilencioso();
  }, UPDATE_RECHECK_INTERVAL_MS);
}

let agentProc = null;
let agentUrl = null;
// Token efímero por arranque: el agente solo acepta requests que lo traigan
// (header X-Agent-Token; ?token= para SSE). Lo conocen únicamente este
// proceso, el agente (vía env) y el renderer (vía preload). Cierra el hueco
// de que cualquier otro proceso local use el agente con la FIEL en sesión.
let agentToken = null;

function getFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function waitForHealth(baseUrl, timeoutMs = 60000) {
  // 60s en lugar de 30s: en equipos con Windows Defender activo + sin firma EV,
  // el primer arranque del PyInstaller (~50 archivos) puede tardar minutos
  // mientras AV los escanea uno por uno. Un timeout chico hacía que main.js
  // continuara sin agente vivo y el renderer se quedaba en "Cargando…" para
  // siempre (sin pista para el user). Si tampoco responde en 60s, el renderer
  // sigue mostrando un mensaje útil (ver app-shell.tsx) en lugar de un blank
  // eterno.
  const deadline = Date.now() + timeoutMs;
  const headers = agentToken ? { 'X-Agent-Token': agentToken } : {};
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const req = http.get(`${baseUrl}/health`, { headers }, (res) => {
        res.resume();
        if (res.statusCode === 200) resolve();
        else retry();
      });
      req.on('error', retry);
    };
    const retry = () => {
      if (Date.now() > deadline) {
        reject(new Error('El agente no respondió a /health a tiempo.'));
      } else {
        setTimeout(attempt, 400);
      }
    };
    attempt();
  });
}

/**
 * Resuelve [cmd, cwd] para spawnear el agente Python según el entorno.
 *
 * - Producción (empaquetado por electron-builder): usa el binario `sat-agent.exe`
 *   incluido como extraResource. `app.isPackaged === true` y el binario vive en
 *   `<resources>/agent/sat-agent.exe` (o sin .exe en macOS/Linux para dev).
 * - Override por env: SAT_AGENT_CMD permite forzar un comando arbitrario
 *   (útil para QA o builds custom). Se respeta siempre, incluso en producción.
 * - Dev (no empaquetado): default a `uv run uvicorn sat_descarga.api.server:app`
 *   desde la raíz del repo.
 */
function resolverComandoAgente(port) {
  if (process.env.SAT_AGENT_CMD) {
    return {
      cmd: process.env.SAT_AGENT_CMD.split(' '),
      cwd: process.cwd(),
    };
  }

  if (app.isPackaged) {
    const exeName = process.platform === 'win32' ? 'sat-agent.exe' : 'sat-agent';
    const agentExe = path.join(process.resourcesPath, 'agent', exeName);
    return {
      // El agente lee --port y/o $SAT_AGENT_PORT.
      cmd: [agentExe, '--port', String(port)],
      // cwd = dir del .exe para que lxml/uvicorn encuentren sus dlls relativos.
      cwd: path.dirname(agentExe),
    };
  }

  // Dev (no empaquetado).
  return {
    cmd: ['uv', 'run', 'uvicorn', 'sat_descarga.api.server:app',
          '--host', '127.0.0.1', '--port', String(port)],
    cwd: REPO_ROOT,
  };
}

/**
 * Directorio raíz del bundle estático del renderer.
 *
 * - Empacado: `<resources>/ui` (extraResource → ui/out copiado ahí).
 * - Debug en Mac/dev: `SAT_RENDERER_BUNDLE_DIR` (absoluto) apunta al `ui/out`
 *   del repo para reproducir el entorno empacado (protocolo `app://` +
 *   trailingSlash) SIN construir un instalador. Ver `pnpm debug:packaged`.
 */
function rendererBundleDir() {
  if (process.env.SAT_RENDERER_BUNDLE_DIR) {
    return path.resolve(process.env.SAT_RENDERER_BUNDLE_DIR);
  }
  return path.join(process.resourcesPath, 'ui');
}

/**
 * Registra el handler del protocolo `app://`. Sirve archivos del bundle del
 * renderer (`<resources>/ui`) resolviendo paths absolutos contra esa raíz.
 *
 * Resolución de rutas (el UI usa `trailingSlash: true`, así que cada ruta es
 * una carpeta con `index.html`):
 *   - `/`                 → `index.html`
 *   - `/empresas/`        → `empresas/index.html`
 *   - `/empresas`         → `empresas/index.html` (sin extensión → prueba dir)
 *   - `/_next/x.js`       → `_next/x.js` (tiene extensión → directo)
 *   - ruta inexistente    → fallback a `index.html` (SPA: cubre reload de rutas
 *                           dinámicas como `/empresas/<RFC>/`, que el router de
 *                           Next hidrata client-side vía useParams)
 *
 * Seguridad: la ruta final se normaliza y se verifica que quede DENTRO de
 * `rendererBundleDir()` (anti path-traversal); si se sale, 403.
 */
function registerAppProtocol() {
  const baseDir = rendererBundleDir();

  protocol.handle(APP_SCHEME, async (request) => {
    let pathname;
    try {
      pathname = decodeURIComponent(new URL(request.url).pathname);
    } catch {
      pathname = '/';
    }

    // Candidatos de archivo a servir, en orden de preferencia.
    const rel = pathname.replace(/^\/+/, '');
    const candidates = [];
    if (rel === '' || pathname.endsWith('/')) {
      candidates.push(path.join(rel, 'index.html'));
    } else if (path.extname(rel)) {
      candidates.push(rel); // asset con extensión (.js, .css, .png, ...)
    } else {
      candidates.push(path.join(rel, 'index.html')); // ruta sin slash → dir
      candidates.push(`${rel}.html`);
    }
    // Fallback SPA: si nada matchea, entregamos el index para que el router
    // client-side de Next resuelva la ruta (incl. rutas dinámicas).
    candidates.push('index.html');

    for (const cand of candidates) {
      const resolved = path.resolve(baseDir, cand);
      // Anti path-traversal: el archivo debe vivir bajo baseDir. path.relative
      // no depende de separadores finales ni de mayúsculas/minúsculas raras.
      const relResolved = path.relative(baseDir, resolved);
      if (relResolved.startsWith('..') || path.isAbsolute(relResolved)) {
        continue;
      }
      try {
        if (fs.existsSync(resolved) && fs.statSync(resolved).isFile()) {
          // En debug, avisamos cuando una ruta cayó al fallback SPA (index.html
          // raíz): es la señal de "esta subruta no tiene archivo prerenderizado
          // → se va a ver como el dashboard". Ver docs/debug en desktop/CLAUDE.md.
          if (DEBUG_RENDERER && cand === 'index.html' && pathname !== '/' && !pathname.endsWith('/index.html')) {
            log.warn(`[protocol] ${pathname} → FALLBACK index.html (sin archivo prerenderizado; se verá como dashboard)`);
          } else if (DEBUG_RENDERER) {
            log.info(`[protocol] ${pathname} → ${cand}`);
          }
          return electronNet.fetch(pathToFileURL(resolved).toString());
        }
      } catch (_) {
        /* probar siguiente candidato */
      }
    }

    if (DEBUG_RENDERER) log.warn(`[protocol] ${pathname} → 404 (ningún candidato existe)`);
    return new Response('Not found', { status: 404 });
  });
}

/**
 * Resuelve la URL del renderer (la app Next.js) según el entorno.
 *
 * - Override por env: SAT_RENDERER_URL siempre gana (debug, builds custom).
 * - Producción: bundle estático exportado a ui/out/ → empaquetado como
 *   extraResource en `<resources>/ui` → servido por el protocolo `app://`
 *   (origen real; ver registerAppProtocol).
 * - Dev (no empaquetado): http://localhost:3001 donde corre `pnpm dev` del UI.
 */
function resolverRendererUrl() {
  if (process.env.SAT_RENDERER_URL) {
    return process.env.SAT_RENDERER_URL;
  }
  if (app.isPackaged) {
    // Host `-` arbitrario pero estable: el handler ignora el host y resuelve
    // por pathname. `app://-/` → index.html del bundle.
    return `${APP_SCHEME}://-/`;
  }
  return 'http://localhost:3001';
}

function spawnAgent(port) {
  const { cmd, cwd } = resolverComandoAgente(port);

  log.info('[agente] iniciando:', cmd.join(' '), 'cwd:', cwd);
  // stdio piped (no inherit): así capturamos stdout/stderr del agente al
  // archivo de electron-log. Si el agente revienta antes de poder configurar
  // su propio logger (`%LOCALAPPDATA%\TodoConta\logs\agent.log`), por lo
  // menos queda traza en `main.log` del shell.
  agentProc = spawn(cmd[0], cmd.slice(1), {
    cwd,
    env: {
      ...process.env,
      SAT_AGENT_PORT: String(port),
      SAT_AGENT_TOKEN: agentToken,
      // Telemetría: el agente Python usa el mismo DSN/entorno que el shell.
      // Sin DSN, su init_sentry() es no-op.
      SENTRY_DSN,
      SENTRY_RELEASE: app.getVersion(),
      SENTRY_ENVIRONMENT,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  if (agentProc.stdout) {
    agentProc.stdout.on('data', (d) => log.info('[agent stdout]', d.toString().trimEnd()));
  }
  if (agentProc.stderr) {
    agentProc.stderr.on('data', (d) => log.info('[agent stderr]', d.toString().trimEnd()));
  }
  agentProc.on('error', (e) => log.error('[agente] no se pudo lanzar:', e.message));
  agentProc.on('exit', (code) => log.info('[agente] terminó (código', code + ')'));
}

/**
 * Asigna puerto/token y lanza el agente (o se conecta a uno externo vía
 * SAT_AGENT_URL). NO espera /health: la ventana se abre de inmediato y el
 * StartupSplash del renderer informa el progreso; quien necesite el agente
 * listo debe esperar con waitForHealth() aparte.
 */
async function startAgent() {
  // Si el dev ya levantó el agente manualmente, conéctate a ese. Si ese
  // agente exige token (SAT_AGENT_TOKEN en su env), pásalo también aquí.
  if (process.env.SAT_AGENT_URL) {
    agentUrl = process.env.SAT_AGENT_URL.replace(/\/+$/, '');
    agentToken = process.env.SAT_AGENT_TOKEN || null;
    return;
  }

  const port = await getFreePort();
  agentUrl = `http://127.0.0.1:${port}`;
  agentToken = crypto.randomBytes(32).toString('hex');
  spawnAgent(port);
}

// ---------------------------------------------------------------------------
// Monitor del agente: detecta si muere DESPUÉS del arranque (crash, OOM) y lo
// reinicia en el MISMO puerto y con el MISMO token — el renderer conserva el
// baseUrl/token que le dio el preload, así que un puerto nuevo lo dejaría
// incomunicado sin recargar la ventana. El renderer se entera de la caída y
// la recuperación solo, por su propio polling de /health (badge Conectado).
// ---------------------------------------------------------------------------

const MONITOR_INTERVAL_MS = 10_000;
const MONITOR_FALLOS_REINICIO = 3; // ~30s sin responder → reinicio
const MONITOR_MAX_REINICIOS = 3;   // consecutivos; un periodo sano resetea

let monitorTimer = null;

async function reiniciarAgente() {
  const port = Number(new URL(agentUrl).port);
  try {
    if (agentProc && !agentProc.killed) agentProc.kill('SIGKILL');
  } catch (_) { /* noop */ }
  agentProc = null;
  spawnAgent(port);
  await waitForHealth(agentUrl, 60000);
}

function iniciarMonitorAgente() {
  // Agente externo (SAT_AGENT_URL): no es nuestro, no lo administramos.
  if (monitorTimer || process.env.SAT_AGENT_URL) return;

  let fallos = 0;
  let reinicios = 0;
  let ocupado = false;

  monitorTimer = setInterval(() => {
    if (ocupado) return;

    const evaluar = (ok) => {
      if (ok) {
        fallos = 0;
        reinicios = 0;
        return;
      }
      fallos += 1;
      if (fallos < MONITOR_FALLOS_REINICIO) return;
      fallos = 0;
      if (reinicios >= MONITOR_MAX_REINICIOS) {
        log.error(
          `[monitor] el agente sigue caído tras ${MONITOR_MAX_REINICIOS} reinicios; se detiene el monitor.`,
        );
        clearInterval(monitorTimer);
        monitorTimer = null;
        return;
      }
      reinicios += 1;
      ocupado = true;
      log.warn(`[monitor] agente sin respuesta; reinicio ${reinicios}/${MONITOR_MAX_REINICIOS}…`);
      reiniciarAgente()
        .then(() => log.info('[monitor] agente reiniciado y respondiendo.'))
        .catch((e) => log.error('[monitor] el reinicio falló:', e && e.message))
        .finally(() => {
          ocupado = false;
        });
    };

    const req = http.get(
      `${agentUrl}/health`,
      { headers: agentToken ? { 'X-Agent-Token': agentToken } : {} },
      (res) => {
        res.resume();
        evaluar(res.statusCode === 200);
      },
    );
    req.on('error', () => evaluar(false));
  }, MONITOR_INTERVAL_MS);
}

function createWindow() {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 1024,
    minHeight: 700,
    backgroundColor: '#F7F9FC',
    // En Windows/Linux esto pinta el ícono del taskbar/ventana; en macOS
    // el dock se setea aparte vía app.dock.setIcon (más abajo).
    icon: APP_ICON,
    // macOS: barra translúcida con traffic lights nativos. Windows: 'hidden'
    // quita la barra nativa pero CONSERVA frame/resize/Aero Snap; la UI dibuja
    // sus propios min/max/cerrar (window-controls.tsx) vía IPC. NO usar
    // titleBarOverlay (dibujaría controles nativos encima de los nuestros).
    // Linux se queda con la barra del sistema.
    titleBarStyle:
      process.platform === 'darwin'
        ? 'hiddenInset'
        : process.platform === 'win32'
          ? 'hidden'
          : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // El preload lee estos args y expone window.satAgent.{baseUrl,token,sentry}.
      additionalArguments: [
        `--sat-agent-url=${agentUrl || ''}`,
        `--sat-agent-token=${agentToken || ''}`,
        // Solo si el main inicializó Sentry (hay DSN). Si no, el renderer NO debe
        // inicializar su SDK o lanza "failed to establish connection with the
        // Electron main process" (típico en `pnpm dev` sin DSN).
        `--sentry-enabled=${SENTRY_DSN ? '1' : '0'}`,
      ],
    },
  });

  // Links externos → navegador del SO (p. ej. el billing de la web).
  // Solo protocolos web seguros: nada de file://, javascript:, esquemas custom.
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const protocolo = new URL(url).protocol;
      if (['http:', 'https:', 'mailto:'].includes(protocolo)) {
        shell.openExternal(url);
      } else {
        log.warn('[window-open] protocolo bloqueado:', url);
      }
    } catch (_) {
      /* URL inválida → no abrir nada */
    }
    return { action: 'deny' };
  });

  // Si tenemos una URL de protocolo pendiente (la app se LANZÓ por un
  // `todoconta://...` antes de que la ventana existiera), la disparamos
  // cuando el renderer termine de cargar.
  win.webContents.once('did-finish-load', () => {
    if (pendingProtocolUrl) {
      const url = pendingProtocolUrl;
      pendingProtocolUrl = null;
      handleProtocolUrl(url);
    }
  });

  // El renderer dibuja el botón maximizar/restaurar según este estado
  // (window-controls.tsx escucha 'window-maximized-changed').
  win.on('maximize', () => win.webContents.send('window-maximized-changed', true));
  win.on('unmaximize', () => win.webContents.send('window-maximized-changed', false));

  const rendererUrl = resolverRendererUrl();
  if (DEBUG_RENDERER) {
    log.info('[debug] renderer URL:', rendererUrl, '| bundle:', rendererBundleDir());
    win.webContents.openDevTools({ mode: 'right' });
  }
  win.loadURL(rendererUrl);
}

// Enfoca y trae al frente la ventana. Lo invoca el LoginPage del renderer
// cuando completa el activate device-code (estilo Notion / 1Password).
ipcMain.handle('focus-window', () => {
  const wins = BrowserWindow.getAllWindows();
  const win = wins[0];
  if (!win) return false;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  win.moveTop();
  // En macOS, además trae la app entera al foreground.
  if (process.platform === 'darwin' && app.dock) {
    try { app.dock.show(); } catch (_) { /* noop */ }
    app.focus({ steal: true });
  }
  // En Windows, hace flash brevemente para que el user vea la transición.
  if (process.platform === 'win32') {
    try { win.flashFrame(true); setTimeout(() => win.flashFrame(false), 600); } catch (_) { /* noop */ }
  }
  return true;
});

// Controles de ventana custom (Windows: titleBarStyle 'hidden' → la UI dibuja
// min/max/cerrar). Cada handler opera sobre la ventana del renderer que invoca.
ipcMain.handle('window-minimize', (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (win) win.minimize();
});

ipcMain.handle('window-maximize-toggle', (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (!win) return false;
  if (win.isMaximized()) win.unmaximize();
  else win.maximize();
  return win.isMaximized();
});

ipcMain.handle('window-close', (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  if (win) win.close();
});

ipcMain.handle('window-is-maximized', (e) => {
  const win = BrowserWindow.fromWebContents(e.sender);
  return win ? win.isMaximized() : false;
});

// Selector de carpeta nativo (lo usa Ajustes para elegir dónde guardar descargas).
ipcMain.handle('elegir-carpeta', async () => {
  const r = await dialog.showOpenDialog({
    properties: ['openDirectory', 'createDirectory'],
  });
  return r.canceled || r.filePaths.length === 0 ? null : r.filePaths[0];
});

// Selector de archivos .zip (contabilidad electrónica: los ZIP que genera el
// software contable del usuario). Multi-selección; devuelve rutas o [].
ipcMain.handle('elegir-zips', async () => {
  const r = await dialog.showOpenDialog({
    properties: ['openFile', 'multiSelections'],
    filters: [{ name: 'ZIP de contabilidad electrónica', extensions: ['zip'] }],
  });
  return r.canceled ? [] : r.filePaths;
});

// Notificaciones nativas del SO.
//   title: string (corto, ≤40 chars idealmente)
//   body: string (mensaje del pool de lib/notify/messages.ts)
//   urgent: boolean (si true, el SO suena; si false, silent)
// El click enfoca la ventana de la app (sale de minimizado, sube al frente).
ipcMain.handle('notify-native', (_e, payload) => {
  if (!Notification.isSupported()) return false;
  const { title, body, urgent } = payload || {};
  if (!title) return false;

  const n = new Notification({
    title: String(title),
    body: body ? String(body) : '',
    silent: !urgent,
  });
  n.on('click', () => {
    const wins = BrowserWindow.getAllWindows();
    const win = wins[0];
    if (!win) return;
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
    win.moveTop();
    // En Windows, limpia el resaltado del taskbar después de enfocar.
    if (process.platform === 'win32') {
      try { win.flashFrame(false); } catch (_) { /* noop */ }
    }
  });
  n.show();
  return true;
});

// Actualizaciones (Ajustes → "Buscar actualizaciones"). `disponible: false`
// significa que el updater no opera (dev sin empaquetar): la UI oculta el botón.
ipcMain.handle('updates-get-state', () => ({
  ...updaterState,
  disponible: app.isPackaged,
}));

ipcMain.handle('updates-check', () => {
  if (!app.isPackaged) {
    return { ...updaterState, disponible: false };
  }
  // No encimar checks: si ya está buscando/descargando, devolver el estado actual.
  if (updaterState.estado !== 'buscando' && updaterState.estado !== 'descargando') {
    busquedaManual = true;
    autoUpdater
      .checkForUpdates()
      .then(engancharDescarga)
      .catch((err) => manejarErrorUpdater(err));
  }
  return { ...updaterState, disponible: true };
});

ipcMain.handle('updates-install', () => {
  if (updaterState.estado !== 'lista') return false;
  // quitAndInstall(isSilent=false, isForceRunAfter=true)
  autoUpdater.quitAndInstall(false, true);
  return true;
});

app.whenReady().then(async () => {
  // macOS: el ícono del dock se cambia explícitamente (no lo agarra del
  // BrowserWindow). En Win/Linux ya quedó vía `icon:` en createWindow.
  if (process.platform === 'darwin' && app.dock) {
    try {
      app.dock.setIcon(nativeImage.createFromPath(APP_ICON));
    } catch (e) {
      console.warn('[icon] no se pudo setear el dock icon:', e.message);
    }
  }

  // Registrar el protocolo `app://` ANTES de abrir la ventana. Solo se usa en
  // prod (en dev el renderer se carga de localhost:3001), pero registrarlo
  // siempre es inofensivo y evita condiciones de carrera si SAT_RENDERER_URL
  // apunta a `app://` para QA.
  try {
    registerAppProtocol();
  } catch (e) {
    log.error('[protocol] no se pudo registrar app://:', e && e.message);
  }

  try {
    await startAgent(); // solo puerto + spawn: milisegundos, ya no espera /health
  } catch (e) {
    log.error('No se pudo lanzar el agente Python:', e && e.message);
    // Abrimos la ventana de todos modos; el renderer mostrará el splash con
    // mensaje útil y botón "Reintentar".
  }

  // Ventana INMEDIATA: antes se esperaba el /health completo y, en equipos
  // con HDD + antivirus escaneando el binario sin firma, eso eran 30-60s sin
  // NADA en pantalla (la app parecía rota). El renderer ya conoce el baseUrl
  // (el puerto se asigna antes del spawn) y su StartupSplash informa el
  // progreso mientras el agente termina de arrancar.
  createWindow();

  if (agentUrl) {
    waitForHealth(agentUrl, 120000)
      .then(() => {
        log.info('[agente] /health OK — agente listo');
        iniciarMonitorAgente();
      })
      .catch((e) => log.error('[agente] no respondió /health:', e && e.message));
  }

  setupAutoUpdaterListeners();
  scheduleUpdateCheck();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});

let _salidaEnCurso = false;

app.on('will-quit', (event) => {
  if (monitorTimer) {
    clearInterval(monitorTimer);
    monitorTimer = null;
  }
  if (!agentProc || _salidaEnCurso) return;
  if (agentProc.exitCode !== null) {
    // Ya estaba muerto (crash previo): no hay nada que esperar.
    agentProc = null;
    return;
  }

  // Detener la salida hasta que el agente muera de verdad: si el main se va
  // antes, un Python colgado queda huérfano consumiendo memoria. SIGTERM
  // primero; si en 2s no salió, SIGKILL y adiós.
  event.preventDefault();
  _salidaEnCurso = true;
  const proc = agentProc;
  agentProc = null;

  const forzar = setTimeout(() => {
    try {
      proc.kill('SIGKILL');
    } catch (_) { /* noop */ }
    app.quit();
  }, 2000);

  proc.once('exit', () => {
    clearTimeout(forzar);
    app.quit();
  });

  try {
    proc.kill();
  } catch (_) {
    clearTimeout(forzar);
    app.quit();
  }
});

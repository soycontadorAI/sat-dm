// Fuente única de las páginas de la app.
//
// Hay dos navegaciones mientras dure la transición (F3,
// todoconta-apps/docs/producto/navegacion-espacios.md):
//
// - **Clásica**: el sidebar plano. Sus atajos ⌘1..⌘9 se asignan por la
//   POSICIÓN en NAV_ITEMS (⌘1 = primer item, ⌘2 = segundo, ...). Si se
//   reordenan, agregan o mueven páginas, el número de cada atajo cambia con
//   ellas; la card de atajos en /ayuda se regenera sola, pero avisa el cambio
//   en el CHANGELOG.
// - **Espacios**: `ESPACIOS`, 5 espacios fijos con sus destinos. De aquí salen
//   el riel, el panel, las páginas del buscador (⌘K), ⌘1..⌘5 y `espacioDe()`.
//   Agregar un destino no mueve ningún atajo: los números son los espacios.
//
// Ninguna URL cambia entre una y otra: el espacio de una pantalla se deriva
// del pathname.

export interface PaginaNav {
  href: string;
  label: string;
  icon: string;
}

// Nav plano del sidebar (Ajustes vive en el menú de cuenta; Ayuda en el footer).
export const NAV_ITEMS: readonly PaginaNav[] = [
  { href: '/', label: 'Inicio', icon: 'ph:squares-four-light' },
  // Tareas va 2.º a propósito (decisión de producto 2026-07-09): recorrió los
  // atajos ⌘2..⌘9 existentes; anotado en el CHANGELOG de esa fecha.
  { href: '/tareas', label: 'Tareas', icon: 'ph:clipboard-text-light' },
  { href: '/empresas', label: 'Empresas', icon: 'ph:buildings-light' },
  { href: '/descarga', label: 'Descargar CFDIs', icon: 'ph:download-simple-light' },
  { href: '/comprobantes', label: 'Comprobantes', icon: 'ph:files-light' },
  { href: '/listas-negras', label: 'Listas negras', icon: 'ph:shield-check-light' },
  { href: '/organizador', label: 'Organizador', icon: 'ph:folders-light' },
  { href: '/historial', label: 'Historial', icon: 'ph:clock-counter-clockwise-light' },
  { href: '/calculadoras', label: 'Calculadoras', icon: 'ph:calculator-light' },
  // Al FINAL a propósito: agregarla en medio movería los atajos ⌘N existentes.
  { href: '/diot', label: 'DIOT', icon: 'ph:file-text-light' },
] as const;

// Páginas fuera del nav plano (footer del sidebar / menú de cuenta).
export const NAV_SECUNDARIO: readonly PaginaNav[] = [
  { href: '/ayuda', label: 'Ayuda', icon: 'ph:question-light' },
  { href: '/ajustes', label: 'Ajustes', icon: 'ph:gear-light' },
] as const;

// Páginas adicionales que el palette ofrece pero no viven en el sidebar.
export const PAGINAS_EXTRA: readonly PaginaNav[] = [
  { href: '/descarga/rapida', label: 'Descarga rápida', icon: 'ph:lightning-light' },
] as const;

// ---------------------------------------------------------------------------
// Navegación por espacios
// ---------------------------------------------------------------------------

export type EspacioId = 'despacho' | 'sat' | 'revisar' | 'cumplimiento' | 'herramientas';

export interface Destino {
  /** Estable: Recientes, telemetría y la pantalla Próximamente lo usan. */
  id: string;
  /**
   * Ruta existente; no se crean URLs nuevas. Sin href = Próximamente (abre la
   * pantalla genérica, sin ruta propia, hasta que la función exista).
   */
  href?: string;
  label: string;
  /** Nombre corto para el sub-destino desplegado ("CFDI", "Nómina"). */
  corto?: string;
  icon: string;
  /** Una línea; se ve en el panel y en ⌘K. */
  descripcion: string;
  /** Texto de la pantalla Próximamente (qué va a hacer). */
  detalle?: string;
  /** Se despliegan en el panel cuando la ruta activa está dentro del destino. */
  hijos?: Destino[];
  estado?: 'nuevo' | 'pronto';
  /** En la web lleva la etiqueta "Escritorio". */
  soloEscritorio?: boolean;
  /** Para ⌘K: 'csf', '69-b', 'balanza'. Se comparan sin acentos. */
  sinonimos?: string[];
}

export interface Espacio {
  id: EspacioId;
  label: string;
  icon: string;
  /** "Lo que bajas del SAT": encabezado del panel. */
  descripcion: string;
  destinos: Destino[];
}

const CALCULADORAS: Destino[] = [
  { id: 'calc-isr', href: '/calculadoras/isr', label: 'ISR de sueldos', corto: 'ISR', icon: 'ph:percent-light', descripcion: 'Retención mensual con subsidio para el empleo', sinonimos: ['isr', 'sueldos', 'salarios', 'retencion'] },
  { id: 'calc-aguinaldo', href: '/calculadoras/aguinaldo', label: 'Aguinaldo', icon: 'ph:gift-light', descripcion: 'Proporcional y su parte exenta', sinonimos: ['aguinaldo'] },
  { id: 'calc-sbc', href: '/calculadoras/sbc', label: 'Salario Base de Cotización', corto: 'SBC', icon: 'ph:heartbeat-light', descripcion: 'Factor de integración y SBC', sinonimos: ['sbc', 'salario base', 'integracion'] },
  { id: 'calc-finiquito', href: '/calculadoras/finiquito', label: 'Finiquito', icon: 'ph:receipt-light', descripcion: 'Partes proporcionales al terminar', sinonimos: ['finiquito'] },
  { id: 'calc-liquidacion', href: '/calculadoras/liquidacion', label: 'Liquidación', icon: 'ph:scales-light', descripcion: 'Finiquito más indemnizaciones', sinonimos: ['liquidacion', 'indemnizacion'] },
  { id: 'calc-carga', href: '/calculadoras/carga-patronal', label: 'Carga patronal', icon: 'ph:factory-light', descripcion: 'Cuotas IMSS, Infonavit e ISN', sinonimos: ['carga patronal', 'imss', 'infonavit', 'cuotas'] },
  { id: 'calc-ptu', href: '/calculadoras/ptu', label: 'PTU', icon: 'ph:users-three-light', descripcion: 'Reparto de utilidades por trabajador', sinonimos: ['ptu', 'utilidades', 'reparto'] },
];

/** ⌘1..⌘5 siguen este orden. Agregar un destino no mueve ningún atajo. */
export const ESPACIOS: readonly Espacio[] = [
  {
    id: 'despacho',
    label: 'Despacho',
    icon: 'ph:squares-four-light',
    descripcion: 'Lo de todas tus empresas',
    destinos: [
      { id: 'inicio', href: '/', label: 'Inicio', icon: 'ph:house-simple-light', descripcion: 'Tu resumen del día', sinonimos: ['inicio', 'resumen', 'panel'] },
      { id: 'tareas', href: '/tareas', label: 'Tareas', icon: 'ph:clipboard-text-light', descripcion: 'Pendientes por empresa', sinonimos: ['tareas', 'pendientes', 'recordatorios'] },
      { id: 'empresas', href: '/empresas', label: 'Empresas', icon: 'ph:buildings-light', descripcion: 'Catálogo, e.firma y Contraseña', sinonimos: ['empresas', 'clientes', 'catalogo', 'rfc', 'efirma', 'e.firma', 'fiel'] },
      { id: 'historial', href: '/historial', label: 'Historial', icon: 'ph:clock-counter-clockwise-light', descripcion: 'Todo lo que descargaste', sinonimos: ['historial', 'actividad', 'descargas'] },
    ],
  },
  {
    id: 'sat',
    label: 'SAT',
    icon: 'ph:cloud-arrow-down-light',
    descripcion: 'Lo que bajas del SAT',
    destinos: [
      { id: 'descarga', href: '/descarga', label: 'Descargar CFDIs', icon: 'ph:download-simple-light', descripcion: 'Emitidos y recibidos, 3 canales', sinonimos: ['descargar', 'bajar', 'xml', 'solicitar', 'web service', 'cfdis', 'facturas'] },
      { id: 'descarga-rapida', href: '/descarga/rapida', label: 'Descarga rápida', icon: 'ph:lightning-light', descripcion: 'Directo del portal, sin esperar', estado: 'nuevo', sinonimos: ['rapida', 'portal', 'captcha', 'contrasena', 'ciec'] },
      {
        id: 'constancia-opinion',
        // Acceso directo: abre Despacho > Empresas con la fila de la empresa
        // activa abierta. El riel pasa a Despacho a propósito (es temporal,
        // hasta que llegue el Expediente fiscal).
        href: '/empresas?abrir=1',
        label: 'Constancia y Opinión 32-D',
        icon: 'ph:seal-check-light',
        descripcion: 'Los documentos de tu empresa activa',
        estado: 'nuevo',
        sinonimos: ['constancia', 'csf', 'situacion fiscal', 'opinion', '32-d', '32d', 'cumplimiento'],
      },
      {
        id: 'expediente',
        label: 'Expediente fiscal',
        icon: 'ph:archive-light',
        descripcion: 'Constancia, 32-D, declaraciones y CSD',
        detalle: 'Juntará por empresa la Constancia, la Opinión 32-D, las declaraciones y sus acuses, la e.firma y los CSD.',
        estado: 'pronto',
        sinonimos: ['expediente', 'documentos'],
        hijos: [
          { id: 'declaraciones', label: 'Declaraciones y acuses', corto: 'Declaraciones', icon: 'ph:file-arrow-down-light', descripcion: 'Declaraciones presentadas y sus acuses', detalle: 'Las declaraciones que presentaste y sus acuses, por periodo.', estado: 'pronto', sinonimos: ['declaraciones', 'acuses'] },
        ],
      },
    ],
  },
  {
    id: 'revisar',
    label: 'Revisar',
    icon: 'ph:files-light',
    descripcion: 'Lo que analizas',
    destinos: [
      {
        id: 'comprobantes',
        href: '/comprobantes',
        label: 'Comprobantes',
        icon: 'ph:files-light',
        descripcion: 'Procesadores de CFDI, Nómina y Pagos',
        sinonimos: ['comprobantes', 'procesadores', 'excel'],
        hijos: [
          { id: 'proc-cfdi', href: '/comprobantes/cfdi', label: 'Procesador de CFDI', corto: 'CFDI', icon: 'ph:file-text-light', descripcion: 'Filtra, valida y exporta a Excel', sinonimos: ['procesador de cfdi', 'cfdi', 'validar', 'estatus', 'cancelados'] },
          { id: 'proc-nomina', href: '/comprobantes/nomina', label: 'Procesador de Nómina', corto: 'Nómina', icon: 'ph:users-light', descripcion: 'Recibos con desglose por empleado', sinonimos: ['nomina', 'recibos', 'empleados'] },
          { id: 'proc-pagos', href: '/comprobantes/pagos', label: 'Procesador de Pagos', corto: 'Pagos', icon: 'ph:credit-card-light', descripcion: 'PPD contra sus complementos', sinonimos: ['pagos', 'complementos', 'ppd', 'rep'] },
          { id: 'retenciones', label: 'CFDI de retenciones', corto: 'Retenciones', icon: 'ph:receipt-light', descripcion: 'Retenciones e información de pagos', detalle: 'Los CFDI de retenciones e información de pagos, junto a tus demás comprobantes.', estado: 'pronto', sinonimos: ['retenciones'] },
          { id: 'cancelaciones', label: 'Cancelaciones', corto: 'Cancelaciones', icon: 'ph:receipt-x-light', descripcion: 'Solicitudes de cancelación y su respuesta', detalle: 'Las solicitudes de cancelación pendientes y su respuesta.', estado: 'pronto', sinonimos: ['cancelaciones', 'cancelar'] },
        ],
      },
      { id: 'listas-negras', href: '/listas-negras', label: 'Listas negras', icon: 'ph:shield-check-light', descripcion: 'Proveedores contra 69 y 69-B', sinonimos: ['listas negras', 'lista negra', '69', '69-b', '69b', 'efos', 'edos', 'proveedores'] },
      { id: 'xml-pdf', label: 'XML a PDF', icon: 'ph:file-pdf-light', descripcion: 'Tus CFDIs a PDF, en lote', detalle: 'Convertirá tus CFDIs a PDF en lote, también desde las tablas de Comprobantes.', estado: 'pronto', sinonimos: ['pdf', 'xml a pdf', 'imprimir'] },
    ],
  },
  {
    id: 'cumplimiento',
    label: 'Cumplimiento',
    icon: 'ph:seal-check-light',
    descripcion: 'Lo que presentas y tramitas',
    destinos: [
      {
        id: 'diot',
        href: '/diot',
        label: 'DIOT',
        icon: 'ph:file-text-light',
        descripcion: 'TXT de carga masiva del periodo',
        sinonimos: ['diot', 'txt', 'terceros', 'proveedores'],
        hijos: [
          { id: 'diot-generar', href: '/diot', label: 'Generar TXT', corto: 'Generar TXT', icon: 'ph:file-code-light', descripcion: 'Prellenada con los recibidos del periodo' },
          { id: 'diot-presentar', label: 'Presentar DIOT', corto: 'Presentar', icon: 'ph:paper-plane-tilt-light', descripcion: 'Sube el TXT y baja el acuse', detalle: 'Presentar la DIOT desde la app y bajar su acuse.', estado: 'pronto', sinonimos: ['presentar diot'] },
          { id: 'diot-presentadas', label: 'DIOT presentadas', corto: 'Presentadas', icon: 'ph:stamp-light', descripcion: 'Las que ya presentaste, con su acuse', detalle: 'Las DIOT que ya presentaste, con su acuse.', estado: 'pronto', sinonimos: ['diot presentadas', 'acuse de diot'] },
        ],
      },
      { id: 'contabilidad', label: 'Contabilidad electrónica', icon: 'ph:books-light', descripcion: 'Catálogo, balanzas y acuses', detalle: 'Envío del catálogo de cuentas y las balanzas, y los acuses de Recibido, Aceptado o Rechazado.', estado: 'pronto', sinonimos: ['contabilidad', 'contabilidad electronica', 'balanza', 'catalogo de cuentas', 'anexo 24'] },
      {
        id: 'efirma-csd',
        label: 'e.firma y CSD',
        icon: 'ph:fingerprint-light',
        descripcion: 'Renovación y sellos digitales',
        detalle: 'La renovación de la e.firma y la solicitud de Certificados de Sello Digital.',
        estado: 'pronto',
        sinonimos: ['csd', 'sello digital', 'renovar'],
        hijos: [
          { id: 'renovar-efirma', label: 'Renovar e.firma', corto: 'Renovar e.firma', icon: 'ph:fingerprint-light', descripcion: 'El .ren y el respaldo de tu llave nueva', detalle: 'Generar el .ren de la renovación y guardar el respaldo de tu llave nueva.', estado: 'pronto', sinonimos: ['renovar efirma', 'renovar e.firma', 'renovacion'] },
          { id: 'solicitar-csd', label: 'Solicitar CSD', corto: 'Solicitar CSD', icon: 'ph:certificate-light', descripcion: 'La solicitud de un sello digital', detalle: 'Generar la solicitud de un Certificado de Sello Digital.', estado: 'pronto', sinonimos: ['csd', 'sello digital', 'certificado de sello'] },
        ],
      },
    ],
  },
  {
    id: 'herramientas',
    label: 'Herramientas',
    icon: 'ph:toolbox-light',
    descripcion: 'Cálculos y archivos',
    destinos: [
      { id: 'calculadoras', href: '/calculadoras', label: 'Calculadoras', icon: 'ph:calculator-light', descripcion: 'ISR, aguinaldo, finiquito y más', sinonimos: ['calculadoras', 'calculadora', 'nomina'], hijos: CALCULADORAS },
      { id: 'organizador', href: '/organizador', label: 'Organizador', icon: 'ph:folders-light', descripcion: 'Renombra y quita duplicados', soloEscritorio: true, sinonimos: ['organizador', 'carpetas', 'duplicados', 'renombrar', 'ordenar'] },
    ],
  },
];

/** Pantallas fuera de los espacios (riel abajo y menú de cuenta). */
export const DESTINOS_SIN_ESPACIO: readonly Destino[] = [
  { id: 'ayuda', href: '/ayuda', label: 'Ayuda', icon: 'ph:question-light', descripcion: 'Preguntas frecuentes, atajos y contacto', sinonimos: ['ayuda', 'atajos', 'soporte', 'contacto'] },
  { id: 'ajustes', href: '/ajustes', label: 'Ajustes', icon: 'ph:gear-light', descripcion: 'Preferencias de la aplicación', sinonimos: ['ajustes', 'preferencias', 'tema', 'carpeta de descargas', 'apariencia', 'navegacion'] },
  { id: 'ajustes-api', href: '/ajustes/api', label: 'API y conexiones', icon: 'ph:plugs-connected-light', descripcion: 'Llaves de API y la conexión con tu IA (MCP)', sinonimos: ['api', 'mcp', 'llaves', 'keys', 'claude', 'chatgpt', 'conexiones'] },
  { id: 'ajustes-equipo', href: '/ajustes/equipo', label: 'Equipo', icon: 'ph:users-light', descripcion: 'Colaboradores y sus permisos', sinonimos: ['equipo', 'colaboradores', 'usuarios', 'invitar'] },
  { id: 'suscripcion', href: '/suscripcion', label: 'Suscripción y cuenta', icon: 'ph:credit-card-light', descripcion: 'Tu plan, facturación y método de pago', sinonimos: ['suscripcion', 'plan', 'pago', 'factura', 'cuenta'] },
];

export interface DestinoUbicado {
  destino: Destino;
  /** null para Ayuda, Ajustes y Suscripción. */
  espacio: Espacio | null;
  /** El destino de primer nivel que lo contiene (si es un hijo). */
  padre: Destino | null;
}

/** Todos los destinos (con sus hijos) con su espacio y su padre. */
export function todosLosDestinos(): DestinoUbicado[] {
  const out: DestinoUbicado[] = [];
  for (const espacio of ESPACIOS) {
    for (const d of espacio.destinos) {
      out.push({ destino: d, espacio, padre: null });
      for (const h of d.hijos ?? []) out.push({ destino: h, espacio, padre: d });
    }
  }
  for (const d of DESTINOS_SIN_ESPACIO) out.push({ destino: d, espacio: null, padre: null });
  return out;
}

export function espacioPorId(id: EspacioId): Espacio {
  return ESPACIOS.find((e) => e.id === id) ?? ESPACIOS[0];
}

export function destinoPorId(id: string): DestinoUbicado | null {
  return todosLosDestinos().find((u) => u.destino.id === id) ?? null;
}

/** Quita query, hash y la diagonal final (el build de escritorio usa trailingSlash). */
export function normalizarRuta(ruta: string): string {
  const sinQuery = ruta.split(/[?#]/)[0] || '/';
  if (sinQuery.length > 1 && sinQuery.endsWith('/')) return sinQuery.slice(0, -1);
  return sinQuery;
}

function coincide(pathname: string, href: string): boolean {
  const ruta = normalizarRuta(href);
  if (ruta === '/') return pathname === '/';
  return pathname === ruta || pathname.startsWith(`${ruta}/`);
}

/**
 * Destino activo de una ruta: el de href más largo que la contiene (las URLs no
 * cambian; `/calculadoras/isr` es ISR y `/empresas/detalle` es Empresas). Los
 * accesos directos con query (`/empresas?abrir=1`) no compiten con su ruta.
 */
export function destinoDe(pathname: string): DestinoUbicado | null {
  const p = normalizarRuta(pathname);
  let mejor: DestinoUbicado | null = null;
  let largo = -1;
  for (const u of todosLosDestinos()) {
    const href = u.destino.href;
    if (!href || href.includes('?')) continue;
    if (!coincide(p, href)) continue;
    const l = normalizarRuta(href).length;
    // Empate (DIOT y "Generar TXT" comparten /diot): gana el hijo, para que el
    // padre se marque "abierto" y el hijo "activo".
    if (l > largo || (l === largo && u.padre && !mejor?.padre)) {
      mejor = u;
      largo = l;
    }
  }
  return mejor;
}

/** Espacio de una ruta por prefijo más largo. Ayuda, Ajustes y Suscripción no tienen. */
export function espacioDe(pathname: string): EspacioId | null {
  return destinoDe(pathname)?.espacio?.id ?? null;
}

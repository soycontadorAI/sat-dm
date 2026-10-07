// ---------------------------------------------------------------------------
// Constants for the SAT Descarga Masiva UI
// ---------------------------------------------------------------------------

/**
 * Agente local de desarrollo (`pnpm dev` en el navegador contra el agente
 * levantado a mano); sin la env var, localhost:8787. El build web nunca lo
 * usa (ver `getAgentBaseUrl`).
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_SAT_API_URL ?? 'http://localhost:8787';

import { esWeb } from './modo';
import { getConexion } from './conexion-web';

/**
 * Base URL efectiva del agente. Dentro de Electron, el preload inyecta
 * `window.satAgent.baseUrl` (puerto efímero); en la versión web viene de la
 * conexión guardada por el provisioner (localStorage) y, sin ella, es `null`:
 * la web nunca cae a localhost (no hay agente local y la CSP de
 * app.todoconta.com bloquea la petición). En dev cae a API_BASE_URL.
 */
export function getAgentBaseUrl(): string | null {
  if (typeof window !== 'undefined') {
    const injected = (window as unknown as { satAgent?: { baseUrl?: string } }).satAgent?.baseUrl;
    if (injected) return injected;
  }
  if (esWeb()) return getConexion()?.baseUrl ?? null;
  return API_BASE_URL;
}

/**
 * Token de autenticación con el agente. Dentro de Electron lo inyecta el
 * preload (`window.satAgent.token`); en la versión web viene de la conexión
 * guardada; en dev (agente levantado a mano) no hay token y el agente no lo
 * exige.
 */
export function getAgentToken(): string | null {
  if (typeof window !== 'undefined') {
    const injected = (window as unknown as { satAgent?: { token?: string } }).satAgent?.token;
    if (injected) return injected;
    if (esWeb()) {
      const conexion = getConexion();
      if (conexion) return conexion.token;
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// CodEstado labels (VerificaSolicitud response states)
// ---------------------------------------------------------------------------

export interface CodEstadoInfo {
  label: string;
  color: string;
  description: string;
}

export const COD_ESTADO_LABELS: Map<number, CodEstadoInfo> = new Map([
  [
    1,
    {
      label: 'En cola',
      color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
      description: 'La solicitud fue recibida y está en espera de procesamiento.',
    },
  ],
  [
    2,
    {
      label: 'Procesando',
      color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-400',
      description: 'El SAT está procesando la solicitud.',
    },
  ],
  [
    3,
    {
      label: 'Lista',
      color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
      description: 'Los paquetes están listos para descargar.',
    },
  ],
  [
    4,
    {
      label: 'Error',
      color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
      description: 'Ocurrió un error en el servidor del SAT.',
    },
  ],
  [
    5,
    {
      label: 'Rechazada',
      color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
      description: 'La solicitud fue rechazada por el SAT.',
    },
  ],
  [
    6,
    {
      label: 'Vencida',
      color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
      description: 'La solicitud venció sin resolverse. Crea una nueva solicitud.',
    },
  ],
]);

// ---------------------------------------------------------------------------
// Folder structure patterns (from organizador.py ESTRUCTURAS)
// ---------------------------------------------------------------------------

export const ESTRUCTURAS = [
  { value: 'rfc_emisor/anio/mes', label: 'RFC Emisor / Año / Mes' },
  { value: 'rfc_emisor/anio', label: 'RFC Emisor / Año' },
  { value: 'anio/mes/rfc_emisor', label: 'Año / Mes / RFC Emisor' },
  { value: 'anio/mes', label: 'Año / Mes' },
  { value: 'anio/mes/dia', label: 'Año / Mes / Día' },
  { value: 'tipo/anio/mes', label: 'Tipo / Año / Mes' },
  { value: 'rfc_emisor/tipo/anio/mes', label: 'RFC Emisor / Tipo / Año / Mes' },
  { value: 'rfc_receptor/anio/mes', label: 'RFC Receptor / Año / Mes' },
  { value: 'plano', label: 'Plano (sin subcarpetas)' },
] as const;

/** Valor sentinela del Select de estructura para "Personalizada…". */
export const ESTRUCTURA_CUSTOM = 'custom';

/** Prefijo de segmento literal (carpeta/parte de texto fijo) — espejo del backend. */
export const PREFIJO_TEXTO = 'txt:';

/** Entrada de catálogo para los builders (niveles de carpeta / partes del nombre). */
export interface SegmentoCatalogo {
  value: string;
  label: string;
  ejemplo: string;
  /** true = "Texto personalizado": editable y se puede repetir. */
  custom?: boolean;
}

/**
 * Variables disponibles como nivel de la estructura personalizada.
 * `value` es el token que entiende el backend (organizador.py TOKENS);
 * `ejemplo` alimenta la vista previa tipo Finder.
 */
export const NIVELES_CUSTOM: SegmentoCatalogo[] = [
  { value: 'anio', label: 'Año', ejemplo: '2026' },
  { value: 'mes', label: 'Mes', ejemplo: '05' },
  { value: 'dia', label: 'Día', ejemplo: '07' },
  { value: 'flujo', label: 'Emitidos / Recibidos', ejemplo: 'Emitidos' },
  { value: 'tipo', label: 'Tipo de comprobante', ejemplo: 'Ingreso' },
  { value: 'rfc', label: 'RFC de la empresa', ejemplo: 'CULL551116HM8' },
  { value: 'rfc_emisor', label: 'RFC del emisor', ejemplo: 'SAHA010125PV9' },
  { value: 'rfc_receptor', label: 'RFC del receptor', ejemplo: 'XAXX010101000' },
  { value: 'texto', label: 'Texto personalizado', ejemplo: 'CFDI', custom: true },
];

/** Tokens de NIVELES_CUSTOM que clasifican contra la empresa activa. */
export const NIVELES_REQUIEREN_RFC: string[] = ['rfc', 'flujo'];

/**
 * Partes disponibles para componer el nombre de archivo en Renombrar
 * (espejo de organizador.py NOMBRE_TOKENS).
 */
export const PARTES_NOMBRE: SegmentoCatalogo[] = [
  { value: 'fecha', label: 'Fecha', ejemplo: '2026-05-07' },
  { value: 'rfc_emisor', label: 'RFC del emisor', ejemplo: 'SAHA010125PV9' },
  { value: 'nombre_emisor', label: 'Nombre del emisor', ejemplo: 'Acme SA' },
  { value: 'rfc_receptor', label: 'RFC del receptor', ejemplo: 'XAXX010101000' },
  { value: 'folio_fiscal', label: 'Folio fiscal', ejemplo: 'A1B2C3D4' },
  { value: 'serie_folio', label: 'Serie y folio', ejemplo: 'A-1024' },
  { value: 'tipo', label: 'Tipo', ejemplo: 'Ingreso' },
  { value: 'total', label: 'Total', ejemplo: '1160.00' },
  { value: 'texto', label: 'Texto personalizado', ejemplo: 'CFDI', custom: true },
];

/** Valor sentinela del Select de nombre de archivo para "Personalizado…". */
export const PATRON_CUSTOM = 'custom';

/** Separadores disponibles entre partes del nombre. */
export const SEPARADORES_NOMBRE = [
  { label: '-', value: '-' },
  { label: '_', value: '_' },
  { label: '␣', value: ' ' },
  { label: '·', value: ' · ' },
] as const;

// ---------------------------------------------------------------------------
// Rename patterns (from organizador.py PATRONES_NOMBRE)
// ---------------------------------------------------------------------------

// El ejemplo recibe el RFC de la empresa activa (los patrones con emisor lo
// muestran personalizado; el ejemplo típico es un CFDI emitido por ella).
export const PATRONES_NOMBRE = [
  {
    value: 'emisor_fecha_total',
    label: 'Emisor - Fecha - Total',
    ejemplo: (rfc = 'SAHA010125PV9') => `${rfc}_2026-05-07_1160.00_A1B2C3D4`,
  },
  {
    value: 'receptor_fecha_total',
    label: 'Receptor - Fecha - Total',
    ejemplo: () => 'XAXX010101000_2026-05-07_1160.00_A1B2C3D4',
  },
  {
    value: 'uuid',
    label: 'UUID',
    ejemplo: () => 'A1B2C3D4-E5F6-7A8B-9C0D-E1F2A3B4C5D6',
  },
  {
    value: 'fecha_emisor_total',
    label: 'Fecha - Emisor - Total',
    ejemplo: (rfc = 'SAHA010125PV9') => `2026-05-07_${rfc}_1160.00`,
  },
  {
    value: 'fecha_uuid',
    label: 'Fecha - UUID',
    ejemplo: () => '2026-05-07_A1B2C3D4-E5F6-7A8B-9C0D-E1F2A3B4C5D6',
  },
] as const;

// ---------------------------------------------------------------------------
// Tipo de solicitud (download content type)
// ---------------------------------------------------------------------------

export const TIPO_SOLICITUD = [
  { value: 'CFDI', label: 'CFDI (XMLs completos)' },
  { value: 'Metadata', label: 'Metadata (resumen CSV)' },
] as const;

// ---------------------------------------------------------------------------
// Tipo de comprobante (emitido / recibido)
// ---------------------------------------------------------------------------

export const TIPO_COMPROBANTE = [
  { value: 'E', label: 'Emitidos' },
  { value: 'R', label: 'Recibidos' },
] as const;

// ---------------------------------------------------------------------------
// Estado del comprobante (for SolicitudRequest filters)
// ---------------------------------------------------------------------------

export const ESTADO_COMPROBANTE = [
  { value: 'Vigente', label: 'Vigente' },
  { value: 'Cancelado', label: 'Cancelado' },
  { value: 'Todos', label: 'Todos' },
] as const;

// ---------------------------------------------------------------------------
// Efecto del comprobante (from CFDI metadata)
// ---------------------------------------------------------------------------

export const EFECTO_COMPROBANTE: Record<string, string> = {
  I: 'Ingreso',
  E: 'Egreso',
  P: 'Pago',
  T: 'Traslado',
  N: 'Nómina',
};

// ---------------------------------------------------------------------------
// Polling intervals (mirroring sat_descarga/config.py)
// ---------------------------------------------------------------------------

export const HEALTH_POLL_INTERVAL_MS = 5_000;
export const VERIFICAR_POLL_INTERVAL_MS = 15_000;

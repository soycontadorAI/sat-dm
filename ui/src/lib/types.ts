// ---------------------------------------------------------------------------
// Types mirroring the Python Pydantic models in sat_descarga/server.py
// ---------------------------------------------------------------------------

// GET /health
export interface HealthResponse {
  status: string;
  rfc_cargado: string | null;
  efirma_lista: boolean;
  /** Vencimiento de la e.firma en sesión ("YYYY-MM-DD") o null si no hay. */
  efirma_vencimiento?: string | null;
  /** True/false si hay e.firma cargada; null si no hay. */
  efirma_vigente?: boolean | null;
  /** Estado del navegador del portal (Chromium): el warm-up lo descarga al arrancar. */
  navegador?: NavegadorStatus;
  /**
   * Modo de grabación del agente (datos de demo para los tutoriales). La UI
   * calla lo que envejece un video (banners de venta, cuenta regresiva de la
   * prueba, recordatorios); nunca muestra un aviso de que está activo.
   */
  modo_grabacion?: boolean;
}

/** Estado del navegador de descargas (Playwright/Chromium) reportado por /health. */
export interface NavegadorStatus {
  estado: 'pendiente' | 'instalando' | 'listo' | 'error' | 'desconocido' | string;
  detalle?: string | null;
}

// POST /auth/cargar-fiel
export interface CargarFielResponse {
  ok: boolean;
  rfc: string;
  numero_serie: string;
}

// DELETE /auth/fiel
export interface DescargarFielResponse {
  ok: boolean;
  mensaje: string;
}

// POST /solicitar — request body
export interface SolicitudRequest {
  fecha_inicio: string; // ISO date "YYYY-MM-DD"
  fecha_fin: string;
  tipo_solicitud: string; // "CFDI" | "Metadata"
  tipo_comprobante: string; // "E" | "R"
  rfc_emisor?: string;
  rfc_receptor?: string;
}

// POST /solicitar — response
export interface SolicitudResponse {
  ok: boolean;
  id_solicitud: string;
}

// POST /verificar — request body
export interface VerificarRequest {
  id_solicitud: string;
  poll: boolean;
}

// POST /verificar — response
export interface VerificarResponse {
  cod_estado: number;
  mensaje: string;
  numero_cfdis: number;
  package_ids: string[];
  terminada: boolean;
}

// POST /descargar — response
export interface DescargarResponse {
  ok: boolean;
  archivos: string[];
  total: number;
  mensaje?: string;
}

// POST /descarga-completa — request body
export interface DescargaCompletaRequest {
  fecha_inicio: string;
  fecha_fin: string;
  tipo_comprobante: string;
  directorio_salida: string;
  extraer: boolean;
}

// POST /solicitar-folio — request body
export interface SolicitudFolioRequest {
  uuids: string[];
  tipo_solicitud: string;
  directorio_salida: string;
  extraer: boolean;
}

// POST /organizar (planned endpoint — models match organizador.py)
export interface OrganizadorRequest {
  origen: string;
  destino: string;
  estructura: string;
  copiar: boolean;
  /** RFC de la empresa; requerido si la estructura usa "rfc" o "flujo". */
  rfc?: string;
}

// GET/PUT /config/organizador — config GLOBAL del organizador: se define una
// vez y aplica a todas las empresas del usuario (desktop y web).
export interface OrganizadorConfig {
  /** Preset del select de estructura, o "custom". */
  estructura: string;
  niveles_custom: string[];
  /** Preset de renombrado, o "custom". */
  renombrar_patron: string;
  partes_nombre: string[];
  separador: string;
  copiar: boolean;
  /** true si el usuario ya guardó su config (false → la UI migra localStorage). */
  guardada: boolean;
}

export interface OrganizadorResult {
  archivos_procesados: number;
  archivos_movidos: number;
  archivos_omitidos: number;
  errores: string[];
  /** CFDIs de otros RFC: se quedaron en su lugar (nunca hay carpeta "Otros"). */
  de_otro_rfc?: number;
}

// POST /renombrar (planned endpoint — models match organizador.py)
export interface RenombrarRequest {
  directorio: string;
  patron: string;
  /** Modo por partes (builder): tokens de NOMBRE_TOKENS o "txt:Literal". */
  partes?: string[];
  /** Separador entre partes (solo modo por partes). */
  separador?: string;
}

// POST /deduplicar (planned endpoint — models match organizador.py)
export interface DeduplicarRequest {
  directorio: string;
  dry_run: boolean;
}

export interface DeduplicarResult {
  archivos_analizados: number;
  duplicados_encontrados: number;
  duplicados_eliminados: number;
  errores: string[];
}

// CIEC (portal web scraping)
export interface CIECDescargaRequest {
  rfc: string;
  ciec: string;
  fecha_inicio: string;
  fecha_fin: string;
  tipo_comprobante: string;
  directorio_salida: string;
  max_registros: number;
}

// Descarga inteligente (auto-routing CIEC vs Web Service)
export interface DescargaInteligente {
  fecha_inicio: string;
  fecha_fin: string;
  tipo_comprobante: string;
  directorio_salida: string;
  ciec?: string;
  umbral_ciec?: number;
}

// ---------------------------------------------------------------------------
// Jobs CIEC (captcha in-app por SSE) — agente desktop
// ---------------------------------------------------------------------------

export type JobEstado =
  | 'pending'
  | 'running'
  | 'captcha'
  | 'done'
  | 'error'
  | 'cancelled';

// POST /ciec/cfdi (el agente computa el directorio de salida).
// `ciec` es opcional: si falta, el agente la toma del catálogo (keychain).
export interface CiecCfdiRequest {
  rfc: string;
  ciec?: string;
  fecha_inicio: string;
  fecha_fin: string;
  tipo_comprobante?: string;
  max_registros?: number;
}

// POST /ciec/constancia y /ciec/opinion (`ciec` opcional → del catálogo)
export interface CiecDocRequest {
  rfc: string;
  ciec?: string;
}

// POST /cfdi/fiel — descarga CFDIs vía portal con la e.firma en sesión.
// Sin rfc/credenciales: las toma de _get_fiel() del agente.
export interface CfdiFielRequest {
  fecha_inicio: string;
  fecha_fin: string;
  tipo_comprobante?: string;
  max_registros?: number;
}

// Respuesta al iniciar cualquier job (/ciec/*)
export interface JobIniciado {
  job_id: string;
}

// GET /jobs/{id}
export interface JobEstadoResponse {
  id: string;
  estado: JobEstado;
  resultado: unknown;
  error: string | null;
}

// Evento del stream SSE GET /events/{id}
export interface JobEvent {
  event:
    | 'estado'
    | 'captcha_required'
    | 'captcha_timeout'
    | 'log'
    | 'fase'
    | 'done'
    | 'error'
    | 'cancelled'
    | string;
  estado?: string; // event=estado
  imagen?: string; // event=captcha_required (data:image/jpeg;base64,...)
  intento?: number; // captcha_required | fase=recuperando
  max?: number;
  resultado?: unknown; // event=done
  mensaje?: string; // event=log|error|cancelled
  nivel?: 'info' | 'ok' | 'warn' | 'error'; // event=log
  /** event=fase — avance de los trámites de Certifica (renovación/CSD):
   * generando | firmando | enviando | numero_operacion | acuse | recuperando | guardando */
  fase?: string;
  numero?: string; // fase=numero_operacion
  acuse_pdf?: string; // fase=acuse
  /** event=progreso (opcional; hoy solo lo manda el modo de grabación): XML
   * descargados contra el total esperado. */
  actual?: number;
  total?: number;
}

// ---------------------------------------------------------------------------
// Empresas (catálogo persistente del agente; credenciales en keychain del SO)
// ---------------------------------------------------------------------------

export type MetodoEmpresa = 'fiel' | 'ciec';

/** Sentido de la Opinión de Cumplimiento 32-D. 'otro' = sentido no
 * positiva/negativa (p. ej. "sin obligaciones", "no inscrito"). */
export type OpinionStatus = 'positiva' | 'negativa' | 'otro';

/** Un motivo por el que la 32-D salió negativa (una sección del PDF). */
export interface OpinionMotivo {
  titulo: string;
  descripcion: string;
  detalles: string[];
}

export interface RegimenFiscalConfig {
  clave: string;
  descripcion: string;
}

export interface ActividadEconomicaConfig {
  descripcion: string;
  principal?: boolean;
  /** % de ingresos según la CSF; presente cuando se rellenó desde la constancia. */
  porcentaje?: number;
}

// GET /empresas → { empresas: Empresa[] }
export interface Empresa {
  rfc: string;
  nombre: string;
  /** Métodos de autenticación disponibles (una empresa puede tener ambos). */
  metodos: MetodoEmpresa[];
  /**
   * Sync de catálogo: métodos con credenciales EN OTRA instalación del usuario
   * (desktop ⇄ online). Si aquí `metodos` está vacío y esto no, la empresa se
   * importó por sync y requiere capturar credenciales en este lado.
   */
  metodos_sync?: MetodoEmpresa[];
  cer_path?: string | null;
  vencimiento?: string;
  default: boolean;
  /** ISO timestamp si está archivada (soft-delete); null/undefined = activa. */
  archived_at?: string | null;
  /** Path local de la última Constancia de Situación Fiscal descargada. */
  csf_path?: string | null;
  csf_descargada_en?: string | null;
  /** Path local de la última Opinión de Cumplimiento 32-D descargada. */
  opinion_path?: string | null;
  opinion_descargada_en?: string | null;
  /** Sentido de la última 32-D parseada → semáforo (verde/rojo). null = descargada
   * pero aún sin analizar (opinión previa al parser) o sin descargar. */
  opinion_status?: OpinionStatus | null;
  /** Motivos de una 32-D negativa (por qué la situación fiscal está en rojo). */
  opinion_motivos?: OpinionMotivo[];
  /** Régimen(es) fiscal(es) declarados. Se llenan solos al descargar la CSF
   * (parser en el agente) y siguen siendo editables a mano. */
  regimenes_fiscales?: RegimenFiscalConfig[];
  /** Actividades económicas — descripción libre + marca opcional de la principal. */
  actividades_economicas?: ActividadEconomicaConfig[];
  /**
   * ¿La empresa presenta DIOT? null/ausente = derivar del régimen configurado
   * (RESICO está relevado); bool = override manual desde la configuración.
   */
  presenta_diot?: boolean | null;
  /** Renovación de e.firma enviada cuyo cert nuevo aún no se descarga. */
  renovacion_pendiente?: RenovacionPendiente | null;
  /** Certificados de Sello Digital solicitados desde la app. */
  csds?: CsdInfo[];
}

// ---------------------------------------------------------------------------
// Certifica: renovación de e.firma + CSD (jobs SSE, FIEL-only)
// ---------------------------------------------------------------------------

export interface RenovacionPendiente {
  /** 'generada' = el .ren existe pero el envío al SAT falló (se reenvía el mismo
   * con POST /renovar); 'enviada' = ya hay número de operación (falta el cert,
   * se descarga con POST /renovar/recuperar). */
  etapa?: 'generada' | 'enviada';
  numero_operacion?: string | null;
  acuse_pdf?: string | null;
  ren_path?: string;
  key_path: string;
  solicitado_en: string;
}

export interface CsdInfo {
  uso: string;
  numero_operacion: string;
  acuse_pdf?: string | null;
  cer_path?: string | null;
  key_path: string;
  estado: 'pendiente' | 'emitido';
  solicitado_en: string;
  recuperado_en?: string | null;
}

// POST /renovar — irreversible: la UI pide confirmación explícita antes.
export interface RenovarRequest {
  rfc: string;
  password: string;
  confirmar: true;
  correo?: string;
}

export interface RenovarRecuperarRequest {
  rfc: string;
}

// Resultado (event=done) de /renovar y /renovar/recuperar
export interface RenovarResultado {
  numero_operacion: string | null;
  acuse_pdf: string | null;
  estado?: string | null;
  cer: string | null;
  vencimiento: string | null;
  renovada: boolean;
  /** true = el SAT aún no emite el cert; reintentar con /renovar/recuperar. */
  cer_pendiente: boolean;
}

// POST /csd
export interface CsdSolicitarRequest {
  rfc: string;
  password: string;
  /** Contraseña de la .key nueva del CSD (mín. 8). */
  password_csd: string;
  uso: string;
}

export interface CsdRecuperarRequest {
  rfc: string;
  numero_operacion?: string;
}

// Resultado (event=done) de /csd y /csd/recuperar
export interface CsdResultado {
  numero_operacion: string | null;
  acuse_pdf?: string | null;
  estado?: string | null;
  cer: string | null;
  key?: string;
  uso?: string;
  /** true = «bajar después»: el cert se recupera con /csd/recuperar. */
  cert_pendiente: boolean;
  carpeta: string;
}

export interface EmpresaUpdatePatch {
  regimenes_fiscales?: RegimenFiscalConfig[];
  actividades_economicas?: ActividadEconomicaConfig[];
  /** Override manual de la obligación DIOT (ausente = derivar del régimen). */
  presenta_diot?: boolean;
}

// POST /empresas/{rfc}/parsear-csf — re-parsea la constancia ya descargada y
// aplica nombre/regímenes/actividades al catálogo (la CSF manda).
export interface ParsearCsfResponse {
  ok: boolean;
  rfc: string;
  nombre: string;
  regimenes_fiscales: RegimenFiscalConfig[];
  actividades_economicas: ActividadEconomicaConfig[];
}

// POST /empresas/{rfc}/parsear-opinion — re-parsea la 32-D ya descargada y
// aplica su sentido + motivos al catálogo.
export interface ParsearOpinionResponse {
  ok: boolean;
  rfc: string;
  opinion_status: OpinionStatus | '';
  opinion_motivos: OpinionMotivo[];
}

export interface EmpresasResponse {
  empresas: Empresa[];
}

// POST /empresas/ciec
export interface EmpresaCiecRequest {
  rfc: string;
  /** Opcional: vacío → el agente usa el RFC como nombre provisional. */
  nombre?: string;
  ciec: string;
}

// POST /empresas/{rfc}/activar
export interface ActivarEmpresaResponse {
  ok: boolean;
  rfc: string;
  metodos: MetodoEmpresa[];
  efirma_lista: boolean;
}

// GET /empresas/{rfc}/solicitudes (Historial)
export interface Solicitud {
  id_solicitud: string;
  fecha_inicio: string;
  fecha_fin: string;
  tipo: string;            // Etiqueta humana "CFDI · emitidos" / "Metadata · recibidos"
  estado: string;          // "solicitada" / "1"-"5" (SAT) / "vencida" / "descargada"
  timestamp: string;       // Creada (ISO local)
  package_ids?: string[];  // Disponibles cuando estado="3"+
  tipo_comprobante?: string;  // "E" / "R" — usado por el agente para componer la carpeta de salida
  mensaje?: string;        // Mensaje del SAT en la última /verificar
  numero_cfdis?: number;   // CFDIs reportados por el SAT
}

export interface SolicitudesResponse {
  solicitudes: Solicitud[];
}

// GET /solicitudes/actividad — solicitudes de TODAS las empresas, para el
// watcher global de notificaciones (rfc + nombre vienen del catálogo).
export interface SolicitudGlobal extends Solicitud {
  rfc: string;
  nombre: string;
}

export interface SolicitudesActividadResponse {
  solicitudes: SolicitudGlobal[];
}

// ---------------------------------------------------------------------------
// Historial de descargas completadas (GET /historial y /empresas/{rfc}/historial)
// ---------------------------------------------------------------------------

export type CanalDescarga = 'ws' | 'ciec' | 'fiel';
export type TipoDescarga = 'cfdi' | 'metadata' | 'constancia' | 'opinion';

export interface HistorialItem {
  timestamp: string; // ISO datetime
  canal: CanalDescarga;
  tipo: TipoDescarga;
  descripcion: string;
  ruta: string;
  total: number | null; // nº de CFDIs cuando aplica
  estado: string; // "completada" | ...
  // Presentes en /historial (todas las empresas); ausentes en el por-empresa.
  rfc?: string;
  nombre?: string;
}

export interface HistorialResponse {
  descargas: HistorialItem[];
}

// {ok, archivo} — descarga de un PDF (constancia/opinión vía e.firma)
export interface DocumentoResponse {
  ok: boolean;
  archivo: string;
}

// Generic API error shape
export interface ApiErrorDetail {
  detail: string;
}

// ---------------------------------------------------------------------------
// Procesador de comprobantes — CFDI
// ---------------------------------------------------------------------------

export type CfdiTipo = 'I' | 'E' | 'T' | 'N' | 'P';

/**
 * Estado DIOT de un comprobante (filtro «Estado DIOT», migración 009):
 * - 'pasa'     = elegible y con el interruptor encendido (default)
 * - 'excluido' = elegible pero apagado por el usuario
 * - 'noaplica' = no elegible (P/N/T y emitidos)
 */
export type CfdiEstadoDiot = 'pasa' | 'excluido' | 'noaplica';

/** Clasificación manual de deducibilidad; null = «Sin analizar». */
export type CfdiDeducible = 'Deducible' | 'No deducible';

export interface CfdiFiltros {
  desde: string | null;
  hasta: string | null;
  tipo: CfdiTipo | null;
  /**
   * Dirección del CFDI relativa a la empresa activa:
   * - 'E' = "yo soy emisor"  (los receptores son mis clientes)
   * - 'R' = "yo soy receptor" (los emisores son mis proveedores)
   * - null = ambos
   * Se calcula al cargar comparando emisor/receptor con el RFC activo.
   */
  direccion: 'E' | 'R' | null;
  busqueda: string | null;
  solo_con_errores: boolean;
  monto_min: number | null;
  monto_max: number | null;
  /**
   * Filtro por estado del emisor en listas negras:
   * 'EFOS' | 'Aclarado' | '69' | 'Limpio' | 'SinValidar' | null
   * Espejo de la columna `cfdis.emisor_en_lista_negra` (migración 006).
   */
  emisor_lista_negra?: string | null;
  /** Filtro por estado DIOT (interruptor de Comprobantes). */
  diot?: CfdiEstadoDiot | null;
}

export interface CfdiRecord {
  uuid: string;
  file_name: string | null;
  version: string | null;
  tipo: CfdiTipo | string;
  fecha: string;
  fecha_timbrado: string | null;
  serie: string | null;
  folio: string | null;
  emisor_rfc: string;
  emisor_nombre: string;
  emisor_regimen_fiscal: string | null;
  receptor_rfc: string;
  receptor_nombre: string;
  receptor_uso_cfdi: string | null;
  sub_total: number;
  descuento: number;
  total: number;
  iva_trasladado: number;
  ieps_trasladado: number;
  iva_retenido: number;
  isr_retenido: number;
  forma_pago: string | null;
  metodo_pago: string | null;
  moneda: string;
  tipo_cambio: number;
  lugar_expedicion: string | null;
  direccion: 'E' | 'R' | null;
  estado_sat: 'Vigente' | 'Cancelado' | 'No encontrado' | null;
  validado_en: string | null;
  /**
   * Etiqueta del emisor en listas negras del SAT (Art. 69 y 69-B).
   * 'EFOS' | 'Aclarado' | '69' | 'Limpio' | null (sin validar).
   * Espejo de la columna `cfdis.emisor_en_lista_negra` (migración 006).
   */
  emisor_en_lista_negra: string | null;
  /** JSON serializado con el detalle del match (situación, supuestos, fecha pub.). */
  emisor_listas_match: string | null;
  receptor_en_lista_negra: string | null;
  receptor_listas_match: string | null;
  validado_listas_en: string | null;
  warnings: string[];
  cargado_en: string;
  /** ¿La fila es elegible para la DIOT? (recibidos de tipo I/E). Derivada. */
  elegible_diot: boolean;
  /** Interruptor «pasa a la DIOT» (solo tiene efecto en filas elegibles). */
  incluir_diot: boolean;
  deducible: CfdiDeducible | null;
}

export interface CfdiListResponse {
  total: number;
  page: number;
  page_size: number;
  items: CfdiRecord[];
}

export interface CfdiStats {
  total_comprobantes: number;        // respeta filtros activos
  total_global: number;              // count global SIN filtros — para detectar "buffer vacío"
  monto_total: number;
  iva_trasladado: number;
  ieps_trasladado: number;
  iva_retenido: number;
  isr_retenido: number;
  con_errores: number;
  por_tipo: Record<string, number>;
  // Contadores GLOBALES del buffer (scope de la empresa, sin filtros de UI)
  // para la línea «X de Y operaciones pasan a la DIOT» sobre la tabla.
  diot_elegibles: number;
  diot_pasan: number;
  diot_no_aplica: number;
  deducible_no: number;
  deducible_sin_clasificar: number;
}

/** Patch de flags editables por comprobante (PATCH /procesador/cfdi/{uuid}). */
export interface CfdiFlagsPatch {
  incluir_diot?: boolean;
  /** 'Sin analizar' regresa la clasificación a null en el agente. */
  deducible?: CfdiDeducible | 'Sin analizar';
}

export interface CfdiFlagsResponse {
  ok: boolean;
  item: CfdiRecord;
  contadores: Pick<
    CfdiStats,
    'diot_elegibles' | 'diot_pasan' | 'diot_no_aplica' | 'deducible_no' | 'deducible_sin_clasificar'
  >;
}

export interface ReporteTotalesMes {
  reporte: 'totales-mes';
  items: {
    mes: string;
    comprobantes: number;
    sub_total: number;
    iva_trasladado: number;
    ieps_trasladado: number;
    iva_retenido: number;
    isr_retenido: number;
    total: number;
  }[];
}

export interface TopContraparte {
  rfc: string;
  nombre: string;
  comprobantes: number;
  monto: number;
}

export interface ReporteTopContrapartes {
  reporte: 'top-contrapartes';
  emisores: TopContraparte[];
  receptores: TopContraparte[];
}

export interface ItemIntegridad {
  uuid: string;
  tipo: string;
  fecha: string;
  serie: string | null;
  folio: string | null;
  emisor_rfc: string;
  emisor_nombre: string;
  receptor_rfc: string;
  receptor_nombre: string;
  total: number;
  warnings: string[];
}

export interface ReporteIntegridad {
  reporte: 'integridad';
  items: ItemIntegridad[];
}

export interface ProcesadorCargarResponse {
  agregados: number;
  duplicados: number;
  /** XMLs omitidos por no corresponder al RFC de la empresa (ni emisor ni receptor). */
  omitidos_rfc: number;
  errores: { filename: string; mensaje: string }[];
  archivos_encontrados?: number; // solo en cargar-desde-empresa
}

export interface CargarDesdeEmpresaRequest {
  rfc: string;
  desde?: string;
  hasta?: string;
  /** 'E' (emitidos) o 'R' (recibidos). Reservado para uso programático
   *  futuro (calculadoras IVA, etc.) omitirlo para escanear ambos. */
  tipo?: 'E' | 'R';
}

export interface ValidarSatResponse {
  validados: number;
  vigentes: number;
  cancelados: number;
  no_encontrados: number;
  errores: number;
}

// ---------------------------------------------------------------------------
// Listas negras del SAT (Art. 69 y 69-B)
// ---------------------------------------------------------------------------

export interface ListaNegraMatch {
  rfc: string;
  en_lista_69b: boolean;
  /** Definitivo | Presunto | Desvirtuado | Sentencia Favorable | null */
  situacion_69b: string | null;
  fecha_publicacion_69b: string | null;
  en_lista_69: boolean;
  /** firmes | exigibles | no_localizados | sentencias | cancelados | entes_publicos_omisos */
  supuestos_69: string[];
  /** alto | medio | limpio */
  risk_level: string;
  error: string | null;
}

export interface ListasNegrasMetadata {
  lista_69b_updated_at: string | null;
  lista_69_updated_at: string | null;
  record_count_69b: number | null;
  record_count_69: number | null;
}

export interface ListasNegrasConsultarResponse {
  matches: ListaNegraMatch[];
  metadata: ListasNegrasMetadata;
}

export interface ProcesadorValidarListasNegrasResponse {
  validados: number;
  efos: number;
  aclarados: number;
  lista_69: number;
  limpios: number;
  metadata: ListasNegrasMetadata;
}

export interface ProcesadorListasNegrasStats {
  efos_emisores_unicos: number;
  cfdis_edos: number;
  cfdis_emisor_aclarado: number;
  cfdis_emisor_69: number;
  cfdis_limpios: number;
  cfdis_sin_validar: number;
}

/** Una fila agregada por emisor_rfc en la vista de listas negras. */
export interface EmisorListaNegra {
  emisor_rfc: string;
  emisor_nombre: string | null;
  /** 'EFOS' | 'Aclarado' | '69' | 'Limpio' | null (sin validar) */
  emisor_en_lista_negra: string | null;
  /** Detalle parseado del match (situación 69-B, supuestos 69, etc.). */
  emisor_listas_match: {
    situacion_69b: string | null;
    fecha_publicacion_69b: string | null;
    supuestos_69: string[];
    risk_level: string;
  } | null;
  fecha_mas_reciente: string | null;
  validado_listas_en: string | null;
  num_cfdis: number;
  total_acumulado: number;
}

export interface EmisoresListasNegrasResponse {
  total: number;
  page: number;
  page_size: number;
  items: EmisorListaNegra[];
}

// ---------------------------------------------------------------------------
// Procesador de comprobantes — Pagos
// ---------------------------------------------------------------------------

export type PagoStatus = 'sin_complemento' | 'pago_parcial' | 'pagado_completo' | 'sobrante';

export interface PagosFiltros {
  desde: string | null;
  hasta: string | null;
  busqueda: string | null;
  status: PagoStatus[] | null;
  solo_extemporaneos: boolean;
}

export interface PagosStats {
  total_ingresos_ppd: number;       // respeta filtros
  total_global_ppd: number;         // sin filtros — para detectar buffer vacío
  sin_complemento: number;
  pagos_parciales: number;
  pagos_completos: number;
  sobrantes: number;
  monto_total_sin_pagar: number;
  total_pagos: number;              // total CFDIs tipo P
  pagos_huerfanos: number;
  incidencias_pue: number;
  porcentaje_conciliados: number;
  complementos_extemporaneos: number;
  monto_complementos_extemporaneos: number;
}

export interface FacturaPPD {
  uuid: string;
  fecha: string;
  serie: string | null;
  folio: string | null;
  emisor_rfc: string;
  emisor_nombre: string;
  receptor_rfc: string;
  receptor_nombre: string;
  total: number;
  total_pagado: number;
  saldo_pendiente: number;
  num_pagos: number;
  moneda: string;
  estado_sat: 'Vigente' | 'Cancelado' | 'No encontrado' | null;
  status: PagoStatus;
  warnings: string[];
}

export interface FacturasPPDResponse {
  total: number;
  page: number;
  page_size: number;
  items: FacturaPPD[];
}

export interface PagoRelacionadoDetalle {
  cfdi_pago_uuid: string;
  fecha_emision_complemento: string;
  cfdi_pago_fecha_pago: string;
  cfdi_pago_forma: string | null;
  docto_num_parcialidad: number;
  docto_imp_saldo_ant: number;
  docto_imp_pagado: number;
  docto_imp_saldo_insoluto: number;
  docto_moneda: string | null;
  pago_emisor_rfc: string;
  pago_emisor_nombre: string;
}

export interface ReporteAnalisisFechas {
  reporte: 'analisis-fechas';
  items: {
    cfdi_pago_uuid: string;
    fecha_emision_complemento: string;
    cfdi_pago_fecha_pago: string;
    emisor_rfc: string;
    emisor_nombre: string;
    monto_complemento: number;
    limite: string;
    dias_retraso: number;
    factura_uuid: string;
    factura_folio: string | null;
  }[];
}

export interface ReportePagosHuerfanos {
  reporte: 'huerfanos';
  items: {
    cfdi_pago_uuid: string;
    fecha_emision: string;
    emisor_rfc: string;
    emisor_nombre: string;
    monto: number;
    documentos_referenciados: string | null; // pipe-separated UUIDs
  }[];
}

export interface ReporteIncidenciasPue {
  reporte: 'incidencias-pue';
  items: {
    factura_uuid: string | null;
    factura_fecha: string | null;
    emisor_rfc: string | null;
    emisor_nombre: string | null;
    factura_total: number | null;
    factura_metodo_pago: string | null;
    complemento_uuid: string;
    cfdi_pago_fecha_pago: string;
    monto_pagado: number;
    docto_metodo_pago: string | null;
    descripcion_riesgo: string;
  }[];
}

// ---------------------------------------------------------------------------
// Procesador de comprobantes — Nómina
// ---------------------------------------------------------------------------

export type TipoNomina = 'O' | 'E';
export type ClaseConcepto = 'Percepcion' | 'Deduccion' | 'OtroPago';

export interface NominaFiltros {
  desde: string | null;
  hasta: string | null;
  busqueda: string | null;
  tipo_nomina: TipoNomina | null;
  periodicidad: string | null;
  solo_con_errores: boolean;
}

export interface NominaStats {
  total_recibos: number;           // respeta filtros
  total_global_recibos: number;    // sin filtros — empty state
  total_empleados: number;
  total_conceptos: number;
  nominas_ordinarias: number;
  nominas_extraordinarias: number;
  total_percepciones: number;
  total_deducciones: number;
  total_otros_pagos: number;
  neto_a_pagar: number;
  conceptos_con_errores: number;
}

export interface NominaRecibo {
  cfdi_uuid: string;
  fecha: string;                   // fecha del CFDI
  fecha_pago: string;
  fecha_inicial_pago: string;
  fecha_final_pago: string;
  emisor_rfc: string;
  emisor_nombre: string;
  receptor_rfc: string;
  receptor_nombre: string;
  registro_patronal: string | null;
  curp: string | null;
  nss: string | null;
  num_empleado: string | null;
  puesto: string | null;
  departamento: string | null;
  tipo_contrato: string | null;
  tipo_regimen: string | null;
  tipo_jornada: string | null;
  periodicidad_pago: string | null;
  fecha_inicio_rel_laboral: string | null;
  antiguedad: string | null;
  salario_base_cot_apor: number;
  salario_diario_integrado: number;
  riesgo_trabajo: string | null;
  banco: string | null;
  cuenta_bancaria: string | null;
  sindicalizado: string | null;
  clave_ent_fed: string | null;
  tipo_nomina: TipoNomina | null;
  num_dias_pagados: number;
  total_percepciones: number;
  total_deducciones: number;
  total_otros_pagos: number;
  neto: number;
  estado_sat: 'Vigente' | 'Cancelado' | 'No encontrado' | null;
  warnings: string[];
}

export interface NominaRecibosResponse {
  total: number;
  page: number;
  page_size: number;
  items: NominaRecibo[];
}

export interface NominaConceptoDetalle {
  clase: ClaseConcepto;
  tipo_concepto: string;
  clave_interna: string | null;
  concepto: string | null;
  importe_gravado: number;
  importe_exento: number;
  importe: number;
  subsidio_causado: number;
}

export interface EmployeeIsrBreakdown {
  rfc: string;
  nombre: string;
  percepciones_gravadas: number;
  isr_retenido: number;
  isr_teorico: number;
  diferencia: number;
  periodicidad: string;
  periodos_detectados: number;
  meses_detectados: number;
  advertencia_periodo: string | null;
}

export interface IsrAnalisis {
  year_detected: number;
  tarifa_label: string;
  isr_bruto: number;
  subsidio_aplicado: number;
  isr_teorico: number;
  isr_diferencia: number;
  limite_spe: number;
  aplica_spe: boolean;
}

export interface ReporteDeducibilidad {
  reporte: 'deducibilidad';
  periodo_inicio: string;
  periodo_fin: string;
  total_percepciones: number;
  percepciones_gravadas: number;
  percepciones_exentas: number;
  total_deducciones: number;
  seguro_social: number;
  isr_retenido: number;
  aportaciones_retiro_cesantia: number;
  otros_deducciones: number;
  salario_neto: number;
  isr_analisis: IsrAnalisis;
  empleados_analizados: number;
  desglose_por_empleado: EmployeeIsrBreakdown[];
  advertencias_periodo: string[];
  recomendaciones: string[];
  detalle_analisis: {
    cumplimiento_retenciones: string;
    adecuacion_fiscal: string;
    observaciones: string[];
  };
}

export interface ImssRegistro {
  rfc: string;
  nss: string;
  nombre: string;
  fechas_registro: string[];
  salario_base_cot_apor: number;
  salario_diario_integrado: number;
  dias_trabajados: number;
  aportaciones_patronal: number;
  aportaciones_obrero: number;
  seguro_social: number;
  tipo_regimen: string;
  riesgo_trabajo: string;
  observaciones: string[];
}

export interface ReporteImss {
  reporte: 'imss';
  periodo_inicio: string;
  periodo_fin: string;
  total_empleados: number;
  registros: ImssRegistro[];
  totales: {
    suma_sbc: number;
    suma_dias: number;
    suma_aportaciones_patronal: number;
    suma_aportaciones_obrero: number;
    suma_seguro_social: number;
  };
  alertas: {
    empleados_sin_nss: string[];
    sbc_fuera_limites: string[];
    dias_anomalous: string[];
  };
}

export interface PeriodoVariaciones {
  empleados_variacion: number;
  empleados_variacion_pct: number;
  percepciones_variacion: number;
  percepciones_variacion_pct: number;
  deducciones_variacion: number;
  deducciones_variacion_pct: number;
  empleados_nuevos: string[];
  empleados_eliminados: string[];
  conceptos_nuevos: string[];
  conceptos_eliminados: string[];
}

export interface PeriodoMetricas {
  inicio: string;
  fin: string;
  total_empleados: number;
  total_percepciones: number;
  total_deducciones: number;
  promedio_por_empleado: number;
}

export interface ReportePeriodoVsPeriodo {
  reporte: 'periodo-vs-periodo';
  insuficiente: boolean;
  mensaje_insuficiente: string | null;
  periodo_previo: PeriodoMetricas | null;
  periodo_actual: PeriodoMetricas | null;
  variaciones: PeriodoVariaciones | null;
  analisis_detallado: {
    tendencia: string;
    observaciones: string[];
  } | null;
}

// ---------------------------------------------------------------------------
// Calculadoras fiscales y laborales
// (espejo de sat_descarga/api/routers/calculadoras.py + sat_descarga/calculadoras/)
// ---------------------------------------------------------------------------

export type CalculadoraNombre =
  | 'aguinaldo'
  | 'sbc'
  | 'isr'
  | 'finiquito'
  | 'liquidacion'
  | 'carga-patronal'
  | 'ptu';

export type TipoSalario = 'diario' | 'mensual';
export type MetodoIsrAguinaldo = 'ley' | 'reglamento';
export type PeriodicidadIsr = 'diario' | 'semanal' | 'decenal' | 'quincenal' | 'mensual';
export type ClaseRiesgo = 'I' | 'II' | 'III' | 'IV' | 'V';
export type TipoTerminacion =
  | 'DESPIDO_INJUSTIFICADO'
  | 'RESCISION_ART51'
  | 'TERMINACION_COLECTIVA'
  | 'RENUNCIA_VOLUNTARIA';

// --- Requests de cálculo (el hook agrega `rfc` con la empresa activa) -------

export interface CalculadoraAguinaldoRequest {
  salario: number;
  tipo_salario: TipoSalario;
  fecha_ingreso: string; // "YYYY-MM-DD"
  dias_aguinaldo: number;
  fecha_calculo?: string | null;
  ingreso_ordinario_mensual?: number | null;
  metodo_isr: MetodoIsrAguinaldo;
  /** ZLFN: el salario mínimo (umbral de validación) es mayor al general. */
  es_zona_fronteriza: boolean;
  anio: number;
  rfc?: string | null;
}

export interface CalculadoraSbcRequest {
  salario: number;
  tipo_salario: TipoSalario;
  antiguedad_anios: number;
  dias_aguinaldo: number;
  prima_vacacional: number; // 0.25..1
  /** ZLFN: el salario mínimo (umbral de validación) es mayor al general. */
  es_zona_fronteriza: boolean;
  anio: number;
  rfc?: string | null;
}

export interface CalculadoraIsrRequest {
  ingreso_gravado: number;
  periodicidad: PeriodicidadIsr;
  es_asimilado: boolean;
  /** ZLFN: el salario mínimo (umbral de retención) es mayor al general. */
  es_zona_fronteriza: boolean;
  mes: number; // 1..12 (enero vs resto afecta el subsidio)
  anio: number;
  rfc?: string | null;
}

export interface CalculadoraFiniquitoRequest {
  salario: number;
  tipo_salario: TipoSalario;
  fecha_ingreso: string;
  fecha_baja: string;
  dias_aguinaldo: number;
  prima_vacacional: number;
  anio: number;
  rfc?: string | null;
}

export interface CalculadoraLiquidacionRequest extends CalculadoraFiniquitoRequest {
  tipo_terminacion: TipoTerminacion;
  es_zona_fronteriza: boolean;
  ultimo_sueldo_mensual?: number | null;
}

export interface PrestacionAdicional {
  nombre: string;
  monto: number;
  tipo: 'mensual' | 'anual';
}

export interface CalculadoraCargaPatronalRequest {
  salario: number;
  tipo_salario: TipoSalario;
  antiguedad_anios: number;
  /** ZLFN: el salario mínimo (umbral de validación) es mayor al general. */
  es_zona_fronteriza: boolean;
  clase_riesgo: ClaseRiesgo;
  /** En porcentaje (p. ej. 0.54355). null → prima media de la clase. */
  prima_riesgo_trabajo?: number | null;
  codigo_estado: string;
  /** Decimal 0..0.1 (p. ej. 0.03). null → tasa nominal del estado. */
  tasa_impuesto_estatal?: number | null;
  incluir_aguinaldo_mensual: boolean;
  incluir_vacaciones_mensual: boolean;
  prestaciones_adicionales: PrestacionAdicional[];
  anio: number;
  rfc?: string | null;
}

export interface TrabajadorPtuRequest {
  nombre: string;
  salario_diario: number;
  dias_trabajados: number; // 1..366
  percepcion_anual: number;
  rfc?: string;
  curp?: string;
  nss?: string;
  es_confianza: boolean;
  ptu_anio_1: number;
  ptu_anio_2: number;
  ptu_anio_3: number;
  ingreso_mensual_ordinario: number;
  isr_mensual_ordinario: number;
}

export interface CalculadoraPtuRequest {
  utilidad_fiscal: number;
  ejercicio: number; // 2021-2025
  nombre: string;
  rfc_empresa: string;
  ptu_no_cobrada: number;
  tipo_persona: 'Moral' | 'Física';
  fecha_pago?: string | null;
  criterio_exencion: 'UMA' | 'SMG';
  trabajadores: TrabajadorPtuRequest[];
  rfc?: string | null;
}

// --- Resultados --------------------------------------------------------------

/** Paso del desglose "paso a paso" que generan aguinaldo y otras calculadoras. */
export interface DesglosePaso {
  numero: number;
  descripcion: string;
  formula: string;
  valores: Record<string, unknown>;
  resultado: number | string;
}

export interface DesgloseConPasos {
  pasos: DesglosePaso[];
  parametros: Record<string, number | string>;
}

export interface ComparacionMetodosAguinaldo {
  metodo_ley: { isr_calculado: number; tasa_efectiva: number };
  metodo_reglamento: {
    isr_calculado: number;
    tasa_efectiva: number;
    aguinaldo_mensualizado: number;
  };
  diferencia: number;
  metodo_recomendado: MetodoIsrAguinaldo;
}

export interface AguinaldoResultado {
  salario_diario: number;
  dias_trabajados: number;
  dias_aguinaldo_proporcionales: number;
  aguinaldo_bruto: number;
  parte_exenta: number;
  parte_gravada: number;
  isr_retenido: number;
  tasa_efectiva_isr: number;
  aguinaldo_neto: number;
  desglose: DesgloseConPasos;
  comparacion_metodos: ComparacionMetodosAguinaldo | null;
}

export interface SbcResultado {
  salario_diario_base: number;
  factor_integracion: number;
  sbc_diario: number;
  sbc_mensual: number;
  tope_sbc: number;
  excede_tope: boolean;
  desglose: {
    salario_base: { dias: number; integracion_diaria: number };
    aguinaldo: { dias: number; integracion_diaria: number };
    prima_vacacional: {
      dias_vacaciones: number;
      porcentaje: number;
      integracion_diaria: number;
    };
    total_integrado: number;
  };
}

export interface IsrResultado {
  ingreso_bruto: number;
  base_gravable: number;
  isr_bruto: number;
  subsidio_aplicado: number;
  isr_final: number;
  tasa_efectiva: number;
  ingreso_neto: number;
  periodicidad: string;
  desglose: {
    limite_inferior: number;
    excedente_limite_inferior: number;
    tasa_marginal: number;
    impuesto_marginal: number;
    cuota_fija: number;
    isr_antes_subsidio: number;
    subsidio: number;
    isr_final: number;
    rango_tarifa: {
      limite_inferior: number;
      limite_superior: number | null;
      cuota_fija: number;
      porcentaje_sobre_excedente: number;
    };
  };
}

export interface Antiguedad {
  anios: number;
  meses: number;
  dias: number;
  anios_completos: number;
  total_dias: number;
  texto: string;
}

export interface SalarioDevengado {
  dias: number;
  monto_por_dia: number;
  monto: number;
}

export interface AguinaldoProporcional {
  dias_correspondientes: number;
  dias_aguinaldo_anual: number;
  monto: number;
  exencion: number;
  gravado: number;
  exento: number;
}

export interface VacacionesProporcionales {
  dias_vacaciones_anuales: number;
  dias_correspondientes: number;
  monto_por_dia: number;
  monto: number;
}

export interface PrimaVacacionalProporcional {
  porcentaje: number;
  monto: number;
  exencion: number;
  gravado: number;
  exento: number;
}

export interface FiniquitoResultado {
  salario_diario: number;
  salario_mensual: number;
  antiguedad: Antiguedad;
  salario_devengado: SalarioDevengado;
  aguinaldo_proporcional: AguinaldoProporcional;
  vacaciones_proporcionales: VacacionesProporcionales;
  prima_vacacional: PrimaVacacionalProporcional;
  fiscal: {
    total_gravado: number;
    total_exento: number;
    isr_retenido: number;
  };
  subtotal_bruto: number;
  total_isr: number;
  total_neto: number;
}

/** Conceptos del finiquito dentro de una liquidación. */
export interface FiniquitoConceptos {
  salario_devengado: SalarioDevengado;
  aguinaldo_proporcional: AguinaldoProporcional;
  vacaciones_proporcionales: VacacionesProporcionales;
  prima_vacacional: PrimaVacacionalProporcional;
  subtotal: number;
  total_gravado: number;
  total_exento: number;
}

export interface LiquidacionIndemnizacion {
  tres_meses_constitucional: {
    dias_sdi: number;
    salario_diario_integrado: number;
    monto: number;
    aplica: boolean;
    fundamento_legal: string;
  };
  veinte_dias_por_anio: {
    anios_completos: number;
    dias_por_anio: number;
    salario_diario_integrado: number;
    monto: number;
    aplica: boolean;
    fundamento_legal: string;
    razon_no_aplica: string | null;
  };
  prima_antiguedad: {
    anios_servicio: number;
    dias_por_anio: number;
    salario_diario: number;
    monto: number;
    aplica: boolean;
    salario_tope: number;
    salario_aplicable: number;
    fundamento_legal: string;
    razon_no_aplica?: string;
  };
  subtotal: number;
  exencion: number;
  gravado: number;
  exento: number;
}

export interface LiquidacionFiscalIndemnizacion {
  total_bruto: number;
  exencion_90_uma: number;
  base_gravable: number;
  ultimo_sueldo_mensual: number;
  isr_ultimo_sueldo: number;
  tasa_efectiva: number;
  usa_tasa_efectiva: boolean;
  isr: number;
}

export interface LiquidacionResultado {
  salario_diario: number;
  salario_mensual: number;
  salario_diario_integrado: number;
  factor_integracion: number;
  antiguedad: Antiguedad;
  finiquito: FiniquitoConceptos;
  indemnizacion: LiquidacionIndemnizacion | null;
  fiscal: {
    finiquito: { base_gravable: number; isr: number };
    indemnizacion: LiquidacionFiscalIndemnizacion;
    total_gravado: number;
    total_exento: number;
    total_isr: number;
  };
  total_bruto: number;
  total_isr: number;
  total_neto: number;
  aplica_indemnizacion: boolean;
  aplica_tres_meses: boolean;
  aplica_veinte_dias: boolean;
  aplica_prima_antiguedad: boolean;
  tipo_terminacion: TipoTerminacion;
}

export interface CuotasImss {
  enfermedad_maternidad: number;
  invalidez_vida: number;
  cesantia_vejez: number;
  guarderias: number;
  riesgos_trabajo: number;
  total: number;
}

export interface CargaPatronalConcepto {
  nombre: string;
  descripcion: string;
  monto_mensual: number;
  monto_anual: number;
  categoria: string;
}

export interface CargaPatronalResultado {
  salario_diario: number;
  salario_mensual: number;
  salario_anual: number;
  sbc: number;
  sbc_mensual: number;
  cuotas_imss: CuotasImss;
  infonavit: number;
  impuesto_estatal: number;
  aguinaldo_prorrateo: number;
  vacaciones_prorrateo: number;
  prestaciones_adicionales: number;
  isr_empleado: number;
  salario_neto: number;
  carga_patronal_mensual: number;
  costo_total_mensual: number;
  costo_total_anual: number;
  prima_riesgo_aplicada: number;
  tasa_estatal_aplicada: number;
  desglose: {
    conceptos: CargaPatronalConcepto[];
    total_salarios: number;
    total_carga_patronal: number;
    costo_total: number;
  };
}

export interface PtuTrabajadorResultado {
  nombre: string;
  rfc: string;
  curp: string;
  nss: string;
  salario_diario: number;
  dias_trabajados: number;
  percepcion_anual: number;
  es_confianza: boolean;
  salario_tope_confianza: number | null;
  ingreso_mensual_ordinario: number;
  isr_mensual_ordinario: number;
  factor_dias: number;
  ptu_dias: number;
  factor_salarios: number;
  ptu_salarios: number;
  ptu_bruta: number;
  tope_tres_meses: number;
  promedio_tres_anios: number;
  monto_maximo: number;
  ptu_real: number;
  exencion_aplicable: number;
  ptu_exenta: number;
  ptu_gravada: number;
  art96: {
    base_gravable: number;
    isr_total: number;
    isr_ordinario: number;
    isr_ptu: number;
    ptu_neta: number;
  };
  art174: {
    ptu_promedio_mensual: number;
    base_promediada: number;
    isr_base_promediada: number;
    isr_ordinario_sin_subsidio: number;
    diferencia_isr: number;
    tasa_efectiva: number;
    isr_ptu: number;
    ptu_neta: number;
  };
  comparacion: {
    diferencia_isr: number;
    metodo_recomendado: 'art96' | 'art174';
    isr_recomendado: number;
    ptu_neta_final: number;
  };
  advertencias: string[];
}

export interface PtuResultado {
  config: {
    ejercicio: number;
    anio_pago: number;
    uma_diaria: number;
    smg_general: number;
    smg_frontera: number;
    criterio_exencion: 'UMA' | 'SMG';
    dias_exencion: number;
    exencion_por_trabajador: number;
    tipo_persona: string;
    fecha_pago: string | null;
    fecha_limite_pago: string;
  };
  empresa: {
    nombre: string;
    rfc: string;
    utilidad_fiscal: number;
    ptu_no_cobrada: number;
    ptu_generada: number;
    ptu_a_repartir: number;
    bolsa_dias: number;
    bolsa_salarios: number;
  };
  trabajadores: PtuTrabajadorResultado[];
  totales: {
    ptu_bruta: number;
    ptu_real: number;
    ptu_exenta: number;
    ptu_gravada: number;
    isr_art96: number;
    isr_art174: number;
    isr_recomendado: number;
    ptu_neta_a_pagar: number;
  };
  advertencias: string[];
}

// --- Mapas nombre → request/resultado (tipan calculadoraCalcular) -----------

export interface CalculadoraRequestMap {
  aguinaldo: CalculadoraAguinaldoRequest;
  sbc: CalculadoraSbcRequest;
  isr: CalculadoraIsrRequest;
  finiquito: CalculadoraFiniquitoRequest;
  liquidacion: CalculadoraLiquidacionRequest;
  'carga-patronal': CalculadoraCargaPatronalRequest;
  ptu: CalculadoraPtuRequest;
}

export interface CalculadoraResultadoMap {
  aguinaldo: AguinaldoResultado;
  sbc: SbcResultado;
  isr: IsrResultado;
  finiquito: FiniquitoResultado;
  liquidacion: LiquidacionResultado;
  'carga-patronal': CargaPatronalResultado;
  ptu: PtuResultado;
}

/** Inputs de una calculadora = su request sin el RFC (lo agrega el hook). */
export type CalculadoraInputs<N extends CalculadoraNombre> = Omit<
  CalculadoraRequestMap[N],
  'rfc'
>;

// --- Respuestas del agente ---------------------------------------------------

export interface CalculoResponse<R> {
  ok: boolean;
  resultado: R;
  advertencias: string[];
  guardado_en: string | null;
}

export interface CalculadoraEstado {
  inputs: Record<string, unknown>;
  resultado: Record<string, unknown>;
  anio: number;
  actualizado_en: string;
}

export interface CalculadoraEstadoResponse {
  ok: boolean;
  estado: CalculadoraEstado | null;
}

export interface CalculadoraGuardado {
  id: string;
  calculadora: string;
  nombre: string;
  inputs: Record<string, unknown>;
  resultado: Record<string, unknown>;
  anio: number;
  creado_en: string;
}

export interface CalculadorasEstadoResponse {
  ok: boolean;
  estados: Record<string, CalculadoraEstado>;
  guardados: CalculadoraGuardado[];
}

export interface CalculadoraGuardadoRequest {
  calculadora: CalculadoraNombre;
  nombre: string;
  inputs: Record<string, unknown>;
  resultado: Record<string, unknown>;
  anio: number;
}

// --- Indicadores del ejercicio (GET /calculadoras/indicadores/{anio}) -------

export interface EstadoIsn {
  codigo: string;
  nombre: string;
  tasa_nomina: number;
}

export interface TipoTerminacionInfo {
  label: string;
  descripcion: string;
  finiquito: boolean;
  tres_meses: boolean;
  veinte_dias: boolean;
  prima_antiguedad: boolean | 'condicional';
  fundamento_legal: string;
}

export interface IndicadoresCalculadoras {
  ok: boolean;
  anio: number;
  uma_diaria: number;
  uma_mensual: number;
  uma_anual: number;
  smg_general: number;
  smg_frontera: number;
  tope_sbc_diario: number;
  tarifa_isr_mensual: unknown;
  spe: unknown;
  imss: unknown;
  estados_isn: EstadoIsn[];
  /** Prima media por clase de riesgo, en decimal (0.0054355 = 0.54355%). */
  primas_riesgo: Record<string, number>;
  descripcion_clases_riesgo: Record<string, string>;
  tipos_terminacion: Record<string, TipoTerminacionInfo>;
  advertencias: string[];
}

// ---------------------------------------------------------------------------
// DIOT 2025 (carga masiva) — /diot/*
// ---------------------------------------------------------------------------
//
// Un renglón lleva las 54 claves del layout oficial (docs/producto/diot-2025.md en el
// repo raíz) + metadatos de UI que el TXT ignora (nombre, origen, estimado,
// num_cfdis). Los montos son enteros sin decimales.

export interface FilaDiot {
  // Datos del tercero (campos 1–7)
  tipo_tercero: string; // '04' | '05' | '15'
  tipo_operacion: string;
  rfc: string;
  id_fiscal: string;
  nombre_extranjero: string;
  pais: string;
  lugar_jurisdiccion: string;
  manifiesto: string; // '01' | '02'
  // Metadatos de UI (no se exportan)
  nombre?: string;
  origen?: 'cfdi' | 'manual';
  estimado?: boolean;
  num_cfdis?: number;
  // Los 47 montos enteros (valor_16, dev_16, acred_excl_16, iva_retenido, ...)
  [monto: string]: string | number | boolean | undefined;
}

export interface HallazgoDiot {
  fila: number | null;
  campo: string | null;
  mensaje: string;
}

export interface EstadoDiot {
  filas: FilaDiot[];
  origen: 'prellenado' | 'manual' | null;
  generado_en: string | null;
  actualizado_en: string | null;
  errores: HallazgoDiot[];
  advertencias: HallazgoDiot[];
  /** Solo en la respuesta de prellenar. */
  resumen?: ResumenPrellenadoDiot;
}

export interface ResumenPrellenadoDiot {
  cfdis_considerados: number;
  /** Elegibles del periodo que el usuario apagó con el interruptor DIOT en Comprobantes. */
  cfdis_excluidos?: number;
  cfdis_sin_desglose: number;
  proveedores: number;
}

export interface CampoDiotMeta {
  clave: string;
  etiqueta: string;
  tipo: 'catalogo' | 'texto' | 'entero';
  seccion: 'tercero' | 'valores' | 'iva_acreditable' | 'iva_no_acreditable' | 'adicionales';
}

export interface CatalogosDiot {
  tipo_tercero: Record<string, string>;
  tipo_operacion: Record<string, string>;
  operaciones_por_tercero: Record<string, string[]>;
  manifiesto: Record<string, string>;
  paises: Record<string, string>;
  campos: CampoDiotMeta[];
}

// ---------------------------------------------------------------------------
// Tareas personales (centro de mando) — /tareas*
// ---------------------------------------------------------------------------

export type TareaTipo = 'fiscal' | 'manual' | 'recurrente';
export type TareaEstado = 'pendiente' | 'curso' | 'hecho';
export type TareaPrioridad = 'alta' | 'media' | 'baja';

export interface Tarea {
  id: string;
  titulo: string;
  /** RFC de la empresa vinculada, o null = tarea general. */
  rfc: string | null;
  tipo: TareaTipo;
  estado: TareaEstado;
  prioridad: TareaPrioridad;
  /** Fecha límite "YYYY-MM-DD" o null (sin fecha). */
  fecha: string | null;
  origen: 'manual' | 'sugerencia';
  /** Id determinista de la sugerencia aceptada (suprime re-derivarla). */
  sugerencia_id: string | null;
  creado_en: string;
  actualizado_en: string;
  completado_en: string | null;
  /** Reservado: evento espejo en Google Calendar (docs/producto/tareas-gcal-sync.md). */
  gcal_event_id: string | null;
}

// GET /tareas
export interface TareasResponse {
  tareas: Tarea[];
  sugerencias_descartadas: string[];
}

// POST /tareas
export interface TareaCrearRequest {
  titulo: string;
  rfc?: string | null;
  tipo?: TareaTipo;
  estado?: TareaEstado;
  prioridad?: TareaPrioridad;
  fecha?: string | null;
  sugerencia_id?: string;
}

// PATCH /tareas/{id} — solo se aplican los campos enviados
export interface TareaPatchRequest {
  titulo?: string;
  rfc?: string | null;
  tipo?: TareaTipo;
  estado?: TareaEstado;
  prioridad?: TareaPrioridad;
  fecha?: string | null;
}

import { API_BASE_URL, getAgentToken } from './constants';
import { agregarBreadcrumb, capturarExcepcion } from './telemetria';
import type {
  HealthResponse,
  CargarFielResponse,
  DescargarFielResponse,
  SolicitudRequest,
  SolicitudResponse,
  VerificarRequest,
  VerificarResponse,
  DescargarResponse,
  DescargaCompletaRequest,
  SolicitudFolioRequest,
  OrganizadorConfig,
  OrganizadorRequest,
  OrganizadorResult,
  RenombrarRequest,
  DeduplicarRequest,
  DeduplicarResult,
  CiecCfdiRequest,
  CiecDocRequest,
  CfdiFielRequest,
  RenovarRequest,
  RenovarRecuperarRequest,
  CsdSolicitarRequest,
  CsdRecuperarRequest,
  JobIniciado,
  JobEstadoResponse,
  JobEvent,
  EmpresasResponse,
  EmpresaCiecRequest,
  EmpresaUpdatePatch,
  ParsearCsfResponse,
  ParsearOpinionResponse,
  ActivarEmpresaResponse,
  SolicitudesResponse,
  SolicitudesActividadResponse,
  HistorialResponse,
  DocumentoResponse,
  Tarea,
  TareasResponse,
  TareaCrearRequest,
  TareaPatchRequest,
  CfdiListResponse,
  CfdiStats,
  CfdiFiltros,
  CfdiFlagsPatch,
  CfdiFlagsResponse,
  CargarDesdeEmpresaRequest,
  ProcesadorCargarResponse,
  ReporteTotalesMes,
  ReporteTopContrapartes,
  ReporteIntegridad,
  ValidarSatResponse,
  PagosFiltros,
  PagosStats,
  FacturasPPDResponse,
  PagoRelacionadoDetalle,
  ReporteAnalisisFechas,
  ReportePagosHuerfanos,
  ReporteIncidenciasPue,
  NominaFiltros,
  NominaStats,
  NominaRecibosResponse,
  NominaConceptoDetalle,
  ReporteDeducibilidad,
  ReporteImss,
  ReportePeriodoVsPeriodo,
  ListaNegraMatch,
  ListasNegrasMetadata,
  ListasNegrasConsultarResponse,
  ProcesadorValidarListasNegrasResponse,
  ProcesadorListasNegrasStats,
  EmisoresListasNegrasResponse,
  CalculadoraNombre,
  CalculadoraRequestMap,
  CalculadoraResultadoMap,
  CalculoResponse,
  CalculadorasEstadoResponse,
  CalculadoraEstadoResponse,
  CalculadoraGuardado,
  CalculadoraGuardadoRequest,
  IndicadoresCalculadoras,
  EstadoDiot,
  FilaDiot,
  CatalogosDiot,
} from './types';

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    /** Cuerpo JSON completo de la respuesta (p. ej. `tope_empresas` del 402). */
    public readonly body?: unknown,
  ) {
    super(`[${status}] ${detail}`);
    this.name = 'ApiError';
  }
}

/**
 * Datos del 402 del agente cuando el plan no tiene lugar para otra empresa
 * activa (alta o desarchivar). `null` si el error es de otro tipo.
 */
export function topeEmpresasDeError(e: unknown): TopeEmpresas | null {
  if (!(e instanceof ApiError) || e.status !== 402) return null;
  const body = e.body as { codigo?: unknown; tope_empresas?: unknown } | undefined;
  if (body?.codigo !== 'tope_empresas' || !body.tope_empresas) return null;
  const t = body.tope_empresas as Partial<TopeEmpresas>;
  if (typeof t.tope !== 'number' || typeof t.activas !== 'number') return null;
  return {
    plan_codigo: t.plan_codigo ?? null,
    plan_nombre: t.plan_nombre ?? null,
    tope: t.tope,
    activas: t.activas,
    sobran: typeof t.sobran === 'number' ? t.sobran : 0,
    siguiente_plan: t.siguiente_plan ?? null,
  };
}

// ---------------------------------------------------------------------------
// API Client
// ---------------------------------------------------------------------------

export class SatApiClient {
  private readonly baseUrl: string;

  /**
   * ¿El agente respondió alguna vez en esta sesión? Arranca en `false` y pasa a
   * `true` con la primera respuesta HTTP (cualquier status). Sirve para distinguir
   * "el agente aún no termina de levantar" (carrera de arranque esperada en equipos
   * lentos; el health poll reintenta y se recupera solo) de "el agente se cayó /
   * se perdió la conexión" — solo este último vale reportar a Sentry.
   */
  private agenteVistoArriba = false;

  constructor(baseUrl?: string) {
    this.baseUrl = (baseUrl ?? API_BASE_URL).replace(/\/+$/, '');
  }

  // -----------------------------------------------------------------------
  // Internal helpers
  // -----------------------------------------------------------------------

  /** Header de autenticación con el agente (token efímero inyectado por Electron). */
  private tokenHeaders(): Record<string, string> {
    const token = getAgentToken();
    return token ? { 'X-Agent-Token': token } : {};
  }

  private async request<T>(
    path: string,
    options: RequestInit = {},
    opts: { reportarFallosDeRed?: boolean } = {},
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const method = options.method ?? 'GET';
    agregarBreadcrumb({ category: 'http', message: `${method} ${path}`, level: 'info' });

    let res: Response;
    try {
      res = await fetch(url, {
        ...options,
        headers: {
          ...this.tokenHeaders(),
          ...(options.headers ?? {}),
        },
      });
    } catch (err) {
      // Fallo de red. Solo lo reportamos si el agente YA respondió alguna vez en
      // esta sesión (= se cayó / se perdió la conexión). Antes de eso es la carrera
      // de arranque (el binario del agente tarda en aceptar conexiones en equipos
      // lentos): ruido esperado que el health poll resuelve solo, no un fallo real.
      if (opts.reportarFallosDeRed !== false && this.agenteVistoArriba) {
        capturarExcepcion(err, { path, method });
      }
      throw err;
    }

    // Hubo respuesta HTTP (cualquier status): el agente está arriba.
    this.agenteVistoArriba = true;

    if (!res.ok) {
      let detail: string;
      let cuerpo: unknown;
      try {
        cuerpo = await res.json();
        const body = cuerpo as { detail?: string };
        detail = body.detail ?? JSON.stringify(body);
      } catch {
        detail = await res.text().catch(() => res.statusText);
      }
      const error = new ApiError(res.status, detail, cuerpo);
      // Solo capturamos 5xx (fallo real del agente). Los 4xx son esperados
      // (409 job concurrente, 400/422 validación, 401 token) y harían ruido.
      // El 503 tampoco se reporta: por convención del agente significa
      // "servicio externo no disponible, reintenta" (SAT caído/lento,
      // playwright instalándose) — transitorio esperado, no un bug.
      if (res.status >= 500 && res.status !== 503) {
        capturarExcepcion(error, { path, method });
      }
      throw error;
    }

    return res.json() as Promise<T>;
  }

  private async post<T>(
    path: string,
    body: Record<string, unknown> = {},
  ): Promise<T> {
    return this.request<T>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  private async del<T>(path: string): Promise<T> {
    return this.request<T>(path, { method: 'DELETE' });
  }

  private async patch<T>(
    path: string,
    body: Record<string, unknown> = {},
  ): Promise<T> {
    return this.request<T>(path, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  }

  /** URL absoluta para un path del agente (p. ej. para EventSource). */
  url(path: string): string {
    return `${this.baseUrl}${path}`;
  }

  /**
   * URL (con token) para bajar un item del historial en la versión web:
   * `archivo` sirve el archivo directo (PDFs), `zip` empaqueta carpetas.
   * El token va en el query string porque `<a download>` no manda headers.
   */
  urlDescargaHistorial(ruta: string, formato: 'archivo' | 'zip'): string {
    return this.urlConToken(`/descargas/${formato}?ruta=${encodeURIComponent(ruta)}`);
  }

  /**
   * Como `url()`, pero con el token como query param. Solo para EventSource,
   * que no acepta headers; el resto de requests manda el header.
   */
  private urlConToken(path: string): string {
    const token = getAgentToken();
    if (!token) return this.url(path);
    const sep = path.includes('?') ? '&' : '?';
    return `${this.baseUrl}${path}${sep}token=${encodeURIComponent(token)}`;
  }

  // -----------------------------------------------------------------------
  // Health
  // -----------------------------------------------------------------------

  async health(): Promise<HealthResponse> {
    // El health es la sonda de liveness: su fallo de red es estado esperado
    // (lo maneja `useServerHealth` marcando isConnected=false y reintentando),
    // no un error que valga reportar. Nunca va a Sentry.
    return this.request<HealthResponse>('/health', {}, { reportarFallosDeRed: false });
  }

  // -----------------------------------------------------------------------
  // Auth / e-firma
  // -----------------------------------------------------------------------

  /**
   * Upload the FIEL (e-firma) files to the local Python server.
   *
   * Uses FormData because the Python endpoint expects `UploadFile` + `Form`.
   */
  async cargarFiel(
    cerFile: File,
    keyFile: File,
    password: string,
  ): Promise<CargarFielResponse> {
    const formData = new FormData();
    formData.append('cer_file', cerFile);
    formData.append('key_file', keyFile);
    formData.append('password', password);

    return this.request<CargarFielResponse>('/auth/cargar-fiel', {
      method: 'POST',
      body: formData,
      // Do NOT set Content-Type — the browser sets the multipart boundary automatically.
    });
  }

  /**
   * Unload the FIEL from server memory and delete temporary files.
   */
  async descargarFiel(): Promise<DescargarFielResponse> {
    return this.request<DescargarFielResponse>('/auth/fiel', {
      method: 'DELETE',
    });
  }

  // -----------------------------------------------------------------------
  // Web Service: async flow
  // -----------------------------------------------------------------------

  /**
   * Step 1: Request a bulk download from the SAT.
   * Returns a RequestID to poll with `verificar`.
   */
  async solicitar(req: SolicitudRequest): Promise<SolicitudResponse> {
    return this.post<SolicitudResponse>('/solicitar', req as unknown as Record<string, unknown>);
  }

  /**
   * Step 2: Check the status of a download request.
   * When `cod_estado === 3` the packages are ready.
   */
  async verificar(req: VerificarRequest): Promise<VerificarResponse> {
    return this.post<VerificarResponse>('/verificar', req as unknown as Record<string, unknown>);
  }

  /**
   * Step 3: Download the packages for a completed request.
   *
   * Sin `directorioSalida` el agente usa la convención por empresa
   * (`<descargas>/cfdi/{RFC}/`), igual que CIEC.
   */
  async descargar(
    idSolicitud: string,
    directorioSalida?: string,
    extraer = true,
  ): Promise<DescargarResponse> {
    const params = new URLSearchParams({
      id_solicitud: idSolicitud,
      extraer: String(extraer),
    });
    if (directorioSalida) params.set('directorio_salida', directorioSalida);
    return this.request<DescargarResponse>(`/descargar?${params}`, {
      method: 'POST',
    });
  }

  /**
   * All-in-one: solicitar + poll + descargar in a single blocking call.
   * WARNING: Can block for hours for CFDI downloads.
   */
  async descargaCompleta(
    req: DescargaCompletaRequest,
  ): Promise<DescargarResponse> {
    return this.post<DescargarResponse>('/descarga-completa', req as unknown as Record<string, unknown>);
  }

  // -----------------------------------------------------------------------
  // Download by UUID
  // -----------------------------------------------------------------------

  /**
   * Download specific CFDIs by UUID.
   * Blocking: solicitar-folio + poll + descargar in one call.
   */
  async solicitarFolio(
    req: SolicitudFolioRequest,
  ): Promise<DescargarResponse> {
    return this.post<DescargarResponse>('/solicitar-folio', req as unknown as Record<string, unknown>);
  }

  // -----------------------------------------------------------------------
  // File tools (organizar, renombrar, deduplicar)
  // -----------------------------------------------------------------------

  /**
   * Organize XML files into a folder structure based on their content.
   */
  async organizar(req: OrganizadorRequest): Promise<OrganizadorResult> {
    return this.post<OrganizadorResult>('/organizar', req as unknown as Record<string, unknown>);
  }

  /**
   * Bulk-rename XML files based on their CFDI content.
   */
  async renombrar(req: RenombrarRequest): Promise<OrganizadorResult> {
    return this.post<OrganizadorResult>('/renombrar', req as unknown as Record<string, unknown>);
  }

  /**
   * Find and remove duplicate XML files (by UUID).
   */
  async deduplicar(req: DeduplicarRequest): Promise<DeduplicarResult> {
    return this.post<DeduplicarResult>('/deduplicar', req as unknown as Record<string, unknown>);
  }

  // -----------------------------------------------------------------------
  // Jobs CIEC (captcha in-app por SSE) — agente desktop
  // -----------------------------------------------------------------------

  /** Inicia una descarga de CFDIs vía CIEC. Devuelve { job_id }. */
  async ciecCfdi(req: CiecCfdiRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/ciec/cfdi', req as unknown as Record<string, unknown>);
  }

  /** Inicia la descarga de la Constancia de Situación Fiscal vía CIEC. */
  async ciecConstancia(req: CiecDocRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/ciec/constancia', req as unknown as Record<string, unknown>);
  }

  /** Inicia la descarga de la Opinión de Cumplimiento 32-D vía CIEC. */
  async ciecOpinion(req: CiecDocRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/ciec/opinion', req as unknown as Record<string, unknown>);
  }

  /** Entrega la solución del captcha (o `null` para cancelar el job). */
  async responderCaptcha(jobId: string, solution: string | null): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>(`/jobs/${jobId}/captcha`, { solution });
  }

  /** Estado actual de un job. */
  async getJob(jobId: string): Promise<JobEstadoResponse> {
    return this.request<JobEstadoResponse>(`/jobs/${jobId}`);
  }

  /**
   * Suscribe al stream SSE de progreso de un job (incluye `captcha_required`).
   * Devuelve el `EventSource`; el caller debe llamar `.close()` al terminar.
   * Solo en navegador/Electron (usa la API EventSource).
   */
  subscribeJob(
    jobId: string,
    onEvent: (ev: JobEvent) => void,
    onError?: (e: Event) => void,
  ): EventSource {
    const es = new EventSource(this.urlConToken(`/events/${jobId}`));
    es.onmessage = (e) => {
      try {
        onEvent(JSON.parse(e.data) as JobEvent);
      } catch {
        /* ignorar líneas no-JSON */
      }
    };
    if (onError) es.onerror = onError;
    return es;
  }

  // -----------------------------------------------------------------------
  // Documentos vía e.firma (FIEL en sesión; sin captcha)
  // -----------------------------------------------------------------------

  /** Inicia una descarga de CFDIs vía portal con la e.firma en sesión (sin captcha). */
  async cfdiFiel(req: CfdiFielRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/cfdi/fiel', req as unknown as Record<string, unknown>);
  }

  async constanciaFiel(): Promise<DocumentoResponse> {
    return this.post<DocumentoResponse>('/constancia/fiel');
  }

  async opinionFiel(): Promise<DocumentoResponse> {
    return this.post<DocumentoResponse>('/opinion/fiel');
  }

  // -----------------------------------------------------------------------
  // Certifica: renovación de e.firma + CSD (jobs SSE; FIEL-only, sin captcha)
  // -----------------------------------------------------------------------

  /** Renueva la e.firma EN LÍNEA (irreversible; requiere confirmar=true). → {job_id} */
  async renovarEfirma(req: RenovarRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/renovar', req as unknown as Record<string, unknown>);
  }

  /** Descarga el cert de una renovación pendiente (reintento no destructivo). */
  async renovarRecuperar(req: RenovarRecuperarRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/renovar/recuperar', req as unknown as Record<string, unknown>);
  }

  /** Genera y envía una solicitud de CSD de extremo a extremo. → {job_id} */
  async csdSolicitar(req: CsdSolicitarRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/csd', req as unknown as Record<string, unknown>);
  }

  /** Descarga el cert de un CSD pendiente («bajar después»). → {job_id} */
  async csdRecuperar(req: CsdRecuperarRequest): Promise<JobIniciado> {
    return this.post<JobIniciado>('/csd/recuperar', req as unknown as Record<string, unknown>);
  }

  // -----------------------------------------------------------------------
  // Empresas (catálogo persistente; credenciales en keychain del SO)
  // -----------------------------------------------------------------------

  async listEmpresas(): Promise<EmpresasResponse> {
    return this.request<EmpresasResponse>('/empresas');
  }

  /** Registra una empresa por e.firma (multipart .cer/.key/password/nombre). */
  async addEmpresaFiel(
    cerFile: File,
    keyFile: File,
    password: string,
    nombre = '',
    rfcEsperado?: string,
  ): Promise<{ ok: boolean; rfc: string }> {
    const formData = new FormData();
    formData.append('cer_file', cerFile);
    formData.append('key_file', keyFile);
    formData.append('password', password);
    // Opcional: vacío → el agente usa la razón social del certificado.
    formData.append('nombre', nombre);
    // Al agregar e.firma a una empresa existente, valida que el RFC del cert coincida.
    if (rfcEsperado) formData.append('rfc_esperado', rfcEsperado);
    return this.request<{ ok: boolean; rfc: string }>('/empresas/fiel', {
      method: 'POST',
      body: formData,
    });
  }

  /** Registra una empresa por CIEC (RFC + nombre + contraseña CIEC). */
  async addEmpresaCiec(req: EmpresaCiecRequest): Promise<{ ok: boolean; rfc: string }> {
    return this.post<{ ok: boolean; rfc: string }>(
      '/empresas/ciec',
      req as unknown as Record<string, unknown>,
    );
  }

  async removeEmpresa(rfc: string): Promise<{ ok: boolean }> {
    return this.del<{ ok: boolean }>(`/empresas/${encodeURIComponent(rfc)}`);
  }

  /** Quita SOLO la e.firma de la empresa (la CIEC no se toca). */
  async removeEfirmaEmpresa(rfc: string): Promise<{ ok: boolean }> {
    return this.del<{ ok: boolean }>(`/empresas/${encodeURIComponent(rfc)}/fiel`);
  }

  /** Activa una empresa para la sesión (FIEL → carga la e.firma en memoria). */
  async activarEmpresa(rfc: string): Promise<ActivarEmpresaResponse> {
    return this.post<ActivarEmpresaResponse>(`/empresas/${encodeURIComponent(rfc)}/activar`);
  }

  /** Marca una empresa como predeterminada (activa) del catálogo. */
  async setDefaultEmpresa(rfc: string): Promise<{ ok: boolean; rfc: string }> {
    return this.post<{ ok: boolean; rfc: string }>(
      `/empresas/${encodeURIComponent(rfc)}/default`,
    );
  }

  /** Archiva la empresa (soft-delete; la oculta de la lista principal). */
  async archiveEmpresa(rfc: string): Promise<{ ok: boolean; rfc: string }> {
    return this.post<{ ok: boolean; rfc: string }>(
      `/empresas/${encodeURIComponent(rfc)}/archive`,
    );
  }

  /** Desarchiva la empresa (la regresa a la lista principal). */
  async unarchiveEmpresa(rfc: string): Promise<{ ok: boolean; rfc: string }> {
    return this.post<{ ok: boolean; rfc: string }>(
      `/empresas/${encodeURIComponent(rfc)}/unarchive`,
    );
  }

  /** Ajuste: continuidad de credenciales con el espacio en línea. */
  async getSyncCredenciales(): Promise<{ activado: boolean }> {
    return this.request<{ activado: boolean }>('/config/sync-credenciales');
  }

  async setSyncCredenciales(activado: boolean): Promise<{ activado: boolean }> {
    return this.request<{ activado: boolean }>('/config/sync-credenciales', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ activado }),
    });
  }

  /**
   * (Solo desktop) Sube las credenciales de la empresa al espacio en línea del
   * usuario: van cifradas directo a su agente personal en la nube — nunca a
   * bases de datos compartidas.
   */
  async subirAlEspacio(
    rfc: string,
    metodos: string[],
  ): Promise<{ ok: boolean; subidos: string[] }> {
    return this.post<{ ok: boolean; subidos: string[] }>(
      `/empresas/${encodeURIComponent(rfc)}/subir-al-espacio`,
      { metodos },
    );
  }

  /**
   * Re-parsea la CSF ya descargada y aplica nombre, regímenes y actividades
   * al catálogo (botón «Rellenar desde la constancia»).
   */
  async parsearCsf(rfc: string): Promise<ParsearCsfResponse> {
    return this.post<ParsearCsfResponse>(
      `/empresas/${encodeURIComponent(rfc)}/parsear-csf`,
    );
  }

  /**
   * Re-parsea la Opinión 32-D ya descargada y aplica su sentido + motivos al
   * catálogo (botón «Re-analizar opinión»).
   */
  async parsearOpinion(rfc: string): Promise<ParsearOpinionResponse> {
    return this.post<ParsearOpinionResponse>(
      `/empresas/${encodeURIComponent(rfc)}/parsear-opinion`,
    );
  }

  /** Aplica un patch parcial a la empresa (regimenes_fiscales, actividades_economicas). */
  async updateEmpresa(
    rfc: string,
    patch: EmpresaUpdatePatch,
  ): Promise<{ ok: boolean; rfc: string }> {
    return this.patch<{ ok: boolean; rfc: string }>(
      `/empresas/${encodeURIComponent(rfc)}`,
      patch as unknown as Record<string, unknown>,
    );
  }

  /** Historial de solicitudes de una empresa. */
  async listSolicitudes(rfc: string): Promise<SolicitudesResponse> {
    return this.request<SolicitudesResponse>(
      `/empresas/${encodeURIComponent(rfc)}/solicitudes`,
    );
  }

  /** Borra una solicitud del catálogo local (no afecta al SAT). */
  async deleteSolicitud(rfc: string, idSolicitud: string): Promise<{ ok: boolean }> {
    return this.del<{ ok: boolean }>(
      `/empresas/${encodeURIComponent(rfc)}/solicitudes/${encodeURIComponent(idSolicitud)}`,
    );
  }

  /**
   * Solicitudes WS de TODAS las empresas no archivadas (con rfc + nombre).
   * La consume el watcher global para notificar éxitos/fallas por empresa.
   */
  async solicitudesActividad(): Promise<SolicitudesActividadResponse> {
    return this.request<SolicitudesActividadResponse>('/solicitudes/actividad');
  }

  /** Historial de descargas completadas de TODAS las empresas (recientes primero). */
  async listHistorial(): Promise<HistorialResponse> {
    return this.request<HistorialResponse>('/historial');
  }

  /** Historial de descargas completadas de una empresa. */
  async listHistorialEmpresa(rfc: string): Promise<HistorialResponse> {
    return this.request<HistorialResponse>(
      `/empresas/${encodeURIComponent(rfc)}/historial`,
    );
  }

  /** Abre en el SO una descarga del historial: su carpeta o el archivo (PDF). */
  async abrir(ruta: string, modo: 'carpeta' | 'archivo' = 'carpeta'): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>('/abrir', { ruta, modo });
  }

  // -----------------------------------------------------------------------
  // Tareas personales
  // -----------------------------------------------------------------------

  /** Tareas del usuario + ids de sugerencias descartadas. */
  async listTareas(): Promise<TareasResponse> {
    return this.request<TareasResponse>('/tareas');
  }

  async crearTarea(req: TareaCrearRequest): Promise<Tarea> {
    return this.post<Tarea>('/tareas', { ...req });
  }

  /** Patch parcial: solo se aplican los campos enviados. */
  async actualizarTarea(id: string, patch: TareaPatchRequest): Promise<Tarea> {
    return this.patch<Tarea>(`/tareas/${encodeURIComponent(id)}`, { ...patch });
  }

  async eliminarTarea(id: string): Promise<{ ok: boolean }> {
    return this.del<{ ok: boolean }>(`/tareas/${encodeURIComponent(id)}`);
  }

  /** Persiste el descarte de una sugerencia derivada (no vuelve a aparecer). */
  async descartarSugerencia(id: string): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>('/tareas/sugerencias/descartar', { id });
  }

  // -----------------------------------------------------------------------
  // Ajustes
  // -----------------------------------------------------------------------

  /** Carpeta base donde se guardan las descargas. */
  async getDescargasDir(): Promise<{ dir: string }> {
    return this.request<{ dir: string }>('/config/descargas-dir');
  }

  /** Cambia la carpeta base de descargas. */
  async setDescargasDir(dir: string): Promise<{ dir: string }> {
    return this.request<{ dir: string }>('/config/descargas-dir', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dir }),
    });
  }

  /** Config GLOBAL del organizador (aplica a todas las empresas). */
  async getOrganizadorConfig(): Promise<OrganizadorConfig> {
    return this.request<OrganizadorConfig>('/config/organizador');
  }

  /** Guarda un patch parcial de la config global del organizador. */
  async setOrganizadorConfig(
    patch: Partial<Omit<OrganizadorConfig, 'guardada'>>,
  ): Promise<OrganizadorConfig> {
    return this.request<OrganizadorConfig>('/config/organizador', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
  }

  // -----------------------------------------------------------------------
  // Procesador de comprobantes — CFDI
  // -----------------------------------------------------------------------
  //
  // El buffer está AISLADO POR EMPRESA: todos los métodos llevan el `rfc`
  // de la empresa activa como primer parámetro (el agente lo exige y acota
  // datos, filtros, reportes y exports a esa empresa).

  /** Sube XMLs por multipart al buffer de la empresa (drag&drop, examinar). */
  async procesadorCargar(rfc: string, files: File[]): Promise<ProcesadorCargarResponse> {
    const form = new FormData();
    form.append('rfc', rfc);
    for (const f of files) form.append('files', f);
    return this.request<ProcesadorCargarResponse>('/procesador/cfdi/cargar', {
      method: 'POST',
      body: form,
    });
  }

  /** Importa CFDIs ya descargados por el agente para una empresa registrada. */
  async procesadorCargarDesdeEmpresa(
    req: CargarDesdeEmpresaRequest,
  ): Promise<ProcesadorCargarResponse> {
    return this.post<ProcesadorCargarResponse>(
      '/procesador/cfdi/cargar-desde-empresa',
      req as unknown as Record<string, unknown>,
    );
  }

  /** Valida contra el SAT los CFDIs del buffer de la empresa (o los uuids indicados). */
  async procesadorValidarSat(rfc: string, uuids?: string[]): Promise<ValidarSatResponse> {
    return this.post<ValidarSatResponse>('/procesador/cfdi/validar-sat', {
      rfc,
      uuids: uuids ?? null,
    });
  }

  /** Lista paginada del buffer con filtros. */
  async procesadorListar(
    rfc: string,
    filtros?: Partial<CfdiFiltros>,
    page = 1,
    pageSize = 50,
  ): Promise<CfdiListResponse> {
    const qs = _filtrosToQuery({ ...filtros, rfc, page, page_size: pageSize });
    return this.request<CfdiListResponse>(`/procesador/cfdi?${qs}`);
  }

  /** Stats agregados (cards superiores). */
  async procesadorStats(rfc: string, filtros?: Partial<CfdiFiltros>): Promise<CfdiStats> {
    const qs = _filtrosToQuery({ ...(filtros ?? {}), rfc });
    return this.request<CfdiStats>(`/procesador/cfdi/stats?${qs}`);
  }

  /** Reporte específico: 'totales-mes' | 'top-contrapartes' | 'integridad'. */
  async procesadorReporte(
    rfc: string,
    nombre: 'totales-mes',
    filtros?: Partial<CfdiFiltros>,
  ): Promise<ReporteTotalesMes>;
  async procesadorReporte(
    rfc: string,
    nombre: 'top-contrapartes',
    filtros?: Partial<CfdiFiltros>,
  ): Promise<ReporteTopContrapartes>;
  async procesadorReporte(
    rfc: string,
    nombre: 'integridad',
    filtros?: Partial<CfdiFiltros>,
  ): Promise<ReporteIntegridad>;
  async procesadorReporte(
    rfc: string,
    nombre: string,
    filtros?: Partial<CfdiFiltros>,
  ): Promise<ReporteTotalesMes | ReporteTopContrapartes | ReporteIntegridad> {
    const qs = _filtrosToQuery({ ...(filtros ?? {}), rfc });
    return this.request(`/procesador/cfdi/reporte/${nombre}?${qs}`);
  }

  /** Filtros persistidos de la empresa (lectura). */
  async procesadorFiltrosGet(rfc: string): Promise<CfdiFiltros> {
    return this.request<CfdiFiltros>(`/procesador/cfdi/filtros?rfc=${encodeURIComponent(rfc)}`);
  }

  /** Filtros persistidos de la empresa (escritura). */
  async procesadorFiltrosSet(
    rfc: string,
    filtros: Partial<CfdiFiltros>,
  ): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>('/procesador/cfdi/filtros', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...filtros, rfc }),
    });
  }

  /** Actualiza flags por fila (interruptor DIOT / clasificación deducible). */
  async procesadorActualizarCfdi(
    rfc: string,
    uuid: string,
    patch: CfdiFlagsPatch,
  ): Promise<CfdiFlagsResponse> {
    return this.patch<CfdiFlagsResponse>(
      `/procesador/cfdi/${encodeURIComponent(uuid)}`,
      { rfc, ...patch },
    );
  }

  /** Vacía el buffer y los filtros de UNA empresa (las demás no se tocan). */
  async procesadorBorrar(rfc: string): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>(
      `/procesador/cfdi?rfc=${encodeURIComponent(rfc)}`,
      { method: 'DELETE' },
    );
  }

  /** Descarga el buffer filtrado como Blob (xlsx o csv). */
  async procesadorExportar(
    rfc: string,
    formato: 'xlsx' | 'csv',
    filtros?: Partial<CfdiFiltros>,
  ): Promise<Blob> {
    const qs = _filtrosToQuery({ ...(filtros ?? {}), rfc, formato });
    const r = await fetch(this.url(`/procesador/cfdi/exportar?${qs}`), { headers: this.tokenHeaders() });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`Error al exportar: ${r.status} ${text}`);
    }
    return await r.blob();
  }

  // -----------------------------------------------------------------------
  // Procesador de comprobantes — Pagos
  // -----------------------------------------------------------------------
  //
  // Vista especializada sobre el buffer compartido. NO tiene cargar/borrar —
  // los XMLs entran por `procesadorCargar` (CFDI). Filtros propios con key
  // `'pagos_actuales'` en el backend.

  /** Facturas PPD paginadas con status calculado. */
  async procesadorPagosListar(
    rfc: string,
    filtros?: Partial<PagosFiltros>,
    page = 1,
    pageSize = 50,
  ): Promise<FacturasPPDResponse> {
    const params: Record<string, unknown> = {
      rfc,
      desde: filtros?.desde,
      hasta: filtros?.hasta,
      busqueda: filtros?.busqueda,
      page,
      page_size: pageSize,
    };
    if (filtros?.status && filtros.status.length > 0) {
      params.status = filtros.status.join(',');
    }
    const qs = _filtrosToQuery(params);
    return this.request<FacturasPPDResponse>(`/procesador/pagos?${qs}`);
  }

  /** KPIs del procesador de Pagos. */
  async procesadorPagosStats(
    rfc: string,
    filtros?: Partial<PagosFiltros>,
  ): Promise<PagosStats> {
    const qs = _filtrosToQuery({
      rfc,
      desde: filtros?.desde,
      hasta: filtros?.hasta,
      busqueda: filtros?.busqueda,
    });
    return this.request<PagosStats>(`/procesador/pagos/stats?${qs}`);
  }

  /** Drilldown: complementos asociados a una factura PPD de la empresa. */
  async procesadorPagosDetalleFactura(
    rfc: string,
    uuid: string,
  ): Promise<{ uuid: string; items: PagoRelacionadoDetalle[] }> {
    return this.request(
      `/procesador/pagos/factura/${encodeURIComponent(uuid)}/pagos?rfc=${encodeURIComponent(rfc)}`,
    );
  }

  /** Reporte específico. */
  async procesadorPagosReporte(
    rfc: string,
    nombre: 'analisis-fechas',
    filtros?: Partial<PagosFiltros>,
  ): Promise<ReporteAnalisisFechas>;
  async procesadorPagosReporte(
    rfc: string,
    nombre: 'huerfanos',
    filtros?: Partial<PagosFiltros>,
  ): Promise<ReportePagosHuerfanos>;
  async procesadorPagosReporte(
    rfc: string,
    nombre: 'incidencias-pue',
    filtros?: Partial<PagosFiltros>,
  ): Promise<ReporteIncidenciasPue>;
  async procesadorPagosReporte(
    rfc: string,
    nombre: string,
    filtros?: Partial<PagosFiltros>,
  ): Promise<ReporteAnalisisFechas | ReportePagosHuerfanos | ReporteIncidenciasPue> {
    const qs = _filtrosToQuery({
      rfc,
      desde: filtros?.desde,
      hasta: filtros?.hasta,
      busqueda: filtros?.busqueda,
    });
    return this.request(`/procesador/pagos/reporte/${nombre}?${qs}`);
  }

  /** Filtros persistidos del procesador de Pagos (por empresa). */
  async procesadorPagosFiltrosGet(rfc: string): Promise<PagosFiltros> {
    return this.request<PagosFiltros>(
      `/procesador/pagos/filtros?rfc=${encodeURIComponent(rfc)}`,
    );
  }

  async procesadorPagosFiltrosSet(
    rfc: string,
    filtros: Partial<PagosFiltros>,
  ): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>('/procesador/pagos/filtros', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...filtros, rfc }),
    });
  }

  /** Descarga XLSX multi-sheet del procesador de Pagos. */
  async procesadorPagosExportar(
    rfc: string,
    filtros?: Partial<PagosFiltros>,
  ): Promise<Blob> {
    const qs = _filtrosToQuery({
      rfc,
      desde: filtros?.desde,
      hasta: filtros?.hasta,
      busqueda: filtros?.busqueda,
    });
    const r = await fetch(this.url(`/procesador/pagos/exportar?${qs}`), { headers: this.tokenHeaders() });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`Error al exportar: ${r.status} ${text}`);
    }
    return await r.blob();
  }

  // -------------------------------------------------------------------------
  // Procesador de comprobantes — Nómina
  // -------------------------------------------------------------------------
  // Vista especializada sobre el buffer compartido `cfdis` + tablas
  // `nomina_recibos` y `nomina_conceptos`. Mismo flujo de carga que CFDI:
  // los XMLs entran por `procesadorCargar`. Filtros propios con key
  // `'nomina_actuales'` en el backend.

  private _filtrosNominaParams(filtros?: Partial<NominaFiltros>): Record<string, unknown> {
    return {
      desde: filtros?.desde,
      hasta: filtros?.hasta,
      busqueda: filtros?.busqueda,
      tipo_nomina: filtros?.tipo_nomina,
      periodicidad: filtros?.periodicidad,
      solo_con_errores: filtros?.solo_con_errores ? 'true' : undefined,
    };
  }

  /** Recibos de nómina paginados (1 fila por CFDI tipo N). */
  async procesadorNominaListar(
    rfc: string,
    filtros?: Partial<NominaFiltros>,
    page = 1,
    pageSize = 50,
  ): Promise<NominaRecibosResponse> {
    const qs = _filtrosToQuery({
      rfc,
      ...this._filtrosNominaParams(filtros),
      page,
      page_size: pageSize,
    });
    return this.request<NominaRecibosResponse>(`/procesador/nomina?${qs}`);
  }

  /** KPIs del procesador de Nómina. */
  async procesadorNominaStats(
    rfc: string,
    filtros?: Partial<NominaFiltros>,
  ): Promise<NominaStats> {
    const qs = _filtrosToQuery({ rfc, ...this._filtrosNominaParams(filtros) });
    return this.request<NominaStats>(`/procesador/nomina/stats?${qs}`);
  }

  /** Drilldown: conceptos de un recibo de nómina de la empresa, por clase. */
  async procesadorNominaConceptosDeRecibo(
    rfc: string,
    uuid: string,
  ): Promise<{ uuid: string; items: NominaConceptoDetalle[] }> {
    return this.request(
      `/procesador/nomina/recibo/${encodeURIComponent(uuid)}/conceptos?rfc=${encodeURIComponent(rfc)}`,
    );
  }

  /** Reporte específico (Deductibilidad / IMSS / Periodo vs Periodo). */
  async procesadorNominaReporte(
    rfc: string,
    nombre: 'deducibilidad',
    filtros?: Partial<NominaFiltros>,
  ): Promise<ReporteDeducibilidad>;
  async procesadorNominaReporte(
    rfc: string,
    nombre: 'imss',
    filtros?: Partial<NominaFiltros>,
  ): Promise<ReporteImss>;
  async procesadorNominaReporte(
    rfc: string,
    nombre: 'periodo-vs-periodo',
    filtros?: Partial<NominaFiltros>,
  ): Promise<ReportePeriodoVsPeriodo>;
  async procesadorNominaReporte(
    rfc: string,
    nombre: string,
    filtros?: Partial<NominaFiltros>,
  ): Promise<ReporteDeducibilidad | ReporteImss | ReportePeriodoVsPeriodo> {
    const qs = _filtrosToQuery({ rfc, ...this._filtrosNominaParams(filtros) });
    return this.request(`/procesador/nomina/reporte/${nombre}?${qs}`);
  }

  /** Filtros persistidos del procesador de Nómina (por empresa). */
  async procesadorNominaFiltrosGet(rfc: string): Promise<NominaFiltros> {
    return this.request<NominaFiltros>(
      `/procesador/nomina/filtros?rfc=${encodeURIComponent(rfc)}`,
    );
  }

  async procesadorNominaFiltrosSet(
    rfc: string,
    filtros: Partial<NominaFiltros>,
  ): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>('/procesador/nomina/filtros', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...filtros, rfc }),
    });
  }

  /** Descarga XLSX multi-sheet del procesador de Nómina (con disclaimer fiscal). */
  async procesadorNominaExportar(
    rfc: string,
    filtros?: Partial<NominaFiltros>,
  ): Promise<Blob> {
    const qs = _filtrosToQuery({ rfc, ...this._filtrosNominaParams(filtros) });
    const r = await fetch(this.url(`/procesador/nomina/exportar?${qs}`), { headers: this.tokenHeaders() });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`Error al exportar: ${r.status} ${text}`);
    }
    return await r.blob();
  }

  // -------------------------------------------------------------------------
  // Auth + license (proxy hacia todoconta-apps via el agente)
  // -------------------------------------------------------------------------
  // El Bearer token NO llega al renderer — vive solo en el proceso Python.
  // El renderer solo conoce el estado derivado (autenticado, is_founder, etc.)

  /** Genera un device_code y devuelve el URL público de activación. */
  async authInit(): Promise<AuthInitResponse> {
    return this.post<AuthInitResponse>('/auth/init', {});
  }

  /** Polling del device_code hasta que el usuario completa el login web. */
  async authPoll(device_code: string): Promise<AuthPollResponse> {
    return this.post<AuthPollResponse>('/auth/poll', { device_code });
  }

  /** Login en-app con correo + contraseña (directo contra Supabase). */
  async authLoginPassword(email: string, password: string): Promise<AuthSessionResponse> {
    return this.post<AuthSessionResponse>('/auth/login-password', { email, password });
  }

  /**
   * (Solo versión web) Entrega al agente una sesión de Supabase que el
   * provisioner ya autenticó, para que la persista como un login local.
   */
  async authAdoptSession(session: {
    access_token: string;
    refresh_token?: string | null;
    user_id: string;
    email?: string | null;
  }): Promise<AuthSessionResponse> {
    return this.post<AuthSessionResponse>('/auth/adopt-session', session);
  }

  /**
   * Envía un código de 6 dígitos al correo. Con `crearCuenta` el código
   * también registra al usuario (con `nombre` opcional). `tipo='signup'`
   * reenvía la confirmación de un registro con contraseña.
   */
  async authOtpSend(
    email: string,
    opts: { crearCuenta?: boolean; nombre?: string; tipo?: 'email' | 'signup' } = {},
  ): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>('/auth/otp-send', {
      email,
      crear_cuenta: opts.crearCuenta ?? false,
      nombre: opts.nombre ?? '',
      tipo: opts.tipo ?? 'email',
    });
  }

  /** Verifica el código tecleado en la app y guarda la sesión en el agente. */
  async authOtpVerify(
    email: string,
    token: string,
    tipo: 'email' | 'signup' = 'email',
  ): Promise<AuthSessionResponse> {
    return this.post<AuthSessionResponse>('/auth/otp-verify', { email, token, tipo });
  }

  /**
   * Registro con correo + contraseña. Si `requiere_confirmacion` viene true,
   * Supabase mandó un código al correo y hay que verificarlo (tipo='signup').
   */
  async authSignup(
    email: string,
    password: string,
    nombre: string,
  ): Promise<AuthSessionResponse> {
    return this.post<AuthSessionResponse>('/auth/signup', { email, password, nombre });
  }

  /**
   * Inicia el OAuth con Google (PKCE). Devuelve la URL de Supabase que el
   * renderer abre en el navegador del SO; al volver, Supabase entrega el
   * `auth_code` por el deep link `todoconta://auth-callback`.
   */
  async authOauthStart(provider: 'google' = 'google'): Promise<{ url: string }> {
    return this.post<{ url: string }>('/auth/oauth/start', { provider });
  }

  /** Canjea el auth_code del deep link por la sesión (la guarda en el agente). */
  async authOauthCallback(code: string): Promise<AuthSessionResponse> {
    return this.post<AuthSessionResponse>('/auth/oauth/callback', { code });
  }

  /** Estado de licencia del usuario actual (cached 24h). */
  async authLicense(refresh = false): Promise<LicenseStatus> {
    const qs = refresh ? '?refresh=true' : '';
    return this.request<LicenseStatus>(`/auth/license${qs}`);
  }

  /** Crea una Stripe Checkout session (Fundador) y devuelve la URL para abrir. */
  async authUpgrade(): Promise<{ url: string; session_id?: string }> {
    return this.post<{ url: string; session_id?: string }>('/auth/upgrade', {});
  }

  /**
   * Checkout de la suscripción anual (tarjeta). El backend elige el precio:
   * 'anual' → regular $2,990 o promo $1,495 si es elegible;
   * 'anual_ia' → $4,990 (founders pagan su precio dedicado).
   */
  async authSubscribe(plan: 'anual' | 'anual_ia' = 'anual'): Promise<AuthSubscribeResponse> {
    return this.post<AuthSubscribeResponse>('/auth/subscribe', { plan });
  }

  /**
   * Planes v3: contratar o cambiar de plan (`{plan, intervalo}`). Sin
   * suscripción v3 el servicio responde la `url` del Checkout de Stripe; con
   * una activa puede cambiar el plan con prorrateo y responder sin `url`.
   * Solo se llama con el interruptor de planes v3 encendido.
   */
  async authSubscribePlan(
    plan: PlanV3Venta,
    intervalo: IntervaloPlan,
  ): Promise<SubscribePlanResponse> {
    return this.post<SubscribePlanResponse>('/auth/subscribe', { plan, intervalo });
  }

  /** Cancela la suscripción al fin del periodo. */
  async authCancelSubscription(): Promise<CancelSubscriptionResponse> {
    return this.post<CancelSubscriptionResponse>('/auth/cancel-subscription', {});
  }

  /**
   * Registra intención de pago por transferencia; devuelve datos bancarios.
   * Sin `plan`, el cuerpo vacío de siempre; con un plan v3 (solo anual), `{plan}`.
   */
  async authTransferIntent(plan?: PlanV3Venta): Promise<TransferIntentResponse> {
    return this.post<TransferIntentResponse>('/auth/transfer-intent', plan ? { plan } : {});
  }

  /** Cierra sesión local (borra keyring + cache). */
  async authLogout(): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>('/auth/logout', {});
  }

  /**
   * Carga la FIEL de la empresa activa en sesión del agente.
   *
   * Antes lo hacía el lifespan del agente al arranque, pero en Windows con
   * binario sin firma el `keyring.get_password()` quedaba bloqueado y el
   * agente nunca aceptaba conexiones. Ahora el renderer lo invoca post-login.
   * Es idempotente y nunca falla (los errores devuelven `ok=false`).
   */
  async autocargarFiel(): Promise<{
    ok: boolean;
    cargada: boolean;
    rfc: string | null;
    error?: string;
  }> {
    return this.post('/auth/autocargar-fiel', {});
  }

  // -----------------------------------------------------------------------
  // Listas negras del SAT (Art. 69 y 69-B)
  // -----------------------------------------------------------------------

  /** Consulta ad-hoc de RFCs. No persiste en SQLite. */
  async listasNegrasConsultar(rfcs: string[]): Promise<ListasNegrasConsultarResponse> {
    return this.post<ListasNegrasConsultarResponse>('/listas-negras/consultar', { rfcs });
  }

  /** Cuándo se actualizaron las listas en el origen (cron mensual del día 5). */
  async listasNegrasMetadata(): Promise<ListasNegrasMetadata> {
    return this.request<ListasNegrasMetadata>('/listas-negras/metadata');
  }

  /** Valida los RFCs del buffer de la empresa y persiste el resultado por fila. */
  async procesadorValidarListasNegras(
    rfc: string,
    opts: { uuids?: string[]; force_refresh?: boolean } = {},
  ): Promise<ProcesadorValidarListasNegrasResponse> {
    return this.post<ProcesadorValidarListasNegrasResponse>(
      '/procesador/cfdi/validar-listas-negras',
      {
        rfc,
        uuids: opts.uuids ?? null,
        force_refresh: opts.force_refresh ?? false,
      },
    );
  }

  /** KPIs (EFOS / EDOS / Aclarado / 69 / Limpios / Sin validar) sobre el buffer filtrado. */
  async procesadorListasNegrasStats(
    rfc: string,
    filtros?: Partial<CfdiFiltros>,
  ): Promise<ProcesadorListasNegrasStats> {
    const qs = _filtrosToQuery({ ...(filtros ?? {}), rfc });
    return this.request<ProcesadorListasNegrasStats>(
      `/procesador/cfdi/listas-negras/stats?${qs}`,
    );
  }

  /** Una fila por emisor_rfc (no por CFDI) con SUM(total) + COUNT, ordenada por total desc. */
  async procesadorListasNegrasPorEmisor(
    rfc: string,
    filtros?: Partial<CfdiFiltros>,
    page = 1,
    pageSize = 50,
  ): Promise<EmisoresListasNegrasResponse> {
    const qs = _filtrosToQuery({ ...(filtros ?? {}), rfc, page, page_size: pageSize });
    return this.request<EmisoresListasNegrasResponse>(
      `/procesador/cfdi/listas-negras/por-emisor?${qs}`,
    );
  }

  // -----------------------------------------------------------------------
  // Calculadoras fiscales y laborales
  // -----------------------------------------------------------------------

  /**
   * Calcula una calculadora. Si el body lleva `rfc`, el agente auto-guarda
   * el estado (inputs + resultado) para esa empresa en el mismo round-trip.
   */
  async calculadoraCalcular<N extends CalculadoraNombre>(
    nombre: N,
    body: CalculadoraRequestMap[N],
  ): Promise<CalculoResponse<CalculadoraResultadoMap[N]>> {
    return this.post<CalculoResponse<CalculadoraResultadoMap[N]>>(
      `/calculadoras/${nombre}`,
      body as unknown as Record<string, unknown>,
    );
  }

  /** Estado completo de la empresa: último estado por calculadora + guardados. */
  async calculadoraEstado(rfc: string): Promise<CalculadorasEstadoResponse> {
    return this.request<CalculadorasEstadoResponse>(
      `/calculadoras/estado/${encodeURIComponent(rfc)}`,
    );
  }

  /** Último estado (inputs + resultado) de una calculadora, o null si no hay. */
  async calculadoraEstadoDe(
    rfc: string,
    calculadora: CalculadoraNombre,
  ): Promise<CalculadoraEstadoResponse> {
    return this.request<CalculadoraEstadoResponse>(
      `/calculadoras/estado/${encodeURIComponent(rfc)}/${calculadora}`,
    );
  }

  /** Guarda un snapshot con nombre (botón "Guardar cálculo"). */
  async calculadoraGuardar(
    rfc: string,
    body: CalculadoraGuardadoRequest,
  ): Promise<{ ok: boolean; guardado: CalculadoraGuardado }> {
    return this.post<{ ok: boolean; guardado: CalculadoraGuardado }>(
      `/calculadoras/guardados/${encodeURIComponent(rfc)}`,
      body as unknown as Record<string, unknown>,
    );
  }

  /** Elimina un cálculo guardado por id. */
  async calculadoraEliminarGuardado(rfc: string, id: string): Promise<{ ok: boolean }> {
    return this.del<{ ok: boolean }>(
      `/calculadoras/guardados/${encodeURIComponent(rfc)}/${encodeURIComponent(id)}`,
    );
  }

  /** Indicadores del ejercicio (UMA, SMG, ISN por estado, clases de riesgo, ...). */
  async calculadoraIndicadores(anio: number): Promise<IndicadoresCalculadoras> {
    return this.request<IndicadoresCalculadoras>(`/calculadoras/indicadores/${anio}`);
  }

  /**
   * Exporta un cálculo (recalcula server-side desde los inputs).
   * Premium: el gating vive en la UI (`license.premium_features_unlocked`).
   */
  async calculadoraExportar(
    formato: 'xlsx' | 'pdf' | 'recibos-ptu',
    calculadora: CalculadoraNombre,
    inputs: Record<string, unknown>,
    rfc?: string | null,
  ): Promise<Blob> {
    const r = await fetch(this.url(`/calculadoras/exportar/${formato}`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...this.tokenHeaders() },
      body: JSON.stringify({ calculadora, inputs, rfc: rfc ?? null }),
    });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`Error al exportar: ${r.status} ${text}`);
    }
    return await r.blob();
  }

  // -----------------------------------------------------------------------
  // DIOT 2025 (carga masiva)
  // -----------------------------------------------------------------------
  //
  // Estado editable por empresa Y periodo (YYYY-MM). El prellenado lee el
  // buffer del procesador; los XMLs entran por `procesadorCargar`.

  /** Estado guardado del periodo (filas + validaciones server-side). */
  async diotEstado(rfc: string, periodo: string): Promise<EstadoDiot> {
    const qs = new URLSearchParams({ rfc, periodo });
    return this.request<EstadoDiot>(`/diot/estado?${qs}`);
  }

  /** Guarda la tabla completa del periodo (full-replace). */
  async diotGuardar(rfc: string, periodo: string, filas: FilaDiot[]): Promise<EstadoDiot> {
    return this.request<EstadoDiot>('/diot/estado', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rfc, periodo, filas }),
    });
  }

  /** Prellena desde el buffer del procesador (conserva renglones manuales). */
  async diotPrellenar(rfc: string, periodo: string): Promise<EstadoDiot> {
    return this.post<EstadoDiot>('/diot/prellenar', { rfc, periodo });
  }

  /** Catálogos oficiales (tipo de tercero/operación, países, campos). */
  async diotCatalogos(): Promise<CatalogosDiot> {
    return this.request<CatalogosDiot>('/diot/catalogos');
  }

  /**
   * Descarga el TXT de carga masiva del periodo como Blob.
   * Premium: el gating vive en la UI (`license.premium_features_unlocked`).
   */
  async diotExportar(rfc: string, periodo: string): Promise<Blob> {
    const qs = new URLSearchParams({ rfc, periodo });
    const r = await fetch(this.url(`/diot/exportar?${qs}`), { headers: this.tokenHeaders() });
    if (!r.ok) {
      const text = await r.text();
      throw new Error(`Error al exportar: ${r.status} ${text}`);
    }
    return await r.blob();
  }

  // -----------------------------------------------------------------------
  // API keys de la cuenta (gestión + conexión MCP)
  // -----------------------------------------------------------------------
  // El agente proxya a la API de servicios con el Bearer de la sesión; el
  // renderer nunca ve el token. Aplica en desktop y en web por igual.

  /** Lista las API keys del usuario (activas y revocadas, recientes primero). */
  async listApiKeys(): Promise<ListApiKeysResponse> {
    return this.request<ListApiKeysResponse>('/cuenta/api-keys');
  }

  /** Emite una API key nueva. La key completa viaja UNA sola vez en la respuesta. */
  async createApiKey(nombre: string): Promise<CreateApiKeyResponse> {
    return this.post<CreateApiKeyResponse>('/cuenta/api-keys', { nombre });
  }

  /** Revoca una API key por id (los sistemas que la usen dejan de funcionar). */
  async revokeApiKey(id: string): Promise<{ ok: boolean }> {
    return this.del<{ ok: boolean }>(`/cuenta/api-keys?id=${encodeURIComponent(id)}`);
  }

  // -----------------------------------------------------------------------
  // Equipo (despachos/empresarial) — proxy a /api/desktop/teams/*
  // -----------------------------------------------------------------------

  /** Equipo del usuario + miembros + isAdmin (o `{team: null}` si no tiene equipo). */
  async getTeam(): Promise<TeamResponse> {
    return this.request<TeamResponse>('/cuenta/teams');
  }

  /** Empresas del equipo (con id de Supabase) para el allow-list de permisos. */
  async getTeamEmpresas(): Promise<TeamEmpresasResponse> {
    return this.request<TeamEmpresasResponse>('/cuenta/teams/empresas');
  }

  /** Invita a un miembro por correo (solo admin). */
  async inviteTeamMember(email: string): Promise<InviteMemberResponse> {
    return this.post<InviteMemberResponse>('/cuenta/teams/members', { email });
  }

  /** Remueve a un miembro del equipo (solo admin). */
  async removeTeamMember(memberId: string): Promise<{ ok: boolean }> {
    return this.request<{ ok: boolean }>('/cuenta/teams/members', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ member_id: memberId }),
    });
  }

  /** El usuario sale de su equipo (el admin no puede: debe cancelar su suscripción). */
  async leaveTeam(): Promise<{ ok: boolean }> {
    return this.post<{ ok: boolean }>('/cuenta/teams/leave');
  }

  /** Ajusta el modo de acceso + allow-list de empresas de un miembro (solo admin). */
  async setTeamMemberPermissions(
    memberId: string,
    accessMode: TeamAccessMode,
    empresaIds: string[],
  ): Promise<{ ok: boolean; access_mode: TeamAccessMode; empresa_ids: string[] }> {
    return this.patch('/cuenta/teams/members/permissions', {
      member_id: memberId,
      access_mode: accessMode,
      empresa_ids: empresaIds,
    });
  }
}

// ---------------------------------------------------------------------------
// Tipos de auth + license
// ---------------------------------------------------------------------------

export interface AuthInitResponse {
  device_code: string;
  expires_at: string;
  activate_url: string;
}

/** Respuesta de login-password / otp-verify / signup (auth en-app). */
export interface AuthSessionResponse {
  ok: boolean;
  user?: { id: string; email: string | null };
  requiere_confirmacion?: boolean;
}

export type AuthPollStatus = 'ok' | 'pending' | 'expired' | 'not_found';

export interface AuthPollResponse {
  status: AuthPollStatus;
  user?: { id: string; email: string | null };
}

export type DesktopPlan = 'founder' | 'premium' | 'trial' | 'free';

/**
 * Plan v3 resuelto por el backend (F0 de docs/operacion/plan-app-v3.md en
 * todoconta-apps). Incluye los legados para que la UI los nombre sin adivinar.
 */
export type PlanCodigo =
  | 'esencial'
  | 'pro'
  | 'completo'
  | 'medida'
  | 'trial'
  | 'gratis'
  | 'desktop'
  | 'desktop_ia'
  | 'fundador'
  | 'profesional'
  | 'despachos'
  | 'empresarial'
  | 'legado';

/** Topes del plan. `null` = sin tope. */
export interface LimitesPlan {
  empresas: number | null;
  usuarios: number | null;
}

export interface CapacidadesPlan {
  web: boolean;
  exportar: boolean;
  mcp: boolean;
  abacus: boolean;
  api: boolean;
  /** Piloto automático (F7). */
  piloto: boolean;
  /** Vigilancia (F8): en la app y por correo, y por WhatsApp. */
  vigilancia: { app_correo: boolean; whatsapp: boolean };
  /** Reporte mensual para el cliente con logo (F9b). */
  reporte_cliente: boolean;
}

export interface LicenseStatus {
  authenticated: boolean;
  user_id?: string;
  email?: string | null;

  // Plan derivado + cuenta regresiva (pueden faltar en fallback offline sin cache).
  plan?: DesktopPlan;
  days_remaining?: number | null;
  expires_at?: string | null;
  subscription_cancel_at_period_end?: boolean;

  // Promo anual del 50% (bloqueado de por vida).
  promo_active?: boolean;
  promo_ends_at?: string | null;
  promo_price_mxn?: number;
  regular_price_mxn?: number;
  promo_days?: number;

  // Fundador.
  is_founder?: boolean;
  founder_acquired_at?: string | null;
  founder_window_open?: boolean;
  founder_window_closes_at?: string;
  founder_price_mxn?: number;

  premium_features_unlocked?: boolean;
  ai_credits_balance?: number;

  // Plan anual CON IA (campos aditivos del backend; pueden faltar en versiones viejas).
  ai_features_unlocked?: boolean;
  ia_price_mxn?: number;
  ia_founder_price_mxn?: number;

  // Planes v3 (campos aditivos desde F0). Faltan con un backend viejo, un cache
  // de antes de F0 o el fallback offline sin cache: tratar la ausencia como
  // "sin datos", nunca como candado.
  plan_codigo?: PlanCodigo;
  plan_nombre?: string;
  limites?: LimitesPlan;
  capacidades?: CapacidadesPlan;
  uso?: { empresas_activas: number | null };
  legado?: boolean;
  precio_asegurado_mxn?: number | null;
  // Planes v3, F1 (aditivos; faltan = apagado / sin datos).
  /** Interruptor del Día C: el backend ya cobra y aplica los planes v3. */
  planes_v3_activo?: boolean;
  /** Intervalo de la suscripción v3 vigente; null en legado y sin suscripción. */
  intervalo?: IntervaloPlan | null;
  // Flags del cache local del agente.
  from_cache?: boolean;
  stale?: boolean;
  offline?: boolean;
  reason?: string;
}

/** Planes v3 que se contratan desde la app (A la medida se cotiza aparte). */
export type PlanV3Venta = 'esencial' | 'pro' | 'completo';
export type IntervaloPlan = 'anual' | 'mensual';

export interface SubscribePlanResponse {
  /** Checkout de Stripe para abrir en el navegador (alta nueva). */
  url?: string;
  session_id?: string;
  /** Cambio aplicado sin checkout (suscripción v3 existente, con prorrateo). */
  ok?: boolean;
  plan?: string;
  intervalo?: IntervaloPlan;
  message?: string;
}

/** Cuerpo `tope_empresas` del 402 del agente (ver `topeEmpresasDeError`). */
export interface TopeEmpresas {
  plan_codigo: PlanCodigo | null;
  plan_nombre: string | null;
  tope: number;
  activas: number;
  /** Cuántas exceden el tope (altas en dos equipos sin internet). */
  sobran: number;
  siguiente_plan: { codigo: string; nombre: string; empresas: number | null } | null;
}

export interface AuthSubscribeResponse {
  url: string;
  session_id?: string;
  promo?: boolean;
  plan?: 'anual' | 'anual_ia';
}

export interface CancelSubscriptionResponse {
  ok: boolean;
  cancel_at?: string | null;
  manual?: boolean;
  message?: string;
}

export interface DatosBancarios {
  banco: string;
  clabe: string;
  beneficiario: string;
  referencia: string;
}

export interface TransferIntentResponse {
  ok: boolean;
  amount_mxn: number;
  promo: boolean;
  banco: DatosBancarios;
  message?: string;
}

// ---------------------------------------------------------------------------
// API keys de la cuenta (API pública + MCP)
// ---------------------------------------------------------------------------

export interface ApiKey {
  id: string;
  nombre: string;
  prefijo: string;
  scopes: string[];
  creada_en: string;
  ultima_vez_usada: string | null;
  revocada_en: string | null;
}

export interface ListApiKeysResponse {
  keys: ApiKey[];
}

/** Respuesta al emitir una key: `key` es el secreto completo (se ve UNA vez). */
export interface CreateApiKeyResponse {
  key: string;
  prefijo: string;
  nombre: string;
  scopes: string[];
}

// ---------------------------------------------------------------------------
// Equipo (despachos/empresarial)
// ---------------------------------------------------------------------------

export type TeamAccessMode = 'all' | 'restricted';

export interface TeamMember {
  id: string;
  email: string;
  role: 'admin' | 'member';
  status: 'pending' | 'active' | 'removed';
  invited_at: string;
  accepted_at: string | null;
  access_mode: TeamAccessMode;
  /** IDs (Supabase) de las empresas del equipo a las que tiene acceso restringido. */
  empresa_ids: string[];
}

export interface Team {
  id: string;
  name: string;
  max_members: number;
  admin_user_id: string;
}

export interface TeamAdmin {
  email: string | null;
  full_name: string | null;
  subscription_plan: string | null;
  subscription_status: string | null;
}

export interface TeamResponse {
  team: Team | null;
  members: TeamMember[];
  isAdmin?: boolean;
  admin?: TeamAdmin | null;
}

/** Empresa del equipo (del lado Supabase, con su `id` UUID) para el allow-list. */
export interface TeamEmpresa {
  id: string;
  rfc: string;
  nombre: string | null;
  archived_at: string | null;
}

export interface TeamEmpresasResponse {
  empresas: TeamEmpresa[];
}

export interface InviteMemberResponse {
  ok: boolean;
  /** true si el invitado ya tenía cuenta → quedó activo de inmediato. */
  autoActivated?: boolean;
}


function _filtrosToQuery(filtros: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filtros)) {
    if (value === null || value === undefined || value === '') continue;
    if (typeof value === 'boolean') {
      if (value) params.set(key, 'true');
      continue;
    }
    params.set(key, String(value));
  }
  return params.toString();
}

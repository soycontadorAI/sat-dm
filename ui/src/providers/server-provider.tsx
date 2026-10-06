'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { SatApiClient } from '@/lib/api-client';
import { getAgentBaseUrl } from '@/lib/constants';
import { esWeb } from '@/lib/modo';
import {
  clearConexion,
  getConexion,
  setConexion,
  type ConexionAgente,
} from '@/lib/conexion-web';
import { useServerHealth } from '@/hooks/use-server-health';
import type { NavegadorStatus } from '@/lib/types';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface FielStatus {
  loaded: boolean;
  rfc: string | null;
  numeroSerie: string | null;
  /** Vencimiento de la e.firma en sesión ("YYYY-MM-DD") o null. */
  vencimiento: string | null;
}

interface ServerContextValue {
  /** Typed API client instance (stable reference). */
  apiClient: SatApiClient;

  /** Whether the Python server at localhost:8787 is reachable. */
  isConnected: boolean;

  /** Current e-firma status from the server. */
  fielStatus: FielStatus;

  /** Estado del navegador del portal (instalando/listo/error) o null. */
  navegador: NavegadorStatus | null;

  /**
   * El agente corre en modo de grabación (tutoriales con datos de demo): sin
   * banners de venta, sin cuenta regresiva de la prueba ni recordatorios. No
   * se anuncia en pantalla.
   */
  modoGrabacion: boolean;

  /**
   * (Versión web) True mientras el navegador NO conoce su agente: aún no hay
   * conexión guardada (primer uso o desconexión). En desktop siempre false.
   */
  webSinConexion: boolean;

  /** (Versión web) Guarda la conexión con el agente del usuario y reconecta. */
  conectar: (conexion: ConexionAgente) => void;

  /** (Versión web) Olvida la conexión guardada (soporte / cambio de cuenta). */
  desconectar: () => void;

  /** Upload the FIEL (.cer + .key + password) to the local server. */
  cargarFiel: (
    cerFile: File,
    keyFile: File,
    password: string,
  ) => Promise<{ rfc: string; numeroSerie: string }>;

  /** Unload the FIEL from server memory. */
  descargarFiel: () => Promise<void>;

  /** Force an immediate health check (e.g. after cargar/descargar fiel). */
  refreshHealth: () => void;
}

const ServerContext = createContext<ServerContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface ServerProviderProps {
  children: ReactNode;
  /** Override the base URL for the Python server. */
  baseUrl?: string;
}

export function ServerProvider({ children, baseUrl }: ServerProviderProps) {
  // (Versión web) La conexión con el agente del usuario vive en localStorage;
  // se hidrata en un efecto (no en el initializer) para que el primer render
  // coincida con el prerender estático y no haya hydration mismatch.
  const [conexionWeb, setConexionWebState] = useState<ConexionAgente | null>(null);
  const [webHidratado, setWebHidratado] = useState(false);
  useEffect(() => {
    if (esWeb()) setConexionWebState(getConexion());
    setWebHidratado(true);
  }, []);

  const conectar = useCallback((conexion: ConexionAgente) => {
    setConexion(conexion);
    setConexionWebState({ ...conexion, baseUrl: conexion.baseUrl.replace(/\/+$/, '') });
  }, []);

  const desconectar = useCallback(() => {
    clearConexion();
    setConexionWebState(null);
  }, []);

  // En Electron el agente corre en un puerto efímero que el preload inyecta en
  // window.satAgent.baseUrl; en la web viene de la conexión guardada; en dev
  // cae a API_BASE_URL (localhost:8787).
  const resolvedBaseUrl = baseUrl ?? conexionWeb?.baseUrl ?? getAgentBaseUrl();
  const apiClient = useMemo(() => new SatApiClient(resolvedBaseUrl), [resolvedBaseUrl]);

  // Sin conexión en la web no hay a quién pollear: el health check se apaga
  // hasta que el login (o /conectar) entregue el agente del usuario.
  const webSinConexion = esWeb() && webHidratado && !conexionWeb && !baseUrl;

  const {
    isConnected,
    rfcCargado,
    efirmaLista,
    efirmaVencimiento,
    navegador,
    modoGrabacion,
    refresh: refreshHealth,
  } = useServerHealth(apiClient, undefined, { enabled: !webSinConexion });

  // Track numero_serie separately — the /health endpoint does not return it,
  // so we store it when cargarFiel succeeds and clear it on descargarFiel.
  const numeroSerieRef = useRef<string | null>(null);

  const fielStatus: FielStatus = useMemo(
    () => ({
      loaded: efirmaLista,
      rfc: rfcCargado,
      numeroSerie: efirmaLista ? numeroSerieRef.current : null,
      vencimiento: efirmaLista ? efirmaVencimiento : null,
    }),
    [efirmaLista, rfcCargado, efirmaVencimiento],
  );

  const cargarFiel = useCallback(
    async (cerFile: File, keyFile: File, password: string) => {
      const res = await apiClient.cargarFiel(cerFile, keyFile, password);
      numeroSerieRef.current = res.numero_serie;
      // Trigger an immediate health refresh so isConnected/fielStatus update
      refreshHealth();
      return { rfc: res.rfc, numeroSerie: res.numero_serie };
    },
    [apiClient, refreshHealth],
  );

  const descargarFiel = useCallback(async () => {
    await apiClient.descargarFiel();
    numeroSerieRef.current = null;
    refreshHealth();
  }, [apiClient, refreshHealth]);

  const value: ServerContextValue = useMemo(
    () => ({
      apiClient,
      isConnected,
      fielStatus,
      navegador,
      modoGrabacion,
      webSinConexion,
      conectar,
      desconectar,
      cargarFiel,
      descargarFiel,
      refreshHealth,
    }),
    [
      apiClient,
      isConnected,
      fielStatus,
      navegador,
      modoGrabacion,
      webSinConexion,
      conectar,
      desconectar,
      cargarFiel,
      descargarFiel,
      refreshHealth,
    ],
  );

  return (
    <ServerContext.Provider value={value}>{children}</ServerContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Access the server connection state and API client.
 *
 * Must be used inside `<ServerProvider>`.
 */
export function useServer(): ServerContextValue {
  const ctx = useContext(ServerContext);
  if (!ctx) {
    throw new Error('useServer must be used within a <ServerProvider>');
  }
  return ctx;
}

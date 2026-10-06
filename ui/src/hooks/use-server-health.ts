'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import type { SatApiClient } from '@/lib/api-client';
import type { NavegadorStatus } from '@/lib/types';
import { HEALTH_POLL_INTERVAL_MS } from '@/lib/constants';

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

interface ServerHealthState {
  /** Whether the last health check succeeded. */
  isConnected: boolean;
  /** RFC loaded on the server (null if no FIEL is loaded). */
  rfcCargado: string | null;
  /** Whether the server has a FIEL loaded and ready. */
  efirmaLista: boolean;
  /** Vencimiento de la e.firma en sesión ("YYYY-MM-DD") o null. */
  efirmaVencimiento: string | null;
  /** Estado del navegador del portal (instalando/listo/error) o null. */
  navegador: NavegadorStatus | null;
  /** El agente corre en modo de grabación (ver HealthResponse.modo_grabacion). */
  modoGrabacion: boolean;
  /** Manually trigger an immediate health check. */
  refresh: () => void;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

/**
 * Polls the Python server's /health endpoint at a fixed interval.
 *
 * - On success: sets `isConnected = true` and extracts `rfc_cargado` /
 *   `efirma_lista` from the response.
 * - On failure (network error, server down): sets `isConnected = false`.
 * - Cleans up the interval on unmount.
 *
 * @param apiClient - A `SatApiClient` instance (should be a stable reference).
 * @param intervalMs - Polling interval in milliseconds (default 5 000).
 * @param opts.enabled - Con `false` no se hace ningún check (p. ej. la versión
 *   web antes de conocer el agente del usuario) y `isConnected` queda en false.
 */
export function useServerHealth(
  apiClient: SatApiClient,
  intervalMs: number = HEALTH_POLL_INTERVAL_MS,
  opts: { enabled?: boolean } = {},
): ServerHealthState {
  const enabled = opts.enabled ?? true;
  const [isConnected, setIsConnected] = useState(false);
  const [rfcCargado, setRfcCargado] = useState<string | null>(null);
  const [efirmaLista, setEfirmaLista] = useState(false);
  const [efirmaVencimiento, setEfirmaVencimiento] = useState<string | null>(null);
  const [navegador, setNavegador] = useState<NavegadorStatus | null>(null);
  const [modoGrabacion, setModoGrabacion] = useState(false);

  // Ref to track whether we should still process the result (component mounted).
  const mountedRef = useRef(true);

  // Evita encimar checks: si el agente tarda más que el intervalo (equipo o
  // red lentos), los requests pendientes se acumulaban sin tope.
  const checkingRef = useRef(false);

  // Counter to force an immediate check (bumped by `refresh()`).
  const [refreshCounter, setRefreshCounter] = useState(0);

  const checkHealth = useCallback(async () => {
    if (!enabled || checkingRef.current) return;
    checkingRef.current = true;
    try {
      const data = await apiClient.health();
      if (!mountedRef.current) return;

      setIsConnected(true);
      setRfcCargado(data.rfc_cargado);
      setEfirmaLista(data.efirma_lista);
      setEfirmaVencimiento(data.efirma_vencimiento ?? null);
      setNavegador(data.navegador ?? null);
      setModoGrabacion(data.modo_grabacion === true);
    } catch {
      if (!mountedRef.current) return;

      setIsConnected(false);
      setRfcCargado(null);
      setEfirmaLista(false);
      setEfirmaVencimiento(null);
      setNavegador(null);
    } finally {
      checkingRef.current = false;
    }
  }, [apiClient, enabled]);

  // Run on mount and whenever refreshCounter changes (manual refresh).
  useEffect(() => {
    checkHealth();
  }, [checkHealth, refreshCounter]);

  // Periodic polling. Con la ventana oculta (minimizada / en background) no
  // tiene caso pollear — se salta el tick y, al volver a ser visible, se
  // dispara un check inmediato para que el badge no muestre estado viejo.
  useEffect(() => {
    mountedRef.current = true;

    const tick = () => {
      if (document.hidden) return;
      checkHealth();
    };
    const id = setInterval(tick, intervalMs);

    const onVisibilityChange = () => {
      if (!document.hidden) checkHealth();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);

    return () => {
      mountedRef.current = false;
      clearInterval(id);
      document.removeEventListener('visibilitychange', onVisibilityChange);
    };
  }, [checkHealth, intervalMs]);

  const refresh = useCallback(() => {
    setRefreshCounter((c) => c + 1);
  }, []);

  return {
    isConnected,
    rfcCargado,
    efirmaLista,
    efirmaVencimiento,
    navegador,
    modoGrabacion,
    refresh,
  };
}

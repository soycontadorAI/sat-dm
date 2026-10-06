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

import { useServer } from '@/providers/server-provider';
import { identificarUsuario } from '@/lib/telemetria';
import { PLANES_V3 } from '@/lib/features';
import type {
  CapacidadesPlan,
  LicenseStatus,
  LimitesPlan,
  PlanCodigo,
} from '@/lib/api-client';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface AuthContextValue {
  /** Estado actual de licencia del usuario. null mientras carga inicial. */
  license: LicenseStatus | null;
  /** True si nunca se ha cargado el estado todavía. */
  loading: boolean;
  /** Re-fetch del backend (force_refresh). Lo llaman botones de "refrescar". */
  refresh: () => Promise<void>;
  /** Logout — limpia keyring y vuelve a la pantalla de login. */
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

/**
 * AuthProvider — fuente de verdad del estado de autenticación + licencia.
 *
 * - Carga el estado al montar con cache (render instantáneo, sin red) y luego
 *   reconcilia en background con un force-refresh (corrige banners/badges si el
 *   estado cambió en el servidor: ventana de fundadores cerrada, promo activa,
 *   suscripción, etc.) sin bloquear ni mostrar spinner.
 * - Re-fetch automático cada 6h con force (ignora el cache de 24h del agente)
 *   para que sesiones largas no queden desactualizadas.
 * - Expone `refresh()` para invalidar manualmente y `logout()`.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const { apiClient, isConnected, webSinConexion } = useServer();
  const [license, setLicense] = useState<LicenseStatus | null>(null);
  const [loading, setLoading] = useState(true);

  // Versión web sin conexión con su agente: no hay a quién preguntarle la
  // licencia — se trata como "no autenticado" para que el shell muestre el
  // login (que en la web pasa por el provisioner) en vez de un loader eterno.
  useEffect(() => {
    if (!webSinConexion) return;
    setLicense({ authenticated: false });
    setLoading(false);
  }, [webSinConexion]);
  // ID monotónico de la última petición iniciada. Como puede haber varios
  // fetches en vuelo (startup cache+force, intervalo 6h, refresh manual, o una
  // reconexión que recrea el apiClient con otro puerto), solo aplicamos la
  // respuesta del más reciente — así un resultado viejo nunca pisa al nuevo.
  const latestRequest = useRef(0);

  const fetchLicense = useCallback(
    async (force = false) => {
      const requestId = ++latestRequest.current;
      const sigueVigente = () => requestId === latestRequest.current;
      try {
        const data = await apiClient.authLicense(force);
        if (!sigueVigente()) return; // llegó tarde: ya ganó una petición más nueva
        setLicense(data);
        // Identifica al usuario en Sentry (o lo desliga si no hay sesión) para
        // que los reportes traigan quién es. Idempotente entre re-fetches.
        identificarUsuario(
          data.authenticated ? { id: data.user_id, email: data.email } : null,
        );
        // Disparar autocarga de FIEL en background si el usuario está
        // autenticado. Antes lo hacía el lifespan del agente, pero bloqueaba
        // el startup en Windows (keyring sin prompt UI). Ahora es lazy y no
        // bloquea — si falla, la app sigue funcional y el usuario carga la
        // FIEL a mano desde Empresas.
        if (data.authenticated) {
          apiClient.autocargarFiel().catch((e) => {
            console.warn('[auth] autocargarFiel falló (no bloqueante):', e);
          });
        }
      } catch (e) {
        console.warn('[auth] authLicense falló:', e);
        // Mantenemos el estado previo si lo había; si no, marcamos no-auth.
        if (sigueVigente()) setLicense((prev) => prev ?? { authenticated: false });
      } finally {
        setLoading(false);
      }
    },
    [apiClient],
  );

  // Carga inicial: cache primero (render instantáneo) y luego un force-refresh
  // en background para reconciliar con el servidor. El force no vuelve a poner
  // `loading=true` (solo se apaga en el finally), así que el shell no parpadea;
  // si el estado cambió (p. ej. ventana de fundadores cerrada), los banners se
  // corrigen solos en cuanto llega la respuesta. Offline-safe: el agente cae a
  // su cache si no hay red.
  useEffect(() => {
    if (!isConnected) return;
    void fetchLicense(false).then(() => fetchLicense(true));
  }, [isConnected, fetchLicense]);

  // Re-fetch cada 6h con force: ignora el cache de 24h del agente para que una
  // sesión abierta por días refleje cambios del servidor a tiempo.
  useEffect(() => {
    if (!isConnected) return;
    const interval = setInterval(() => {
      fetchLicense(true);
    }, 6 * 60 * 60 * 1000);
    return () => clearInterval(interval);
  }, [isConnected, fetchLicense]);

  const refresh = useCallback(() => fetchLicense(true), [fetchLicense]);

  const logout = useCallback(async () => {
    try {
      await apiClient.authLogout();
    } catch (e) {
      console.warn('[auth] logout falló:', e);
    }
    setLicense({ authenticated: false });
    setLoading(false);
    identificarUsuario(null); // desliga al usuario de los próximos reportes
  }, [apiClient]);

  const value = useMemo<AuthContextValue>(
    () => ({ license, loading, refresh, logout }),
    [license, loading, refresh, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth debe usarse dentro de <AuthProvider>');
  }
  return ctx;
}

/**
 * `useRequireAuth` — devuelve la license cuando ya hay sesión; antes de eso,
 * permite a las páginas mostrar un loader.
 */
export function useRequireAuth(): {
  ready: boolean;
  authenticated: boolean;
  license: LicenseStatus | null;
} {
  const { license, loading } = useAuth();
  if (loading || license === null) {
    return { ready: false, authenticated: false, license: null };
  }
  return {
    ready: true,
    authenticated: license.authenticated === true,
    license,
  };
}

/** Plan v3 de la licencia (F0). Ver `usePlanLicencia`. */
export interface PlanLicencia {
  codigo: PlanCodigo;
  nombre: string;
  limites: LimitesPlan;
  capacidades: CapacidadesPlan;
  empresasActivas: number | null;
  legado: boolean;
  precioAseguradoMxn: number | null;
}

/**
 * Plan, topes y capacidades de la licencia (campos aditivos desde F0).
 *
 * Devuelve `null` mientras no hay licencia o cuando el backend/cache no los
 * trae (versión vieja, offline sin cache). Quien gatee algo con esto debe
 * tratar `null` como "sin datos" y NO poner candado; lo de hoy sigue saliendo
 * de `premium_features_unlocked` y `ai_features_unlocked`.
 */
export function usePlanLicencia(): PlanLicencia | null {
  const { license } = useAuth();
  return useMemo(() => {
    if (
      !license?.authenticated ||
      !license.plan_codigo ||
      !license.limites ||
      !license.capacidades
    ) {
      return null;
    }
    return {
      codigo: license.plan_codigo,
      nombre: license.plan_nombre ?? license.plan_codigo,
      limites: license.limites,
      capacidades: license.capacidades,
      empresasActivas: license.uso?.empresas_activas ?? null,
      legado: license.legado === true,
      precioAseguradoMxn: license.precio_asegurado_mxn ?? null,
    };
  }, [license]);
}

/**
 * Interruptor de los planes v3 (F1): el flag `PLANES_V3` (para probar antes de
 * tiempo) O la licencia diciendo que el backend ya los activó
 * (`planes_v3_activo`, Día C). Sin el campo = apagado: la app se ve como hoy.
 */
export function usePlanesV3(): boolean {
  const { license } = useAuth();
  return PLANES_V3 || license?.planes_v3_activo === true;
}

'use client';

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import {
  NAV_ESPACIOS,
  NAV_ESPACIOS_DEFAULT_DESDE,
  NAV_ESPACIOS_PARA_TODOS,
} from '@/lib/features';
import {
  LLAVE_DEFAULT_RECORDADO,
  LLAVE_LABS,
  LLAVE_PREFERENCIA,
  esModo,
  modoDeLabs,
  resolverModoNavegacion,
  type ModoNavegacion,
  type OrigenModo,
} from '@/lib/navegacion-modo';
import { agregarBreadcrumb } from '@/lib/telemetria';
import { useAuth } from '@/providers/auth-provider';

/** Evento window: otra instancia (Ajustes) cambió la preferencia. */
const EVENTO_CAMBIO = 'tc:navegacion-cambio';

interface NavegacionContextValue {
  modo: ModoNavegacion;
  origen: OrigenModo;
  /** Ya se leyó la preferencia de la instalación (post-mount). */
  listo: boolean;
  /** Preferencia explícita (null = sigue la regla por default). */
  preferencia: ModoNavegacion | null;
  /** Fija la preferencia de la instalación; null la borra (vuelve al default). */
  setPreferencia: (m: ModoNavegacion | null) => void;
  /** El selector de Ajustes > Apariencia > Navegación se muestra. */
  selectorVisible: boolean;
}

const NavegacionContext = createContext<NavegacionContextValue | null>(null);

function leer(llave: string): string | null {
  try {
    return localStorage.getItem(llave);
  } catch {
    return null;
  }
}

function escribir(llave: string, valor: string | null) {
  try {
    if (valor === null) localStorage.removeItem(llave);
    else localStorage.setItem(llave, valor);
  } catch {
    /* sin storage: la preferencia dura la sesión */
  }
}

/**
 * Dueño del modo de navegación (clásica o espacios) de esta instalación. Va
 * dentro de AuthProvider (la regla del 2 de noviembre mira el plan) y arriba
 * del login, para que `?labs=espacios` se capture aunque no haya sesión.
 */
export function NavegacionProvider({ children }: { children: ReactNode }) {
  const { license } = useAuth();
  const [preferencia, setPreferenciaState] = useState<ModoNavegacion | null>(null);
  const [labs, setLabs] = useState(false);
  const [recordado, setRecordado] = useState(false);
  const [listo, setListo] = useState(false);

  // localStorage y la URL solo post-mount (export estático: el primer render
  // del servidor y del cliente deben coincidir).
  useEffect(() => {
    const deLabs = modoDeLabs(window.location.search);
    if (deLabs) {
      escribir(LLAVE_PREFERENCIA, deLabs);
      escribir(LLAVE_LABS, deLabs === 'espacios' ? '1' : null);
      agregarBreadcrumb({ category: 'nav', message: `labs: ${deLabs}` });
    }
    const pref = leer(LLAVE_PREFERENCIA);
    setPreferenciaState(esModo(pref) ? pref : null);
    setLabs(leer(LLAVE_LABS) === '1');
    setRecordado(leer(LLAVE_DEFAULT_RECORDADO) === 'espacios');
    setListo(true);

    const onCambio = () => {
      const p = leer(LLAVE_PREFERENCIA);
      setPreferenciaState(esModo(p) ? p : null);
    };
    window.addEventListener(EVENTO_CAMBIO, onCambio);
    window.addEventListener('storage', onCambio);
    return () => {
      window.removeEventListener(EVENTO_CAMBIO, onCambio);
      window.removeEventListener('storage', onCambio);
    };
  }, []);

  const desde = useMemo(() => new Date(NAV_ESPACIOS_DEFAULT_DESDE), []);
  const enPrueba = license?.plan === 'trial' || license?.plan_codigo === 'trial';
  const deLicencia = (license as { navegacion?: unknown } | null)?.navegacion;

  const { modo, origen } = resolverModoNavegacion({
    disponible: NAV_ESPACIOS,
    preferencia: listo ? preferencia : null,
    licencia: esModo(deLicencia) ? deLicencia : null,
    paraTodos: NAV_ESPACIOS_PARA_TODOS,
    enPrueba: !!license?.authenticated && enPrueba,
    recordado,
    ahora: new Date(),
    desde,
  });

  // Hasta leer la instalación, clásica (el splash cubre esa fracción).
  const modoFinal: ModoNavegacion = listo ? modo : 'clasica';

  // La regla de la prueba se recuerda: al pagar o al terminar la prueba no
  // regresan a la clásica.
  useEffect(() => {
    if (listo && origen === 'prueba' && !recordado) {
      escribir(LLAVE_DEFAULT_RECORDADO, 'espacios');
      setRecordado(true);
    }
  }, [listo, origen, recordado]);

  useEffect(() => {
    if (!listo || !license?.authenticated) return;
    agregarBreadcrumb({
      category: 'nav',
      message: `nav_modo: ${modoFinal}`,
      data: { origen },
    });
  }, [listo, license?.authenticated, modoFinal, origen]);

  const setPreferencia = useCallback((m: ModoNavegacion | null) => {
    escribir(LLAVE_PREFERENCIA, m);
    setPreferenciaState(m);
    agregarBreadcrumb({ category: 'nav', message: `nav_cambio_modo: ${m ?? 'default'}` });
    window.dispatchEvent(new Event(EVENTO_CAMBIO));
  }, []);

  const selectorVisible =
    NAV_ESPACIOS && (labs || preferencia !== null || Date.now() >= desde.getTime());

  const value = useMemo<NavegacionContextValue>(
    () => ({
      modo: modoFinal,
      origen,
      listo,
      preferencia,
      setPreferencia,
      selectorVisible,
    }),
    [modoFinal, origen, listo, preferencia, setPreferencia, selectorVisible],
  );

  return <NavegacionContext.Provider value={value}>{children}</NavegacionContext.Provider>;
}

export function useNavegacion(): NavegacionContextValue {
  const ctx = useContext(NavegacionContext);
  if (!ctx) {
    // Fuera del shell (no debería pasar): la clásica, sin selector.
    return {
      modo: 'clasica',
      origen: 'default',
      listo: false,
      preferencia: null,
      setPreferencia: () => {},
      selectorVisible: false,
    };
  }
  return ctx;
}

/** Atajo: ¿esta instalación ve la navegación por espacios? */
export function useEspacios(): boolean {
  return useNavegacion().modo === 'espacios';
}

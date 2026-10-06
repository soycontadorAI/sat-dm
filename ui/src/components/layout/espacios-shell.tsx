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
import { usePathname, useRouter } from 'next/navigation';

import {
  ESPACIOS,
  destinoDe,
  destinoPorId,
  espacioPorId,
  normalizarRuta,
  type Destino,
  type DestinoUbicado,
  type EspacioId,
} from '@/lib/navegacion';
import { EVENTO_SIDEBAR_TOGGLE } from '@/lib/atajos';
import { nombreCortoEmpresa } from '@/lib/tareas';
import { agregarBreadcrumb } from '@/lib/telemetria';
import { registrarReciente } from '@/hooks/use-recientes';
import { useEmpresas } from '@/hooks/use-empresas';

// ---------------------------------------------------------------------------
// Estado del shell de espacios: qué espacio se ve, si el panel está abierto,
// la última pantalla de cada espacio y el destino "Pronto" abierto (que no
// tiene ruta). Lo consumen el riel, el panel, la barra de título, ⌘K y los
// atajos ⌘1..⌘5 / ⌘B.
// ---------------------------------------------------------------------------

const LLAVE_PANEL = 'tc:panel-espacio';
const LLAVE_ULTIMAS = 'tc:espacio-pantallas';
const LLAVE_ULTIMO = 'tc:espacio-ultimo';

export type ViaNav = 'riel' | 'panel' | 'recientes' | 'buscador' | 'atajo' | 'enlace';

interface EspaciosShellValue {
  /** Espacio del panel (el de la pantalla, o el último que abriste). */
  espacioActivo: EspacioId;
  /**
   * Espacio que se marca en el riel: el de la pantalla (o del "Pronto"
   * abierto). null en Ayuda, Ajustes, Suscripción y Planes, que no viven en
   * ningún espacio.
   */
  espacioMarcado: EspacioId | null;
  /** Destino de la ruta actual (o el Pronto abierto). */
  destinoActivo: DestinoUbicado | null;
  /** Destino Próximamente abierto (sin ruta); null si se ve una pantalla real. */
  pronto: DestinoUbicado | null;
  panelAbierto: boolean;
  togglePanel: () => void;
  /** Riel o ⌘1..⌘5: última pantalla del espacio (o su primer destino). */
  irAEspacio: (id: EspacioId, via: ViaNav) => void;
  /** Navega a una ruta (cierra el Pronto abierto). */
  navegar: (href: string, via: ViaNav) => void;
  /** Abre un destino: su ruta, o la pantalla Próximamente si no tiene. */
  abrirDestino: (d: Destino, via: ViaNav) => void;
}

const EspaciosShellContext = createContext<EspaciosShellValue | null>(null);

function leerJson<T>(llave: string, def: T): T {
  try {
    const raw = localStorage.getItem(llave);
    return raw ? (JSON.parse(raw) as T) : def;
  } catch {
    return def;
  }
}

function escribir(llave: string, valor: unknown) {
  try {
    localStorage.setItem(llave, typeof valor === 'string' ? valor : JSON.stringify(valor));
  } catch {
    /* sin storage */
  }
}

/** Parámetros de un solo uso que no se recuerdan como "última pantalla". */
const PARAMS_TRANSITORIOS = ['abrir', 'alta', 'bajar', 'rfc'];

function rutaParaRecordar(pathname: string, search: string): string {
  const p = normalizarRuta(pathname);
  if (!search || p === '/empresas') return p;
  const params = new URLSearchParams(search);
  if (p !== '/empresas/detalle') PARAMS_TRANSITORIOS.forEach((k) => params.delete(k));
  const qs = params.toString();
  return qs ? `${p}?${qs}` : p;
}

/** Destinos que trabajan sobre la empresa activa (su reciente lleva el nombre). */
function esPorEmpresa(u: DestinoUbicado): boolean {
  const esp = u.espacio?.id;
  return esp === 'sat' || esp === 'revisar' || esp === 'cumplimiento' || u.destino.id.startsWith('calc-');
}

function primerDestinoConRuta(id: EspacioId): string {
  const esp = espacioPorId(id);
  return esp.destinos.find((d) => d.href && !d.href.includes('?'))?.href ?? '/';
}

export function EspaciosShellProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname() ?? '/';
  const router = useRouter();
  const { empresas } = useEmpresas();

  const [panelAbierto, setPanelAbierto] = useState(true);
  const [ultimas, setUltimas] = useState<Partial<Record<EspacioId, string>>>({});
  const [ultimoEspacio, setUltimoEspacio] = useState<EspacioId>('despacho');
  const [prontoId, setProntoId] = useState<string | null>(null);

  useEffect(() => {
    setPanelAbierto(leerJson<string>(LLAVE_PANEL, '1') !== '0');
    setUltimas(leerJson(LLAVE_ULTIMAS, {}));
    const u = leerJson<string>(LLAVE_ULTIMO, 'despacho');
    if (ESPACIOS.some((e) => e.id === u)) setUltimoEspacio(u as EspacioId);
  }, []);

  const activa = useMemo(() => {
    const activas = empresas.filter((e) => !e.archived_at);
    return activas.find((e) => e.default) ?? activas[0] ?? null;
  }, [empresas]);
  const activaRef = useRef(activa);
  activaRef.current = activa;

  const destinoRuta = useMemo(() => destinoDe(pathname), [pathname]);

  // Cambio de ruta: cierra el Pronto, recuerda la pantalla del espacio y la
  // anota en Recientes.
  useEffect(() => {
    setProntoId(null);
    const u = destinoDe(pathname);
    if (!u?.espacio) return;
    const esp = u.espacio.id;
    const ruta = rutaParaRecordar(pathname, window.location.search);
    setUltimoEspacio(esp);
    escribir(LLAVE_ULTIMO, esp);
    setUltimas((prev) => {
      const next = { ...prev, [esp]: ruta };
      escribir(LLAVE_ULTIMAS, next);
      return next;
    });
    // Recientes: el destino (o su padre si comparten ruta, como DIOT) con la
    // empresa activa si trabaja sobre ella.
    const base = u.padre && u.padre.href === u.destino.href ? u.padre : u.destino;
    const empresa = activaRef.current;
    const porEmpresa = esPorEmpresa(u) && !!empresa;
    registrarReciente(
      esp,
      {
        id: base.id,
        href: ruta,
        label: porEmpresa ? `${base.label}, ${nombreCortoEmpresa(empresa!.nombre)}` : base.label,
        icon: base.icon,
        rfc: porEmpresa ? empresa!.rfc : null,
      },
      { generico: true },
    );
  }, [pathname]);

  const togglePanel = useCallback(() => {
    setPanelAbierto((abierto) => {
      escribir(LLAVE_PANEL, abierto ? '0' : '1');
      agregarBreadcrumb({ category: 'nav', message: `nav_panel: ${!abierto}` });
      return !abierto;
    });
  }, []);

  // ⌘B (GlobalShortcuts) usa el mismo evento que el sidebar clásico.
  useEffect(() => {
    const onToggle = () => togglePanel();
    window.addEventListener(EVENTO_SIDEBAR_TOGGLE, onToggle);
    return () => window.removeEventListener(EVENTO_SIDEBAR_TOGGLE, onToggle);
  }, [togglePanel]);

  const pronto = prontoId ? destinoPorId(prontoId) : null;
  const espacioDeRuta = destinoRuta?.espacio?.id ?? null;
  const espacioMarcado: EspacioId | null = pronto?.espacio?.id ?? espacioDeRuta;
  const espacioActivo: EspacioId = espacioMarcado ?? ultimoEspacio;

  const abrirPanel = useCallback(() => {
    setPanelAbierto(true);
    escribir(LLAVE_PANEL, '1');
  }, []);

  const navegar = useCallback(
    (href: string, via: ViaNav) => {
      setProntoId(null);
      agregarBreadcrumb({ category: 'nav', message: `nav_destino: ${normalizarRuta(href)}`, data: { via } });
      router.push(href);
    },
    [router],
  );

  const irAEspacio = useCallback(
    (id: EspacioId, via: ViaNav) => {
      if (!pronto && espacioDeRuta === id) {
        // Ya estás ahí. Un clic en el riel esconde o muestra el panel; el
        // atajo (⌘1..⌘5) o el buscador solo lo vuelven a mostrar.
        if (via === 'riel') togglePanel();
        else abrirPanel();
        return;
      }
      agregarBreadcrumb({ category: 'nav', message: `nav_espacio: ${id}`, data: { via } });
      abrirPanel();
      navegar(ultimas[id] ?? primerDestinoConRuta(id), via);
    },
    [espacioDeRuta, pronto, togglePanel, abrirPanel, navegar, ultimas],
  );

  const abrirDestino = useCallback(
    (d: Destino, via: ViaNav) => {
      if (d.href) {
        navegar(d.href, via);
        return;
      }
      agregarBreadcrumb({ category: 'nav', message: `nav_destino: ${d.id} (pronto)`, data: { via } });
      setProntoId(d.id);
    },
    [navegar],
  );

  const value = useMemo<EspaciosShellValue>(
    () => ({
      espacioActivo,
      espacioMarcado,
      destinoActivo: pronto ?? destinoRuta,
      pronto,
      panelAbierto,
      togglePanel,
      irAEspacio,
      navegar,
      abrirDestino,
    }),
    [
      espacioActivo,
      espacioMarcado,
      pronto,
      destinoRuta,
      panelAbierto,
      togglePanel,
      irAEspacio,
      navegar,
      abrirDestino,
    ],
  );

  return <EspaciosShellContext.Provider value={value}>{children}</EspaciosShellContext.Provider>;
}

/** Estado del shell de espacios; null con la navegación clásica. */
export function useEspaciosShell(): EspaciosShellValue | null {
  return useContext(EspaciosShellContext);
}

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';

import { EVENTO_PALETTE_OPEN, EVENTO_SIDEBAR_TOGGLE, esMac, formatearAtajo } from '@/lib/atajos';
import { ESPACIOS, NAV_ITEMS, destinoDe } from '@/lib/navegacion';
import { agregarBreadcrumb } from '@/lib/telemetria';
import { useAtajosGlobales, type AtajoGlobal } from '@/hooks/use-atajos-globales';
import { useEspaciosShell } from '@/components/layout/espacios-shell';
import {
  CommandPalette,
  type VistaPalette,
} from '@/components/layout/command-palette';
import { CommandPaletteEspacios } from '@/components/layout/command-palette-espacios';

/** Quién abrió el buscador (telemetría `palette_abierto`). */
type ViaPalette = 'atajo' | 'titlebar' | 'sidebar';

/** Atajo numérico para el dígito `d` (1..9), con su gemelo del teclado numérico. */
function digito(d: number, accion: () => void): AtajoGlobal[] {
  return [
    { tecla: `Digit${d}`, esCode: true, accion },
    { tecla: `Numpad${d}`, esCode: true, accion },
  ];
}

/**
 * Registro central de atajos de teclado (⌘ en mac, Ctrl en win/linux) y dueño
 * del estado del buscador (⌘K). Se monta UNA sola vez, en la rama autenticada
 * del AppShell (sin atajos en login/splash).
 *
 * - Clásica: ⌘1..⌘9 por posición en NAV_ITEMS.
 * - Espacios (F3): ⌘1..⌘5 abren los espacios (su última pantalla) y ⌘6..⌘9
 *   ya no abren nada: avisan dónde quedó lo que abrían antes. ⌘B esconde el
 *   panel del espacio y ⌘K abre el buscador con órdenes.
 *
 * Tabla de referencia para el usuario: lib/atajos.ts (`atajosDe(modo)`) →
 * tarjeta en /ayuda.
 */
export function GlobalShortcuts({ espacios = false }: { espacios?: boolean }) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const shell = useEspaciosShell();
  const conEspacios = espacios && !!shell;

  const [open, setOpen] = useState(false);
  const [vista, setVista] = useState<VistaPalette>('root');
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(esMac());
  }, []);

  function abrir(v: VistaPalette, via: ViaPalette) {
    setVista(v);
    setOpen(true);
    agregarBreadcrumb({ category: 'nav', message: 'palette_abierto', data: { via, vista: v } });
  }

  // "Buscar" del sidebar clásico y "Busca o pide algo" de la barra de título
  // abren el buscador por evento window.
  useEffect(() => {
    const onAbrir = (e: Event) => {
      const via = (e as CustomEvent<{ via?: ViaPalette } | undefined>).detail?.via ?? 'sidebar';
      abrir('root', via);
    };
    window.addEventListener(EVENTO_PALETTE_OPEN, onAbrir);
    return () => window.removeEventListener(EVENTO_PALETTE_OPEN, onAbrir);
  }, []);

  /** Ruta propia de un atajo: en espacios pasa por el shell (cierra un "Pronto" abierto). */
  function ir(href: string) {
    if (conEspacios && shell) shell.navegar(href, 'atajo');
    else router.push(href);
  }

  // ⌘6..⌘9 con espacios: dónde quedó lo que abrían en el menú anterior.
  function avisoAtajoViejo(d: number) {
    const item = NAV_ITEMS[d - 1];
    const u = item ? destinoDe(item.href) : null;
    agregarBreadcrumb({ category: 'nav', message: 'atajo_viejo', data: { digito: d } });
    if (!item || !u?.espacio) return;
    const i = ESPACIOS.findIndex((e) => e.id === u.espacio!.id);
    toast(`${item.label} ahora está en ${u.espacio.label} (${formatearAtajo({ tecla: String(i + 1) }, mac)})`, {
      description: `Los números abren los espacios. ${formatearAtajo({ tecla: '6' }, mac)} a ${formatearAtajo({ tecla: '9' }, mac)} ya no abren nada.`,
      action: { label: 'Abrir', onClick: () => ir(item.href) },
    });
  }

  const numericos: AtajoGlobal[] = conEspacios
    ? [
        ...ESPACIOS.flatMap((e, i) => digito(i + 1, () => shell!.irAEspacio(e.id, 'atajo'))),
        ...[6, 7, 8, 9].flatMap((d) => digito(d, () => avisoAtajoViejo(d))),
      ]
    : // ⌘1..⌘9 por posición en NAV_ITEMS (ver nota de orden en lib/navegacion.ts).
      // Solo hay 9 dígitos: a partir de la 10.ª página ya no hay atajo numérico
      // (navegable por ⌘K); `Digit10` no existe como e.code.
      NAV_ITEMS.slice(0, 9).flatMap((item, i) => digito(i + 1, () => router.push(item.href)));

  const atajos: AtajoGlobal[] = [
    // ⌘K: toggle del buscador (siempre reabre en la vista principal).
    { tecla: 'k', accion: () => (open ? setOpen(false) : abrir('root', 'atajo')) },
    // ⌘E: directo al cambio de empresa; segundo ⌘E lo cierra.
    {
      tecla: 'e',
      accion: () =>
        open && vista === 'empresas' ? setOpen(false) : abrir('empresas', 'atajo'),
    },
    // ⇧⌘L: alternar tema (pisa "system" a propósito; /ajustes lo restaura).
    {
      tecla: 'l',
      shift: true,
      accion: () => setTheme(resolvedTheme === 'dark' ? 'light' : 'dark'),
    },
    { tecla: ',', accion: () => ir('/ajustes') },
    // ⌘B: colapsa el sidebar clásico o esconde el panel del espacio.
    { tecla: 'b', accion: () => window.dispatchEvent(new Event(EVENTO_SIDEBAR_TOGGLE)) },
    { tecla: 'd', shift: true, accion: () => ir('/descarga/rapida') },
    // ⌘N: el query param lo lee /empresas para abrir el alta (y lo limpia).
    { tecla: 'n', accion: () => ir('/empresas?alta=1') },
    { tecla: 'f1', mod: false, accion: () => ir('/ayuda') },
    ...numericos,
  ];

  useAtajosGlobales(atajos);

  if (conEspacios) {
    return (
      <CommandPaletteEspacios
        open={open}
        vista={vista}
        onOpenChange={setOpen}
        onVistaChange={setVista}
      />
    );
  }

  return (
    <CommandPalette
      open={open}
      vista={vista}
      onOpenChange={setOpen}
      onVistaChange={setVista}
    />
  );
}

'use client';

import { useEffect, useState } from 'react';

import { Bell } from '@/components/notifications/bell';
import { ReportButton } from '@/components/feedback/report-button';
import { PlanBadge } from '@/components/auth/plan-badge';
import { EmpresaSwitcher } from '@/components/layout/empresa-switcher';
import { WindowControls } from '@/components/layout/window-controls';
import { Icon } from '@/components/ui/icon';
import { EVENTO_PALETTE_OPEN, detectarPlataforma, formatearAtajo } from '@/lib/atajos';
import { cn } from '@/lib/utils';

type EstiloDrag = React.CSSProperties & { WebkitAppRegion?: string };
const NO_DRAG: EstiloDrag = { WebkitAppRegion: 'no-drag' };

/**
 * Franja superior de la ventana. En Electron es una región arrastrable
 * (`-webkit-app-region: drag`) y el chrome depende del SO:
 * - macOS (`titleBarStyle: hiddenInset`): reserva a la izquierda el espacio de
 *   los semáforos nativos (78 px).
 * - Windows (`titleBarStyle: hidden`): sin barra nativa; la app dibuja sus
 *   propios min/max/cerrar (`WindowControls`) pegados al borde derecho.
 * En el navegador es solo una franja normal.
 *
 * Con la navegación por espacios (`espacios`) la barra lleva, a la izquierda,
 * el selector de empresa y, al centro, "Busca o pide algo" (⌘K). Los dos van
 * en zona `no-drag`, como la campana; los huecos de los lados siguen sirviendo
 * para arrastrar la ventana.
 */
export function Titlebar({ espacios = false }: { espacios?: boolean }) {
  const [{ desktop, mac, win }, set] = useState({
    desktop: false,
    mac: false,
    win: false,
  });

  useEffect(() => {
    set(detectarPlataforma());
  }, []);

  const conControles = desktop && win;
  const style: EstiloDrag = {
    paddingLeft: desktop && mac ? 78 : 14,
    // En Windows los controles van pegados al borde (sin padding).
    paddingRight: conControles ? 0 : 6,
  };
  if (desktop) style.WebkitAppRegion = 'drag';

  const derecha = (
    <div className="flex h-full items-center gap-2" style={desktop ? NO_DRAG : undefined}>
      <PlanBadge />
      <ReportButton />
      <Bell />
      {conControles && <WindowControls />}
    </div>
  );

  if (!espacios) {
    return (
      <div
        className="flex h-9 shrink-0 select-none items-center gap-2 border-b bg-card"
        style={style}
      >
        {/* La marca vive en el sidebar; la franja queda como zona de drag. */}
        <div className="ml-auto flex h-full items-center">{derecha}</div>
      </div>
    );
  }

  return (
    <div
      className="flex h-[38px] shrink-0 select-none items-center gap-3 border-b bg-card"
      style={style}
    >
      {/* Lados iguales (flex-1) para que el buscador quede centrado en la ventana. */}
      <div className="flex min-w-0 flex-1 basis-0 items-center">
        <EmpresaSwitcher variant="titlebar" />
      </div>
      <BotonBuscar mac={mac} />
      <div className="flex min-w-0 flex-1 basis-0 items-center justify-end">{derecha}</div>
    </div>
  );
}

/** "Busca o pide algo" con su ⌘K: abre el buscador (descubre las órdenes). */
function BotonBuscar({ mac }: { mac: boolean }) {
  return (
    <button
      type="button"
      onClick={() =>
        window.dispatchEvent(new CustomEvent(EVENTO_PALETTE_OPEN, { detail: { via: 'titlebar' } }))
      }
      style={NO_DRAG}
      className={cn(
        'flex h-7 w-[min(380px,36vw)] shrink-0 items-center gap-2 rounded-lg border border-border bg-background pl-2.5 pr-1.5 text-[12.5px] text-muted-foreground transition-colors',
        'hover:border-foreground/25 hover:bg-card',
      )}
    >
      <Icon icon="ph:magnifying-glass-light" className="size-3.75 shrink-0" />
      <span className="truncate">Busca o pide algo</span>
      <kbd className="ml-auto inline-flex h-4.5 shrink-0 items-center rounded-[5px] border border-border bg-muted px-1.5 font-sans text-[10.5px] font-medium text-muted-foreground">
        {formatearAtajo({ tecla: 'K' }, mac)}
      </kbd>
    </button>
  );
}

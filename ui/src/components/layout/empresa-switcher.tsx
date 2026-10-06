'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { esMac, formatearAtajo } from '@/lib/atajos';
import { nombreCortoEmpresa } from '@/lib/tareas';
import { mensajeDeError } from '@/lib/errores';
import { useEmpresas } from '@/hooks/use-empresas';
import type { Empresa } from '@/lib/types';
import { EmpresaBadge } from '@/components/empresas/empresa-badge';
import { Icon } from '@/components/ui/icon';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Selector de empresa activa: badge PF/PM + nombre truncado + RFC. Abre un
 * menú con todas las empresas (la activa con check) y un acceso a
 * "Administrar empresas". Cambiar de empresa usa `seleccionar()` (default +
 * carga de e.firma); el evento `empresas:refresh` sincroniza el resto de la UI.
 *
 * - `variant="sidebar"` (default): navegación clásica, arriba del menú.
 * - `variant="titlebar"`: navegación por espacios, compacto a la izquierda de
 *   la barra de título (nombre corto y RFC). Se abre también con ⌘E (lista
 *   en el buscador).
 */
export function EmpresaSwitcher({
  collapsed = false,
  variant = 'sidebar',
}: {
  collapsed?: boolean;
  variant?: 'sidebar' | 'titlebar';
}) {
  const router = useRouter();
  const { empresas, seleccionar } = useEmpresas();
  const [cambiando, setCambiando] = useState(false);

  const activas = empresas.filter((e) => !e.archived_at);
  const activa = activas.find((e) => e.default) ?? activas[0] ?? null;

  async function onSelect(e: Empresa) {
    if (cambiando || e.rfc === activa?.rfc) return;
    setCambiando(true);
    try {
      await seleccionar(e.rfc, e.metodos);
    } catch (err) {
      toast.error(mensajeDeError(err));
    } finally {
      setCambiando(false);
    }
  }

  if (variant === 'titlebar') {
    return (
      <EmpresaSwitcherTitlebar
        activas={activas}
        activa={activa}
        cambiando={cambiando}
        onSelect={onSelect}
        onAdministrar={() => router.push('/empresas')}
        onAgregar={() => router.push('/empresas?alta=1')}
      />
    );
  }

  if (!activa) {
    // Catálogo vacío (o aún cargando): acceso directo al alta.
    return (
      <button
        onClick={() => router.push('/empresas')}
        title={collapsed ? 'Agregar empresa' : undefined}
        className={cn(
          'flex items-center gap-2 rounded-lg border border-dashed text-sm font-medium text-muted-foreground transition-colors hover:border-foreground hover:text-foreground',
          collapsed ? 'justify-center p-2' : 'w-full px-3 py-2.5',
        )}
      >
        <Icon icon="ph:plus-light" className="size-4 shrink-0" />
        {!collapsed && 'Agregar empresa'}
      </button>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          title={collapsed ? `${activa.nombre} · ${activa.rfc}` : undefined}
          className={cn(
            'flex items-center gap-2.5 rounded-[10px] border bg-card text-left transition-colors hover:bg-muted',
            collapsed ? 'justify-center p-1.5' : 'w-full px-2.5 py-2',
          )}
        >
          <EmpresaBadge rfc={activa.rfc} />
          {!collapsed && (
            <>
              <span className="flex min-w-0 flex-1 flex-col gap-px">
                <span className="truncate text-[12.5px] font-semibold leading-tight text-foreground">
                  {activa.nombre}
                </span>
                <span className="truncate font-mono text-[11px] text-muted-foreground">
                  {activa.rfc}
                </span>
              </span>
              <Icon
                icon={cambiando ? 'ph:circle-notch-light' : 'ph:caret-down-light'}
                className={cn(
                  'size-4 shrink-0 text-muted-foreground',
                  cambiando && 'animate-spin',
                )}
              />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side={collapsed ? 'right' : 'bottom'}
        align="start"
        className={cn(
          'rounded-xl',
          collapsed ? 'w-64' : 'w-[var(--radix-dropdown-menu-trigger-width)]',
        )}
      >
        <DropdownMenuLabel>Cambiar de empresa</DropdownMenuLabel>
        <div className="max-h-72 overflow-y-auto">
          {activas.map((e) => {
            const esActiva = e.rfc === activa.rfc;
            return (
              <DropdownMenuItem
                key={e.rfc}
                onSelect={() => onSelect(e)}
                className={cn('gap-2.5 rounded-lg', esActiva && 'bg-muted')}
              >
                <EmpresaBadge rfc={e.rfc} size="sm" />
                <span className="flex min-w-0 flex-1 flex-col gap-px">
                  <span className="truncate text-[12.5px] font-semibold leading-tight">
                    {e.nombre}
                  </span>
                  <span className="truncate font-mono text-[11px] text-muted-foreground">
                    {e.rfc}
                  </span>
                </span>
                {esActiva && (
                  <Icon
                    icon="ph:check-circle-light"
                    className="size-4 shrink-0 text-foreground"
                  />
                )}
              </DropdownMenuItem>
            );
          })}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => router.push('/empresas')}
          className="gap-2 rounded-lg font-semibold"
        >
          <Icon icon="ph:buildings-light" className="size-4" />
          Administrar empresas
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

const NO_DRAG = { WebkitAppRegion: 'no-drag' } as React.CSSProperties & {
  WebkitAppRegion?: string;
};

/** Variante compacta de la barra de título (navegación por espacios). */
function EmpresaSwitcherTitlebar({
  activas,
  activa,
  cambiando,
  onSelect,
  onAdministrar,
  onAgregar,
}: {
  activas: Empresa[];
  activa: Empresa | null;
  cambiando: boolean;
  onSelect: (e: Empresa) => void;
  onAdministrar: () => void;
  onAgregar: () => void;
}) {
  const [mac, setMac] = useState(false);
  useEffect(() => {
    setMac(esMac());
  }, []);

  if (!activa) {
    return (
      <button
        type="button"
        onClick={onAgregar}
        style={NO_DRAG}
        className="flex h-7.5 min-w-0 items-center gap-1.5 rounded-lg border border-dashed border-border px-2.5 text-[12.5px] font-semibold text-muted-foreground transition-colors hover:border-foreground hover:text-foreground"
      >
        <Icon icon="ph:plus-light" className="size-3.5 shrink-0" />
        Agregar empresa
      </button>
    );
  }

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              style={NO_DRAG}
              aria-label={`Empresa activa: ${activa.nombre}. Cambiar de empresa`}
              className="flex h-7.5 min-w-0 max-w-[330px] items-center gap-2 rounded-lg border border-border bg-card pl-1 pr-2 text-left transition-colors hover:bg-muted data-[state=open]:bg-muted"
            >
              <EmpresaBadge rfc={activa.rfc} size="xs" />
              <span className="min-w-0 truncate text-[12.5px] font-semibold tracking-[-0.01em] text-foreground">
                {nombreCortoEmpresa(activa.nombre)}
              </span>
              <span className="hidden shrink-0 font-mono text-[11px] text-muted-foreground lg:inline">
                {activa.rfc}
              </span>
              <Icon
                icon={cambiando ? 'ph:circle-notch-light' : 'ph:caret-down-light'}
                className={cn('size-3.5 shrink-0 text-muted-foreground', cambiando && 'animate-spin')}
              />
            </button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          Cambiar de empresa ({formatearAtajo({ tecla: 'E' }, mac)})
        </TooltipContent>
      </Tooltip>
      <DropdownMenuContent side="bottom" align="start" className="w-80 rounded-xl">
        <DropdownMenuLabel>Cambiar de empresa</DropdownMenuLabel>
        <div className="max-h-80 overflow-y-auto">
          {activas.map((e) => {
            const esActiva = e.rfc === activa.rfc;
            return (
              <DropdownMenuItem
                key={e.rfc}
                onSelect={() => onSelect(e)}
                className={cn('gap-2.5 rounded-lg', esActiva && 'bg-muted')}
              >
                <EmpresaBadge rfc={e.rfc} size="sm" />
                <span className="flex min-w-0 flex-1 flex-col gap-px">
                  <span className="truncate text-[12.5px] font-semibold leading-tight">
                    {e.nombre}
                  </span>
                  <span className="truncate font-mono text-[11px] text-muted-foreground">
                    {e.rfc}
                  </span>
                </span>
                {esActiva && (
                  <Icon icon="ph:check-circle-light" className="size-4 shrink-0 text-foreground" />
                )}
              </DropdownMenuItem>
            );
          })}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onAdministrar} className="gap-2 rounded-lg font-semibold">
          <Icon icon="ph:buildings-light" className="size-4" />
          Administrar empresas
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

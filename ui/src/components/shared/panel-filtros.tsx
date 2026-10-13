'use client';

import { useState, type ReactNode } from 'react';

import { Card } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';

interface Props {
  filtrosActivos: number;
  onLimpiar: () => void;
  /** Nota del encabezado cerrado sin filtros, p. ej. «Mostrando todas las facturas». */
  sinFiltros: string;
  children: ReactNode;
}

/**
 * Panel de filtros de los procesadores (CFDI, Pagos y Nómina). Arranca
 * cerrado: el usuario lo abre cuando quiere filtrar. Cerrado sigue avisando
 * si el listado está filtrado, porque los filtros persisten entre sesiones.
 */
export function PanelFiltros({ filtrosActivos, onLimpiar, sinFiltros, children }: Props) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="gap-0 overflow-hidden py-0">
      {/* Encabezado-toggle: contador de filtros activos + nota cuando está
          colapsado, para saber de un vistazo si el listado está filtrado. */}
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3.5 px-5 py-3.75 text-left transition-colors hover:bg-secondary"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="inline-flex items-center gap-2 text-sm font-bold tracking-tight">
          <Icon icon="ph:funnel-light" className="size-4 text-foreground/70" />
          Filtros
          {filtrosActivos > 0 && (
            <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1.5 text-[11.5px] font-bold tabular-nums text-primary-foreground">
              {filtrosActivos}
            </span>
          )}
          {!open && (
            <span className="whitespace-nowrap text-xs font-medium text-muted-foreground">
              {filtrosActivos > 0 ? 'El listado está filtrado' : sinFiltros}
            </span>
          )}
        </span>
        <span className="inline-flex items-center gap-3">
          {filtrosActivos > 0 && (
            <span
              role="button"
              tabIndex={0}
              className="text-xs font-semibold text-primary hover:underline hover:underline-offset-2"
              onClick={(e) => {
                e.stopPropagation();
                onLimpiar();
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.stopPropagation();
                  onLimpiar();
                }
              }}
            >
              Limpiar
            </span>
          )}
          <Icon
            icon="ph:caret-down-light"
            className={cn(
              'size-4 text-muted-foreground transition-transform',
              open && 'rotate-180',
            )}
          />
        </span>
      </button>

      {open && <div className="space-y-4 border-t px-5 pb-5 pt-4">{children}</div>}
    </Card>
  );
}

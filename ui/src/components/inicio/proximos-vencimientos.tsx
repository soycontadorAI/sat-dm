import Link from 'next/link';

import { PanelInicio, PanelVacio } from '@/components/inicio/panel-inicio';
import { colorEmpresa, iniciales } from '@/lib/empresa-visual';
import type { VencimientoEmpresa } from '@/lib/inicio-stats';
import { cn } from '@/lib/utils';

interface ProximosVencimientosProps {
  items: VencimientoEmpresa[];
}

function etiquetaDias(dias: number, vencida: boolean): string {
  if (vencida) return 'Vencida';
  if (dias === 0) return 'Hoy';
  return dias === 1 ? '1 día' : `${dias} días`;
}

/** e.firmas a 30 días o menos de vencer, de la más urgente a la menos. */
export function ProximosVencimientos({ items }: ProximosVencimientosProps) {
  return (
    <PanelInicio
      titulo="Próximos vencimientos de e.firma"
      icono="ph:hourglass-medium-light"
      sub={items.length > 0 ? `${items.length} por vencer` : undefined}
    >
      {items.length === 0 ? (
        <PanelVacio icono="ph:check-circle-light">
          Ninguna e.firma vence en los próximos 30 días.
        </PanelVacio>
      ) : (
        <div className="flex flex-col">
          {items.map(({ empresa, semaforo }) => (
            <Link
              key={empresa.rfc}
              href={`/empresas/detalle?rfc=${empresa.rfc}`}
              className="group flex items-center gap-3 border-t border-border/60 py-2.5 first:border-t-0 first:pt-0 last:pb-0"
            >
              <span
                className="flex size-8 shrink-0 items-center justify-center rounded-lg font-mono text-[11px] font-bold text-background"
                style={{ background: colorEmpresa(empresa.rfc) }}
              >
                {iniciales(empresa.nombre)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13px] font-semibold group-hover:text-primary">
                  {empresa.nombre}
                </span>
                <span className="block font-mono text-[10.5px] text-muted-foreground">
                  {empresa.rfc}
                </span>
              </span>
              <span
                className={cn(
                  'shrink-0 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-bold',
                  semaforo.estado === 'rojo'
                    ? 'bg-destructive/10 text-destructive'
                    : 'bg-warning/10 text-warning',
                )}
              >
                {etiquetaDias(semaforo.dias, semaforo.vencida)}
              </span>
            </Link>
          ))}
        </div>
      )}
    </PanelInicio>
  );
}

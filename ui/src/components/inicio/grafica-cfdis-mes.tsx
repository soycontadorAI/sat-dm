import { PanelInicio, PanelVacio } from '@/components/inicio/panel-inicio';
import { formatNumber } from '@/lib/formatting';
import type { MesCfdis } from '@/lib/inicio-stats';
import { cn } from '@/lib/utils';

interface GraficaCfdisMesProps {
  meses: MesCfdis[];
  cargando: boolean;
}

/** Barras de CFDIs descargados por mes (últimos 6). CSS puro, sin libs. */
export function GraficaCfdisMes({ meses, cargando }: GraficaCfdisMesProps) {
  const maximo = Math.max(...meses.map((m) => m.total));

  return (
    <PanelInicio
      titulo="CFDIs descargados por mes"
      icono="ph:chart-bar-light"
      sub="últimos 6 meses"
    >
      {cargando && maximo === 0 ? (
        <div className="h-[170px] animate-pulse rounded-lg bg-secondary/60" />
      ) : maximo === 0 ? (
        <PanelVacio icono="ph:chart-bar-light">
          Aún no hay descargas de CFDIs registradas. Cuando descargues, aquí
          verás tu volumen mes a mes.
        </PanelVacio>
      ) : (
        <div className="flex h-[150px] items-end gap-3 pt-2">
          {meses.map((m, i) => (
            <div
              key={m.clave}
              className="flex h-full flex-1 flex-col items-center justify-end gap-2"
            >
              <div className="flex w-full flex-1 items-end justify-center">
                <div
                  className={cn(
                    'relative w-3/5 max-w-[38px] rounded-t-[5px]',
                    i === meses.length - 1 ? 'bg-primary' : 'bg-primary/20',
                  )}
                  style={{ height: `${Math.max((m.total / maximo) * 100, 3)}%` }}
                >
                  <span className="absolute -top-[18px] left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] font-bold tabular-nums text-muted-foreground">
                    {formatNumber(m.total)}
                  </span>
                </div>
              </div>
              <span className="text-[11px] font-medium capitalize text-muted-foreground">
                {m.etiqueta}
              </span>
            </div>
          ))}
        </div>
      )}
    </PanelInicio>
  );
}

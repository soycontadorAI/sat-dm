import Link from 'next/link';

import { PanelInicio, PanelVacio } from '@/components/inicio/panel-inicio';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { formatNumber } from '@/lib/formatting';
import type { HistorialItem } from '@/lib/types';

interface DescargasRecientesProps {
  descargas: HistorialItem[];
  cargando: boolean;
  className?: string;
}

/** "hoy, 10:47 a.m." / "ayer, 07:06 p.m." / "06 jul, 10:47 a.m." */
function fechaRelativa(iso: string): string {
  const f = new Date(iso);
  if (Number.isNaN(f.getTime())) return iso;
  const hora = f.toLocaleTimeString('es-MX', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
  });
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const dia = new Date(f);
  dia.setHours(0, 0, 0, 0);
  const diffDias = Math.round((hoy.getTime() - dia.getTime()) / 86_400_000);
  if (diffDias === 0) return `hoy, ${hora}`;
  if (diffDias === 1) return `ayer, ${hora}`;
  const fecha = f
    .toLocaleDateString('es-MX', { day: '2-digit', month: 'short' })
    .replace('.', '');
  return `${fecha}, ${hora}`;
}

/** Últimas descargas de todas las empresas (WS, CIEC y documentos). */
export function DescargasRecientes({
  descargas,
  cargando,
  className,
}: DescargasRecientesProps) {
  return (
    <PanelInicio
      titulo="Descargas recientes"
      icono="ph:clock-counter-clockwise-light"
      className={className}
      accion={
        <Button variant="ghost" size="sm" asChild>
          <Link href="/historial">
            Ver historial
            <Icon icon="ph:arrow-right-light" className="size-3.5" />
          </Link>
        </Button>
      }
    >
      {cargando && descargas.length === 0 ? (
        <div className="h-[120px] animate-pulse rounded-lg bg-secondary/60" />
      ) : descargas.length === 0 ? (
        <PanelVacio icono="ph:download-simple-light">
          Aquí verás tus descargas más recientes. Empieza en{' '}
          <Link href="/descarga" className="font-semibold text-primary">
            Descargar CFDIs
          </Link>
          .
        </PanelVacio>
      ) : (
        <table className="w-full border-collapse">
          <tbody>
            {descargas.map((d, i) => (
              <tr
                key={`${d.timestamp}-${i}`}
                className="border-t border-border/60 first:border-t-0"
              >
                <td className="py-2.5 pr-3">
                  <div className="text-[13px] font-medium">{d.descripcion}</div>
                  <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                    {d.nombre || d.rfc || '–'}
                  </div>
                </td>
                <td className="whitespace-nowrap py-2.5 pr-3 text-right font-mono text-[11px] text-muted-foreground">
                  {fechaRelativa(d.timestamp)}
                </td>
                <td className="whitespace-nowrap py-2.5 text-right text-[13px] font-bold tabular-nums">
                  {typeof d.total === 'number' ? (
                    <>
                      {formatNumber(d.total)}
                      <span className="text-[11px] font-normal text-muted-foreground">
                        {' '}
                        CFDIs
                      </span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">–</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </PanelInicio>
  );
}

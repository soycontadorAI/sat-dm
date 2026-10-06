import Link from 'next/link';

import { PanelInicio, PanelVacio } from '@/components/inicio/panel-inicio';
import type { EstadoCartera } from '@/lib/inicio-stats';

interface EstadoCarteraDonutProps {
  cartera: EstadoCartera;
}

/**
 * Donut (conic-gradient) del estado de las empresas activas: al día vs.
 * e.firma por vencer vs. solo con CIEC. Colores de DATOS del semáforo, por
 * eso van como variables CSS inline y no como clases de superficie.
 */
export function EstadoCarteraDonut({ cartera }: EstadoCarteraDonutProps) {
  const segmentos = [
    { etiqueta: 'Al día', valor: cartera.alDia, color: 'var(--success)' },
    {
      etiqueta: 'e.firma por vencer',
      valor: cartera.porVencer,
      color: 'var(--warning)',
    },
    {
      etiqueta: 'Solo con Contraseña',
      valor: cartera.soloCiec,
      color: 'var(--accent-ai)',
    },
  ];
  const total = cartera.activas.length;

  let acumulado = 0;
  const gradiente = segmentos
    .filter((s) => s.valor > 0)
    .map((s) => {
      const desde = (acumulado / total) * 360;
      acumulado += s.valor;
      const hasta = (acumulado / total) * 360;
      return `${s.color} ${desde}deg ${hasta}deg`;
    })
    .join(', ');

  return (
    <PanelInicio titulo="Estado de la cartera" icono="ph:shield-check-light">
      {total === 0 ? (
        <PanelVacio icono="ph:buildings-light">
          Registra tu primera empresa en{' '}
          <Link href="/empresas" className="font-semibold text-primary">
            Empresas
          </Link>{' '}
          para ver aquí el estado de tu cartera.
        </PanelVacio>
      ) : (
        <div className="flex items-center gap-6">
          <div
            className="relative size-[116px] shrink-0 rounded-full"
            style={{ background: `conic-gradient(${gradiente})` }}
          >
            <div className="absolute inset-[22px] rounded-full bg-card" />
            <div className="absolute inset-0 z-[1] flex flex-col items-center justify-center">
              <span className="text-2xl font-extrabold leading-none tracking-tight">
                {total}
              </span>
              <span className="mt-0.5 text-[11px] font-medium text-muted-foreground">
                {total === 1 ? 'empresa' : 'empresas'}
              </span>
            </div>
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2.5">
            {segmentos.map((s) => (
              <div
                key={s.etiqueta}
                className="flex items-center gap-2 text-[13px]"
              >
                <span
                  className="size-2.5 shrink-0 rounded-[3px]"
                  style={{ background: s.color }}
                />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">
                  {s.etiqueta}
                </span>
                <span className="font-bold tabular-nums">{s.valor}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </PanelInicio>
  );
}

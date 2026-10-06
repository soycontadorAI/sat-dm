'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import type { CfdiStats } from '@/lib/types';

interface Props {
  stats: CfdiStats | null;
}

function formatoMXN(n: number): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(n);
}

function tiposLabel(porTipo: Record<string, number>): string {
  const ETIQUETAS: Record<string, string> = {
    I: 'Ingresos',
    E: 'Egresos',
    P: 'Pagos',
    N: 'Nóminas',
    T: 'Traslados',
  };
  return Object.entries(porTipo)
    .map(([k, v]) => `${v} ${ETIQUETAS[k] ?? k}`)
    .join(', ');
}

export function CfdiStats({ stats }: Props) {
  const total = stats?.total_comprobantes ?? 0;
  const totalGlobal = stats?.total_global ?? 0;
  const monto = stats?.monto_total ?? 0;
  const ivaT = stats?.iva_trasladado ?? 0;
  const iepsT = stats?.ieps_trasladado ?? 0;
  const ivaR = stats?.iva_retenido ?? 0;
  const isrR = stats?.isr_retenido ?? 0;
  const conErrores = stats?.con_errores ?? 0;
  const porTipo = stats?.por_tipo ?? {};
  const hayFiltros = totalGlobal > 0 && total !== totalGlobal;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:files-light" className="size-4" />
            Comprobantes
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          <div className="text-2xl font-semibold">
            {total.toLocaleString('es-MX')}
            {hayFiltros && (
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                de {totalGlobal.toLocaleString('es-MX')}
              </span>
            )}
          </div>
          {total > 0 && (
            <p className="text-xs text-muted-foreground">{tiposLabel(porTipo)}</p>
          )}
          {conErrores > 0 && (
            <p className="text-xs text-amber-600">
              {conErrores} con advertencias
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:currency-circle-dollar-light" className="size-4" />
            Monto total
          </CardTitle>
          <CardDescription>Suma del campo Total</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-semibold">{formatoMXN(monto)}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:percent-light" className="size-4" />
            Impuestos
          </CardTitle>
          <CardDescription>IVA trasladado, IVA retenido e ISR retenido</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1 text-sm">
          <div>
            <span className="text-muted-foreground">IVA trasladado:</span>{' '}
            <span className="font-mono">{formatoMXN(ivaT)}</span>
          </div>
          {iepsT > 0 && (
            <div>
              <span className="text-muted-foreground">IEPS trasladado:</span>{' '}
              <span className="font-mono">{formatoMXN(iepsT)}</span>
            </div>
          )}
          <div>
            <span className="text-muted-foreground">IVA retenido:</span>{' '}
            <span className="font-mono">{formatoMXN(ivaR)}</span>
          </div>
          <div>
            <span className="text-muted-foreground">ISR retenido:</span>{' '}
            <span className="font-mono">{formatoMXN(isrR)}</span>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

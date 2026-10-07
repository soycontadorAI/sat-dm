'use client';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import type { NominaStats } from '@/lib/types';

interface Props {
  stats: NominaStats | null;
}

function formatoMXN(n: number): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(n);
}

export function NominaStatsCards({ stats }: Props) {
  const totalRecibos = stats?.total_recibos ?? 0;
  const totalGlobal = stats?.total_global_recibos ?? 0;
  const empleados = stats?.total_empleados ?? 0;
  const totalPerc = stats?.total_percepciones ?? 0;
  const totalDed = stats?.total_deducciones ?? 0;
  const neto = stats?.neto_a_pagar ?? 0;
  const ordinarias = stats?.nominas_ordinarias ?? 0;
  const extraordinarias = stats?.nominas_extraordinarias ?? 0;

  const hayFiltros = totalGlobal > 0 && totalRecibos !== totalGlobal;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:receipt-light" className="size-4" />
            Recibos
          </CardTitle>
          <CardDescription>Recibos de nómina cargados</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          <div className="text-2xl font-semibold">
            {totalRecibos.toLocaleString('es-MX')}
          </div>
          <p className="text-xs text-muted-foreground">
            {hayFiltros && `De ${totalGlobal.toLocaleString('es-MX')}: `}
            {ordinarias} ordinarias y {extraordinarias} extraordinarias
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:users-three-light" className="size-4" />
            Empleados
          </CardTitle>
          <CardDescription>RFCs únicos en el periodo</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-semibold">
            {empleados.toLocaleString('es-MX')}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:trend-up-light" className="size-4" />
            Percepciones
          </CardTitle>
          <CardDescription>Total bruto (gravado + exento)</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1">
          <div className="text-2xl font-semibold">{formatoMXN(totalPerc)}</div>
          <p className="text-xs text-muted-foreground">
            Deducciones: {formatoMXN(totalDed)}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Icon icon="ph:wallet-light" className="size-4" />
            Neto a pagar
          </CardTitle>
          <CardDescription>Percepciones − deducciones + otros</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-semibold">{formatoMXN(neto)}</div>
        </CardContent>
      </Card>
    </div>
  );
}

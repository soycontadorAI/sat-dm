'use client';

import { useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Icon } from '@/components/ui/icon';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type {
  CfdiFiltros,
  ItemIntegridad,
  ReporteIntegridad,
  ReporteTopContrapartes,
  ReporteTotalesMes,
  TopContraparte,
} from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa activa (los reportes salen de SU buffer). */
  rfc: string;
  filtros: Partial<CfdiFiltros>;
}

function formatoMXN(n: number): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(n);
}

function mesLegible(yyyymm: string): string {
  const [y, m] = yyyymm.split('-');
  if (!y || !m) return yyyymm;
  const date = new Date(Number(y), Number(m) - 1, 1);
  return date.toLocaleDateString('es-MX', { month: 'long', year: 'numeric' });
}

export function CfdiReportes({ rfc, filtros }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon icon="ph:chart-bar-light" className="size-4" />
          Reportes
        </CardTitle>
        <CardDescription>Agregaciones sobre el subset filtrado.</CardDescription>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="totales-mes">
          <TabsList>
            <TabsTrigger value="totales-mes">Totales por mes</TabsTrigger>
            <TabsTrigger value="top-contrapartes">Top contrapartes</TabsTrigger>
            <TabsTrigger value="integridad">Integridad</TabsTrigger>
          </TabsList>

          <TabsContent value="totales-mes">
            <TotalesMesPanel rfc={rfc} filtros={filtros} />
          </TabsContent>
          <TabsContent value="top-contrapartes">
            <TopContrapartesPanel rfc={rfc} filtros={filtros} />
          </TabsContent>
          <TabsContent value="integridad">
            <IntegridadPanel rfc={rfc} filtros={filtros} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-paneles
// ---------------------------------------------------------------------------

function useReporte<T>(rfc: string,
                      nombre: 'totales-mes' | 'top-contrapartes' | 'integridad',
                      filtros: Partial<CfdiFiltros>) {
  const { apiClient } = useServer();
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (apiClient.procesadorReporte as any)(rfc, nombre, filtros)
      .then((r: T) => mounted && setData(r))
      .catch((e: unknown) => {
        if (mounted) setError(mensajeDeError(e));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [apiClient, rfc, nombre, JSON.stringify(filtros)]); // eslint-disable-line react-hooks/exhaustive-deps

  return { data, loading, error };
}

function ReporteEstado({ loading, error, empty }: { loading: boolean; error: string | null; empty?: boolean }) {
  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
        <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
        Cargando…
      </div>
    );
  }
  if (error) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }
  if (empty) {
    return (
      <div className="py-6 text-center text-sm text-muted-foreground">
        Sin datos para los filtros actuales.
      </div>
    );
  }
  return null;
}

function TotalesMesPanel({ rfc, filtros }: { rfc: string; filtros: Partial<CfdiFiltros> }) {
  const { data, loading, error } = useReporte<ReporteTotalesMes>(rfc, 'totales-mes', filtros);
  const items = data?.items ?? [];
  if (loading || error || items.length === 0) {
    return <ReporteEstado loading={loading} error={error} empty={items.length === 0} />;
  }
  // Solo mostramos la columna IEPS si algún mes la tiene >0 (evita una columna
  // vacía para corpora donde no hay IEPS — la mayoría de CFDIs de servicios
  // profesionales / comercio general).
  const muestraIeps = items.some((r) => (r.ieps_trasladado ?? 0) > 0);

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Mes</TableHead>
          <TableHead className="text-right">Comprobantes</TableHead>
          <TableHead className="text-right">Subtotal</TableHead>
          <TableHead className="text-right">IVA trasl.</TableHead>
          {muestraIeps && <TableHead className="text-right">IEPS trasl.</TableHead>}
          <TableHead className="text-right">IVA ret.</TableHead>
          <TableHead className="text-right">ISR ret.</TableHead>
          <TableHead className="text-right">Total</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((r) => (
          <TableRow key={r.mes}>
            <TableCell className="capitalize">{mesLegible(r.mes)}</TableCell>
            <TableCell className="text-right font-mono">{r.comprobantes}</TableCell>
            <TableCell className="text-right font-mono">{formatoMXN(r.sub_total)}</TableCell>
            <TableCell className="text-right font-mono">{formatoMXN(r.iva_trasladado)}</TableCell>
            {muestraIeps && (
              <TableCell className="text-right font-mono">{formatoMXN(r.ieps_trasladado)}</TableCell>
            )}
            <TableCell className="text-right font-mono">{formatoMXN(r.iva_retenido)}</TableCell>
            <TableCell className="text-right font-mono">{formatoMXN(r.isr_retenido)}</TableCell>
            <TableCell className="text-right font-mono font-medium">{formatoMXN(r.total)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function TopContrapartesPanel({ rfc, filtros }: { rfc: string; filtros: Partial<CfdiFiltros> }) {
  const { data, loading, error } = useReporte<ReporteTopContrapartes>(rfc, 'top-contrapartes', filtros);
  if (loading || error) return <ReporteEstado loading={loading} error={error} />;
  const emisores = data?.emisores ?? [];
  const receptores = data?.receptores ?? [];
  if (emisores.length === 0 && receptores.length === 0) {
    return <ReporteEstado loading={false} error={null} empty />;
  }
  // Según la dirección filtrada (R/E), mostramos solo la lista relevante:
  //  - 'R' (Recibidos): el emisor del CFDI me vendió → proveedor.
  //  - 'E' (Emitidos):  el receptor del CFDI me compró → cliente.
  //  - null (ambas): mostramos los dos rankings.
  if (filtros.direccion === 'R') {
    return <ContrapartesList titulo="Top proveedores" items={emisores} />;
  }
  if (filtros.direccion === 'E') {
    return <ContrapartesList titulo="Top clientes" items={receptores} />;
  }
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <ContrapartesList titulo="Top proveedores" items={emisores} />
      <ContrapartesList titulo="Top clientes" items={receptores} />
    </div>
  );
}

function ContrapartesList({ titulo, items }: { titulo: string; items: TopContraparte[] }) {
  return (
    <div>
      <h3 className="mb-2 text-sm font-medium">{titulo}</h3>
      {items.length === 0 ? (
        <div className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
          Sin datos.
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>RFC / Nombre</TableHead>
              <TableHead className="text-right">CFDIs</TableHead>
              <TableHead className="text-right">Monto</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.rfc}>
                <TableCell>
                  <div className="font-medium leading-tight">{r.nombre || '–'}</div>
                  <div className="font-mono text-xs text-muted-foreground">{r.rfc}</div>
                </TableCell>
                <TableCell className="text-right font-mono">{r.comprobantes}</TableCell>
                <TableCell className="text-right font-mono">{formatoMXN(r.monto)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function IntegridadPanel({ rfc, filtros }: { rfc: string; filtros: Partial<CfdiFiltros> }) {
  const { data, loading, error } = useReporte<ReporteIntegridad>(rfc, 'integridad', filtros);
  const items: ItemIntegridad[] = data?.items ?? [];
  if (loading || error || items.length === 0) {
    return <ReporteEstado loading={loading} error={error} empty={items.length === 0} />;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>UUID / Folio</TableHead>
          <TableHead>Emisor</TableHead>
          <TableHead>Receptor</TableHead>
          <TableHead className="text-right">Total</TableHead>
          <TableHead>Advertencias</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((r) => (
          <TableRow key={r.uuid}>
            <TableCell>
              <div className="font-mono text-xs">{r.uuid}</div>
              {(r.serie || r.folio) && (
                <div className="text-xs text-muted-foreground">
                  {r.serie || ''} / {r.folio || ''}
                </div>
              )}
            </TableCell>
            <TableCell className="text-xs">{r.emisor_nombre || r.emisor_rfc}</TableCell>
            <TableCell className="text-xs">{r.receptor_nombre || r.receptor_rfc}</TableCell>
            <TableCell className="text-right font-mono text-xs">{formatoMXN(r.total)}</TableCell>
            <TableCell>
              <ul className="list-disc pl-4 text-xs text-amber-900 space-y-0.5">
                {r.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

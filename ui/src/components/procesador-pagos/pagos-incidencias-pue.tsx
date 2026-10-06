'use client';

import { useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { PagosFiltros, ReporteIncidenciasPue } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa activa (el reporte sale de SU buffer). */
  rfc: string;
  filtros: Partial<PagosFiltros>;
}

function formatoFecha(iso: string | null): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatoMXN(n: number | null): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(n ?? 0);
}

export function PagosIncidenciasPue({ rfc, filtros }: Props) {
  const { apiClient } = useServer();
  const [data, setData] = useState<ReporteIncidenciasPue | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    apiClient
      .procesadorPagosReporte(rfc, 'incidencias-pue', filtros)
      .then((r) => {
        if (mounted) setData(r);
      })
      .catch((e) => {
        if (mounted) setError(mensajeDeError(e));
      });
    return () => {
      mounted = false;
    };
  }, [apiClient, rfc, JSON.stringify(filtros)]); // eslint-disable-line react-hooks/exhaustive-deps

  if (error || !data || data.items.length === 0) return null;

  const explicacion = data.items[0]?.descripcion_riesgo;

  return (
    <Card className="border-destructive">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base text-destructive">
          <Icon icon="ph:warning-octagon-light" className="size-5" />
          Incidencias PUE + complemento ({data.items.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 p-4 pt-0">
        {explicacion && (
          <Alert variant="destructive">
            <Icon icon="ph:warning-octagon-light" className="size-4" />
            <AlertTitle>Riesgo fiscal</AlertTitle>
            <AlertDescription>{explicacion}</AlertDescription>
          </Alert>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>UUID Factura PUE</TableHead>
              <TableHead>Fecha</TableHead>
              <TableHead>Emisor</TableHead>
              <TableHead className="text-right">Total factura</TableHead>
              <TableHead>UUID Complemento</TableHead>
              <TableHead className="text-right">Monto pagado</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((i, idx) => (
              <TableRow key={`${i.complemento_uuid}-${idx}`}>
                <TableCell className="font-mono text-xs">{i.factura_uuid || '–'}</TableCell>
                <TableCell className="text-xs">{formatoFecha(i.factura_fecha)}</TableCell>
                <TableCell className="text-xs">
                  <div className="font-medium">{i.emisor_nombre || '–'}</div>
                  <div className="font-mono text-[10px] text-muted-foreground">
                    {i.emisor_rfc || '–'}
                  </div>
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatoMXN(i.factura_total)}
                </TableCell>
                <TableCell className="font-mono text-xs">{i.complemento_uuid}</TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatoMXN(i.monto_pagado)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

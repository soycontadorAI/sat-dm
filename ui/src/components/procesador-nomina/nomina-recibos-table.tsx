'use client';

import { Fragment, useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import type {
  NominaConceptoDetalle,
  NominaRecibo,
  NominaRecibosResponse,
} from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa activa (el drilldown consulta SU buffer). */
  rfc: string;
  data: NominaRecibosResponse | null;
  page: number;
  pageSize: number;
  loading: boolean;
  onPage: (p: number) => void;
}

const PERIODICIDAD_LABEL: Record<string, string> = {
  '01': 'Diario',
  '02': 'Semanal',
  '03': 'Catorcenal',
  '04': 'Quincenal',
  '05': 'Mensual',
  '06': 'Bimestral',
  '07': 'Unidad de obra',
  '08': 'Comisión',
  '09': 'Precio alzado',
  '10': 'Decenal',
  '99': 'Otra',
};

function formatoFecha(iso: string): string {
  if (!iso) return '–';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('es-MX', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

function formatoMXN(n: number): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(n);
}

function badgeEstadoSat(estado: NominaRecibo['estado_sat']) {
  if (!estado) {
    return (
      <Badge variant="secondary" className="text-[10px]">
        Sin validar
      </Badge>
    );
  }
  if (estado === 'Vigente') {
    return (
      <Badge variant="secondary" className="bg-emerald-100 text-emerald-700 text-[10px]">
        <Icon icon="ph:check-circle-light" className="size-3" /> Vigente
      </Badge>
    );
  }
  if (estado === 'Cancelado') {
    return (
      <Badge variant="destructive" className="text-[10px]">
        <Icon icon="ph:x-circle-light" className="size-3" /> Cancelado
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="bg-amber-100 text-amber-700 text-[10px]">
      <Icon icon="ph:warning-light" className="size-3" /> No encontrado
    </Badge>
  );
}

export function NominaRecibosTable({ rfc, data, page, pageSize, loading, onPage }: Props) {
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const [expandido, setExpandido] = useState<string | null>(null);

  if (loading && items.length === 0) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
          Cargando…
        </CardContent>
      </Card>
    );
  }

  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
          <Icon icon="ph:list-magnifying-glass-light" className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Sin resultados</p>
          <p className="text-sm text-muted-foreground">
            Ajusta los filtros o carga más XMLs.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden p-0">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-28">Fecha pago</TableHead>
            <TableHead>Empleado</TableHead>
            <TableHead>NSS</TableHead>
            <TableHead>Periodicidad</TableHead>
            <TableHead className="w-16 text-center">Tipo</TableHead>
            <TableHead className="text-right">Días</TableHead>
            <TableHead className="text-right">Percepciones</TableHead>
            <TableHead className="text-right">Deducciones</TableHead>
            <TableHead className="text-right">Neto</TableHead>
            <TableHead>Estatus</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((r) => {
            const abierto = expandido === r.cfdi_uuid;
            return (
              <Fragment key={r.cfdi_uuid}>
                <TableRow>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatoFecha(r.fecha_pago)}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium leading-tight">{r.receptor_nombre}</div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {r.receptor_rfc}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {r.nss || '–'}
                  </TableCell>
                  <TableCell className="text-xs">
                    {PERIODICIDAD_LABEL[r.periodicidad_pago ?? ''] ??
                      r.periodicidad_pago ??
                      '–'}
                  </TableCell>
                  <TableCell className="text-center">
                    <Badge
                      variant="secondary"
                      className={cn(
                        'text-[10px]',
                        r.tipo_nomina === 'E'
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-blue-50 text-blue-700',
                      )}
                    >
                      {r.tipo_nomina ?? '–'}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {r.num_dias_pagados}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {formatoMXN(r.total_percepciones)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {formatoMXN(r.total_deducciones)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm font-semibold">
                    {formatoMXN(r.neto)}
                  </TableCell>
                  <TableCell>{badgeEstadoSat(r.estado_sat)}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setExpandido(abierto ? null : r.cfdi_uuid)}
                      title="Ver conceptos"
                    >
                      <Icon
                        icon={abierto ? 'ph:caret-up-light' : 'ph:caret-down-light'}
                        className="size-4"
                      />
                    </Button>
                  </TableCell>
                </TableRow>
                {abierto && (
                  <TableRow>
                    <TableCell colSpan={11} className="bg-muted/30">
                      <ConceptosDrilldown rfc={rfc} uuid={r.cfdi_uuid} recibo={r} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
      <div className="flex items-center justify-between border-t bg-muted/20 px-4 py-2 text-xs text-muted-foreground">
        <div>
          {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} de {total}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => onPage(page - 1)}
          >
            <Icon icon="ph:caret-left-light" className="size-3" />
            Anterior
          </Button>
          <span className="px-2 font-mono">
            {page} / {totalPages}
          </span>
          <Button
            variant="ghost"
            size="sm"
            disabled={page >= totalPages || loading}
            onClick={() => onPage(page + 1)}
          >
            Siguiente
            <Icon icon="ph:caret-right-light" className="size-3" />
          </Button>
        </div>
      </div>
    </Card>
  );
}

const CLASE_LABEL: Record<string, string> = {
  Percepcion: 'Percepción',
  Deduccion: 'Deducción',
  OtroPago: 'Otro pago',
};

function ConceptosDrilldown({
  rfc,
  uuid,
  recibo,
}: {
  rfc: string;
  uuid: string;
  recibo: NominaRecibo;
}) {
  const { apiClient } = useServer();
  const [items, setItems] = useState<NominaConceptoDetalle[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    apiClient
      .procesadorNominaConceptosDeRecibo(rfc, uuid)
      .then((r) => {
        if (mounted) setItems(r.items);
      })
      .catch((e) => {
        if (mounted) setError(mensajeDeError(e));
      });
    return () => {
      mounted = false;
    };
  }, [apiClient, rfc, uuid]);

  if (error) {
    return <div className="p-3 text-xs text-destructive">Error: {error}</div>;
  }
  if (!items) {
    return (
      <div className="flex items-center gap-2 p-3 text-xs text-muted-foreground">
        <Icon icon="ph:circle-notch-light" className="size-3 animate-spin" />
        Cargando conceptos…
      </div>
    );
  }
  if (items.length === 0) {
    return <div className="p-3 text-xs text-muted-foreground">Sin conceptos.</div>;
  }

  return (
    <div className="space-y-2 p-2">
      <div className="grid grid-cols-2 gap-2 text-[11px] text-muted-foreground sm:grid-cols-4">
        <div>
          <span className="font-medium">CURP:</span>{' '}
          <span className="font-mono">{recibo.curp || '–'}</span>
        </div>
        <div>
          <span className="font-medium">SBC:</span>{' '}
          <span className="font-mono">{formatoMXN(recibo.salario_base_cot_apor)}</span>
        </div>
        <div>
          <span className="font-medium">SDI:</span>{' '}
          <span className="font-mono">{formatoMXN(recibo.salario_diario_integrado)}</span>
        </div>
        <div>
          <span className="font-medium">Puesto:</span> {recibo.puesto || '–'}
        </div>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Clase</TableHead>
            <TableHead>Tipo</TableHead>
            <TableHead>Concepto</TableHead>
            <TableHead className="text-right">Gravado</TableHead>
            <TableHead className="text-right">Exento</TableHead>
            <TableHead className="text-right">Importe</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((c, i) => {
            const importe = c.clase === 'Percepcion'
              ? c.importe_gravado + c.importe_exento
              : c.importe;
            return (
              <TableRow key={`${c.clase}-${c.tipo_concepto}-${i}`}>
                <TableCell className="text-xs">
                  {CLASE_LABEL[c.clase] ?? c.clase}
                </TableCell>
                <TableCell className="font-mono text-xs">{c.tipo_concepto}</TableCell>
                <TableCell className="text-xs">{c.concepto ?? '–'}</TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {c.clase === 'Percepcion' ? formatoMXN(c.importe_gravado) : '–'}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {c.clase === 'Percepcion' ? formatoMXN(c.importe_exento) : '–'}
                </TableCell>
                <TableCell className="text-right font-mono text-xs">
                  {formatoMXN(importe)}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

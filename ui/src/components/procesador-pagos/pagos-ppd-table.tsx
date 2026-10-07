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
  FacturaPPD,
  FacturasPPDResponse,
  PagoRelacionadoDetalle,
} from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa activa (los drilldowns consultan SU buffer). */
  rfc: string;
  data: FacturasPPDResponse | null;
  page: number;
  pageSize: number;
  loading: boolean;
  onPage: (p: number) => void;
}

function formatoFecha(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatoMXN(n: number, moneda = 'MXN'): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: moneda || 'MXN',
    minimumFractionDigits: 2,
  }).format(n);
}

function badgeEstadoSat(estado: FacturaPPD['estado_sat']) {
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

const STATUS_BADGE: Record<FacturaPPD['status'], { label: string; cls: string; bg: string }> = {
  sin_complemento: {
    label: 'Sin complemento',
    cls: 'bg-rose-100 text-rose-700',
    bg: 'bg-rose-50/40',
  },
  pago_parcial: {
    label: 'Parcial',
    cls: 'bg-amber-100 text-amber-700',
    bg: 'bg-amber-50/40',
  },
  pagado_completo: {
    label: 'Pagado',
    cls: 'bg-emerald-100 text-emerald-700',
    bg: '',
  },
  sobrante: {
    label: 'Sobrante',
    cls: 'bg-sky-100 text-sky-700',
    bg: 'bg-sky-50/40',
  },
};

export function PagosPPDTable({ rfc, data, page, pageSize, loading, onPage }: Props) {
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
            <TableHead className="w-28">Fecha</TableHead>
            <TableHead>Emisor</TableHead>
            <TableHead>Receptor</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead className="text-right">Pagado</TableHead>
            <TableHead className="text-right">Saldo</TableHead>
            <TableHead className="w-20 text-center">Pagos</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Estatus</TableHead>
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((f) => {
            const status = STATUS_BADGE[f.status];
            const abierto = expandido === f.uuid;
            return (
              <Fragment key={f.uuid}>
                <TableRow className={cn(status.bg)}>
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatoFecha(f.fecha)}
                  </TableCell>
                  <TableCell>
                    <div className="font-medium leading-tight">{f.emisor_nombre}</div>
                    <div className="font-mono text-xs text-muted-foreground">{f.emisor_rfc}</div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium leading-tight">{f.receptor_nombre}</div>
                    <div className="font-mono text-xs text-muted-foreground">{f.receptor_rfc}</div>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {formatoMXN(f.total, f.moneda)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {formatoMXN(f.total_pagado, f.moneda)}
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {formatoMXN(f.saldo_pendiente, f.moneda)}
                  </TableCell>
                  <TableCell className="text-center font-mono text-sm">{f.num_pagos}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className={cn('text-[10px]', status.cls)}>
                      {status.label}
                    </Badge>
                    {f.warnings.length > 0 && (
                      <div className="text-[10px] text-amber-700 mt-0.5">
                        {f.warnings.join(' · ')}
                      </div>
                    )}
                  </TableCell>
                  <TableCell>{badgeEstadoSat(f.estado_sat)}</TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setExpandido(abierto ? null : f.uuid)}
                      title="Ver pagos relacionados"
                      disabled={f.num_pagos === 0}
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
                    <TableCell colSpan={10} className="bg-muted/30">
                      <PagosDetalleDrilldown rfc={rfc} uuid={f.uuid} moneda={f.moneda} />
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

function PagosDetalleDrilldown({
  rfc,
  uuid,
  moneda,
}: {
  rfc: string;
  uuid: string;
  moneda: string;
}) {
  const { apiClient } = useServer();
  const [items, setItems] = useState<PagoRelacionadoDetalle[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    apiClient
      .procesadorPagosDetalleFactura(rfc, uuid)
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
        <Icon icon="ph:circle-notch-light" className="size-3 animate-spin" /> Cargando pagos…
      </div>
    );
  }
  if (items.length === 0) {
    return <div className="p-3 text-xs text-muted-foreground">Sin pagos relacionados.</div>;
  }

  return (
    <div className="space-y-1 p-2">
      <div className="text-xs font-semibold text-ghost">
        Pagos relacionados ({items.length})
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>UUID Complemento</TableHead>
            <TableHead>Fecha pago</TableHead>
            <TableHead>Forma</TableHead>
            <TableHead className="text-center">Parcialidad</TableHead>
            <TableHead className="text-right">Saldo ant.</TableHead>
            <TableHead className="text-right">Pagado</TableHead>
            <TableHead className="text-right">Saldo insoluto</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((p, i) => (
            <TableRow key={`${p.cfdi_pago_uuid}-${i}`}>
              <TableCell className="font-mono text-xs">{p.cfdi_pago_uuid}</TableCell>
              <TableCell className="text-xs">{formatoFecha(p.cfdi_pago_fecha_pago)}</TableCell>
              <TableCell className="text-xs">{p.cfdi_pago_forma || '–'}</TableCell>
              <TableCell className="text-center text-xs">{p.docto_num_parcialidad}</TableCell>
              <TableCell className="text-right font-mono text-xs">
                {formatoMXN(p.docto_imp_saldo_ant, moneda)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {formatoMXN(p.docto_imp_pagado, moneda)}
              </TableCell>
              <TableCell className="text-right font-mono text-xs">
                {formatoMXN(p.docto_imp_saldo_insoluto, moneda)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

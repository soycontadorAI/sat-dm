'use client';

import { Fragment, useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type {
  CfdiDeducible,
  CfdiFlagsPatch,
  CfdiListResponse,
  CfdiRecord,
} from '@/lib/types';
import {
  MatchBadge,
  TONO_BASE_CLASE,
  TONO_CLASES,
  type EtiquetaLista,
} from '@/components/listas-negras/match-badge';
import { cn } from '@/lib/utils';

interface Props {
  data: CfdiListResponse | null;
  page: number;
  pageSize: number;
  loading: boolean;
  onPage: (p: number) => void;
  /** Persiste flags por fila (interruptor DIOT / deducibilidad). */
  onFlags: (uuid: string, patch: CfdiFlagsPatch) => void;
  /** false = la empresa no presenta DIOT (p. ej. RESICO): sin columna DIOT. */
  mostrarDiot?: boolean;
}

/** Override optimista por uuid mientras el PATCH + recarga viajan al agente. */
type FlagsOverride = { incluir_diot?: boolean; deducible?: CfdiDeducible | null };

function formatoFecha(iso: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatoMXN(n: number): string {
  return new Intl.NumberFormat('es-MX', {
    style: 'currency',
    currency: 'MXN',
    minimumFractionDigits: 2,
  }).format(n);
}

const TIPO_LABEL: Record<string, string> = {
  I: 'Ingreso',
  E: 'Egreso',
  P: 'Pago',
  N: 'Nómina',
  T: 'Traslado',
};

function badgeListaNegra(etiqueta: string | null, rfc: string) {
  if (!etiqueta) {
    return (
      <span className="text-xs text-muted-foreground" title={`${rfc} sin validar contra listas negras`}>
        –
      </span>
    );
  }
  // 'EFOS' | 'Aclarado' | '69' | 'Limpio' — MatchBadge ya valida estos valores.
  return <MatchBadge etiqueta={etiqueta as EtiquetaLista} />;
}

// Estatus SAT comparte la paleta tonal de listas negras para que Vigente
// y Limpio sean el mismo verde, Cancelado y EFOS el mismo rojo, etc.
const ESTILOS_ESTATUS: Record<
  NonNullable<CfdiRecord['estado_sat']>,
  { label: string; icon: string; tono: keyof typeof TONO_CLASES }
> = {
  Vigente:         { label: 'Vigente',       icon: 'ph:check-circle-light', tono: 'verde' },
  Cancelado:       { label: 'Cancelado',     icon: 'ph:x-circle-light',     tono: 'rojo' },
  'No encontrado': { label: 'No encontrado', icon: 'ph:warning-light',      tono: 'amber' },
};

function badgeEstado(estado: CfdiRecord['estado_sat']) {
  if (!estado) {
    return (
      <span className={cn(TONO_BASE_CLASE, TONO_CLASES.neutro)}>
        Sin validar
      </span>
    );
  }
  const e = ESTILOS_ESTATUS[estado];
  return (
    <span className={cn(TONO_BASE_CLASE, TONO_CLASES[e.tono])}>
      <Icon icon={e.icon} className="size-3 shrink-0" />
      {e.label}
    </span>
  );
}

export function CfdiTable({
  data,
  page,
  pageSize,
  loading,
  onPage,
  onFlags,
  mostrarDiot = true,
}: Props) {
  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const [expandido, setExpandido] = useState<string | null>(null);
  // La data fresca del agente es la verdad: al llegar, pisa los overrides
  // (en éxito coincide con lo optimista; en error, revierte lo pintado).
  const [overrides, setOverrides] = useState<Record<string, FlagsOverride>>({});
  useEffect(() => setOverrides({}), [data]);

  const aplicarFlags = (uuid: string, patch: CfdiFlagsPatch) => {
    const override: FlagsOverride = {};
    if (patch.incluir_diot !== undefined) override.incluir_diot = patch.incluir_diot;
    if (patch.deducible !== undefined) {
      override.deducible = patch.deducible === 'Sin analizar' ? null : patch.deducible;
    }
    setOverrides((o) => ({ ...o, [uuid]: { ...o[uuid], ...override } }));
    onFlags(uuid, patch);
  };

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
            <TableHead className="w-24">Tipo</TableHead>
            <TableHead>Emisor</TableHead>
            <TableHead>Receptor</TableHead>
            <TableHead className="text-right">Total</TableHead>
            <TableHead>Estatus</TableHead>
            <TableHead>Listas 69/69-B</TableHead>
            <TableHead className="w-36">
              <span title="Clasificación manual de deducibilidad por comprobante.">
                Deducible
              </span>
            </TableHead>
            {mostrarDiot && (
              <TableHead className="w-20">
                <span title="Indica si el comprobante se incluye al generar la DIOT. Por defecto todas las operaciones elegibles pasan.">
                  DIOT
                </span>
              </TableHead>
            )}
            <TableHead className="w-10" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((c) => {
            const hayWarnings = (c.warnings?.length ?? 0) > 0;
            const abierto = expandido === c.uuid;
            const ov = overrides[c.uuid];
            const incluir = ov?.incluir_diot ?? c.incluir_diot;
            const deducible = ov?.deducible !== undefined ? ov.deducible : c.deducible;
            const excluido = mostrarDiot && c.elegible_diot && !incluir;
            return (
              <Fragment key={c.uuid}>
                <TableRow
                  className={cn(
                    hayWarnings && 'bg-amber-50/40',
                    excluido && 'opacity-60',
                  )}
                >
                  <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                    {formatoFecha(c.fecha)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary" className="text-[10px]">
                      {TIPO_LABEL[c.tipo] ?? c.tipo}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium leading-tight">
                      {c.emisor_nombre || '–'}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {c.emisor_rfc}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="font-medium leading-tight">
                      {c.receptor_nombre || '–'}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground">
                      {c.receptor_rfc}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono text-sm">
                    {formatoMXN(c.total)}
                    {c.moneda !== 'MXN' && (
                      <div className="text-[10px] text-muted-foreground">{c.moneda}</div>
                    )}
                  </TableCell>
                  <TableCell>{badgeEstado(c.estado_sat)}</TableCell>
                  <TableCell>{badgeListaNegra(c.emisor_en_lista_negra, c.emisor_rfc)}</TableCell>
                  <TableCell>
                    <Select
                      value={deducible ?? 'Sin analizar'}
                      onValueChange={(v) =>
                        aplicarFlags(c.uuid, {
                          deducible: v as CfdiFlagsPatch['deducible'],
                        })
                      }
                    >
                      <SelectTrigger
                        aria-label="Deducibilidad"
                        className={cn(
                          'h-8 w-33 text-xs font-semibold',
                          deducible === 'Deducible' && 'text-green-600 dark:text-green-500',
                          deducible === 'No deducible' && 'text-red-600 dark:text-red-500',
                          !deducible && 'font-normal italic text-muted-foreground',
                        )}
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Sin analizar">Sin analizar</SelectItem>
                        <SelectItem value="Deducible">Deducible</SelectItem>
                        <SelectItem value="No deducible">No deducible</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  {mostrarDiot && (
                    <TableCell>
                      {c.elegible_diot ? (
                        <Switch
                          size="sm"
                          checked={incluir}
                          onCheckedChange={(v) =>
                            aplicarFlags(c.uuid, { incluir_diot: v })
                          }
                          aria-label="Incluir en la DIOT"
                        />
                      ) : (
                        <span
                          className={cn(TONO_BASE_CLASE, TONO_CLASES.neutro)}
                          title={
                            c.tipo === 'P'
                              ? 'Los complementos de pago no se declaran en la DIOT.'
                              : 'Solo las operaciones recibidas de Ingreso/Egreso se declaran en la DIOT.'
                          }
                        >
                          No aplica
                        </span>
                      )}
                    </TableCell>
                  )}
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setExpandido(abierto ? null : c.uuid)}
                      title="Ver detalle"
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
                    <TableCell colSpan={mostrarDiot ? 10 : 9} className="bg-muted/30">
                      <div className="grid grid-cols-2 gap-4 p-2 text-xs sm:grid-cols-4">
                        <div>
                          <div className="text-muted-foreground">UUID</div>
                          <div className="font-mono">{c.uuid}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Serie / Folio</div>
                          <div className="font-mono">
                            {c.serie || '–'} / {c.folio || '–'}
                          </div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">IVA trasladado</div>
                          <div className="font-mono">{formatoMXN(c.iva_trasladado)}</div>
                        </div>
                        {c.ieps_trasladado > 0 && (
                          <div>
                            <div className="text-muted-foreground">IEPS trasladado</div>
                            <div className="font-mono">{formatoMXN(c.ieps_trasladado)}</div>
                          </div>
                        )}
                        <div>
                          <div className="text-muted-foreground">Retenciones</div>
                          <div className="font-mono">
                            IVA {formatoMXN(c.iva_retenido)} · ISR {formatoMXN(c.isr_retenido)}
                          </div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Método pago</div>
                          <div>{c.metodo_pago || '–'}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Forma pago</div>
                          <div>{c.forma_pago || '–'}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Uso CFDI</div>
                          <div>{c.receptor_uso_cfdi || '–'}</div>
                        </div>
                        <div>
                          <div className="text-muted-foreground">Lugar expedición</div>
                          <div>{c.lugar_expedicion || '–'}</div>
                        </div>
                      </div>
                      {hayWarnings && (
                        <div className="border-t bg-amber-50/60 p-2 text-xs text-amber-900">
                          <div className="font-medium mb-1">Advertencias</div>
                          <ul className="list-disc pl-4 space-y-0.5">
                            {c.warnings.map((w, i) => (
                              <li key={i}>{w}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
      {/* Paginación */}
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

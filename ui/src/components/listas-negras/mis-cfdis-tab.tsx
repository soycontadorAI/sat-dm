'use client';

import Link from 'next/link';
import { useCallback, useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useEmpresas } from '@/hooks/use-empresas';
import { ProcesadorSinEmpresa } from '@/components/shared/procesador-sin-empresa';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Icon } from '@/components/ui/icon';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type {
  EmisoresListasNegrasResponse,
  ListasNegrasMetadata,
  ProcesadorListasNegrasStats,
} from '@/lib/types';

import { MatchBadge, type EtiquetaLista } from './match-badge';
import { MetadataChip } from './metadata-chip';
import { StatsCards } from './stats-cards';
import { mensajeDeError } from '@/lib/errores';

type FiltroEmisor = 'EFOS' | 'Aclarado' | '69' | 'Limpio' | 'SinValidar' | 'todos';

const FILTRO_LABEL: Record<Exclude<FiltroEmisor, 'todos'>, EtiquetaLista | 'SinValidar'> = {
  EFOS: 'EFOS', Aclarado: 'Aclarado', '69': '69', Limpio: 'Limpio', SinValidar: 'SinValidar',
};

export function MisCfdisTab() {
  const { apiClient } = useServer();
  const { empresas, loading: empresasLoading } = useEmpresas();
  const empresaActiva = empresas.find((e) => e.default);
  const rfcActivo = empresaActiva?.rfc ?? null;
  const sinEmpresa = !empresasLoading && rfcActivo === null;
  const [stats, setStats] = useState<ProcesadorListasNegrasStats | null>(null);
  const [metadata, setMetadata] = useState<ListasNegrasMetadata | null>(null);
  const [listado, setListado] = useState<EmisoresListasNegrasResponse | null>(null);
  const [filtro, setFiltro] = useState<FiltroEmisor>('todos');
  const [loading, setLoading] = useState(false);
  const [validating, setValidating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const refrescar = useCallback(async (etiquetaFiltro: FiltroEmisor) => {
    if (!rfcActivo) return;
    setLoading(true);
    setError(null);
    try {
      const [s, l] = await Promise.all([
        apiClient.procesadorListasNegrasStats(rfcActivo, {}),
        apiClient.procesadorListasNegrasPorEmisor(
          rfcActivo,
          etiquetaFiltro === 'todos'
            ? {}
            : { emisor_lista_negra: etiquetaFiltro },
          1, 50,
        ),
      ]);
      setStats(s);
      setListado(l);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setLoading(false);
    }
  }, [apiClient, rfcActivo]);

  useEffect(() => {
    refrescar(filtro);
  }, [filtro, refrescar]);

  async function validar(forceRefresh: boolean) {
    if (!rfcActivo) return;
    setValidating(true);
    setError(null);
    setInfo(null);
    try {
      const r = await apiClient.procesadorValidarListasNegras(rfcActivo, {
        force_refresh: forceRefresh,
      });
      setMetadata(r.metadata);
      if (r.validados === 0) {
        setInfo('Todos los RFCs ya están verificados (válidos por 30 días). Usa "Forzar revalidación" si necesitas volver a consultar.');
      } else {
        setInfo(
          `Validados ${r.validados} RFCs: EFOS ${r.efos}, aclarados ${r.aclarados}, ` +
          `en 69 ${r.lista_69} y limpios ${r.limpios}.`,
        );
      }
      await refrescar(filtro);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setValidating(false);
    }
  }

  const sinDatos = stats && Object.values(stats).every((v) => v === 0);

  // El cruce trabaja sobre el buffer del procesador, que vive POR empresa.
  if (sinEmpresa || !rfcActivo) {
    return <ProcesadorSinEmpresa listo={sinEmpresa} />;
  }

  return (
    <div className="space-y-4">
      {/* Header con acciones */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="text-base">Cruce con mis CFDIs</CardTitle>
              <CardDescription>
                Requiere que tengas comprobantes cargados en{' '}
                <Link href="/comprobantes/cfdi" className="font-medium underline underline-offset-2">
                  Comprobantes
                </Link>
                .
              </CardDescription>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => validar(true)}
                disabled={validating || loading}
                title="Volver a consultar a todos los RFCs"
              >
                <Icon icon="ph:arrows-clockwise-light" className="size-4" />
                Forzar revalidación
              </Button>
              <Button
                size="sm"
                onClick={() => validar(false)}
                disabled={validating || loading}
              >
                {validating ? (
                  <>
                    <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                    Validando…
                  </>
                ) : (
                  <>
                    <Icon icon="ph:shield-check-light" className="size-4" />
                    Validar listas negras
                  </>
                )}
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {error && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-light" className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {info && !error && (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertDescription>{info}</AlertDescription>
        </Alert>
      )}

      <StatsCards stats={stats} loading={loading} />

      {/* Tabla filtrada */}
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <CardTitle className="text-base">CFDIs por estado del emisor</CardTitle>
              <CardDescription>
                Filtra la lista por etiqueta del emisor.
              </CardDescription>
            </div>
            <Select value={filtro} onValueChange={(v) => setFiltro(v as FiltroEmisor)}>
              <SelectTrigger className="w-45">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="EFOS">EFOS</SelectItem>
                <SelectItem value="Aclarado">Aclarados</SelectItem>
                <SelectItem value="69">En lista 69</SelectItem>
                <SelectItem value="Limpio">Limpios</SelectItem>
                <SelectItem value="SinValidar">Sin validar</SelectItem>
                <SelectItem value="todos">Todos</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {sinDatos ? (
            <div className="p-10 text-center text-sm text-muted-foreground">
              No hay CFDIs cargados en el procesador.{' '}
              <Link href="/comprobantes/cfdi" className="font-medium text-foreground underline underline-offset-2">
                Carga tus XMLs primero
              </Link>
              {' '}y vuelve a esta página para validar.
            </div>
          ) : listado && listado.items.length === 0 ? (
            <div className="p-10 text-center text-sm text-muted-foreground">
              No hay emisores con el filtro seleccionado.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Emisor</TableHead>
                  <TableHead>RFC</TableHead>
                  <TableHead>Resultado</TableHead>
                  <TableHead className="text-right">CFDIs</TableHead>
                  <TableHead className="text-right">Total</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {listado?.items.map((emisor) => {
                  const etiqueta = (emisor.emisor_en_lista_negra ?? 'Limpio') as EtiquetaLista;
                  return (
                    <TableRow key={emisor.emisor_rfc}>
                      <TableCell className="text-sm">{emisor.emisor_nombre || '–'}</TableCell>
                      <TableCell className="font-mono text-xs">{emisor.emisor_rfc}</TableCell>
                      <TableCell>
                        {emisor.emisor_en_lista_negra ? (
                          <MatchBadge etiqueta={etiqueta} />
                        ) : (
                          <span className="text-xs text-muted-foreground">Sin validar</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right text-sm tabular-nums">
                        {emisor.num_cfdis.toLocaleString('es-MX')}
                      </TableCell>
                      <TableCell className="text-right text-sm font-medium tabular-nums">
                        {emisor.total_acumulado.toLocaleString('es-MX', {
                          style: 'currency', currency: 'MXN',
                        })}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
        {listado && listado.items.length > 0 && (
          <div className="border-t px-4 py-2 text-xs text-muted-foreground">
            {listado.total} {listado.total === 1 ? 'emisor' : 'emisores'} (mostrando primeros{' '}
            {Math.min(listado.items.length, listado.page_size)}, ordenado por total descendente)
          </div>
        )}
      </Card>
    </div>
  );
}

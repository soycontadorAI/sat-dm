'use client';

import { useCallback, useMemo, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
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
import { etiquetaMetodo, type MetodoPortal } from '@/lib/empresa-metodo';
import { abrirODescargar, iconoAbrir, tituloAbrir } from '@/lib/descargas';
import type { HistorialItem } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa cuyo historial portal queremos mostrar. */
  rfc: string;
  /**
   * Historial completo (todas las empresas, todos los canales). El componente
   * filtra a CFDIs vía portal (ciec/fiel) de la empresa indicada por `rfc`.
   * Se pasa por prop (no se hace fetch interno) para que el caller pueda
   * compartir la fuente con `useHistorial().refresh()` tras un job que terminó.
   */
  descargas: HistorialItem[];
  /** Cuántas descargas mostrar (default 5). */
  max?: number;
}

function fechaLegible(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('es-MX', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/**
 * Listado compacto de descargas previas hechas por el portal (scraping) para
 * la empresa activa. Hermana del componente `SolicitudesList` que usa el flujo
 * WS — aquí cada fila es una descarga ya completada (no hay polling ni estado).
 */
export function PortalDescargasRecientes({ rfc, descargas, max = 5 }: Props) {
  const { apiClient } = useServer();
  const [accionBusy, setAccionBusy] = useState<string | null>(null);
  const [accionError, setAccionError] = useState<string | null>(null);

  const items = useMemo(() => {
    return descargas
      .filter(
        (d) =>
          d.rfc === rfc &&
          d.tipo === 'cfdi' &&
          (d.canal === 'ciec' || d.canal === 'fiel'),
      )
      .slice(0, max);
  }, [descargas, rfc, max]);

  const abrirCarpeta = useCallback(
    async (ruta: string) => {
      if (!ruta) return;
      setAccionBusy(ruta);
      setAccionError(null);
      try {
        await abrirODescargar(apiClient, ruta, 'carpeta');
      } catch (e) {
        setAccionError(mensajeDeError(e));
      } finally {
        setAccionBusy(null);
      }
    },
    [apiClient],
  );

  if (items.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon icon="ph:clock-counter-clockwise-light" className="size-4" />
          Descargas recientes
        </CardTitle>
        <CardDescription>Últimas descargas del portal para esta empresa.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        {accionError && (
          <div className="px-4 pb-3">
            <Alert variant="destructive">
              <AlertDescription>{accionError}</AlertDescription>
            </Alert>
          </div>
        )}
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Fecha</TableHead>
              <TableHead>Descarga</TableHead>
              <TableHead className="text-right">CFDIs</TableHead>
              <TableHead className="text-right">Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((d, i) => (
              <DescargaPortalRow
                key={`${d.timestamp}-${i}`}
                d={d}
                busy={accionBusy === d.ruta}
                onAbrirCarpeta={() => abrirCarpeta(d.ruta)}
              />
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

interface RowProps {
  d: HistorialItem;
  busy: boolean;
  onAbrirCarpeta: () => void;
}

function DescargaPortalRow({ d, busy, onAbrirCarpeta }: RowProps) {
  const canal = d.canal as MetodoPortal; // ya filtrado a 'fiel' | 'ciec'
  return (
    <TableRow>
      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
        {fechaLegible(d.timestamp)}
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-0.5">
          <span className="text-sm">{d.descripcion || 'CFDIs'}</span>
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Icon
              icon={canal === 'fiel' ? 'ph:shield-check-light' : 'ph:key-light'}
              className="size-3"
            />
            {etiquetaMetodo(canal)}
          </span>
        </div>
      </TableCell>
      <TableCell className="text-right font-mono text-sm">{d.total ?? '–'}</TableCell>
      <TableCell className="text-right">
        {d.ruta && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onAbrirCarpeta}
            disabled={busy}
            title={tituloAbrir('carpeta')}
          >
            <Icon
              icon={busy ? 'ph:circle-notch-light' : iconoAbrir('carpeta')}
              className={busy ? 'size-4 animate-spin' : 'size-4'}
            />
          </Button>
        )}
      </TableCell>
    </TableRow>
  );
}

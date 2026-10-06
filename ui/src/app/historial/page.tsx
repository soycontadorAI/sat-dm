'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

import { useHistorial } from '@/hooks/use-historial';
import { useEmpresas } from '@/hooks/use-empresas';
import { useServer } from '@/providers/server-provider';
import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
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
import { abrirODescargar, iconoAbrir, tituloAbrir } from '@/lib/descargas';
import type { CanalDescarga, HistorialItem, TipoDescarga } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

const TIPO_META: Record<TipoDescarga, { label: string; icon: string }> = {
  cfdi: { label: 'CFDIs', icon: 'ph:download-simple-light' },
  metadata: { label: 'Listado', icon: 'ph:database-light' },
  constancia: { label: 'Constancia', icon: 'ph:file-text-light' },
  opinion: { label: 'Opinión 32-D', icon: 'ph:seal-check-light' },
};

const CANAL_LABEL: Record<CanalDescarga, string> = {
  ws: 'Web Service',
  ciec: 'Contraseña',
  fiel: 'e.firma',
};

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

export default function HistorialPage() {
  const { descargas, loading, error, refresh } = useHistorial();
  const { empresas } = useEmpresas();
  const { apiClient } = useServer();
  const [accionError, setAccionError] = useState<string | null>(null);

  // Empresa activa = la marcada como default en el catálogo del agente. El
  // historial solo muestra sus descargas; para ver otra, actívala en /empresas.
  const empresaActiva = empresas.find((e) => e.default);

  const abrir = useCallback(
    async (ruta: string, modo: 'carpeta' | 'archivo') => {
      setAccionError(null);
      try {
        await abrirODescargar(apiClient, ruta, modo);
      } catch (e) {
        setAccionError(mensajeDeError(e));
      }
    },
    [apiClient],
  );

  const filtradas = empresaActiva
    ? descargas.filter((d) => d.rfc === empresaActiva.rfc)
    : [];

  // Render incremental: el historial crece sin tope con cada descarga y pintar
  // cientos de filas de golpe congela equipos modestos. Se muestran 50 y un
  // botón "Mostrar más"; al cambiar de empresa se reinicia.
  const PAGE = 50;
  const [visibleCount, setVisibleCount] = useState(PAGE);
  useEffect(() => setVisibleCount(PAGE), [empresaActiva?.rfc]);
  const visibles = filtradas.slice(0, visibleCount);

  const description = empresaActiva
    ? `Descargas completadas de ${empresaActiva.nombre} (${empresaActiva.rfc}).`
    : 'Selecciona una empresa activa en Empresas para ver su historial.';

  return (
    <div className="space-y-6">
      <PageHeading
        title="Historial"
        description={description}
        action={
          <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
            {loading ? (
              <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
            ) : (
              <Icon icon="ph:arrows-clockwise-light" className="size-4" />
            )}
            Actualizar
          </Button>
        }
      />

      {(error || accionError) && (
        <Alert variant="destructive">
          <AlertDescription>{accionError || error}</AlertDescription>
        </Alert>
      )}

      {!empresaActiva ? (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertDescription>
            {/* Un solo <p>: AlertDescription es grid y apilaría texto y Link. */}
            <p>
              No hay empresa activa. Actívala desde{' '}
              <Link href="/empresas" className="font-medium underline underline-offset-2">
                Empresas
              </Link>
              .
            </p>
          </AlertDescription>
        </Alert>
      ) : filtradas.length === 0 ? (
        <Card className="flex flex-col items-center gap-2 p-10 text-center">
          <Icon icon="ph:clock-counter-clockwise-light" className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Aún no hay descargas registradas</p>
          <p className="text-sm text-muted-foreground">
            Cuando completes una descarga (Contraseña del SAT o Web Service) aparecerá aquí.
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
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
              {visibles.map((d, i) => (
                <DescargaRow
                  key={`${d.rfc}-${d.timestamp}-${i}`}
                  d={d}
                  onAbrir={abrir}
                />
              ))}
            </TableBody>
          </Table>
          {filtradas.length > visibleCount && (
            <div className="border-t border-border p-2 text-center">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setVisibleCount((n) => n + PAGE)}
              >
                Mostrar más ({filtradas.length - visibleCount} restantes)
              </Button>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function DescargaRow({
  d,
  onAbrir,
}: {
  d: HistorialItem;
  onAbrir: (ruta: string, modo: 'carpeta' | 'archivo') => Promise<void>;
}) {
  const meta = TIPO_META[d.tipo] ?? { label: d.tipo, icon: 'ph:download-simple-light' };
  const [busy, setBusy] = useState<'carpeta' | 'archivo' | null>(null);

  // Un PDF (constancia/opinión) se puede abrir directo; los CFDIs son una carpeta.
  const esPdf =
    (d.tipo === 'constancia' || d.tipo === 'opinion') &&
    !!d.ruta &&
    d.ruta.toLowerCase().endsWith('.pdf');

  async function abrir(modo: 'carpeta' | 'archivo') {
    setBusy(modo);
    try {
      await onAbrir(d.ruta, modo);
    } finally {
      setBusy(null);
    }
  }

  return (
    <TableRow>
      <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
        {fechaLegible(d.timestamp)}
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="gap-1">
              <Icon icon={meta.icon} className="size-3" /> {meta.label}
            </Badge>
            <span className="text-xs text-muted-foreground">{CANAL_LABEL[d.canal] ?? d.canal}</span>
          </div>
          {d.descripcion && (
            <span className="text-xs text-muted-foreground">{d.descripcion}</span>
          )}
        </div>
      </TableCell>
      <TableCell className="text-right font-mono text-sm">
        {d.total ?? '–'}
      </TableCell>
      <TableCell className="text-right">
        {d.ruta && (
          <div className="inline-flex items-center gap-1">
            {esPdf && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => abrir('archivo')}
                disabled={busy !== null}
                title={tituloAbrir('archivo')}
              >
                {busy === 'archivo' ? (
                  <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                ) : (
                  <Icon icon={iconoAbrir('archivo')} className="size-4" />
                )}
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => abrir('carpeta')}
              disabled={busy !== null}
              title={tituloAbrir('carpeta')}
            >
              {busy === 'carpeta' ? (
                <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
              ) : (
                <Icon icon={iconoAbrir('carpeta')} className="size-4" />
              )}
            </Button>
          </div>
        )}
      </TableCell>
    </TableRow>
  );
}

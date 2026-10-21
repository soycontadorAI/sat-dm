'use client';

import { useCallback, useEffect, useState } from 'react';
import { format, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { ResourceList } from '@/components/shared/resource-list';
import { useAuth } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';
import { mensajeDeError } from '@/lib/errores';
import { formatCurrency, formatNumber } from '@/lib/formatting';
import { clasePunto, llevaTotal, tienePiloto, nombreDireccion, textoEstado, textoSolicitud } from '@/lib/calendario';
import type { CalendarioCelda, CalendarioDia, DireccionCfdi } from '@/lib/types';
import { cn } from '@/lib/utils';

const LIMITE_LISTA = 200;

function tituloFecha(fecha: string): string {
  const t = format(parseISO(fecha), "EEEE d 'de' MMMM 'de' yyyy", { locale: es });
  return t.charAt(0).toUpperCase() + t.slice(1);
}

function TarjetaDireccion({
  dir,
  c,
  onReintentar,
  reintentando,
}: {
  dir: DireccionCfdi;
  c: CalendarioCelda | undefined;
  /** Solo con piloto; sin él no hay botón. */
  onReintentar?: (dir: DireccionCfdi) => void;
  reintentando?: boolean;
}) {
  const estado = c?.estado ?? 'pendiente';
  return (
    <div className="min-w-0 space-y-2 rounded-lg border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-bold tracking-tight">{nombreDireccion(dir)}</span>
        <span className="inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium">
          <span className={cn('size-2 rounded-full', clasePunto(estado))} />
          {textoEstado(estado)}
        </span>
      </div>
      <dl className="space-y-0.5 text-xs text-muted-foreground">
        <div className="flex justify-between">
          <dt>En la base</dt>
          <dd className="font-medium tabular-nums text-foreground">{formatNumber(c?.total_bd ?? 0)}</dd>
        </div>
        {c?.total_sat != null && (
          <div className="flex justify-between">
            <dt>SAT</dt>
            <dd className="font-medium tabular-nums text-foreground">{formatNumber(c.total_sat)}</dd>
          </div>
        )}
        {c?.intentos ? (
          <div className="flex justify-between">
            <dt>Intentos</dt>
            <dd className="font-medium tabular-nums text-foreground">{c.intentos}</dd>
          </div>
        ) : null}
      </dl>
      {(estado === 'error' || estado === 'diferencia') && (c?.error_mensaje || c?.error_codigo) && (
        <p
          className={cn(
            'text-xs [overflow-wrap:anywhere]',
            estado === 'error' ? 'text-destructive' : 'text-muted-foreground',
          )}
        >
          {c.error_codigo ? `${c.error_codigo}: ` : ''}
          {c.error_mensaje}
        </p>
      )}
      {onReintentar && (estado === 'error' || estado === 'diferencia') && (
        <Button size="sm" variant="outline" disabled={reintentando} onClick={() => onReintentar(dir)}>
          <Icon
            icon={reintentando ? 'ph:circle-notch-light' : 'ph:arrow-clockwise-light'}
            className={cn('mr-1.5 size-3.5', reintentando && 'animate-spin')}
          />
          Reintentar
        </Button>
      )}
      {!llevaTotal(estado) && estado === 'pendiente' && (
        <p className="text-xs text-muted-foreground">Nadie lo ha pedido todavía.</p>
      )}
    </div>
  );
}

function contraparte(c: CalendarioDia['cfdis'][number]): string {
  return c.direccion === 'E'
    ? c.receptor_nombre || c.receptor_rfc || ''
    : c.emisor_nombre || c.emisor_rfc || '';
}

interface Props {
  rfc: string;
  /** null = cerrado. */
  fecha: string | null;
  onClose: () => void;
  /** Tras reintentar: el padre recarga el calendario. */
  onCambio?: () => void;
}

export function DiaDialog({ rfc, fecha, onClose, onCambio }: Props) {
  const { apiClient } = useServer();
  const { license } = useAuth();
  const conPiloto = tienePiloto(license);
  const [reintentando, setReintentando] = useState<DireccionCfdi | null>(null);
  const [datos, setDatos] = useState<CalendarioDia | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!fecha) return;
    let vivo = true;
    setDatos(null);
    setError(null);
    setCargando(true);
    apiClient
      .calendarioDia(rfc, fecha)
      .then((d) => vivo && setDatos(d))
      .catch((e) => vivo && setError(mensajeDeError(e)))
      .finally(() => vivo && setCargando(false));
    return () => {
      vivo = false;
    };
  }, [apiClient, rfc, fecha]);

  const reintentar = useCallback(
    async (dir: DireccionCfdi) => {
      if (!fecha) return;
      setReintentando(dir);
      try {
        await apiClient.calendarioReintentar(rfc, fecha, dir);
        toast.success('Se volvió a pedir al SAT');
        onCambio?.();
        setDatos(await apiClient.calendarioDia(rfc, fecha));
      } catch (e) {
        toast.error(mensajeDeError(e));
      } finally {
        setReintentando(null);
      }
    },
    [apiClient, rfc, fecha, onCambio],
  );

  return (
    <Dialog open={fecha !== null} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[85vh] grid-cols-1 overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{fecha ? tituloFecha(fecha) : ''}</DialogTitle>
          <DialogDescription>Lo que hay en la base para este día y cómo llegó.</DialogDescription>
        </DialogHeader>

        {cargando && (
          <div className="space-y-3" aria-busy>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="h-24 animate-pulse rounded-lg bg-secondary/60" />
              <div className="h-24 animate-pulse rounded-lg bg-secondary/60" />
            </div>
            <div className="h-32 animate-pulse rounded-lg bg-secondary/60" />
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <Icon icon="ph:warning-circle-light" className="size-4" />
            <AlertTitle>No se pudo cargar el día</AlertTitle>
            <AlertDescription>
              <p>{error}</p>
            </AlertDescription>
          </Alert>
        )}

        {datos && (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
              <TarjetaDireccion
                dir="E"
                c={datos.E}
                onReintentar={conPiloto ? reintentar : undefined}
                reintentando={reintentando === 'E'}
              />
              <TarjetaDireccion
                dir="R"
                c={datos.R}
                onReintentar={conPiloto ? reintentar : undefined}
                reintentando={reintentando === 'R'}
              />
            </div>

            <section className="space-y-2">
              <h3 className="text-sm font-bold tracking-tight">Solicitudes al SAT</h3>
              {datos.solicitudes.length === 0 ? (
                <p className="text-sm text-muted-foreground">Ninguna solicitud cubre este día.</p>
              ) : (
                <ResourceList
                  items={datos.solicitudes}
                  getKey={(s) => s.id_solicitud}
                  columns={[
                    {
                      key: 'id',
                      header: 'Solicitud',
                      width: 'w-24',
                      render: (s) => <span className="font-mono text-xs text-muted-foreground">{s.id_solicitud.slice(0, 8)}</span>,
                    },
                    {
                      key: 'tipo',
                      header: 'Tipo',
                      width: 'w-24',
                      render: (s) => (
                        <Badge variant="outline">{s.tipo_comprobante === 'E' ? 'Emitidos' : 'Recibidos'}</Badge>
                      ),
                    },
                    {
                      key: 'rango',
                      header: 'Periodo',
                      render: (s) => (
                        <span className="text-xs tabular-nums">
                          {s.fecha_inicio} a {s.fecha_fin}
                        </span>
                      ),
                    },
                    {
                      key: 'estado',
                      header: 'Estado',
                      width: 'w-56',
                      render: (s) => (
                        <span className="block text-xs">
                          <span className="font-medium">{textoSolicitud(s.estado)}</span>
                          {s.numero_cfdis != null && (
                            <span className="text-muted-foreground"> · {formatNumber(s.numero_cfdis)} CFDI</span>
                          )}
                          {s.mensaje && <span className="block truncate text-muted-foreground">{s.mensaje}</span>}
                        </span>
                      ),
                    },
                  ]}
                />
              )}
            </section>

            <section className="space-y-2">
              <h3 className="text-sm font-bold tracking-tight">
                Comprobantes{' '}
                <span className="font-normal text-muted-foreground">({formatNumber(datos.cfdis_total)})</span>
              </h3>
              {datos.cfdis.length === 0 ? (
                <p className="text-sm text-muted-foreground">No hay comprobantes en la base para este día.</p>
              ) : (
                <div className="space-y-1">
                  <ResourceList
                    items={datos.cfdis.slice(0, LIMITE_LISTA)}
                    // Una autofactura sale en emitidos y en recibidos: la llave lleva la dirección.
                    getKey={(c) => `${c.direccion}-${c.uuid}`}
                    columns={[
                      {
                        key: 'folio',
                        header: 'Folio',
                        width: 'w-28',
                        render: (c) => (
                          <span className="text-xs">
                            {[c.serie, c.folio].filter(Boolean).join('-') || c.uuid.slice(0, 8)}
                          </span>
                        ),
                      },
                      {
                        key: 'tipo',
                        header: 'Tipo',
                        width: 'w-28',
                        render: (c) => (
                          <span className="text-xs">
                            {nombreDireccion(c.direccion)}
                            {c.tipo ? ` · ${c.tipo}` : ''}
                          </span>
                        ),
                      },
                      {
                        key: 'contraparte',
                        header: 'Contraparte',
                        render: (c) => <span className="block truncate text-xs">{contraparte(c)}</span>,
                      },
                      {
                        key: 'total',
                        header: 'Total',
                        width: 'w-32',
                        align: 'right',
                        render: (c) => (
                          <span className="text-xs tabular-nums">
                            {formatCurrency(c.total)}
                            {c.moneda && c.moneda !== 'MXN' ? ` ${c.moneda}` : ''}
                          </span>
                        ),
                      },
                      {
                        key: 'estado_sat',
                        header: 'Estado SAT',
                        width: 'w-24',
                        hideOnMobile: true,
                        render: (c) => <span className="text-xs">{c.estado_sat ?? ''}</span>,
                      },
                    ]}
                  />
                  {datos.cfdis_total > LIMITE_LISTA && (
                    <p className="px-1 text-xs text-muted-foreground">
                      y {formatNumber(datos.cfdis_total - LIMITE_LISTA)} más
                    </p>
                  )}
                </div>
              )}
            </section>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

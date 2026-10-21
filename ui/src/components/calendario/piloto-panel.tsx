'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { es } from 'date-fns/locale';
import { toast } from 'sonner';

import { ResourceList } from '@/components/shared/resource-list';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { useServer } from '@/providers/server-provider';
import { mensajeDeError } from '@/lib/errores';
import { esWeb } from '@/lib/modo';
import {
  avisosSinLeer,
  desdeInicial,
  empresasVisibles,
  etiquetaEstado,
  historialTerminado,
  infoAviso,
  mesesDisponibles,
  porcentajeHistorial,
  textoCierre,
  textoEmpezados,
  textoHistorial,
  textoHistorialEmpresa,
  textoIncluidas,
  textoPausa,
  textoProximaPasada,
} from '@/lib/piloto';
import type { PilotoEmpresa, PilotoEstado, PilotoHistorial } from '@/lib/types';
import { cn } from '@/lib/utils';

const REFRESCO_MS = 60_000;
const SIN_HISTORIAL = 'ninguno';
const DIAS_CIERRE = Array.from({ length: 28 }, (_, i) => i + 1);

function fechaRelativa(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: es });
  } catch {
    return '';
  }
}

function SelectorDia({
  value,
  onChange,
  disabled,
}: {
  value: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  return (
    <Select value={String(value)} onValueChange={(v) => onChange(Number(v))} disabled={disabled}>
      <SelectTrigger size="sm" className="w-20" aria-label="Día de cierre">
        <SelectValue />
      </SelectTrigger>
      <SelectContent className="max-h-64">
        {DIAS_CIERRE.map((d) => (
          <SelectItem key={d} value={String(d)}>
            {d}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SelectorMes({
  historial,
  value,
  onChange,
  disabled,
  conVacio,
}: {
  historial: PilotoHistorial;
  /** "YYYY-MM-01" o '' (sin elegir). */
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  /** Ofrece la opción de no llenar historial (diálogo de activación). */
  conVacio?: boolean;
}) {
  const opciones = mesesDisponibles(historial.minimo, historial.maximo);
  return (
    <Select
      value={value || (conVacio ? SIN_HISTORIAL : '')}
      onValueChange={(v) => onChange(v === SIN_HISTORIAL ? '' : v)}
      disabled={disabled}
    >
      <SelectTrigger size="sm" className="w-36" aria-label="Llenar historial desde">
        <SelectValue placeholder="Elige un mes" />
      </SelectTrigger>
      <SelectContent className="max-h-64">
        {conVacio && <SelectItem value={SIN_HISTORIAL}>No llenar</SelectItem>}
        {opciones.map((o) => (
          <SelectItem key={o.valor} value={o.valor}>
            {o.etiqueta}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function pastilla(etiqueta: string) {
  const clase =
    etiqueta === 'Activa'
      ? 'bg-success/10 text-success'
      : etiqueta === 'Pausada'
        ? 'bg-warning/10 text-warning'
        : 'bg-secondary text-muted-foreground';
  return (
    <span className={cn('inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold', clase)}>
      {etiqueta}
    </span>
  );
}

export function PilotoPanel() {
  const { apiClient, isConnected } = useServer();
  const [estado, setEstado] = useState<PilotoEstado | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activarOpen, setActivarOpen] = useState(false);
  const [empresasOpen, setEmpresasOpen] = useState(false);
  const [diaNuevo, setDiaNuevo] = useState(5);
  const [histNuevo, setHistNuevo] = useState('');
  const [histElegido, setHistElegido] = useState('');
  const [confirmarDetener, setConfirmarDetener] = useState(false);
  const [cambiarHist, setCambiarHist] = useState(false);
  const [ocupado, setOcupado] = useState(false);
  const [errorActivar, setErrorActivar] = useState<string | null>(null);
  const [ahora, setAhora] = useState(() => new Date());
  const refrescoTarde = useRef<ReturnType<typeof setTimeout> | null>(null);

  const cargar = useCallback(async () => {
    try {
      const e = await apiClient.pilotoEstado();
      setEstado(e);
      setError(null);
      setAhora(new Date());
    } catch (err) {
      setError(mensajeDeError(err));
    }
  }, [apiClient]);

  useEffect(() => {
    if (!isConnected) return;
    void cargar();
    const t = setInterval(() => void cargar(), REFRESCO_MS);
    return () => clearInterval(t);
  }, [cargar, isConnected]);

  useEffect(
    () => () => {
      if (refrescoTarde.current) clearTimeout(refrescoTarde.current);
    },
    [],
  );

  if (!estado) {
    if (!error) return <div className="h-20 animate-pulse rounded-xl bg-secondary/60" />;
    return (
      <p className="rounded-xl border bg-card px-4 py-3 text-xs text-muted-foreground">
        Descarga automática: {error}
      </p>
    );
  }

  if (!estado.disponible) {
    return (
      <p className="rounded-xl border bg-card px-4 py-3 text-xs text-muted-foreground">
        La descarga automática no está disponible en esta instalación.
      </p>
    );
  }

  const etiqueta = etiquetaEstado(estado);
  const cierre = textoCierre(estado.cierre);
  const pausa = textoPausa(estado.pausado_por);
  const sinLeer = avisosSinLeer(estado.avisos);
  const conError = estado.ejecuciones.filter((x) => x.estado === 'error' && x.error_mensaje);
  const visibles = empresasVisibles(estado.empresas);

  const abrirActivar = () => {
    setDiaNuevo(estado.dia_cierre || 5);
    setHistNuevo(desdeInicial(estado.historial));
    setErrorActivar(null);
    setActivarOpen(true);
  };

  const aplicar = async (cfg: { activo?: boolean; dia_cierre?: number; historial_desde?: string | null }, okMsg?: string) => {
    setOcupado(true);
    try {
      setEstado(await apiClient.pilotoConfig(cfg));
      if (okMsg) toast.success(okMsg);
      return true;
    } catch (e) {
      toast.error(mensajeDeError(e));
      return false;
    } finally {
      setOcupado(false);
    }
  };

  const activar = async () => {
    setOcupado(true);
    setErrorActivar(null);
    try {
      setEstado(
        await apiClient.pilotoConfig({
          activo: true,
          dia_cierre: diaNuevo,
          // "No llenar" detiene el historial de forma explícita.
          historial_desde: histNuevo || null,
        }),
      );
      setActivarOpen(false);
      toast.success('Descarga automática activada');
    } catch (e) {
      setErrorActivar(mensajeDeError(e));
    } finally {
      setOcupado(false);
    }
  };

  const alternar = (v: boolean) => {
    if (v) abrirActivar();
    else void aplicar({ activo: false }, 'Descarga automática pausada');
  };

  const llenarHistorial = async () => {
    if (!histElegido) return;
    if (await aplicar({ historial_desde: histElegido }, 'Historial en marcha')) {
      setHistElegido('');
      setCambiarHist(false);
    }
  };

  const detenerHistorial = async () => {
    setConfirmarDetener(false);
    await aplicar({ historial_desde: null }, 'Historial detenido');
  };

  const buscarAhora = async () => {
    try {
      await apiClient.pilotoCorrer();
      toast.info('Buscando pendientes…');
      if (refrescoTarde.current) clearTimeout(refrescoTarde.current);
      refrescoTarde.current = setTimeout(() => void cargar(), 5_000);
    } catch (e) {
      toast.error(mensajeDeError(e));
    }
  };

  const cambiarEmpresa = async (emp: PilotoEmpresa, incluida: boolean) => {
    // Optimista; si falla se recarga el estado real.
    setEstado((s) =>
      s ? { ...s, empresas: s.empresas.map((x) => (x.rfc === emp.rfc ? { ...x, incluida } : x)) } : s,
    );
    try {
      await apiClient.pilotoEmpresa(emp.rfc, incluida);
      void cargar();
    } catch (e) {
      toast.error(mensajeDeError(e));
      void cargar();
    }
  };

  const marcarLeidos = async (ids?: number[]) => {
    try {
      await apiClient.pilotoAvisosLeidos(ids);
      await cargar();
    } catch (e) {
      toast.error(mensajeDeError(e));
    }
  };

  return (
    <section className="space-y-3 rounded-xl border bg-card p-4" aria-label="Descarga automática">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Icon icon="ph:sparkle-light" className="size-4 text-primary" />
          <h2 className="text-sm font-bold tracking-tight">Descarga automática</h2>
          {pastilla(etiqueta)}
        </div>
        <div className="flex items-center gap-2">
          {!estado.activo && (
            <Button size="sm" onClick={abrirActivar}>
              Activar
            </Button>
          )}
          <Switch
            checked={estado.activo}
            onCheckedChange={alternar}
            disabled={ocupado}
            aria-label={estado.activo ? 'Pausar la descarga automática' : 'Activar la descarga automática'}
          />
        </div>
      </div>

      {!estado.activo && (
        <p className="text-sm text-muted-foreground">
          Cada madrugada pide al SAT tus CFDI recientes, verifica cada mes contra el SAT y avisa de
          las cancelaciones. Tú decides cuándo empieza.
        </p>
      )}

      {pausa && (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertDescription>
            <p>
              {pausa}
              {estado.pausado_por === 'licencia' && (
                <>
                  {' '}
                  <Link href="/suscripcion" className="font-medium underline underline-offset-2">
                    Ver planes
                  </Link>
                </>
              )}
            </p>
          </AlertDescription>
        </Alert>
      )}

      {estado.activo && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <span className="inline-flex items-center gap-1.5">
            <Icon icon="ph:clock-light" className="size-4 text-muted-foreground" />
            Próxima pasada: {textoProximaPasada(estado.proxima_pasada, ahora)}
          </span>
          {cierre && <span>{cierre}</span>}
          <button
            type="button"
            onClick={() => setEmpresasOpen(true)}
            className="font-medium underline underline-offset-2 hover:text-primary"
          >
            {textoIncluidas(estado.empresas)}
          </button>
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            Cierre el día
            <SelectorDia
              value={estado.dia_cierre}
              disabled={ocupado}
              onChange={(n) => void aplicar({ dia_cierre: n }, `Cierre el día ${n}`)}
            />
          </span>
          <Button size="sm" variant="outline" onClick={buscarAhora} disabled={estado.pausado_por !== null}>
            <Icon icon="ph:magnifying-glass-light" className="mr-1.5 size-3.5" />
            Buscar ahora
          </Button>
        </div>
      )}

      {estado.activo && estado.historial && (
        <div className="space-y-2 rounded-lg border px-3 py-2.5">
          <h3 className="text-xs font-bold uppercase tracking-wide text-muted-foreground">Historial</h3>
          {estado.historial.desde && !cambiarHist ? (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm">
                  {textoHistorial(estado.historial)}
                </p>
                {confirmarDetener ? (
                  <span className="flex items-center gap-2 text-xs">
                    No se piden meses nuevos.
                    <Button size="xs" variant="outline" onClick={() => void detenerHistorial()} disabled={ocupado}>
                      Detener
                    </Button>
                    <Button size="xs" variant="ghost" onClick={() => setConfirmarDetener(false)}>
                      Cancelar
                    </Button>
                  </span>
                ) : historialTerminado(estado.historial) ? (
                  <Button size="xs" variant="outline" onClick={() => setCambiarHist(true)} disabled={ocupado}>
                    Cambiar mes
                  </Button>
                ) : (
                  <Button size="xs" variant="outline" onClick={() => setConfirmarDetener(true)} disabled={ocupado}>
                    Detener
                  </Button>
                )}
              </div>
              <div
                className="h-1 overflow-hidden rounded-full bg-secondary"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={porcentajeHistorial(estado.historial)}
                aria-label="Avance del historial"
              >
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${porcentajeHistorial(estado.historial)}%` }}
                />
              </div>
            </>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="text-muted-foreground">Llenar historial desde</span>
                <SelectorMes
                  historial={estado.historial}
                  value={histElegido}
                  onChange={setHistElegido}
                  disabled={ocupado}
                />
                <Button size="sm" onClick={() => void llenarHistorial()} disabled={ocupado || !histElegido}>
                  Llenar historial
                </Button>
                {cambiarHist && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      setCambiarHist(false);
                      setHistElegido('');
                    }}
                  >
                    Cancelar
                  </Button>
                )}
              </div>
              {textoEmpezados(estado.historial) && (
                <p className="text-xs text-muted-foreground">{textoEmpezados(estado.historial)}</p>
              )}
            </>
          )}
          <p className="text-xs text-muted-foreground">
            Se pide mes por mes, del más reciente al más antiguo, a ritmo pausado para no saturar al SAT
            (un mes por empresa por día).
          </p>
        </div>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}

      {sinLeer.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold uppercase tracking-wide text-muted-foreground">Avisos</h3>
            {sinLeer.length > 1 && (
              <Button size="xs" variant="ghost" onClick={() => void marcarLeidos()}>
                Marcar todos
              </Button>
            )}
          </div>
          <ul className="divide-y rounded-lg border">
            {sinLeer.map((a) => {
              const info = infoAviso(a.tipo);
              return (
                <li key={a.id} className="flex items-start gap-2.5 px-3 py-2 text-sm">
                  <Icon icon={info.icon} className={cn('mt-0.5 size-4 shrink-0', info.tono)} />
                  <div className="min-w-0 flex-1">
                    <p>{a.mensaje}</p>
                    <p className="text-xs text-muted-foreground">{fechaRelativa(a.creado_en)}</p>
                  </div>
                  <Button size="xs" variant="ghost" onClick={() => void marcarLeidos([a.id])}>
                    Marcar como leído
                  </Button>
                </li>
              );
            })}
          </ul>
        </div>
      )}

      {conError.length > 0 && (
        <details className="text-sm">
          <summary className="cursor-pointer text-xs font-medium text-destructive">
            {conError.length === 1 ? '1 pasada con error' : `${conError.length} pasadas con error`}
          </summary>
          <ul className="mt-1.5 space-y-1 text-xs text-muted-foreground">
            {conError.map((x) => (
              <li key={`${x.rfc}-${x.tipo}-${x.periodo}`}>
                <span className="font-mono">{x.rfc}</span> · {x.periodo}: {x.error_mensaje}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-xs text-muted-foreground">
        {esWeb()
          ? 'Corre en tu espacio en línea.'
          : 'Corre con la app abierta y al abrirla se pone al corriente.'}
      </p>

      <Dialog open={activarOpen} onOpenChange={setActivarOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Activar descarga automática</DialogTitle>
            <DialogDescription>Esto es lo que va a pasar una vez activada.</DialogDescription>
          </DialogHeader>
          <ul className="list-disc space-y-1.5 pl-5 text-sm">
            <li>Cada madrugada pide al SAT los CFDI de los últimos 3 días de cada empresa incluida.</li>
            <li>El día de cierre verifica el mes anterior contra la metadata del SAT: cada día queda consolidado o con diferencia.</li>
            <li>Revisa las cancelaciones de los últimos 12 meses y avisa las de meses ya cerrados.</li>
            <li>No consume las descargas del mes.</li>
            <li>Necesita la e.firma vigente de cada empresa.</li>
          </ul>
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 text-sm font-medium">
              Día de cierre
              <SelectorDia value={diaNuevo} onChange={setDiaNuevo} disabled={ocupado} />
            </div>
            <p className="text-xs text-muted-foreground">
              El cierre espera 3 días después de fin de mes porque el SAT acepta timbrar hasta 72 h
              después.
            </p>
          </div>
          {estado.historial && (
            <div className="space-y-1.5">
              <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                Además, llenar el historial desde…
                <SelectorMes
                  historial={estado.historial}
                  value={histNuevo}
                  onChange={setHistNuevo}
                  disabled={ocupado}
                  conVacio
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Opcional. Se pide mes por mes, del más reciente al más antiguo, a ritmo pausado (un mes
                por empresa por día).
              </p>
            </div>
          )}
          {errorActivar && (
            <Alert variant="destructive">
              <Icon icon="ph:warning-circle-light" className="size-4" />
              <AlertTitle>No se pudo activar</AlertTitle>
              <AlertDescription>
                <p>{errorActivar}</p>
              </AlertDescription>
            </Alert>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setActivarOpen(false)} disabled={ocupado}>
              Cancelar
            </Button>
            <Button onClick={() => void activar()} disabled={ocupado}>
              Activar descarga automática
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={empresasOpen} onOpenChange={setEmpresasOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Empresas incluidas</DialogTitle>
            <DialogDescription>{textoIncluidas(estado.empresas)}</DialogDescription>
          </DialogHeader>
          <ResourceList
            items={visibles}
            getKey={(e) => e.rfc}
            columns={[
              {
                key: 'empresa',
                render: (e) => (
                  <span className="block min-w-0">
                    <span className="block truncate text-sm font-medium">{e.nombre}</span>
                    <span className="block font-mono text-xs text-muted-foreground">{e.rfc}</span>
                    {textoHistorialEmpresa(e) && (
                      <span className="block text-xs text-muted-foreground">{textoHistorialEmpresa(e)}</span>
                    )}
                  </span>
                ),
              },
              {
                key: 'motivo',
                width: 'w-32',
                hideOnMobile: true,
                render: (e) => (
                  <span className="text-xs text-muted-foreground">{!e.elegible ? e.motivo : ''}</span>
                ),
              },
              {
                key: 'incluida',
                width: 'w-14',
                align: 'right',
                render: (e) => (
                  <Switch
                    size="sm"
                    checked={e.incluida}
                    onCheckedChange={(v) => void cambiarEmpresa(e, v)}
                    aria-label={`Incluir ${e.nombre}`}
                  />
                ),
              },
            ]}
          />
        </DialogContent>
      </Dialog>
    </section>
  );
}

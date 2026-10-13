'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { PageHeading } from '@/components/layout/page-heading';
import { CuadroGrid } from '@/components/calendario/cuadro-grid';
import { DiaDialog } from '@/components/calendario/dia-dialog';
import { PilotoPanel } from '@/components/calendario/piloto-panel';
import { VencimientoBadge } from '@/components/fiel/vencimiento-badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useAuth } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';
import { useEmpresas } from '@/hooks/use-empresas';
import { descargarBlob } from '@/lib/descargas';
import { mensajeDeError } from '@/lib/errores';
import { formatNumber } from '@/lib/formatting';
import {
  clasePunto,
  ESTADOS,
  MESES,
  rangoMes,
  resumenAnio,
  textoEstado,
  tienePiloto,
  type FiltroDireccion,
} from '@/lib/calendario';
import type { CalendarioAnio } from '@/lib/types';
import { cn } from '@/lib/utils';

const CLAVE_FILTRO = 'calendario:filtro';

function leerFiltro(): FiltroDireccion {
  try {
    const v = window.localStorage.getItem(CLAVE_FILTRO);
    if (v === 'E' || v === 'R' || v === 'A') return v;
  } catch {
    // sin storage: se queda el default
  }
  return 'A';
}

function guardarFiltro(f: FiltroDireccion) {
  try {
    window.localStorage.setItem(CLAVE_FILTRO, f);
  } catch {
    // sin storage: no se recuerda
  }
}

export default function CalendarioPage() {
  const { isConnected, apiClient } = useServer();
  const { license } = useAuth();
  const { empresas, loading: cargandoEmpresas } = useEmpresas();
  const empresa = empresas.find((e) => e.default);
  const rfc = empresa?.rfc ?? null;
  const sinPiloto = !tienePiloto(license);

  const [anio, setAnio] = useState(() => new Date().getFullYear());
  const [filtro, setFiltro] = useState<FiltroDireccion>('A');
  const [cal, setCal] = useState<CalendarioAnio | null>(null);
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diaAbierto, setDiaAbierto] = useState<string | null>(null);
  const [exportando, setExportando] = useState(false);

  useEffect(() => {
    setFiltro(leerFiltro());
  }, []);

  const cargar = useCallback(() => {
    if (!rfc || !isConnected) return () => {};
    let vivo = true;
    setCargando(true);
    setError(null);
    apiClient
      .calendarioAnio(rfc, anio)
      .then((c) => vivo && setCal(c))
      .catch((e) => vivo && setError(mensajeDeError(e)))
      .finally(() => vivo && setCargando(false));
    return () => {
      vivo = false;
    };
  }, [apiClient, rfc, anio, isConnected]);

  useEffect(() => cargar(), [cargar]);

  // Al cambiar de empresa se descarta lo de la anterior.
  useEffect(() => {
    setCal(null);
  }, [rfc]);

  const cambiarFiltro = (v: string) => {
    const f = v as FiltroDireccion;
    setFiltro(f);
    guardarFiltro(f);
  };

  const direccion = filtro === 'A' ? undefined : filtro;
  const actual = cal ? Number(cal.hoy.slice(0, 4)) : new Date().getFullYear();
  const minimo = cal && cal.anios.length > 0 ? Math.min(...cal.anios, actual) : actual;

  const exportarZip = async (mes: number) => {
    if (!rfc) return;
    setExportando(true);
    try {
      const blob = await apiClient.calendarioZip(rfc, anio, mes, direccion);
      const sufijo = direccion === 'E' ? '_emitidos' : direccion === 'R' ? '_recibidos' : '';
      descargarBlob(blob, `cfdi_${rfc}_${anio}-${String(mes).padStart(2, '0')}${sufijo}.zip`);
      toast.success(`ZIP de ${MESES[mes - 1].toLowerCase()} ${anio} listo`);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setExportando(false);
    }
  };

  const exportarExcel = async (mes: number) => {
    if (!rfc) return;
    setExportando(true);
    try {
      // Misma plantilla predeterminada que el procesador; sin ella, el export base.
      let plantilla: string | undefined;
      try {
        plantilla = (await apiClient.plantillasListar()).predeterminada || undefined;
      } catch {
        plantilla = undefined;
      }
      const { desde, hasta } = rangoMes(anio, mes);
      const blob = await apiClient.procesadorExportar(
        rfc,
        'xlsx',
        { desde, hasta, direccion: direccion ?? null },
        plantilla ? { plantilla } : undefined,
      );
      descargarBlob(blob, `cfdis_${anio}-${String(mes).padStart(2, '0')}.xlsx`);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setExportando(false);
    }
  };

  const resumen = cal ? resumenAnio(cal, filtro) : null;

  return (
    <div className="space-y-5">
      <PageHeading
        title="Cuadro de control"
        description={`Qué días de ${empresa?.nombre ?? 'tu empresa'} ya están en la base, cuáles están en proceso y cuáles fallaron.`}
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/descarga">
              <Icon icon="ph:download-simple-light" className="size-4" />
              Descargar CFDIs
            </Link>
          </Button>
        }
      />

      {!isConnected && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-circle-light" className="size-4" />
          <AlertTitle>Sin conexión</AlertTitle>
          <AlertDescription>
            <p>
              No pudimos conectar con la aplicación. Ciérrala por completo y vuelve a abrirla; si
              sigue igual, escríbenos desde Ayuda.
            </p>
          </AlertDescription>
        </Alert>
      )}

      {isConnected && !cargandoEmpresas && !empresa && (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertTitle>Sin empresa activa</AlertTitle>
          <AlertDescription>
            <p>
              Elige una empresa activa en{' '}
              <Link href="/empresas" className="font-medium underline underline-offset-2">
                Empresas
              </Link>{' '}
              para ver su cuadro de control.
            </p>
          </AlertDescription>
        </Alert>
      )}

      {isConnected && empresa && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="truncate text-sm font-bold tracking-tight">{empresa.nombre}</span>
              <span className="font-mono text-xs text-muted-foreground">{empresa.rfc}</span>
              {empresa.metodos.includes('fiel') && <VencimientoBadge vencimiento={empresa.vencimiento} />}
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label="Año anterior"
                  disabled={anio <= minimo}
                  onClick={() => setAnio((a) => a - 1)}
                >
                  <Icon icon="ph:caret-left-light" className="size-4" />
                </Button>
                <span className="w-12 text-center text-sm font-bold tabular-nums">{anio}</span>
                <Button
                  variant="outline"
                  size="icon-sm"
                  aria-label="Año siguiente"
                  disabled={anio >= actual}
                  onClick={() => setAnio((a) => a + 1)}
                >
                  <Icon icon="ph:caret-right-light" className="size-4" />
                </Button>
              </div>
              <Tabs value={filtro} onValueChange={cambiarFiltro}>
                <TabsList aria-label="Dirección de los comprobantes">
                  <TabsTrigger value="E">Emitidos</TabsTrigger>
                  <TabsTrigger value="R">Recibidos</TabsTrigger>
                  <TabsTrigger value="A">Ambos</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
          </div>

          {sinPiloto && (
            <div className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-accent px-4 py-3 sm:flex-row sm:items-center sm:justify-between dark:border-border">
              <div className="flex items-center gap-2.5 text-sm text-foreground/80">
                <Icon icon="ph:sparkle-light" className="size-4 shrink-0 text-primary" />
                Con Pro, la descarga automática llena cada día sola y cada mes se verifica contra el SAT.
              </div>
              <Button size="sm" variant="outline" asChild>
                <Link href="/suscripcion">Ver planes</Link>
              </Button>
            </div>
          )}

          {!sinPiloto && <PilotoPanel />}

          {error && (
            <Alert variant="destructive">
              <Icon icon="ph:warning-circle-light" className="size-4" />
              <AlertTitle>No se pudo cargar el cuadro de control</AlertTitle>
              <AlertDescription className="space-y-2">
                <p>{error}</p>
                <Button size="sm" variant="outline" onClick={cargar}>
                  Reintentar
                </Button>
              </AlertDescription>
            </Alert>
          )}

          {!cal && cargando && <div className="h-[26rem] animate-pulse rounded-xl bg-secondary/60" />}

          {cal && resumen && (
            <div className={cn('space-y-4 transition-opacity', cargando && 'opacity-60')}>
              <ul className="flex flex-wrap gap-1.5" aria-label={`Resumen de ${cal.anio}`}>
                {ESTADOS.map((e) => (
                  <li
                    key={e}
                    className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2.5 py-1 text-xs"
                  >
                    <span className={cn('size-2.5 rounded-sm', clasePunto(e))} />
                    <span className="text-muted-foreground">{textoEstado(e)}</span>
                    <span className="font-semibold tabular-nums">{formatNumber(resumen[e])}</span>
                  </li>
                ))}
              </ul>

              <div className="rounded-xl border bg-card p-3">
                <CuadroGrid
                  cal={cal}
                  filtro={filtro}
                  sinPiloto={sinPiloto}
                  exportando={exportando}
                  onAbrirDia={setDiaAbierto}
                  onZip={exportarZip}
                  onExcel={exportarExcel}
                />
              </div>

              <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
                {ESTADOS.map((e) => (
                  <span key={e} className="inline-flex items-center gap-1.5">
                    <span className={cn('size-3.5 rounded-[4px]', clasePunto(e))} />
                    {textoEstado(e)}
                  </span>
                ))}
                {filtro === 'A' && <span>Arriba emitidos, abajo recibidos</span>}
              </div>
            </div>
          )}
        </>
      )}

      {rfc && <DiaDialog rfc={rfc} fecha={diaAbierto} onClose={() => setDiaAbierto(null)} onCambio={cargar} />}
    </div>
  );
}

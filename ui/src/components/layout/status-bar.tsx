'use client';

import { useState } from 'react';
import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';

import { cn } from '@/lib/utils';
import { semaforoVencimiento } from '@/lib/vencimiento';
import { useEmpresas } from '@/hooks/use-empresas';
import { useStatusBarStats } from '@/hooks/use-status-bar-stats';
import { useUpdates } from '@/hooks/use-updates';
import { useServer } from '@/providers/server-provider';
import { Icon } from '@/components/ui/icon';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  Popover,
  PopoverContent,
  PopoverDescription,
  PopoverTitle,
  PopoverTrigger,
} from '@/components/ui/popover';
import type { Empresa } from '@/lib/types';
import type { UpdatesState } from '@/lib/updates';

interface EfirmaItem {
  tono: 'green' | 'amber' | 'red' | 'muted';
  icono: string;
  texto: string;
}

/**
 * Estado de e.firma de la empresa activa para la barra: semáforo por vigencia
 * (verde >30 días · amarillo ≤30 · rojo ≤5 o vencida) o neutro para solo-CIEC.
 */
function efirmaItem(empresa: Empresa | null): EfirmaItem | null {
  if (!empresa) return null;
  if (!empresa.metodos.includes('fiel')) {
    return { tono: 'muted', icono: 'ph:key-light', texto: 'Acceso con Contraseña' };
  }
  const sem = semaforoVencimiento(empresa.vencimiento);
  if (!sem) return null;
  if (sem.vencida) {
    return { tono: 'red', icono: 'ph:warning-circle-light', texto: 'e.firma vencida' };
  }
  if (sem.estado === 'verde') {
    const dias = `${sem.dias} ${sem.dias === 1 ? 'día' : 'días'}`;
    return { tono: 'green', icono: 'ph:key-light', texto: `e.firma vigente · ${dias}` };
  }
  return {
    tono: sem.estado === 'rojo' ? 'red' : 'amber',
    icono: 'ph:warning-light',
    // sem.label: "Vence en N días" / "Vence hoy" / "Vence mañana".
    texto: `e.firma ${sem.label.charAt(0).toLowerCase()}${sem.label.slice(1)}`,
  };
}

const TONOS: Record<EfirmaItem['tono'], string> = {
  green: 'font-semibold text-success [&_svg]:text-success',
  amber: 'font-semibold text-warning [&_svg]:text-warning',
  red: 'font-semibold text-destructive [&_svg]:text-destructive',
  muted: '',
};

// Página pública de descarga (para la reinstalación manual de instalaciones
// viejas sin firma; misma URL que usa el main en manejarErrorUpdater).
const URL_DESCARGA = 'https://todoconta.com/descargar';

type AccionVersion = 'check' | 'install' | 'descargar';

interface VersionChip {
  tono: EfirmaItem['tono'];
  icono: string;
  texto: string;
  tooltip: string;
  /** El icono gira (buscando / descargando). */
  spinning?: boolean;
  /** Acción al hacer clic; sin acción = no clicable. */
  accion?: AccionVersion;
}

/**
 * Traduce el estado del auto-updater a un chip para el status bar (análogo a
 * `efirmaItem`). Muestra siempre la versión actual; cuando hay una nueva
 * descargada o pendiente de reinstalar, pinta el chip en color de alerta.
 */
function chipDeVersion(
  updates: UpdatesState | null,
  version: string | undefined,
  conUpdater: boolean,
): VersionChip {
  const v = version ? `v${version}` : '–';

  // Sin updater (navegador/dev): solo la versión, sin acción.
  if (!conUpdater) {
    return {
      tono: 'muted',
      icono: 'ph:seal-check-light',
      texto: v,
      tooltip: `Versión ${version ?? 'desconocida'}`,
    };
  }

  switch (updates?.estado) {
    case 'buscando':
      return {
        tono: 'muted',
        icono: 'ph:circle-notch-light',
        spinning: true,
        texto: v,
        tooltip: 'Buscando actualizaciones…',
      };
    case 'al-dia':
      return {
        tono: 'muted',
        icono: 'ph:check-circle-light',
        texto: v,
        tooltip: 'Estás en la última versión · clic para volver a buscar',
        accion: 'check',
      };
    case 'descargando':
      return {
        tono: 'muted',
        icono: 'ph:circle-notch-light',
        spinning: true,
        texto: `Descargando ${updates?.progreso ?? 0}%`,
        tooltip: `Descargando la versión ${updates?.version ?? ''}…`,
      };
    case 'lista':
      return {
        tono: 'amber',
        icono: 'ph:cloud-arrow-down-light',
        texto: `${updates?.version ? `v${updates.version}` : 'Actualización'} lista`,
        tooltip: `Clic para reiniciar e instalar la versión ${updates?.version ?? ''}`,
        accion: 'install',
      };
    case 'error':
      if (updates?.requiereReinstalar) {
        return {
          tono: 'amber',
          icono: 'ph:warning-light',
          texto: 'Actualizar',
          tooltip:
            'Hay una versión nueva; esta instalación debe actualizarse a mano. Clic para descargar',
          accion: 'descargar',
        };
      }
      return {
        tono: 'muted',
        icono: 'ph:arrow-clockwise-light',
        texto: v,
        tooltip: 'No se pudo buscar actualizaciones. Clic para reintentar',
        accion: 'check',
      };
    default:
      // idle
      return {
        tono: 'muted',
        icono: 'ph:arrow-clockwise-light',
        texto: v,
        tooltip: 'Buscar actualizaciones',
        accion: 'check',
      };
  }
}

/**
 * Chip de versión + auto-update para el status bar. Muestra la versión actual y
 * un icono de refresh para buscar; cuando hay una versión lista, pinta en ámbar
 * y al hacer clic confirma antes de reiniciar (Popover); si la instalación es
 * vieja sin firma (`requiereReinstalar`), abre la página de descarga.
 */
function StatusBarVersion() {
  const { updates, conUpdater, ocupado, check, install } = useUpdates();
  const [confirmarOpen, setConfirmarOpen] = useState(false);
  const version = process.env.NEXT_PUBLIC_APP_VERSION;
  const chip = chipDeVersion(updates, version, conUpdater);

  const contenido = (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 whitespace-nowrap',
        TONOS[chip.tono],
      )}
    >
      <Icon
        icon={chip.icono}
        className={cn('size-3.5', chip.spinning && 'animate-spin')}
      />
      {chip.texto}
    </span>
  );

  // 'lista' → confirmación antes de reiniciar, anclada al chip.
  if (chip.accion === 'install') {
    return (
      <Popover open={confirmarOpen} onOpenChange={setConfirmarOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-label={chip.tooltip}
            className="inline-flex items-center rounded-md px-1 py-0.5 transition-opacity hover:opacity-80"
          >
            {contenido}
          </button>
        </PopoverTrigger>
        <PopoverContent side="top" align="end" className="w-64">
          <PopoverTitle className="text-sm">
            Instalar la versión {updates?.version}
          </PopoverTitle>
          <PopoverDescription className="mt-1 text-xs">
            Se reiniciará la app para aplicar la actualización. Tus datos y
            empresas se conservan.
          </PopoverDescription>
          <div className="mt-3 flex justify-end gap-2">
            <Button
              variant="ghost"
              size="xs"
              onClick={() => setConfirmarOpen(false)}
            >
              Más tarde
            </Button>
            <Button
              size="xs"
              onClick={() => {
                setConfirmarOpen(false);
                void install();
              }}
            >
              Reiniciar ahora
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    );
  }

  const onClick =
    chip.accion === 'check'
      ? () => void check()
      : chip.accion === 'descargar'
        ? () => window.open(URL_DESCARGA, '_blank', 'noopener')
        : undefined;

  const trigger = onClick ? (
    <button
      type="button"
      onClick={onClick}
      disabled={ocupado}
      aria-label={chip.tooltip}
      className="inline-flex items-center rounded-md px-1 py-0.5 transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-70"
    >
      {contenido}
    </button>
  ) : (
    <span className="inline-flex items-center px-1 py-0.5">{contenido}</span>
  );

  return (
    <Tooltip>
      <TooltipTrigger asChild>{trigger}</TooltipTrigger>
      <TooltipContent side="top">{chip.tooltip}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Barra de estado inferior fija: conexión con el agente a la izquierda;
 * estadísticas de la empresa activa (CFDIs del mes, última descarga, e.firma)
 * a la derecha. Visible en todas las pantallas.
 */
export function StatusBar() {
  const { isConnected } = useServer();
  const { empresas } = useEmpresas();

  const activas = empresas.filter((e) => !e.archived_at);
  const activa = activas.find((e) => e.default) ?? activas[0] ?? null;
  const stats = useStatusBarStats(activa?.rfc ?? null);
  const ef = efirmaItem(activa);

  return (
    <div className="flex h-7.5 shrink-0 select-none items-center justify-between gap-4 border-t bg-card px-4 text-xs text-muted-foreground">
      <div className="flex items-center gap-1.5">
        <span
          className={cn(
            'size-1.75 rounded-full',
            isConnected
              ? 'bg-success shadow-[0_0_6px_var(--success)]'
              : 'bg-destructive',
          )}
        />
        <span
          className={cn(
            'font-semibold',
            isConnected ? 'text-success' : 'text-destructive',
          )}
        >
          {isConnected ? 'Conectado' : 'Desconectado'}
        </span>
      </div>

      <div className="flex min-w-0 items-center gap-3">
        {stats && (
          <>
            <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
              <Icon icon="ph:files-light" className="size-3.5" />
              {stats.cfdisMes.toLocaleString('es-MX')} CFDIs este mes
            </span>
            {stats.ultimaDescarga && (
              <>
                <span className="h-3 w-px bg-border" />
                <span className="hidden items-center gap-1.5 whitespace-nowrap sm:inline-flex">
                  <Icon icon="ph:clock-counter-clockwise-light" className="size-3.5" />
                  Última descarga:{' '}
                  {formatDistanceToNow(stats.ultimaDescarga, {
                    locale: es,
                    addSuffix: true,
                  })}
                </span>
              </>
            )}
          </>
        )}
        {ef && (
          <>
            {stats && <span className="h-3 w-px bg-border" />}
            <span
              className={cn(
                'inline-flex items-center gap-1.5 whitespace-nowrap',
                TONOS[ef.tono],
              )}
            >
              <Icon icon={ef.icono} className="size-3.5" />
              {ef.texto}
            </span>
          </>
        )}
        {(stats || ef) && <span className="h-3 w-px bg-border" />}
        <StatusBarVersion />
      </div>
    </div>
  );
}

'use client';

import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';
import type { ListasNegrasMetadata } from '@/lib/types';

/** Días tras los cuales mostramos warning. El cron del SAT es mensual. */
const DIAS_WARNING = 35;

function fechaCorta(iso: string | null): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('es-MX', {
    day: '2-digit', month: 'short', year: 'numeric',
  });
}

function diasDesde(iso: string | null): number | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return Math.floor((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24));
}

interface Props {
  metadata: ListasNegrasMetadata | null;
  className?: string;
}

export function MetadataChip({ metadata, className }: Props) {
  if (!metadata) return null;

  const fecha = fechaCorta(metadata.lista_69b_updated_at);
  const dias = diasDesde(metadata.lista_69b_updated_at);
  const stale = dias !== null && dias > DIAS_WARNING;

  if (!fecha) {
    return (
      <span className={cn(
        'inline-flex items-center gap-1.5 rounded-full border bg-muted px-2.5 py-1 text-xs text-muted-foreground',
        className,
      )}>
        <Icon icon="ph:info-light" className="size-3" />
        Sin datos de actualización
      </span>
    );
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs',
        stale
          ? 'border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300'
          : 'border-muted bg-muted text-muted-foreground',
        className,
      )}
      title={
        stale
          ? `Las listas no se actualizan desde hace ${dias} días (normalmente se actualizan cada mes).`
          : `Listas 69-B actualizadas el ${fecha} (hace ${dias ?? '?'} días).`
      }
    >
      <Icon
        icon={stale ? 'ph:warning-light' : 'ph:database-light'}
        className="size-3"
      />
      Última actualización {fecha}
    </span>
  );
}

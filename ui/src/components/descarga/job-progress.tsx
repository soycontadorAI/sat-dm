'use client';

import { Card } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';
import type { JobUiEstado, LogEntry } from '@/hooks/use-ciec-job';

interface JobProgressProps {
  estado: JobUiEstado;
  log: LogEntry[];
  resultado: unknown;
  error: string | null;
  /** "N de M XML" si el job lo reporta (evento opcional `progreso`). */
  progreso?: { actual: number; total: number } | null;
}

const ESTADO_LABEL: Record<JobUiEstado, string> = {
  idle: 'Sin actividad',
  iniciando: 'Iniciando…',
  corriendo: 'En progreso…',
  captcha: 'Esperando captcha…',
  done: 'Completado',
  error: 'Error',
  cancelled: 'Cancelado',
};

function EstadoIcon({ estado }: { estado: JobUiEstado }) {
  if (estado === 'done') return <Icon icon="ph:check-circle-light" className="size-4 text-success" />;
  if (estado === 'error') return <Icon icon="ph:x-circle-light" className="size-4 text-destructive" />;
  if (estado === 'cancelled') return <Icon icon="ph:prohibit-light" className="size-4 text-muted-foreground" />;
  if (estado === 'captcha') return <Icon icon="ph:key-light" className="size-4 text-foreground" />;
  // Corriendo solo: la señal cian (DESIGN.md, lo automático).
  return <Icon icon="ph:circle-notch-light" className="size-4 animate-spin text-auto" />;
}

// Log sobre tinta (Señal): texto on-dark y los estados en su tono sobre tinta.
const LEVEL_COLOR: Record<NonNullable<LogEntry['level']>, string> = {
  info: 'text-[#AEB6C2]',
  ok: 'text-[#5BC294]',
  warn: 'text-[#E0A34A]',
  error: 'text-[#F07A82]',
};

/** "N de M XML" con una barra que avanza en cian (trabajo automático). */
function Avance({ actual, total }: { actual: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((actual / total) * 100)) : 0;
  return (
    <div className="space-y-1.5">
      <p className="text-sm text-auto-text">
        <span className="font-mono font-medium tabular-nums">{actual.toLocaleString('es-MX')}</span>
        {' de '}
        <span className="font-mono font-medium tabular-nums">{total.toLocaleString('es-MX')}</span>
        {' XML'}
      </p>
      <div className="h-1 overflow-hidden rounded-full bg-muted" aria-hidden>
        <div
          className="h-full rounded-full bg-auto transition-[width] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function Resumen({ resultado }: { resultado: unknown }) {
  if (!resultado || typeof resultado !== 'object') return null;
  const r = resultado as Record<string, unknown>;
  if (typeof r.total === 'number') {
    return (
      <p className="text-sm">
        <span className="font-semibold">{r.total}</span> XML descargados.
      </p>
    );
  }
  if (typeof r.archivo === 'string') {
    return (
      <p className="font-mono text-xs text-muted-foreground break-all">{r.archivo}</p>
    );
  }
  return null;
}

export function JobProgress({ estado, log, resultado, error, progreso }: JobProgressProps) {
  if (estado === 'idle') return null;

  return (
    <Card className="space-y-3 p-4">
      <div className="flex items-center gap-2">
        <EstadoIcon estado={estado} />
        <span
          className={cn(
            'text-sm font-medium',
            (estado === 'iniciando' || estado === 'corriendo') && 'text-auto-text',
          )}
        >
          {ESTADO_LABEL[estado]}
        </span>
      </div>

      {progreso && (estado === 'corriendo' || estado === 'captcha') && (
        <Avance actual={progreso.actual} total={progreso.total} />
      )}

      {estado === 'done' && <Resumen resultado={resultado} />}
      {estado === 'error' && error && (
        <p className="text-sm text-destructive">{error}</p>
      )}

      {/* Log estilo terminal */}
      <div className="max-h-56 overflow-y-auto rounded-md bg-[#10141B] p-3 font-mono text-[11px] leading-relaxed">
        {log.length === 0 ? (
          <span className="text-[#8B94A3]">Sin eventos todavía…</span>
        ) : (
          log.map((l, i) => (
            <div key={i} className="whitespace-pre-wrap">
              <span className="text-[#8B94A3]">{l.t}</span>{' '}
              <span className={cn(LEVEL_COLOR[l.level ?? 'info'])}>{l.msg}</span>
            </div>
          ))
        )}
      </div>
    </Card>
  );
}

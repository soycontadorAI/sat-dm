'use client';

import { Icon } from '@/components/ui/icon';
import { colorEmpresa, iniciales } from '@/lib/empresa-visual';
import { infoVence, nombreCortoEmpresa, TIPO_TAREA_META } from '@/lib/tareas';
import type { Empresa, Tarea } from '@/lib/types';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Piezas compartidas de una tarea (fila de la lista, card del tablero e
// Inicio): chip de empresa, tag de tipo, checkbox circular y la fila entera.
// ---------------------------------------------------------------------------

export function EmpresaChip({
  rfc,
  empresas,
}: {
  rfc: string | null;
  empresas: Empresa[];
}) {
  const empresa = rfc ? empresas.find((e) => e.rfc === rfc) : null;
  if (!empresa) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground">
        <Icon icon="ph:buildings-light" className="size-3.5" />
        General
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground">
      <span
        className="flex size-4 shrink-0 items-center justify-center rounded font-mono text-[8px] font-bold text-background"
        style={{ background: colorEmpresa(empresa.rfc) }}
      >
        {iniciales(empresa.nombre)}
      </span>
      {nombreCortoEmpresa(empresa.nombre)}
    </span>
  );
}

export function TipoTareaTag({ tipo }: { tipo: Tarea['tipo'] }) {
  const meta = TIPO_TAREA_META[tipo];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold',
        tipo === 'fiscal' && 'bg-primary/10 text-primary',
        tipo === 'manual' && 'bg-secondary text-muted-foreground',
        tipo === 'recurrente' && 'bg-accent-ai/10 text-accent-ai',
      )}
    >
      <Icon icon={meta.icon} className="size-[11px]" />
      {meta.label}
    </span>
  );
}

export function CheckTarea({
  hecha,
  onToggle,
}: {
  hecha: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={hecha}
      title={hecha ? 'Marcar pendiente' : 'Marcar hecha'}
      onClick={(e) => {
        e.stopPropagation();
        onToggle();
      }}
      className={cn(
        'flex size-[21px] shrink-0 items-center justify-center rounded-full border-[1.8px] text-white transition-colors',
        hecha
          ? 'border-success bg-success'
          : 'border-input bg-transparent hover:border-primary',
      )}
    >
      {hecha && <Icon icon="ph:check-light" className="size-3.5" />}
    </button>
  );
}

export function VenceBadge({ fecha }: { fecha: string | null }) {
  const info = infoVence(fecha);
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs font-semibold',
        info.tono === 'rojo' && 'text-destructive',
        info.tono === 'ambar' && 'text-warning',
        info.tono === 'normal' && 'text-muted-foreground',
      )}
    >
      <Icon icon={info.icono} className="size-[13px]" />
      {info.texto}
    </span>
  );
}

interface TareaRowProps {
  tarea: Tarea;
  empresas: Empresa[];
  onToggle: (tarea: Tarea) => void;
  onEdit: (tarea: Tarea) => void;
}

/** Fila de tarea: barra de prioridad, check, título + chips, vencimiento. */
export function TareaRow({ tarea, empresas, onToggle, onEdit }: TareaRowProps) {
  const hecha = tarea.estado === 'hecho';
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onEdit(tarea)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') onEdit(tarea);
      }}
      className="flex cursor-pointer items-center gap-3 rounded-xl border bg-card px-4 py-2.5 transition-shadow hover:shadow-sm"
    >
      <span
        title={`Prioridad ${tarea.prioridad}`}
        className={cn(
          'w-1 shrink-0 self-stretch rounded-full',
          tarea.prioridad === 'alta' && 'bg-destructive',
          tarea.prioridad === 'media' && 'bg-warning',
          tarea.prioridad === 'baja' && 'bg-input',
        )}
      />
      <CheckTarea hecha={hecha} onToggle={() => onToggle(tarea)} />
      <div className="min-w-0 flex-1">
        <div
          className={cn(
            'text-[13.5px] font-semibold leading-snug',
            hecha && 'text-muted-foreground line-through decoration-muted-foreground/50',
          )}
        >
          {tarea.titulo}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <EmpresaChip rfc={tarea.rfc} empresas={empresas} />
          <span className="text-border">·</span>
          <TipoTareaTag tipo={tarea.tipo} />
          {tarea.estado === 'curso' && (
            <>
              <span className="text-border">·</span>
              <span className="inline-flex items-center gap-1 text-[11.5px] font-medium text-primary">
                <Icon icon="ph:arrows-clockwise-light" className="size-3" />
                En curso
              </span>
            </>
          )}
        </div>
      </div>
      {!hecha && <VenceBadge fecha={tarea.fecha} />}
    </div>
  );
}

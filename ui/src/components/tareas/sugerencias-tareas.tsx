'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { mensajeDeError } from '@/lib/errores';
import type { Sugerencia } from '@/lib/tareas';

interface SugerenciasTareasProps {
  sugerencias: Sugerencia[];
  onAceptar: (s: Sugerencia) => Promise<void>;
  onDescartar: (id: string) => Promise<void>;
  /** Máximo de cards visibles (3 en /tareas, 2 en Inicio). */
  max?: number;
}

/**
 * Cards de "Sugerencias de TodoConta": pendientes detectados de las empresas
 * (e.firma por vencer, DIOT del mes). Aceptar las convierte en tarea;
 * descartar las suprime para siempre.
 */
export function SugerenciasTareas({
  sugerencias,
  onAceptar,
  onDescartar,
  max = 3,
}: SugerenciasTareasProps) {
  const [ocupada, setOcupada] = useState<string | null>(null);

  if (sugerencias.length === 0) return null;

  async function correr(id: string, accion: () => Promise<void>) {
    setOcupada(id);
    try {
      await accion();
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setOcupada(null);
    }
  }

  return (
    <div>
      <div className="mb-2.5 flex items-center gap-2 text-[12.5px] font-bold text-muted-foreground">
        <span className="inline-flex items-center gap-1.5 text-accent-ai">
          <Icon icon="ph:sparkle-light" className="size-3.75" />
          Sugerencias de TodoConta
        </span>
        <span className="rounded-full bg-secondary px-2 py-0.5 font-mono text-[11px] font-bold text-muted-foreground">
          {sugerencias.length}
        </span>
        <span className="hidden font-medium text-muted-foreground/70 sm:inline">
          detectadas de tus empresas. Acéptalas para convertirlas en tarea.
        </span>
      </div>
      <div className="flex flex-col gap-3 md:flex-row">
        {sugerencias.slice(0, max).map((s) => (
          <div
            key={s.id}
            className="flex min-w-0 flex-1 flex-col gap-2.5 rounded-xl border border-l-[3px] border-l-accent-ai bg-card p-3.5 md:max-w-md"
          >
            <div className="text-[13px] font-semibold leading-snug">{s.titulo}</div>
            <div className="flex items-center gap-1.5 text-[11.5px] text-muted-foreground">
              <Icon icon="ph:info-light" className="size-3" />
              {s.motivo}
            </div>
            <div className="mt-auto flex gap-2">
              <Button
                size="sm"
                className="flex-1"
                disabled={ocupada === s.id}
                onClick={() => correr(s.id, () => onAceptar(s))}
              >
                <Icon icon="ph:plus-light" className="size-3.5" />
                Agregar
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="flex-1"
                disabled={ocupada === s.id}
                onClick={() => correr(s.id, () => onDescartar(s.id))}
              >
                Descartar
              </Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

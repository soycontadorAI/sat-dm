'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { EditarTareaDrawer } from '@/components/tareas/editar-tarea-drawer';
import { TareaRow } from '@/components/tareas/tarea-row';
import { useTareas } from '@/hooks/use-tareas';
import { mensajeDeError } from '@/lib/errores';
import { derivarSugerencias, diasDesdeHoy } from '@/lib/tareas';
import type { Empresa, Tarea } from '@/lib/types';
import { cn } from '@/lib/utils';

interface TareasHoyProps {
  empresas: Empresa[];
}

/**
 * Bloque "Tareas de hoy" del Panel Ejecutivo: las 5 tareas más urgentes
 * (vencidas → hoy → próximas), contadores y sugerencias compactas. Mismo
 * estado que /tareas (el hook sincroniza ambas vistas por evento global).
 */
export function TareasHoy({ empresas }: TareasHoyProps) {
  const {
    tareas,
    descartadas,
    loading,
    toggleHecha,
    actualizar,
    eliminar,
    aceptarSugerencia,
  } = useTareas();
  const [editando, setEditando] = useState<Tarea | null>(null);

  const sugerencias = useMemo(
    () => derivarSugerencias(empresas, tareas, descartadas),
    [empresas, tareas, descartadas],
  );

  const pendientes = tareas.filter((t) => t.estado !== 'hecho');
  const vencidas = pendientes.filter((t) => t.fecha && diasDesdeHoy(t.fecha) < 0);
  const paraHoy = pendientes.filter((t) => t.fecha && diasDesdeHoy(t.fecha) === 0);
  const semana = pendientes.filter((t) => {
    if (!t.fecha) return false;
    const dias = diasDesdeHoy(t.fecha);
    return dias > 0 && dias <= 7;
  });

  const foco = [
    ...vencidas,
    ...paraHoy,
    ...pendientes
      .filter((t) => !vencidas.includes(t) && !paraHoy.includes(t))
      .sort(
        (a, b) =>
          (a.fecha ? diasDesdeHoy(a.fecha) : Infinity) -
          (b.fecha ? diasDesdeHoy(b.fecha) : Infinity),
      ),
  ].slice(0, 5);

  return (
    <section className="rounded-xl border bg-card p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <h2 className="flex items-center gap-2 text-sm font-bold tracking-tight">
          <Icon
            icon="ph:clipboard-text-light"
            className="size-4 shrink-0 text-muted-foreground"
          />
          Tareas de hoy
        </h2>
        <Button variant="ghost" size="sm" asChild>
          <Link href="/tareas">
            Ver todas
          </Link>
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0">
          {loading && tareas.length === 0 ? (
            <div className="h-[140px] animate-pulse rounded-lg bg-secondary/60" />
          ) : foco.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <div className="flex size-11 items-center justify-center rounded-full bg-success/10 text-success">
                <Icon icon="ph:check-circle-light" className="size-6" />
              </div>
              <div className="text-[15px] font-bold">Todo al día</div>
              <p className="text-[13px] text-muted-foreground">
                No tienes tareas pendientes.{' '}
                <Link href="/tareas" className="font-semibold text-primary">
                  Crea la primera
                </Link>
                .
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {foco.map((t) => (
                <TareaRow
                  key={t.id}
                  tarea={t}
                  empresas={empresas}
                  onToggle={toggleHecha}
                  onEdit={setEditando}
                />
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-3 gap-2.5">
            <ContadorTareas n={vencidas.length} etiqueta="Vencidas" tono="rojo" />
            <ContadorTareas n={paraHoy.length} etiqueta="Para hoy" tono="ambar" />
            <ContadorTareas n={semana.length} etiqueta="Esta semana" />
          </div>

          {sugerencias.length > 0 && (
            <div className="border-t border-border/70 pt-3.5">
              <div className="flex items-center gap-1.5 text-xs font-bold">
                <Icon icon="ph:sparkle-light" className="size-3.5 text-accent-ai" />
                Sugerencias de TodoConta
              </div>
              <div className="mt-3 flex flex-col gap-3">
                {sugerencias.slice(0, 2).map((s) => (
                  <div key={s.id} className="border-l-[3px] border-accent-ai pl-3">
                    <div className="text-[12.5px] font-semibold leading-snug">
                      {s.titulo}
                    </div>
                    <div className="mb-2 mt-0.5 flex items-center gap-1 text-[11.5px] text-muted-foreground">
                      <Icon icon="ph:info-light" className="size-3" />
                      {s.motivo}
                    </div>
                    <Button
                      size="xs"
                      onClick={() =>
                        aceptarSugerencia(s).catch((e) =>
                          toast.error(mensajeDeError(e)),
                        )
                      }
                    >
                      <Icon icon="ph:plus-light" className="size-3" />
                      Agregar
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <EditarTareaDrawer
        tarea={editando}
        empresas={empresas}
        onClose={() => setEditando(null)}
        onGuardar={actualizar}
        onEliminar={eliminar}
      />
    </section>
  );
}

function ContadorTareas({
  n,
  etiqueta,
  tono,
}: {
  n: number;
  etiqueta: string;
  tono?: 'rojo' | 'ambar';
}) {
  return (
    <Link
      href="/tareas"
      className="rounded-lg border bg-card p-3 transition hover:border-input hover:shadow-sm"
    >
      <div
        className={cn(
          'text-[22px] font-extrabold leading-none tracking-tight tabular-nums',
          tono === 'rojo' && n > 0 && 'text-destructive',
          tono === 'ambar' && n > 0 && 'text-warning',
        )}
      >
        {n}
      </div>
      <div className="mt-1.5 text-[11px] text-muted-foreground">{etiqueta}</div>
    </Link>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { Dialog as DialogPrimitive } from 'radix-ui';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { mensajeDeError } from '@/lib/errores';
import type {
  Empresa,
  Tarea,
  TareaEstado,
  TareaPatchRequest,
  TareaPrioridad,
  TareaTipo,
} from '@/lib/types';
import { cn } from '@/lib/utils';
import {
  CampoEmpresa,
  CampoFecha,
  CampoPrioridad,
  CampoTipo,
  EMPRESA_GENERAL,
} from '@/components/tareas/tarea-form-campos';

const ESTADOS: { valor: TareaEstado; label: string; dotClass: string }[] = [
  { valor: 'pendiente', label: 'Por hacer', dotClass: 'bg-muted-foreground/50' },
  { valor: 'curso', label: 'En curso', dotClass: 'bg-primary' },
  { valor: 'hecho', label: 'Hecha', dotClass: 'bg-success' },
];

interface EditarTareaDrawerProps {
  tarea: Tarea | null;
  empresas: Empresa[];
  onClose: () => void;
  onGuardar: (id: string, patch: TareaPatchRequest) => Promise<unknown>;
  onEliminar: (id: string) => Promise<void>;
}

/** Panel lateral para editar una tarea (con eliminar + confirmación inline). */
export function EditarTareaDrawer({
  tarea,
  empresas,
  onClose,
  onGuardar,
  onEliminar,
}: EditarTareaDrawerProps) {
  const [titulo, setTitulo] = useState('');
  const [rfc, setRfc] = useState(EMPRESA_GENERAL);
  const [fecha, setFecha] = useState('');
  const [tipo, setTipo] = useState<TareaTipo>('manual');
  const [prioridad, setPrioridad] = useState<TareaPrioridad>('media');
  const [estado, setEstado] = useState<TareaEstado>('pendiente');
  const [confirmando, setConfirmando] = useState(false);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    if (!tarea) return;
    setTitulo(tarea.titulo);
    setRfc(tarea.rfc ?? EMPRESA_GENERAL);
    setFecha(tarea.fecha ?? '');
    setTipo(tarea.tipo);
    setPrioridad(tarea.prioridad);
    setEstado(tarea.estado);
    setConfirmando(false);
    setGuardando(false);
  }, [tarea]);

  async function guardar() {
    if (!tarea || !titulo.trim() || guardando) return;
    setGuardando(true);
    try {
      await onGuardar(tarea.id, {
        titulo: titulo.trim(),
        rfc: rfc === EMPRESA_GENERAL ? null : rfc,
        fecha: fecha || null,
        tipo,
        prioridad,
        estado,
      });
      onClose();
    } catch (e) {
      toast.error(mensajeDeError(e));
      setGuardando(false);
    }
  }

  async function eliminar() {
    if (!tarea) return;
    try {
      await onEliminar(tarea.id);
      onClose();
    } catch (e) {
      toast.error(mensajeDeError(e));
    }
  }

  return (
    <DialogPrimitive.Root open={tarea !== null} onOpenChange={(o) => !o && onClose()}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/50 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className="fixed inset-y-0 right-0 z-50 flex w-full max-w-md flex-col bg-background shadow-lg outline-none duration-200 data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:animate-in data-[state=open]:slide-in-from-right"
          aria-describedby={undefined}
        >
          <div className="flex shrink-0 items-center gap-2 border-b px-5 py-3.5">
            <DialogPrimitive.Title className="flex-1 text-[13px] font-semibold text-ghost">
              Editar tarea
            </DialogPrimitive.Title>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon-sm" title="Cerrar">
                <Icon icon="ph:x-light" className="size-4" />
              </Button>
            </DialogPrimitive.Close>
          </div>

          <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-5">
            <textarea
              rows={2}
              value={titulo}
              onChange={(e) => setTitulo(e.target.value)}
              placeholder="Título de la tarea"
              className="w-full resize-none bg-transparent text-lg font-bold leading-snug tracking-tight outline-none placeholder:text-muted-foreground/60"
            />

            <div className="space-y-2">
              <div className="text-sm font-medium">Estado</div>
              <div className="grid grid-cols-3 gap-1 rounded-lg bg-secondary p-1">
                {ESTADOS.map((s) => (
                  <button
                    key={s.valor}
                    type="button"
                    onClick={() => setEstado(s.valor)}
                    className={cn(
                      'flex items-center justify-center gap-1.5 rounded-md px-1.5 py-2 text-[12.5px] font-semibold transition-colors',
                      estado === s.valor
                        ? 'bg-card text-foreground shadow-xs'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                  >
                    <span className={cn('size-2 rounded-full', s.dotClass)} />
                    {s.label}
                  </button>
                ))}
              </div>
            </div>

            <CampoEmpresa valor={rfc} onChange={setRfc} empresas={empresas} />

            <div className="grid grid-cols-2 gap-3">
              <CampoFecha valor={fecha} onChange={setFecha} />
              <CampoTipo valor={tipo} onChange={setTipo} />
            </div>

            <CampoPrioridad valor={prioridad} onChange={setPrioridad} />

            {confirmando && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3.5">
                <div className="text-[13px] font-bold text-destructive">
                  ¿Eliminar esta tarea?
                </div>
                <p className="mb-3 mt-1 text-xs text-muted-foreground">
                  Esta acción no se puede deshacer.
                </p>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={() => setConfirmando(false)}>
                    Cancelar
                  </Button>
                  <Button variant="destructive" size="sm" onClick={eliminar}>
                    <Icon icon="ph:trash-light" className="size-3.5" />
                    Sí, eliminar
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="flex shrink-0 items-center gap-2 border-t px-5 py-3.5">
            {!confirmando && (
              <Button
                variant="ghost"
                size="sm"
                className="mr-auto text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => setConfirmando(true)}
              >
                <Icon icon="ph:trash-light" className="size-3.5" />
                Eliminar
              </Button>
            )}
            <Button variant="outline" onClick={onClose} className={cn(confirmando && 'ml-auto')}>
              Cancelar
            </Button>
            <Button onClick={guardar} disabled={!titulo.trim() || guardando}>
              <Icon icon="ph:check-circle-light" className="size-4" />
              {guardando ? 'Guardando…' : 'Guardar cambios'}
            </Button>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

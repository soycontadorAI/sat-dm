'use client';

// Usuarios adicionales de Pro y Completo (decidido por Israel 2026-10-06):
// $990 al año o $129 al mes cada uno, en el mismo intervalo que el plan.
//  - `SelectorUsuarios`: elegir cuántos (al contratar y para quien ya paga).
//  - `GestionUsuariosAdicionales`: quien ya paga cambia la cantidad; antes de
//    aplicar ve el prorrateo de Stripe y confirma.
//  - `AgregarUsuarioBoton`: Equipo lleno, un lugar más con un clic (y confirmar).
// El servidor decide el precio y revisa que el equipo quepa; aquí solo se elige.

import { useState } from 'react';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { mensajeDeError } from '@/lib/errores';
import { formatPesosEnteros } from '@/lib/formatting';
import type { CambioUsuariosResponse, IntervaloPlan } from '@/lib/api-client';
import {
  MAX_USUARIOS_ADICIONALES,
  PRECIO_USUARIO_ADICIONAL,
  adicionalesTexto,
  sufijoIntervalo,
  usuariosTexto,
} from '@/lib/planes-v3';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

export function SelectorUsuarios({
  valor,
  onCambio,
  intervalo,
  base,
  deshabilitado = false,
}: {
  valor: number;
  onCambio: (n: number) => void;
  intervalo: IntervaloPlan;
  /** Usuarios que trae el plan (Pro 3, Completo 5). */
  base: number;
  deshabilitado?: boolean;
}) {
  const precio = PRECIO_USUARIO_ADICIONAL[intervalo];
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border bg-secondary/40 p-3.5">
      <div className="min-w-0">
        <p className="text-[13px] font-bold">Usuarios adicionales</p>
        <p className="text-xs leading-relaxed text-muted-foreground">
          {formatPesosEnteros(precio)} {sufijoIntervalo(intervalo)} cada uno. Tu plan queda en{' '}
          {usuariosTexto(base + valor)}.
        </p>
      </div>
      <div className="inline-flex items-center gap-1.5" role="group" aria-label="Usuarios adicionales">
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="Quitar un usuario adicional"
          onClick={() => onCambio(Math.max(0, valor - 1))}
          disabled={deshabilitado || valor <= 0}
        >
          <Icon icon="ph:minus-light" className="size-4" />
        </Button>
        <span className="w-8 text-center text-base font-extrabold tabular-nums" aria-live="polite">
          {valor}
        </span>
        <Button
          variant="outline"
          size="icon-sm"
          aria-label="Agregar un usuario adicional"
          onClick={() => onCambio(Math.min(MAX_USUARIOS_ADICIONALES, valor + 1))}
          disabled={deshabilitado || valor >= MAX_USUARIOS_ADICIONALES}
        >
          <Icon icon="ph:plus-light" className="size-4" />
        </Button>
      </div>
    </div>
  );
}

/** Vista previa (el cobro de hoy) y aplicación de un cambio de usuarios adicionales. */
function useCambioUsuarios(onListo: () => void) {
  const { apiClient } = useServer();
  const [vista, setVista] = useState<CambioUsuariosResponse | null>(null);
  const [busy, setBusy] = useState(false);

  async function previsualizar(n: number) {
    if (busy) return;
    setBusy(true);
    try {
      setVista(await apiClient.cambiarUsuariosAdicionales(n, true));
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusy(false);
    }
  }

  async function aplicar() {
    if (busy || !vista) return;
    setBusy(true);
    try {
      const r = await apiClient.cambiarUsuariosAdicionales(vista.usuarios_adicionales);
      toast.success(r.message ?? 'Listo: tus usuarios quedaron actualizados.');
      setVista(null);
      onListo();
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusy(false);
    }
  }

  return { vista, busy, previsualizar, aplicar, cerrar: () => setVista(null) };
}

function DialogoCambio({
  vista,
  busy,
  planNombre,
  onConfirmar,
  onCerrar,
}: {
  vista: CambioUsuariosResponse | null;
  busy: boolean;
  planNombre: string;
  onConfirmar: () => void;
  onCerrar: () => void;
}) {
  const cobro = typeof vista?.cobro_hoy_mxn === 'number' ? vista.cobro_hoy_mxn : null;
  const n = vista?.usuarios_adicionales ?? 0;
  const sube = !!vista && n > (vista.usuarios_adicionales_antes ?? 0);
  return (
    <Dialog open={vista !== null} onOpenChange={(o) => !o && onCerrar()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {n > 0 ? `¿Quedarte con ${adicionalesTexto(n)}?` : '¿Quitar tus usuarios adicionales?'}
          </DialogTitle>
          <DialogDescription>
            {vista && `Tu plan ${planNombre} queda en ${usuariosTexto(vista.max_usuarios)}. `}
            {cobro !== null && cobro > 0 && `Hoy se cobran ${formatPesosEnteros(cobro)}: la parte proporcional del periodo.`}
            {cobro !== null &&
              cobro < 0 &&
              `Lo que ya pagaste por los que quitas (${formatPesosEnteros(-cobro)}) queda como saldo a favor.`}
            {cobro === 0 && 'Hoy no se cobra nada.'}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="ghost" onClick={onCerrar} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={onConfirmar} disabled={busy}>
            {busy && <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />}
            {sube ? 'Sí, agregar' : 'Sí, cambiar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Quien ya paga Pro o Completo: elige cuántos usuarios adicionales quiere y, al
 * guardar, ve el cobro de hoy antes de confirmar. Para reiniciar el selector
 * cuando cambie la licencia, el padre le pone `key={actuales}`.
 */
export function GestionUsuariosAdicionales({
  planNombre,
  intervalo,
  base,
  actuales,
  onCambiado,
}: {
  planNombre: string;
  intervalo: IntervaloPlan;
  base: number;
  actuales: number;
  onCambiado: () => void;
}) {
  const [valor, setValor] = useState(actuales);
  const c = useCambioUsuarios(onCambiado);
  const cambio = valor !== actuales;
  return (
    <div className="flex flex-col gap-3">
      <SelectorUsuarios valor={valor} onCambio={setValor} intervalo={intervalo} base={base} deshabilitado={c.busy} />
      {cambio && (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => void c.previsualizar(valor)} disabled={c.busy}>
            <Icon
              icon={c.busy ? 'ph:circle-notch-light' : 'ph:users-light'}
              className={cn('size-4', c.busy && 'animate-spin')}
            />
            Guardar cambio
          </Button>
          <button
            type="button"
            onClick={() => setValor(actuales)}
            className="text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground"
          >
            Deshacer
          </button>
        </div>
      )}
      <DialogoCambio
        vista={c.vista}
        busy={c.busy}
        planNombre={planNombre}
        onConfirmar={() => void c.aplicar()}
        onCerrar={c.cerrar}
      />
    </div>
  );
}

/** Equipo lleno en Pro o Completo: agregar un lugar más (con el cobro de hoy antes de confirmar). */
export function AgregarUsuarioBoton({
  planNombre,
  actuales,
  onAgregado,
}: {
  planNombre: string;
  /** Usuarios adicionales que ya paga. */
  actuales: number;
  onAgregado: () => void;
}) {
  const c = useCambioUsuarios(onAgregado);
  return (
    <>
      <Button
        onClick={() => void c.previsualizar(actuales + 1)}
        disabled={c.busy || actuales >= MAX_USUARIOS_ADICIONALES}
      >
        <Icon
          icon={c.busy ? 'ph:circle-notch-light' : 'ph:user-plus-light'}
          className={cn('size-4', c.busy && 'animate-spin')}
        />
        Agregar un usuario
      </Button>
      <DialogoCambio
        vista={c.vista}
        busy={c.busy}
        planNombre={planNombre}
        onConfirmar={() => void c.aplicar()}
        onCerrar={c.cerrar}
      />
    </>
  );
}

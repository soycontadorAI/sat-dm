'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

/**
 * Candado con CTA para una función que el plan no incluye (planes v3, F1). Solo
 * se muestra con el interruptor de planes v3 encendido y con datos del plan:
 * sin datos nunca hay candado.
 */
export function CandadoPlan({
  titulo,
  plan,
  children,
  className,
}: {
  titulo: string;
  /** Plan al que hay que cambiar para tenerla (p. ej. "Pro" o "Completo"). */
  plan: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col gap-3 rounded-lg border border-dashed bg-secondary/40 p-4 sm:flex-row sm:items-center',
        className,
      )}
    >
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
        <Icon icon="ph:lock-simple-light" className="size-4.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13.5px] font-semibold">{titulo}</div>
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{children}</p>
      </div>
      <Button asChild size="sm" className="shrink-0">
        <Link href="/suscripcion">Cambiar a {plan}</Link>
      </Button>
    </div>
  );
}

/** Etiqueta chica "Pro" / "Completo" con candado, para filas de ajustes. */
export function PlanRequerido({ plan }: { plan: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
      <Icon icon="ph:lock-simple-light" className="size-3" />
      {plan}
    </span>
  );
}

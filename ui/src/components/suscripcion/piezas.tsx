'use client';

// Piezas visuales de /suscripcion, compartidas por la vista de antes
// (app/suscripcion/page.tsx) y la de planes v3 (suscripcion-v3.tsx).

import type { ReactNode } from 'react';

import { formatPesosEnteros } from '@/lib/formatting';
import { cn } from '@/lib/utils';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

const INCLUYE_IA = [
  'Abacus: tu asistente fiscal por WhatsApp',
  'Documentos SAT por chat (CSF, 32-D, CFDIs)',
  'Conecta Claude/ChatGPT a tus datos (API + MCP)',
  'Reportes y cálculos fiscales conversacionales',
];

export function IaUpsellCard({
  precio,
  precioLista,
  esFundador,
  busy,
  onPagar,
}: {
  precio: number;
  precioLista: number;
  esFundador?: boolean;
  busy: boolean;
  onPagar: () => void;
}) {
  const conDescuento = esFundador && precio < precioLista;
  return (
    <PlanCard
      markClass="bg-accent text-accent-ai"
      icon="ph:sparkle-light"
      titulo="Anual con IA"
      badge={
        conDescuento ? (
          <EstadoBadge tone="amber">Precio Fundador · de por vida</EstadoBadge>
        ) : (
          <EstadoBadge tone="primary">Nuevo</EstadoBadge>
        )
      }
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <span className="text-3xl font-extrabold tracking-tight tabular-nums">
          {formatPesosEnteros(precio)}
        </span>
        <span className="text-sm font-medium text-muted-foreground">/ año</span>
        {conDescuento && (
          <span className="text-base text-muted-foreground/70 line-through tabular-nums">
            {formatPesosEnteros(precioLista)}
          </span>
        )}
      </div>
      <ul className="flex flex-col gap-2.5">
        {INCLUYE_IA.map((t) => (
          <li key={t} className="flex items-center gap-2.5 text-sm text-foreground/90">
            <Icon icon="ph:check-circle-light" className="size-4 shrink-0 text-success" />
            {t}
          </li>
        ))}
      </ul>
      <p className="text-xs leading-relaxed text-muted-foreground">
        Incluye todo lo del plan Anual. Tu precio se respeta en cada renovación mientras no
        canceles.
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="lg" onClick={onPagar} disabled={busy}>
          <Icon
            icon={busy ? 'ph:circle-notch-light' : 'ph:sparkle-light'}
            className={cn('size-4', busy && 'animate-spin')}
          />
          Pagar {formatPesosEnteros(precio)} con tarjeta
        </Button>
        <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
          <Icon icon="ph:lock-light" className="size-3.5" />
          Pago seguro con Stripe.
        </span>
      </div>
    </PlanCard>
  );
}

export function PlanCard({
  className,
  markClass,
  icon,
  titulo,
  badge,
  children,
}: {
  className?: string;
  markClass: string;
  icon: string;
  titulo: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card className={cn('gap-0 py-0', className)}>
      <div className="flex flex-col gap-5 p-6">
        <div className="flex items-center gap-2.5">
          <span
            className={cn(
              'flex size-8 shrink-0 items-center justify-center rounded-lg',
              markClass,
            )}
          >
            <Icon icon={icon} className="size-5" />
          </span>
          <h2 className="text-lg font-extrabold tracking-tight">{titulo}</h2>
          {badge && <span className="ml-auto">{badge}</span>}
        </div>
        {children}
      </div>
    </Card>
  );
}

export function EstadoBadge({
  tone,
  children,
}: {
  tone: 'primary' | 'success' | 'amber' | 'muted';
  children: ReactNode;
}) {
  const tones: Record<string, string> = {
    primary: 'bg-accent text-primary',
    success: 'bg-success/10 text-success',
    amber: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-400',
    muted: 'bg-secondary text-muted-foreground',
  };
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-bold',
        tones[tone],
      )}
    >
      {children}
    </span>
  );
}

export function MetodoTile({
  on,
  onClick,
  icon,
  titulo,
  sub,
}: {
  on: boolean;
  onClick: () => void;
  icon: string;
  titulo: string;
  sub: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-3 rounded-xl border bg-card p-3.5 text-left transition-colors',
        on ? 'border-primary bg-accent' : 'hover:border-input hover:bg-secondary',
      )}
    >
      <span
        className={cn(
          'flex size-4 shrink-0 items-center justify-center rounded-full border-2',
          on ? 'border-primary' : 'border-input',
        )}
      >
        {on && <span className="size-2 rounded-full bg-primary" />}
      </span>
      <Icon icon={icon} className={cn('size-5 shrink-0', on ? 'text-primary' : 'text-muted-foreground')} />
      <span className="flex min-w-0 flex-col">
        <span className="text-[13px] font-bold">{titulo}</span>
        <span className="truncate text-[11px] text-muted-foreground">{sub}</span>
      </span>
    </button>
  );
}

export function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/60 py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="truncate font-semibold text-foreground">{value}</span>
    </div>
  );
}

export function CopyRow({
  etiqueta,
  valor,
  mono,
  onCopy,
}: {
  etiqueta: string;
  valor: string;
  mono?: boolean;
  onCopy: (texto: string, etiqueta: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border/60 py-2 last:border-0">
      <span className="text-xs text-muted-foreground">{etiqueta}</span>
      <button
        type="button"
        onClick={() => onCopy(valor, etiqueta)}
        className="group inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-sm font-semibold text-foreground hover:bg-card"
        aria-label={`Copiar ${etiqueta}`}
      >
        <span className={cn(mono && 'font-mono text-[13px]')}>{valor}</span>
        <Icon icon="ph:copy-light" className="size-3.5 text-muted-foreground group-hover:text-primary" />
      </button>
    </div>
  );
}

export function Note({ icon, children }: { icon: string; children: ReactNode }) {
  return (
    <div className="flex gap-2.5 rounded-lg border bg-secondary/50 p-3 text-[13px] leading-relaxed text-muted-foreground">
      <Icon icon={icon} className="mt-0.5 size-4 shrink-0 text-muted-foreground/80" />
      <p>{children}</p>
    </div>
  );
}

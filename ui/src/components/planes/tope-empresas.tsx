'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { cn } from '@/lib/utils';
import type { TopeEmpresas } from '@/lib/api-client';
import type { Empresa } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';
import { mensajeTope, topeCerca, topeLleno } from '@/lib/planes-v3';
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

/**
 * Contador "8 de 10 empresas" del plan, con el aviso al 80% y el mensaje al
 * 100% (sección 3 del plan v3). Solo se renderea si el tope aplica.
 */
export function TopeEmpresasBarra({ tope }: { tope: TopeEmpresas }) {
  const lleno = topeLleno(tope);
  const cerca = topeCerca(tope);
  const pct = Math.min(100, Math.round((tope.activas / tope.tope) * 100));
  const plan = tope.plan_codigo === 'trial' ? 'Tu prueba' : `Plan ${tope.plan_nombre ?? ''}`.trim();

  return (
    <div className="rounded-lg border bg-card px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-[13px]">
        <span className="font-semibold">
          <span className="font-mono tabular-nums">{tope.activas}</span> de{' '}
          <span className="font-mono tabular-nums">{tope.tope}</span> empresas
        </span>
        <span className="text-xs text-muted-foreground">{plan}</span>
      </div>
      <div
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={tope.tope}
        aria-valuenow={tope.activas}
        aria-label="Empresas activas de tu plan"
      >
        <span
          className={cn(
            'block h-full rounded-full',
            lleno ? 'bg-destructive' : cerca ? 'bg-warning' : 'bg-primary',
          )}
          style={{ width: `${Math.max(pct, 3)}%` }}
        />
      </div>
      {(cerca || lleno) && (
        <p className="mt-2.5 flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
          <Icon
            icon={lleno ? 'ph:warning-light' : 'ph:info-light'}
            className={cn('mt-0.5 size-3.5 shrink-0', lleno && 'text-destructive')}
          />
          <span>
            {lleno
              ? mensajeTope(tope)
              : `Llevas ${tope.activas} de ${tope.tope} empresas de tu plan.`}{' '}
            <Link href="/suscripcion" className="font-semibold text-foreground hover:underline">
              Ver planes
            </Link>
          </span>
        </p>
      )}
    </div>
  );
}

/**
 * Diálogo al 100%: no se puede agregar ni desarchivar. Ofrece archivar una
 * empresa activa ahí mismo o cambiar de plan.
 */
export function TopeEmpresasDialog({
  tope,
  onOpenChange,
  activas,
  onArchivar,
}: {
  tope: TopeEmpresas | null;
  onOpenChange: (open: boolean) => void;
  activas: Empresa[];
  onArchivar: (rfc: string) => Promise<void>;
}) {
  const router = useRouter();
  const [eligiendo, setEligiendo] = useState(false);
  const [archivando, setArchivando] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function cerrar(open: boolean) {
    if (!open) {
      setEligiendo(false);
      setError(null);
    }
    onOpenChange(open);
  }

  async function archivar(rfc: string) {
    setArchivando(rfc);
    setError(null);
    try {
      await onArchivar(rfc);
      cerrar(false);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setArchivando(null);
    }
  }

  return (
    <Dialog open={tope !== null} onOpenChange={cerrar}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Llegaste al tope de tu plan</DialogTitle>
          <DialogDescription>{tope ? mensajeTope(tope) : ''}</DialogDescription>
        </DialogHeader>

        {eligiendo && (
          <div className="flex max-h-60 flex-col overflow-y-auto rounded-lg border">
            {activas.map((e) => (
              <div
                key={e.rfc}
                className="flex items-center gap-3 border-b px-3 py-2 last:border-0"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[13px] font-medium">{e.nombre}</div>
                  <div className="font-mono text-[11px] text-muted-foreground">{e.rfc}</div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={archivando !== null}
                  onClick={() => void archivar(e.rfc)}
                >
                  {archivando === e.rfc ? (
                    <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                  ) : (
                    'Archivar'
                  )}
                </Button>
              </div>
            ))}
          </div>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}
        <p className="text-xs leading-relaxed text-muted-foreground">
          Archivar no borra nada: guardamos su información y la restauras cuando quieras.
        </p>

        <DialogFooter>
          {!eligiendo && (
            <Button variant="outline" onClick={() => setEligiendo(true)}>
              <Icon icon="ph:archive-light" className="size-4" />
              Archivar
            </Button>
          )}
          <Button
            onClick={() => {
              cerrar(false);
              router.push('/suscripcion');
            }}
          >
            <Icon icon="ph:arrow-up-right-light" className="size-4" />
            Cambiar de plan
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

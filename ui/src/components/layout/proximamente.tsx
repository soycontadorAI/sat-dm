'use client';

import type { DestinoUbicado } from '@/lib/navegacion';
import { useEspaciosShell } from '@/components/layout/espacios-shell';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

/**
 * Pantalla genérica de un destino "Pronto": todavía no existe en la app, pero
 * ya tiene su lugar. Dice qué va a hacer y dónde va a vivir. No tiene ruta
 * propia (no se crean URLs hasta que la función exista) ni promete fechas.
 */
export function Proximamente({ ubicado }: { ubicado: DestinoUbicado }) {
  const shell = useEspaciosShell();
  const { destino, espacio, padre } = ubicado;
  const donde = [espacio?.label, padre?.label, destino.label].filter(Boolean).join(' > ');

  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-16 text-center">
      <span className="mb-5 flex size-14 items-center justify-center rounded-[14px] border border-border bg-card text-foreground shadow-soft">
        <Icon icon={destino.icon} className="size-6.5" />
      </span>
      <span className="mb-3 inline-flex h-6 items-center rounded-full bg-muted px-2.5 text-xs font-semibold text-muted-foreground">
        Próximamente
      </span>
      <h1 className="text-2xl font-bold tracking-[-0.025em] text-foreground">{destino.label}</h1>
      <p className="mt-2 max-w-[54ch] text-[15px] leading-relaxed text-muted-foreground">
        {destino.detalle ?? destino.descripcion}
      </p>
      <p className="mt-5 rounded-full border border-border bg-card px-3.5 py-1.5 text-[13px] text-muted-foreground">
        Va a vivir en <b className="font-semibold text-foreground">{donde}</b>
      </p>
      <p className="mt-6 max-w-[52ch] text-[13px] leading-relaxed text-ghost">
        Todavía no está en la app. Ya tiene su lugar para que, cuando llegue, la encuentres
        aquí mismo.
      </p>
      {shell && espacio && (
        <Button
          variant="outline"
          className="mt-6"
          onClick={() => shell.irAEspacio(espacio.id, 'panel')}
        >
          <Icon icon="ph:arrow-left-light" className="size-4" />
          Volver a {espacio.label}
        </Button>
      )}
    </div>
  );
}

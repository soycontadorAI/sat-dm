'use client';

import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { Icon } from '@/components/ui/icon';

/**
 * Entrada de la DIOT: dos caminos. Generar TXT es el flujo de siempre (prellenar,
 * ajustar y descargar el TXT para presentarlo a mano). Enviar DIOT presenta la
 * declaración en el SAT con la e.firma, con el TXT de TodoConta o con uno propio.
 */
export default function DiotPage() {
  return (
    <div className="space-y-6">
      <PageHeading
        title="DIOT"
        description="Declaración Informativa de Operaciones con Terceros. Genera el TXT de carga masiva o preséntala directo en el SAT."
      />

      <div className="grid gap-4 md:grid-cols-2">
        <Opcion
          href="/diot/generar"
          icon="ph:file-code-light"
          titulo="Generar TXT"
          texto="Prellena la DIOT con tus CFDIs recibidos, o cárgala a mano, ajusta lo que haga falta y descarga el TXT de carga masiva."
          pie="Tú lo presentas en el portal del SAT, o la envías desde aquí al terminar."
        />
        <Opcion
          href="/diot/enviar"
          icon="ph:paper-plane-tilt-light"
          titulo="Enviar DIOT"
          texto="Presenta la DIOT en el SAT con tu e.firma, con el TXT de TodoConta o con uno que generaste en tu software contable, y baja su acuse."
          pie="No incluye estímulos fiscales: si aplicaste alguno, se declara manualmente en el portal."
          pieRojo
        />
      </div>

      <p className="text-sm text-muted-foreground">
        ¿Ya la presentaste?{' '}
        <Link
          href="/diot/presentadas"
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          Ver DIOT presentadas
        </Link>{' '}
        y bajar su declaración, Excel y acuse.
      </p>
    </div>
  );
}

function Opcion({
  href,
  icon,
  titulo,
  texto,
  pie,
  pieRojo,
}: {
  href: string;
  icon: string;
  titulo: string;
  texto: string;
  pie: string;
  pieRojo?: boolean;
}) {
  return (
    <Link
      href={href}
      className="group flex flex-col gap-3 rounded-xl border bg-card p-5 transition-colors hover:border-primary hover:bg-accent"
    >
      <span className="flex size-10 items-center justify-center rounded-[10px] bg-accent text-primary group-hover:bg-card">
        <Icon icon={icon} className="size-5" />
      </span>
      <div className="space-y-1">
        <h2 className="text-base font-bold tracking-tight">{titulo}</h2>
        <p className="text-sm leading-relaxed text-muted-foreground">{texto}</p>
      </div>
      <p className={pieRojo ? 'text-xs font-semibold text-destructive' : 'text-xs text-muted-foreground'}>
        {pie}
      </p>
    </Link>
  );
}

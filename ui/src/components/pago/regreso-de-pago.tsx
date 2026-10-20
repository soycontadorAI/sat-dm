'use client';

import Link from 'next/link';

import { BrandMark } from '@/components/layout/brand-mark';
import { Icon } from '@/components/ui/icon';

// ---------------------------------------------------------------------------
// Vuelta de Stripe Checkout (/pago/listo y /pago/cancelado).
//
// El checkout se abre en el navegador del SO tanto desde la desktop como desde
// la web, y Stripe regresa aquí (success_url / cancel_url que arma
// api.todoconta.com). La página no lee la sesión ni confirma nada: el plan lo
// activa el webhook de Stripe, y la pantalla de Suscripción fuerza un refresh
// de la licencia al entrar. Vive fuera del shell (ver app-shell.tsx) porque
// quien pagó desde la desktop no tiene sesión en este navegador.
// ---------------------------------------------------------------------------

// Deep link que solo trae la app al frente: el renderer ignora cualquier
// acción que no sea `auth-callback` (desktop/main.js, parseProtocolUrl).
const DEEP_LINK_DESKTOP = 'todoconta://pago-listo';

interface Props {
  estado: 'listo' | 'cancelado';
}

export function RegresoDePago({ estado }: Props) {
  const listo = estado === 'listo';

  return (
    <div className="flex min-h-full justify-center bg-background px-6 pb-10 pt-14">
      <div className="w-full max-w-96 text-center">
        <div className="mb-6 flex justify-center">
          <BrandMark size={46} wordmarkSize={24} priority iconClassName="rounded-xl shadow-sm" />
        </div>

        <div className="animate-in fade-in slide-in-from-bottom-1 py-6 duration-200">
          <span
            className={
              listo
                ? 'mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-primary/10 text-primary'
                : 'mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-muted text-muted-foreground'
            }
          >
            <Icon icon={listo ? 'ph:check-light' : 'ph:x-light'} className="size-8" />
          </span>
          <h1 className="text-xl font-semibold text-foreground">
            {listo ? 'Pago recibido' : 'No se hizo ningún cobro'}
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {listo
              ? 'Tu plan se activa en cuanto Stripe nos confirma el cobro, normalmente en unos segundos.'
              : 'Cancelaste el pago. Cuando quieras, elige tu plan desde Suscripción en TodoConta.'}
          </p>
          {listo && (
            <p className="mt-2 text-sm text-muted-foreground">
              Regresa a TodoConta y entra a Suscripción para verlo. Ya puedes cerrar esta pestaña.
            </p>
          )}
        </div>

        <div className="flex flex-col gap-2.5">
          <a
            href={DEEP_LINK_DESKTOP}
            className="flex h-11.5 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[15px] font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
          >
            <Icon icon="ph:desktop-light" className="size-4" />
            Volver a la app de escritorio
          </a>
          <Link
            href="/suscripcion"
            className="flex h-11.5 w-full items-center justify-center gap-2 rounded-lg border border-border text-[15px] font-semibold text-foreground transition-colors hover:bg-muted"
          >
            Ir a TodoConta en la web
          </Link>
        </div>
      </div>
    </div>
  );
}

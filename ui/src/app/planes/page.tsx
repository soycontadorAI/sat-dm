'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

import { Icon } from '@/components/ui/icon';

/**
 * /planes: alias de /suscripcion.
 *
 * Es el destino canónico de los links externos de pricing (landing, correos de
 * la serie de conversión, campañas). Antes se proxeaba al legacy de apps/web
 * (diseño viejo, sesión por cookies); ahora resuelve nativo en el espejo: el
 * usuario llega logueado con su agente y ve SU precio (promo/founder aplicados
 * por el server). Ruta estática (cumple `output: 'export'`).
 *
 * Con los planes v3 activos, /suscripcion muestra Esencial, Pro y Completo (ya
 * no el Anual / Anual con IA de antes). Reenvía `?plan=` e `?intervalo=` para
 * que una liga de la landing ("Elegir Pro mensual") llegue con el plan elegido.
 */
export default function PlanesPage() {
  const router = useRouter();

  useEffect(() => {
    const entrada = new URLSearchParams(window.location.search);
    const salida = new URLSearchParams();
    for (const clave of ['plan', 'intervalo']) {
      const valor = entrada.get(clave);
      if (valor) salida.set(clave, valor);
    }
    const qs = salida.toString();
    router.replace(qs ? `/suscripcion?${qs}` : '/suscripcion');
  }, [router]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-muted-foreground">
      <Icon icon="ph:circle-notch-light" className="size-6 animate-spin" />
      <p className="text-sm">
        Llevándote a tu suscripción…{' '}
        <a href="/suscripcion" className="font-semibold text-primary hover:underline">
          o entra aquí
        </a>
      </p>
    </div>
  );
}

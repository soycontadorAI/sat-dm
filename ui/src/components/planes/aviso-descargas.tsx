'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';

import { useServer } from '@/providers/server-provider';
import {
  EVENTO_TOPE_DESCARGAS,
  type CupoDescargas,
  type TopeDescargas,
} from '@/lib/api-client';
import { fechaLarga, mensajeTopeDescargas } from '@/lib/planes-v3';
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
 * Descargas al SAT del mes en el plan gratis (planes v3, F1). Dos piezas:
 *  - Aviso fijo y discreto bajo la barra de título desde el 80% del tope.
 *  - Diálogo cuando el agente rechaza una descarga (402 `tope_descargas`),
 *    venga de la pantalla que venga (lo anuncia `api-client` con un evento).
 * Sin datos (agente viejo, sin licencia) no se muestra nada.
 */
export function AvisoDescargasMes() {
  const { apiClient, isConnected } = useServer();
  const pathname = usePathname();
  const router = useRouter();
  const [cupo, setCupo] = useState<CupoDescargas | null>(null);
  const [rechazo, setRechazo] = useState<TopeDescargas | null>(null);

  const cargar = useCallback(async () => {
    try {
      setCupo(await apiClient.cupoDescargas());
    } catch {
      setCupo(null); // agente sin el endpoint o sin conexión: sin aviso
    }
  }, [apiClient]);

  // Al conectar, al cambiar de pantalla y cada 2 minutos.
  useEffect(() => {
    if (isConnected) void cargar();
  }, [isConnected, cargar, pathname]);
  useEffect(() => {
    if (!isConnected) return;
    const t = setInterval(() => void cargar(), 2 * 60 * 1000);
    return () => clearInterval(t);
  }, [isConnected, cargar]);

  useEffect(() => {
    function alRechazo(e: Event) {
      setRechazo((e as CustomEvent<TopeDescargas>).detail);
      void cargar();
    }
    window.addEventListener(EVENTO_TOPE_DESCARGAS, alRechazo);
    return () => window.removeEventListener(EVENTO_TOPE_DESCARGAS, alRechazo);
  }, [cargar]);

  const tope = cupo?.aplica ? cupo.tope : null;
  const agotado = tope !== null && cupo !== null && cupo.usadas >= tope;
  const cerca = tope !== null && cupo !== null && !agotado && cupo.usadas >= Math.ceil(tope * 0.8);
  const plan = cupo?.plan_nombre ?? 'Gratis';

  return (
    <>
      {cupo && (agotado || cerca) && (
        <div className="border-b bg-secondary/60">
          <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2">
            <Icon
              icon={agotado ? 'ph:warning-light' : 'ph:info-light'}
              className="size-4 shrink-0 text-muted-foreground"
            />
            <p className="min-w-0 flex-1 truncate text-[13px] text-foreground/90">
              {agotado
                ? `Ya usaste las ${tope} descargas de este mes de tu plan ${plan}. Se renuevan el ${fechaLarga(cupo.reinicia)}.`
                : `Llevas ${cupo.usadas} de ${tope} descargas de este mes en tu plan ${plan}.`}
            </p>
            <Button asChild size="sm" variant={agotado ? 'default' : 'outline'} className="shrink-0">
              <Link href="/suscripcion">Ver planes</Link>
            </Button>
          </div>
        </div>
      )}

      <Dialog open={rechazo !== null} onOpenChange={(o) => !o && setRechazo(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Ya usaste tus descargas del mes</DialogTitle>
            <DialogDescription>{rechazo ? mensajeTopeDescargas(rechazo) : ''}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRechazo(null)}>
              Entendido
            </Button>
            <Button
              onClick={() => {
                setRechazo(null);
                router.push('/suscripcion');
              }}
            >
              <Icon icon="ph:arrow-up-right-light" className="size-4" />
              Ver planes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

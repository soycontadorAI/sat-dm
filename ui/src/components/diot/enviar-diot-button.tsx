'use client';

import Link from 'next/link';

import { useAuth } from '@/providers/auth-provider';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

interface Props {
  periodo: string;
  /** true cuando hay renglones y ningún error duro (igual que Generar TXT). */
  habilitado: boolean;
  numErrores: number;
}

/**
 * "Enviar DIOT" desde Generar TXT: lleva al asistente de envío con el periodo y
 * el TXT de TodoConta ya elegidos. Presentar con el TXT generado por la app es
 * premium igual que generarlo; sin premium lleva a /suscripcion.
 */
export function EnviarDiotButton({ periodo, habilitado, numErrores }: Props) {
  const { license } = useAuth();
  const esPremium = license?.premium_features_unlocked === true;

  if (!esPremium) {
    return (
      <Button size="sm" variant="outline" asChild>
        <Link href="/suscripcion" title="Enviar la DIOT generada es una función premium">
          <Icon icon="ph:lock-simple-light" className="size-4" />
          Enviar DIOT (Premium)
        </Link>
      </Button>
    );
  }

  if (!habilitado) {
    return (
      <Button
        size="sm"
        variant="outline"
        disabled
        title={
          numErrores > 0
            ? `Corrige ${numErrores} error${numErrores === 1 ? '' : 'es'} antes de enviar`
            : 'Agrega proveedores antes de enviar'
        }
      >
        <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
        Enviar DIOT
      </Button>
    );
  }

  return (
    <Button size="sm" variant="outline" asChild>
      <Link href={`/diot/enviar?periodo=${periodo}&origen=generado`}>
        <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
        Enviar DIOT
      </Link>
    </Button>
  );
}

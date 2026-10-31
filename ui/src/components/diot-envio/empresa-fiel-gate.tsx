'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { useEmpresas } from '@/hooks/use-empresas';

interface Props {
  /** Qué se hace con la e.firma ("presentar la DIOT"); completa el aviso. */
  para: string;
  children: (empresa: { rfc: string; nombre: string }) => ReactNode;
}

/**
 * Los trámites de la DIOT entran al portal con la e.firma de la empresa activa.
 * Sin empresa activa, o sin e.firma, se explica y se lleva a Empresas.
 */
export function EmpresaFielGate({ para, children }: Props) {
  const { empresas, loading } = useEmpresas();
  const empresa = empresas.find((e) => e.default) ?? null;

  if (!empresa) {
    if (loading) {
      return (
        <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
          Cargando empresas…
        </div>
      );
    }
    return (
      <Aviso
        titulo="No hay empresa activa"
        texto={`Para ${para} se usa la e.firma de una empresa. Activa una para continuar.`}
      />
    );
  }
  if (!empresa.metodos.includes('fiel')) {
    return (
      <Aviso
        titulo={`${empresa.nombre} no tiene e.firma`}
        texto={`El portal de la DIOT del SAT solo se maneja aquí con e.firma (no CIEC). Agrégala en la empresa para ${para}.`}
      />
    );
  }
  return <>{children({ rfc: empresa.rfc, nombre: empresa.nombre })}</>;
}

function Aviso({ titulo, texto }: { titulo: string; texto: string }) {
  return (
    <Alert variant="warning">
      <Icon icon="ph:warning-light" className="size-4" />
      <AlertTitle>{titulo}</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>{texto}</p>
        <Button variant="outline" size="sm" asChild>
          <Link href="/empresas">
            <Icon icon="ph:buildings-light" className="size-4" />
            Ir a Empresas
          </Link>
        </Button>
      </AlertDescription>
    </Alert>
  );
}

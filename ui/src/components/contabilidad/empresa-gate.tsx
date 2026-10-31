'use client';

import type { ReactNode } from 'react';
import Link from 'next/link';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { useEmpresas } from '@/hooks/use-empresas';

interface Props {
  children: (empresa: { rfc: string; nombre: string }) => ReactNode;
}

/**
 * La contabilidad electrónica entra al portal del SAT con la e.firma de la
 * empresa activa (no hay CIEC). Sin empresa activa, o sin e.firma, se explica y
 * se lleva a Empresas. Lo comparten Enviar y Presentadas.
 */
export function EmpresaGate({ children }: Props) {
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
        texto="La contabilidad electrónica se envía por empresa, con su e.firma. Activa una para continuar."
      />
    );
  }
  if (!empresa.metodos.includes('fiel')) {
    return (
      <Aviso
        titulo={`${empresa.nombre} no tiene e.firma`}
        texto="El portal de contabilidad electrónica del SAT solo acepta e.firma (no CIEC). Agrégala en la empresa para enviar y consultar acuses."
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

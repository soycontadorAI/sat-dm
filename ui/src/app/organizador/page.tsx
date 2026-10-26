'use client';

import { useEffect, useState } from 'react';

import { PageHeading } from '@/components/layout/page-heading';
import { OrganizadorForm } from '@/components/organizador/organizador-form';
import { OrganizadorResults } from '@/components/organizador/organizador-results';
import { OrganizadorWeb } from '@/components/organizador/organizador-web';
import { useOrganizador } from '@/hooks/use-organizador';
import { esWeb } from '@/lib/modo';

export default function OrganizadorPage() {
  const { organizar, renombrar, deduplicar, result, isLoading, error, reset } =
    useOrganizador();
  // En la web el Organizador se explica en vez de mostrar el formulario
  // (trabaja sobre carpetas de la computadora), con cualquier navegación: con
  // la clásica el form aparecía y una ruta "C:/..." tronaba en el agente Linux.
  const [web, setWeb] = useState(false);
  useEffect(() => {
    setWeb(esWeb());
  }, []);

  if (web) {
    return (
      <div className="space-y-6">
        <PageHeading
          title="Organizador de archivos"
          description="Ordena en carpetas, renombra y quita duplicados de las facturas que descargaste."
        />
        <OrganizadorWeb />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <PageHeading
        title="Organizador de archivos"
        description="Ordena en carpetas, renombra y quita duplicados de las facturas que descargaste."
        action={
          result ? (
            <button
              onClick={reset}
              className="text-sm text-muted-foreground underline-offset-4 hover:underline"
            >
              Nueva operación
            </button>
          ) : undefined
        }
      />

      <OrganizadorForm
        onOrganizar={organizar}
        onRenombrar={renombrar}
        onDeduplicar={deduplicar}
        isLoading={isLoading}
      />

      {error && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <OrganizadorResults result={result} />
    </div>
  );
}

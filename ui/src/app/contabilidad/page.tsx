'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { PageHeading } from '@/components/layout/page-heading';
import { EmpresaGate } from '@/components/contabilidad/empresa-gate';
import { EnviarPanel } from '@/components/contabilidad/enviar-panel';
import { PendientesBanner } from '@/components/contabilidad/pendientes-banner';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

/**
 * Enviar: el catálogo y las balanzas que generó el software contable. Los acuses
 * viven en /contabilidad/presentadas (cada uno con su entrada en el menú).
 */
export default function ContabilidadPage() {
  const router = useRouter();
  // Sube cuando algo cambia en el SAT (envío, reintento): el banner relee la cola.
  const [version, setVersion] = useState(0);
  const refrescar = () => setVersion((v) => v + 1);

  return (
    <div className="space-y-6">
      <PageHeading
        title="Enviar contabilidad electrónica"
        description="Envía el catálogo de cuentas y las balanzas de comprobación que generas en tu software contable: primero se validan sin enviar, y solo después se mandan al SAT."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/contabilidad/presentadas">
              <Icon icon="ph:stamp-light" className="size-4" />
              Presentadas
            </Link>
          </Button>
        }
      />
      <EmpresaGate>
        {({ rfc }) => (
          <>
            <PendientesBanner rfc={rfc} refreshKey={version} onCambio={refrescar} />
            <EnviarPanel
              key={rfc}
              rfc={rfc}
              onCambio={refrescar}
              onVerAcuses={(anio) => router.push(`/contabilidad/presentadas?anio=${anio}`)}
            />
          </>
        )}
      </EmpresaGate>
    </div>
  );
}

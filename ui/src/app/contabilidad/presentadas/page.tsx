'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { PageHeading } from '@/components/layout/page-heading';
import { AcusesPanel } from '@/components/contabilidad/acuses-panel';
import { EmpresaGate } from '@/components/contabilidad/empresa-gate';
import { PendientesBanner } from '@/components/contabilidad/pendientes-banner';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';

// `useSearchParams` (el ejercicio llega por ?anio= desde Enviar) requiere un
// <Suspense> bajo `output: 'export'`; ver ui/CLAUDE.md.
export default function ContabilidadPresentadasPage() {
  return (
    <Suspense fallback={null}>
      <PresentadasContenido />
    </Suspense>
  );
}

/** `?anio=2026` → 2026; cualquier otra cosa → el ejercicio en curso. */
function leerAnio(valor: string | null): number {
  const n = Number(valor);
  return Number.isInteger(n) && n >= 2000 && n <= 2100 ? n : new Date().getFullYear();
}

function PresentadasContenido() {
  const router = useRouter();
  const params = useSearchParams();
  const [anio, setAnio] = useState(() => leerAnio(params.get('anio')));
  // Sube cuando el reintento de la cola cambia algo: la tabla relee lo guardado.
  const [version, setVersion] = useState(0);

  return (
    <div className="space-y-6">
      <PageHeading
        title="Contabilidad presentada"
        description="El estatus de lo que enviaste al SAT (Recibido, Aceptado o Rechazado) y sus acuses. Solo el de aceptación ampara el cumplimiento."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/contabilidad">
              <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
              Enviar
            </Link>
          </Button>
        }
      />
      <EmpresaGate>
        {({ rfc }) => (
          <>
            <PendientesBanner rfc={rfc} refreshKey={version} onCambio={() => setVersion((v) => v + 1)} />
            <AcusesPanel
              key={rfc}
              rfc={rfc}
              anio={anio}
              onAnioChange={setAnio}
              onCorregir={() => router.push('/contabilidad')}
              refreshKey={version}
            />
          </>
        )}
      </EmpresaGate>
    </div>
  );
}

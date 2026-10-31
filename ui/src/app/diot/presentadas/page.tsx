'use client';

import { Suspense, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import { PageHeading } from '@/components/layout/page-heading';
import { EmpresaFielGate } from '@/components/diot-envio/empresa-fiel-gate';
import { PresentadasPanel } from '@/components/diot-envio/presentadas-panel';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { leerPeriodoParam } from '@/lib/diot-envio';

// Ver la nota de /diot/enviar: `useSearchParams` va dentro de un <Suspense>.
export default function DiotPresentadasPage() {
  return (
    <Suspense fallback={null}>
      <DiotPresentadasContenido />
    </Suspense>
  );
}

function DiotPresentadasContenido() {
  const params = useSearchParams();
  const inicial = leerPeriodoParam(params.get('periodo'));
  const verificar = params.get('verificar') === '1';

  const [ejercicio, setEjercicio] = useState(() => inicial?.ejercicio ?? new Date().getFullYear());
  const [mes, setMes] = useState<number | 'todos'>(() => inicial?.mes ?? 'todos');

  return (
    <div className="space-y-6">
      <PageHeading
        title="DIOT presentadas"
        description="Las declaraciones que ya presentaste en el SAT, con su estatus, y sus archivos: declaración, Excel y acuse."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/diot/enviar">
              <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
              Enviar DIOT
            </Link>
          </Button>
        }
      />
      <EmpresaFielGate para="consultar la DIOT presentada">
        {({ rfc }) => (
          <PresentadasPanel
            key={rfc}
            rfc={rfc}
            ejercicio={ejercicio}
            onEjercicioChange={setEjercicio}
            mes={mes}
            onMesChange={setMes}
            verificar={verificar}
          />
        )}
      </EmpresaFielGate>
    </div>
  );
}

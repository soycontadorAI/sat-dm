'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { PageHeading } from '@/components/layout/page-heading';
import { EmpresaFielGate } from '@/components/diot-envio/empresa-fiel-gate';
import { PresentarWizard } from '@/components/diot-envio/presentar-wizard';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { leerPeriodoParam, periodoClave } from '@/lib/diot-envio';

// `useSearchParams` requiere un <Suspense> bajo `output: 'export'` (el periodo y
// el origen llegan por query desde Generar TXT; ver ui/CLAUDE.md).
export default function EnviarDiotPage() {
  return (
    <Suspense fallback={null}>
      <EnviarDiotContenido />
    </Suspense>
  );
}

/** La DIOT del mes se presenta al mes siguiente: el periodo por omisión es el anterior. */
function periodoAnterior(hoy: Date = new Date()): { ejercicio: number; mes: number } {
  const mes = hoy.getMonth(); // 0-11 → es el número (1-12) del mes anterior
  return mes === 0 ? { ejercicio: hoy.getFullYear() - 1, mes: 12 } : { ejercicio: hoy.getFullYear(), mes };
}

function EnviarDiotContenido() {
  const router = useRouter();
  const params = useSearchParams();
  const inicial = leerPeriodoParam(params.get('periodo')) ?? periodoAnterior();
  const o = params.get('origen');
  const origen = o === 'generado' || o === 'propio' ? o : null;

  return (
    <div className="space-y-6">
      <PageHeading
        title="Enviar DIOT"
        description="Presenta la DIOT en el portal del SAT con la e.firma de la empresa: primero se valida sin enviar, y solo después se presenta."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/diot/presentadas">
              <Icon icon="ph:stamp-light" className="size-4" />
              DIOT presentadas
            </Link>
          </Button>
        }
      />
      <EmpresaFielGate para="presentar la DIOT">
        {({ rfc }) => (
          <PresentarWizard
            key={rfc}
            rfc={rfc}
            periodoInicial={inicial}
            origenInicial={origen}
            onVerPresentadas={(ejercicio, mes, verificar) =>
              router.push(
                `/diot/presentadas?periodo=${periodoClave(ejercicio, mes)}${verificar ? '&verificar=1' : ''}`,
              )
            }
          />
        )}
      </EmpresaFielGate>
    </div>
  );
}

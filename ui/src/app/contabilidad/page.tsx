'use client';

import { useState } from 'react';
import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { AcusesPanel } from '@/components/contabilidad/acuses-panel';
import { EnviarPanel } from '@/components/contabilidad/enviar-panel';
import { PendientesBanner } from '@/components/contabilidad/pendientes-banner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useEmpresas } from '@/hooks/use-empresas';

type Pestana = 'enviar' | 'acuses';

export default function ContabilidadPage() {
  const { empresas, loading } = useEmpresas();
  const empresa = empresas.find((e) => e.default) ?? null;

  const [pestana, setPestana] = useState<Pestana>('enviar');
  const [anio, setAnio] = useState(() => new Date().getFullYear());
  // Sube cuando algo cambia en el SAT (envío, reintento): las otras vistas releen.
  const [version, setVersion] = useState(0);
  const refrescar = () => setVersion((v) => v + 1);

  const tieneFiel = !!empresa?.metodos.includes('fiel');

  return (
    <div className="space-y-6">
      <PageHeading
        title="Contabilidad electrónica"
        description="Envía el catálogo de cuentas y las balanzas de comprobación que generas en tu software contable, y consulta sus acuses de Aceptado o Rechazado."
      />

      {!empresa ? (
        loading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
            <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
            Cargando empresas…
          </div>
        ) : (
          <SinEmpresa
            titulo="No hay empresa activa"
            texto="La contabilidad electrónica se envía por empresa, con su e.firma. Activa una para continuar."
          />
        )
      ) : !tieneFiel ? (
        <SinEmpresa
          titulo={`${empresa.nombre} no tiene e.firma`}
          texto="El portal de contabilidad electrónica del SAT solo acepta e.firma (no CIEC). Agrégala en la empresa para enviar y consultar acuses."
        />
      ) : (
        <>
          <PendientesBanner rfc={empresa.rfc} refreshKey={version} onCambio={refrescar} />

          <Tabs value={pestana} onValueChange={(v) => setPestana(v as Pestana)}>
            <TabsList>
              <TabsTrigger value="enviar">
                <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
                Enviar
              </TabsTrigger>
              <TabsTrigger value="acuses">
                <Icon icon="ph:stamp-light" className="size-4" />
                Acuses
              </TabsTrigger>
            </TabsList>

            {/* forceMount: Radix desmonta el panel inactivo, y con él el wizard y su job.
                Cambiar de pestaña a media validación perdería el avance, así que ambos
                paneles siguen montados y el inactivo solo se oculta. */}
            <TabsContent value="enviar" forceMount className="pt-3 data-[state=inactive]:hidden">
              <EnviarPanel
                rfc={empresa.rfc}
                onCambio={refrescar}
                onVerAcuses={(a) => {
                  setAnio(a);
                  setPestana('acuses');
                }}
              />
            </TabsContent>
            <TabsContent value="acuses" forceMount className="pt-3 data-[state=inactive]:hidden">
              <AcusesPanel
                rfc={empresa.rfc}
                anio={anio}
                onAnioChange={setAnio}
                onCorregir={() => setPestana('enviar')}
                refreshKey={version}
              />
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}

function SinEmpresa({ titulo, texto }: { titulo: string; texto: string }) {
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

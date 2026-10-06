'use client';

import { useCallback } from 'react';
import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { PortalDescargaForm } from '@/components/descarga/portal-descarga-form';
import { PortalDescargasRecientes } from '@/components/descarga/portal-descargas-recientes';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Callout } from '@/components/shared/callout';
import { Icon } from '@/components/ui/icon';
import { useServer } from '@/providers/server-provider';
import { useEmpresas } from '@/hooks/use-empresas';
import { useHistorial } from '@/hooks/use-historial';
import { metodoPortalPreferido } from '@/lib/empresa-metodo';

export default function DescargaRapidaPage() {
  const { isConnected } = useServer();
  const { empresas } = useEmpresas();
  const { descargas, refresh: refreshHistorial } = useHistorial();

  // Empresa activa = la marcada como default en el catálogo del agente. Esta
  // página NO permite cambiarla aquí; eso se hace desde /empresas.
  const empresaActiva = empresas.find((e) => e.default);
  const metodo = metodoPortalPreferido(empresaActiva);
  const tieneFiel = !!empresaActiva?.metodos.includes('fiel');

  // Al terminar un job exitoso, refrescamos el historial → la lista
  // `PortalDescargasRecientes` (que consume `descargas` por prop) se actualiza
  // sin recargar la página.
  const onJobDone = useCallback(() => {
    refreshHistorial();
  }, [refreshHistorial]);

  const description = !empresaActiva
    ? 'Selecciona una empresa activa en Empresas para descargar sus facturas.'
    : metodo
      ? 'Trae tus facturas directo del portal del SAT, sin esperar al Web Service. Limitada al máximo de descargas que el portal permite por día.'
      : 'Esta empresa no tiene accesos registrados.';

  return (
    <div className="space-y-6">
      <PageHeading
        title="Descarga rápida"
        description={description}
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/descarga">
              <Icon icon="ph:arrow-left-light" className="size-4" />
              Volver a Descargar CFDIs
            </Link>
          </Button>
        }
      />

      {/* Agente local no disponible */}
      {!isConnected && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-circle-light" className="size-4" />
          <AlertTitle>Sin conexión</AlertTitle>
          <AlertDescription>
            No pudimos conectar con la aplicación. Ciérrala por completo y
            vuelve a abrirla; si sigue igual, escríbenos desde Ayuda.
          </AlertDescription>
        </Alert>
      )}

      {/* Sin empresa activa o sin credenciales */}
      {isConnected && (!empresaActiva || !metodo) && (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertTitle>
            {empresaActiva
              ? 'Esta empresa no tiene método de autenticación'
              : 'Sin empresa activa'}
          </AlertTitle>
          <AlertDescription>
            {/* Un solo <p>: AlertDescription es grid y apilaría texto y Link. */}
            <p>
              Agrega tu <strong>e.firma</strong> (recomendado: descarga sin captcha) o tu{' '}
              <strong>Contraseña del SAT</strong> (descarga directa con captcha) en{' '}
              <Link href="/empresas" className="font-medium underline underline-offset-2">
                Empresas
              </Link>
              .
            </p>
          </AlertDescription>
        </Alert>
      )}

      {/* Caso normal: hay empresa activa con método */}
      {isConnected && empresaActiva && metodo && (
        <>
          {/* CTA recíproco: Web Service para volúmenes grandes (solo aplica a FIEL). */}
          {tieneFiel && (
            <Callout
              icon="ph:cloud-arrow-down-light"
              title="¿Tienes muchas facturas?"
              text="Usa la descarga masiva por el Web Service oficial con tu e.firma. No tiene límite diario y normalmente queda lista en un par de horas."
              action={
                <Button variant="outline" size="sm" asChild>
                  <Link href="/descarga">
                    Web Service
                  </Link>
                </Button>
              }
            />
          )}

          <PortalDescargaForm empresa={empresaActiva} onJobDone={onJobDone} />

          <PortalDescargasRecientes rfc={empresaActiva.rfc} descargas={descargas} />
        </>
      )}
    </div>
  );
}

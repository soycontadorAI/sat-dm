'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';

import { Icon } from '@/components/ui/icon';

import { PageHeading } from '@/components/layout/page-heading';
import { DescargaForm, type DescargaFormParams } from '@/components/descarga/descarga-form';
import { PollingDisplay } from '@/components/descarga/polling-display';
import { PackageList } from '@/components/descarga/package-list';
import { SolicitudesList } from '@/components/descarga/solicitudes-list';
import { PortalDescargaForm } from '@/components/descarga/portal-descarga-form';
import { PortalDescargasRecientes } from '@/components/descarga/portal-descargas-recientes';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Callout } from '@/components/shared/callout';
import { useServer } from '@/providers/server-provider';
import { useDescarga } from '@/hooks/use-descarga';
import { useSolicitudes } from '@/hooks/use-solicitudes';
import { useEmpresas } from '@/hooks/use-empresas';
import { useHistorial } from '@/hooks/use-historial';
import { mensajeDeError } from '@/lib/errores';

/**
 * Convierte errores técnicos de requests al SAT (timeouts, conexión rota,
 * SSL roto) en mensajes amigables. Para errores no reconocidos devuelve
 * el original.
 */
function traducirError(raw: string | null): string {
  if (!raw) return '';
  if (/timeout|timed out|read timeout|max retries|ConnectionError|EAI_AGAIN|ECONNRESET/i.test(raw)) {
    return 'El SAT no respondió a tiempo. Esto pasa cuando su Web Service está saturado o caído. Inténtalo de nuevo en unos minutos.';
  }
  if (/SSL|certificate/i.test(raw)) {
    return 'Falló la conexión segura con el SAT. Suele ser intermitente. Inténtalo de nuevo.';
  }
  return raw;
}

/**
 * Detecta si el mensaje (raw o traducido o envuelto en "No se pudo
 * solicitar X: ...") apunta a un problema del lado del SAT. En ese caso
 * vale la pena sugerir la alternativa CIEC para quien tenga prisa.
 */
function esErrorDelSat(texto: string | null | undefined): boolean {
  if (!texto) return false;
  return /SAT no respondió|conexión segura|saturado|caído|timeout|timed out|max retries|ConnectionError|SSL|certificate/i.test(
    texto,
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DescargaPage() {
  const { isConnected, fielStatus, apiClient } = useServer();
  const {
    state,
    requestId,
    codEstado,
    mensaje,
    numeroCfdis,
    packageIds,
    archivosDescargados,
    error,
    solicitar,
    descargar,
    reset,
  } = useDescarga(fielStatus.rfc);
  const {
    solicitudes,
    loading: loadingSolicitudes,
    refresh: refreshSolicitudes,
  } = useSolicitudes(fielStatus.rfc);
  const { empresas } = useEmpresas();
  const { descargas: historial, refresh: refreshHistorial } = useHistorial();

  // Empresa activa: la marcada como default en el catálogo del agente. Es la
  // empresa cuya FIEL está en sesión (si tiene FIEL) y la primera que el usuario
  // ve preseleccionada en todos los flujos.
  const empresaActiva = empresas.find((e) => e.default);
  const tieneFiel = !!empresaActiva?.metodos.includes('fiel');
  const tieneCiec = !!empresaActiva?.metodos.includes('ciec');

  // Flag de "submit en curso": cubre la ventana entre que el usuario hace
  // click y el hook setea state='requesting'. Antes solo R o E (solo) tenían
  // feedback inmediato porque el hook arrancaba primero; en "Ambos" se
  // disparaba primero la previa via apiClient directo y la UI se quedaba
  // sin cambio durante 5–10s, dando la impresión de que nada pasaba.
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // True después de SLOW_NOTICE_MS sin haber resuelto: muestra un aviso
  // intermedio al usuario para que sepa que el SAT está tardando y le
  // sugiere CIEC como alternativa sin tener que esperar el error final.
  const [esperaLarga, setEsperaLarga] = useState(false);

  // Refresca el historial de solicitudes en cada cambio del flujo (nueva solicitud,
  // poll que avanza el estado, descarga completada) para que la lista esté al día.
  useEffect(() => {
    refreshSolicitudes();
  }, [state, codEstado, requestId, refreshSolicitudes]);

  // Descarga una solicitud desde la lista (sin tocar el active flow): pega directo
  // al agente y refresca para que el estado pase a "Descargada". Sirve cuando el
  // active flow se movió a otra solicitud y dejó atrás una en "Lista", o cuando el
  // usuario quiere re-bajar el ZIP de una ya descargada.
  const handleDescargarFromList = useCallback(
    async (idSolicitud: string) => {
      await apiClient.descargar(idSolicitud);
      refreshSolicitudes();
    },
    [apiClient, refreshSolicitudes],
  );

  // Borra la solicitud del catálogo local. Si era la del flujo activo, reseteamos
  // el hook (no queremos seguir polleando un id que ya no existe).
  const handleEliminarFromList = useCallback(
    async (idSolicitud: string) => {
      if (!fielStatus.rfc) return;
      await apiClient.deleteSolicitud(fielStatus.rfc, idSolicitud);
      if (requestId === idSolicitud) reset();
      refreshSolicitudes();
    },
    [apiClient, fielStatus.rfc, refreshSolicitudes, requestId, reset],
  );

  // Expande "Ambos" en dos solicitudes (E + R). El hook arranca PRIMERO con la
  // "última" (R) para que setState('requesting') aplique de inmediato y el
  // botón se desactive sin esperar al SAT. La "previa" (E) sale en paralelo
  // por apiClient directo; queda en el catálogo y aparece en la lista.
  const SLOW_NOTICE_MS = 30_000;

  const handleSubmit = useCallback(
    async (params: DescargaFormParams) => {
      setSubmitError(null);
      setSubmitting(true);
      setEsperaLarga(false);
      const slowTimer = setTimeout(() => setEsperaLarga(true), SLOW_NOTICE_MS);
      try {
        const tipos: ('E' | 'R')[] =
          params.tipo_comprobante === 'A' ? ['E', 'R'] : [params.tipo_comprobante];
        const previas = tipos.slice(0, -1);
        const ultima = tipos[tipos.length - 1];

        // 1) Última por el hook (sin await): el setState síncrono del hook se
        //    aplica antes del primer yield → botón se desactiva instantáneo.
        const ultimaPromise = solicitar({
          fecha_inicio: params.fecha_inicio,
          fecha_fin: params.fecha_fin,
          tipo_solicitud: params.tipo_solicitud,
          tipo_comprobante: ultima,
        });

        // 2) Previas por apiClient directo, capturando errores individualmente
        //    para poder mostrarlos en el Alert (no swallowarlos en silencio).
        const previasPromise = Promise.all(
          previas.map(async (t) => {
            try {
              await apiClient.solicitar({
                fecha_inicio: params.fecha_inicio,
                fecha_fin: params.fecha_fin,
                tipo_solicitud: params.tipo_solicitud,
                tipo_comprobante: t,
              });
              return null;
            } catch (e) {
              const msg = mensajeDeError(e);
              console.warn('[descarga/previa]', t, e);
              return { tipo: t, msg };
            }
          }),
        );

        const [, previasResults] = await Promise.all([ultimaPromise, previasPromise]);
        refreshSolicitudes();

        const previaErrors = previasResults.filter(
          (r): r is { tipo: 'E' | 'R'; msg: string } => r !== null,
        );
        if (previaErrors.length > 0) {
          const tipos = previaErrors
            .map((r) => (r.tipo === 'E' ? 'Emitidos' : 'Recibidos'))
            .join(' y ');
          setSubmitError(
            `No se pudo solicitar ${tipos}: ${traducirError(previaErrors[0].msg)}`,
          );
        }
      } catch (e) {
        const msg = mensajeDeError(e);
        console.error('[descarga/submit]', e);
        setSubmitError(traducirError(msg));
      } finally {
        clearTimeout(slowTimer);
        setEsperaLarga(false);
        setSubmitting(false);
      }
    },
    [apiClient, solicitar, refreshSolicitudes],
  );

  const fielLoaded = fielStatus.loaded;
  const isRequesting = state === 'requesting' || submitting;
  const showForm = state === 'idle' || state === 'error' || isRequesting;
  const showPolling = state === 'polling' || isRequesting || state === 'ready';
  const showPackages = state === 'ready' || state === 'downloading' || state === 'done';

  // -------------------------------------------------------------------------
  // Despacho según credenciales de la empresa activa.
  // -------------------------------------------------------------------------
  // 1. Empresa con FIEL → Web Service (volumen grande, horas) + CTA a /rapida.
  // 2. Empresa con solo CIEC → scraping inline (no hay opción de WS).
  // 3. Empresa sin nada → empty state hacia /empresas.
  // El "no hay empresa activa" cae en el caso 3 (tieneFiel y tieneCiec ambos false).
  // -------------------------------------------------------------------------

  const description = !empresaActiva
    ? 'Selecciona una empresa activa en Empresas para descargar sus facturas.'
    : tieneFiel
      ? 'Descarga en bloque por el Web Service oficial del SAT con tu e.firma. Ideal para grandes volúmenes; normalmente queda lista en un par de horas, aunque en días de mucha demanda el SAT puede tardar más.'
      : tieneCiec
        ? 'Trae tus facturas directo del portal del SAT con tu Contraseña (antes CIEC). Te pediremos resolver el captcha del SAT y aplica el límite diario del portal.'
        : 'Esta empresa no tiene accesos registrados.';

  return (
    <div className="space-y-6">
      <PageHeading
        title="Descargar CFDIs"
        description={description}
        action={
          tieneFiel && state !== 'idle' ? (
            <Button variant="outline" size="sm" onClick={reset}>
              <Icon icon="ph:arrow-counter-clockwise-light" className="size-4" />
              Nueva solicitud
            </Button>
          ) : undefined
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

      {/* ----------------------------------------------------------------- */}
      {/* Caso 3: sin credenciales (incluye "sin empresa activa")            */}
      {/* ----------------------------------------------------------------- */}
      {isConnected && !tieneFiel && !tieneCiec && (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertTitle>
            {empresaActiva ? 'Esta empresa no tiene método de autenticación' : 'Sin empresa activa'}
          </AlertTitle>
          <AlertDescription>
            {/* Un solo <p>: AlertDescription es grid y apilaría texto y Link. */}
            <p>
              Agrega tu <strong>e.firma</strong> (recomendado: desbloquea la descarga masiva por Web
              Service y elimina el captcha) o tu <strong>Contraseña del SAT</strong> (descarga directa con captcha)
              en{' '}
              <Link href="/empresas" className="font-medium underline underline-offset-2">
                Empresas
              </Link>
              .
            </p>
          </AlertDescription>
        </Alert>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Caso 2: solo CIEC → scraping inline                                */}
      {/* ----------------------------------------------------------------- */}
      {isConnected && empresaActiva && !tieneFiel && tieneCiec && (
        <>
          <Alert>
            <Icon icon="ph:info-light" className="size-4" />
            <AlertTitle>Con e.firma desbloqueas más opciones</AlertTitle>
            <AlertDescription>
              <p>
                Agrega la e.firma de esta empresa en{' '}
                <Link href="/empresas" className="font-medium underline underline-offset-2">
                  Empresas
                </Link>{' '}
                para acceder a descarga masiva por Web Service y para descargar el portal sin captcha.
              </p>
            </AlertDescription>
          </Alert>

          <PortalDescargaForm empresa={empresaActiva} onJobDone={refreshHistorial} />

          <PortalDescargasRecientes rfc={empresaActiva.rfc} descargas={historial} />
        </>
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Caso 1: con FIEL → flujo WS + CTA "Descarga rápida"                */}
      {/* ----------------------------------------------------------------- */}
      {isConnected && tieneFiel && (
        <>
          {/* FIEL no cargada en sesión (e.firma corrupta/contraseña mala/timeout). */}
          {!fielLoaded && (
            <Alert>
              <Icon icon="ph:warning-circle-light" className="size-4" />
              <AlertTitle>e-Firma no cargada</AlertTitle>
              <AlertDescription>
                <p>
                  La empresa activa tiene e.firma registrada, pero no se cargó en sesión.
                  Vuelve a activarla desde{' '}
                  <Link href="/empresas" className="font-medium underline underline-offset-2">
                    Empresas
                  </Link>
                  .
                </p>
              </AlertDescription>
            </Alert>
          )}

          {/* CTA: Descarga rápida sin esperar al SAT. */}
          <Callout
            icon="ph:lightning-light"
            title="¿Pocas facturas y las necesitas ya?"
            text="Descarga directa del portal del SAT, sin esperar al Web Service. Limitada al máximo de descargas que el portal permite (500 XML por día)."
            action={
              <Button variant="outline" size="sm" asChild>
                <Link href="/descarga/rapida">
                  Descarga rápida
                </Link>
              </Button>
            }
          />

          {/* Espera larga (>30s): aviso intermedio para que el usuario sepa
              que el SAT está lento y pueda cambiarse a la descarga rápida sin
              esperar el error final (que puede tardar 5+ min entre reintentos). */}
          {submitting && esperaLarga && (
            <Alert variant="warning">
              <Icon icon="ph:hourglass-medium-light" className="size-4" />
              <AlertTitle>El SAT está tardando más de lo normal</AlertTitle>
              <AlertDescription className="space-y-2">
                <div>
                  La solicitud puede tardar varios minutos cuando el Web Service
                  del SAT está saturado. Seguimos reintentando.
                </div>
                <div>
                  Si no quieres esperar, puedes hacer{' '}
                  <Link
                    href="/descarga/rapida"
                    className="font-medium underline underline-offset-2"
                  >
                    Descarga rápida
                  </Link>{' '}
                  (limitada a 500 XML por día).
                </div>
              </AlertDescription>
            </Alert>
          )}

          {/* Error */}
          {(error || submitError) && (() => {
            const esSat = esErrorDelSat(submitError || error);
            const mensaje = esSat
              ? 'El SAT no está respondiendo como se debe. Inténtalo más tarde.'
              : submitError || traducirError(error);
            return (
              <Alert variant="destructive">
                <Icon icon="ph:warning-circle-light" className="size-4" />
                <AlertTitle>Error</AlertTitle>
                <AlertDescription className="space-y-2">
                  <div>{mensaje}</div>
                  {esSat && (
                    <div>
                      También puedes hacer{' '}
                      <Link
                        href="/descarga/rapida"
                        className="font-medium underline underline-offset-2"
                      >
                        Descarga rápida
                      </Link>{' '}
                      (limitada a 500 XML por día).
                    </div>
                  )}
                </AlertDescription>
              </Alert>
            );
          })()}

          {/* Form */}
          {showForm && (
            <DescargaForm
              onSubmit={handleSubmit}
              isLoading={isRequesting}
              disabled={!isConnected || !fielLoaded}
            />
          )}

          {/* Polling status */}
          {showPolling && (
            <PollingDisplay
              requestId={requestId}
              codEstado={codEstado}
              mensaje={mensaje}
              numeroCfdis={numeroCfdis}
              isPolling={state === 'polling' || isRequesting}
            />
          )}

          {/* Package list and download */}
          {showPackages && (
            <PackageList
              packageIds={packageIds}
              onDescargar={descargar}
              isDownloading={state === 'downloading'}
              archivosDescargados={archivosDescargados}
              numeroCfdis={numeroCfdis}
            />
          )}

          {/* Solicitudes recientes — historial WS de la empresa activa */}
          {fielLoaded && (
            <SolicitudesList
              solicitudes={solicitudes}
              loading={loadingSolicitudes}
              onDescargar={handleDescargarFromList}
              onEliminar={handleEliminarFromList}
            />
          )}
        </>
      )}
    </div>
  );
}

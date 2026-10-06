'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { cn } from '@/lib/utils';
import { Icon } from '@/components/ui/icon';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { CaptchaModal } from '@/components/descarga/captcha-modal';
import { JobProgress } from '@/components/descarga/job-progress';
import { NavegadorStatusBanner } from '@/components/shared/navegador-status';
import { RenovarEfirmaWizard } from '@/components/fiel/renovar-efirma-wizard';
import { SubirEspacioDialog } from '@/components/empresas/subir-espacio-dialog';
import { esWeb } from '@/lib/modo';
import { mensajeDeError } from '@/lib/errores';
import { abrirODescargar, iconoAbrir, tituloAbrir } from '@/lib/descargas';
import { semaforoVencimiento } from '@/lib/vencimiento';
import { semaforoOpinion } from '@/lib/opinion';
import { formatDate } from '@/lib/formatting';
import { metodoPortalPreferido, etiquetaMetodo } from '@/lib/empresa-metodo';
import { RENOVACION_EFIRMA_HABILITADA } from '@/lib/features';
import type { Empresa } from '@/lib/types';

interface Props {
  empresa: Empresa;
  /** Llamado cuando termina un job exitoso, para que el padre refresque el semáforo. */
  onJobDone: () => void;
  /**
   * Arranca sola la descarga de este documento al abrir la fila (orden de ⌘K
   * "constancia de ..." para una empresa con Contraseña: el captcha sale aquí).
   */
  autoBajar?: Documento;
  onAutoBajarIniciado?: () => void;
}

type Documento = 'constancia' | 'opinion';
type ModoAbrir = 'archivo' | 'carpeta';

function formatoFecha(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return new Date(iso).toLocaleString('es-MX');
  } catch {
    return iso;
  }
}

/**
 * Fila expandida de una empresa: grid de 3 tarjetas (e.firma con renovación en
 * línea, Constancia de Situación Fiscal y Opinión 32-D con descarga por el
 * canal preferido) + link al expediente fiscal (próximamente).
 */
export function EmpresaRowExpanded({ empresa, onJobDone, autoBajar, onAutoBajarIniciado }: Props) {
  const { apiClient } = useServer();
  const job = useJob();
  // Estado FIEL por documento: /constancia/fiel y /opinion/fiel son endpoints
  // distintos y pueden correr en paralelo. Solo CIEC se serializa (el agente
  // rechaza jobs CIEC concurrentes con 409).
  const [fielBusy, setFielBusy] = useState<Record<Documento, boolean>>({
    constancia: false,
    opinion: false,
  });
  const [fielError, setFielError] = useState<string | null>(null);
  // Acción "abrir" (PDF o carpeta) en curso, para deshabilitar el botón mientras
  // el agente local ejecuta el `open`/`explorer`. Solo una a la vez por fila.
  const [accionBusy, setAccionBusy] = useState<{ kind: Documento; modo: ModoAbrir } | null>(null);
  const [renovarOpen, setRenovarOpen] = useState(false);
  const [subirOpen, setSubirOpen] = useState(false);
  // Documento cuyo job CIEC está corriendo, para animar el botón que se clickeó
  // (el job bloquea ambos, pero solo el pulsado muestra el spinner).
  const [jobKind, setJobKind] = useState<Documento | null>(null);

  const sem = empresa.vencimiento ? semaforoVencimiento(empresa.vencimiento) : null;
  const tieneFiel = empresa.metodos.includes('fiel');
  const archivada = !!empresa.archived_at;
  const metodo = metodoPortalPreferido(empresa);
  const ciecCorriendo =
    job.estado !== 'idle' &&
    job.estado !== 'done' &&
    job.estado !== 'error' &&
    job.estado !== 'cancelled';

  function botonDisabled(kind: Documento): boolean {
    if (!metodo) return true;
    // Mientras corre un job CIEC, ambos botones se bloquean (limitación backend).
    if (ciecCorriendo) return true;
    // FIEL: solo se bloquea el botón del documento en curso; el otro queda libre.
    return fielBusy[kind];
  }

  // ¿Este documento se está descargando ahora? FIEL (síncrono) o el job CIEC
  // que se lanzó desde este botón. Alimenta el spinner + "Descargando…".
  function bajando(kind: Documento): boolean {
    return fielBusy[kind] || (ciecCorriendo && jobKind === kind);
  }

  useEffect(() => {
    if (job.estado === 'done') onJobDone();
    if (job.estado === 'done' || job.estado === 'error' || job.estado === 'cancelled') {
      setJobKind(null);
    }
  }, [job.estado, onJobDone]);

  async function bajar(kind: Documento) {
    if (botonDisabled(kind)) return;
    setFielError(null);

    if (metodo === 'fiel') {
      setFielBusy((prev) => ({ ...prev, [kind]: true }));
      try {
        await (kind === 'constancia' ? apiClient.constanciaFiel() : apiClient.opinionFiel());
        toast.success(
          kind === 'constancia' ? 'Constancia descargada' : 'Opinión 32-D descargada',
        );
        onJobDone();
      } catch (e) {
        const msg = mensajeDeError(e);
        setFielError(msg);
        toast.error(msg);
      } finally {
        setFielBusy((prev) => ({ ...prev, [kind]: false }));
      }
      return;
    }

    setJobKind(kind);
    job.iniciar(
      () =>
        kind === 'constancia'
          ? apiClient.ciecConstancia({ rfc: empresa.rfc })
          : apiClient.ciecOpinion({ rfc: empresa.rfc }),
      { rfc: empresa.rfc },
    );
  }

  // Orden de ⌘K: una sola vez por pedido. Con e.firma solo si es la empresa
  // activa (los endpoints de e.firma usan la que está en sesión).
  useEffect(() => {
    if (!autoBajar) return;
    onAutoBajarIniciado?.();
    if (metodo === 'fiel' && !empresa.default) return;
    void bajar(autoBajar);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoBajar]);

  async function abrir(kind: Documento, modo: ModoAbrir) {
    const ruta = kind === 'constancia' ? empresa.csf_path : empresa.opinion_path;
    if (!ruta || accionBusy) return;
    setFielError(null);
    setAccionBusy({ kind, modo });
    try {
      await abrirODescargar(apiClient, ruta, modo);
    } catch (e) {
      const msg = mensajeDeError(e);
      setFielError(msg);
      toast.error(msg);
    } finally {
      setAccionBusy(null);
    }
  }

  function renderAccionesArchivo(kind: Documento, ruta: string | null | undefined) {
    if (!ruta) return null;
    const ocupado = accionBusy !== null;
    const esPdf = ruta.toLowerCase().endsWith('.pdf');
    const cargandoArchivo = accionBusy?.kind === kind && accionBusy.modo === 'archivo';
    const cargandoCarpeta = accionBusy?.kind === kind && accionBusy.modo === 'carpeta';
    return (
      <>
        {esPdf && (
          <Button
            variant="ghost"
            size="icon"
            onClick={() => abrir(kind, 'archivo')}
            disabled={ocupado}
            title={tituloAbrir('archivo')}
          >
            <Icon
              icon={cargandoArchivo ? 'ph:circle-notch-light' : iconoAbrir('archivo')}
              className={cargandoArchivo ? 'size-4 animate-spin' : 'size-4'}
            />
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={() => abrir(kind, 'carpeta')}
          disabled={ocupado}
          title={tituloAbrir('carpeta')}
        >
          <Icon
            icon={cargandoCarpeta ? 'ph:circle-notch-light' : iconoAbrir('carpeta')}
            className={cargandoCarpeta ? 'size-4 animate-spin' : 'size-4'}
          />
        </Button>
      </>
    );
  }

  /** Botón de descarga + acciones de archivo, con estado de carga. */
  function renderDescarga(kind: Documento, etiquetaNuevo: string) {
    const ruta = kind === 'constancia' ? empresa.csf_path : empresa.opinion_path;
    const trabajando = bajando(kind);
    return (
      <>
        <div className="mt-auto flex items-center gap-1 pt-1">
          <Button
            size="sm"
            variant="outline"
            className="flex-1"
            disabled={botonDisabled(kind)}
            onClick={() => bajar(kind)}
            title={!metodo ? 'Agrega FIEL o Contraseña del SAT en Empresas' : undefined}
          >
            <Icon
              icon={trabajando ? 'ph:circle-notch-light' : 'ph:download-simple-light'}
              className={cn('mr-1.5 size-3.5', trabajando && 'animate-spin')}
            />
            {trabajando ? 'Descargando…' : ruta ? 'Volver a descargar' : etiquetaNuevo}
          </Button>
          {renderAccionesArchivo(kind, ruta)}
        </div>
        {/* Con e.firma la descarga es síncrona y puede tardar (login + visor del
            SAT); sin este aviso el botón solo se ve deshabilitado. Con CIEC el
            terminal de abajo ya narra el avance. */}
        {trabajando && metodo === 'fiel' && (
          <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
            <Icon icon="ph:circle-notch-light" className="mt-0.5 size-3 shrink-0 animate-spin" />
            <span>
              Conectando con el SAT y generando el documento con tu e.firma… puede
              tardar hasta un par de minutos. No cierres la app.
            </span>
          </p>
        )}
      </>
    );
  }

  // Renovación pendiente: 'enviada' (falta bajar el cert) vs 'generada' (el
  // envío falló y se reanuda reenviando el mismo .ren). Con la renovación
  // deshabilitada no se exponen los estados de trámite (no hay forma de
  // avanzarlos): la card muestra el semáforo normal.
  const renEnviada = RENOVACION_EFIRMA_HABILITADA && !!empresa.renovacion_pendiente?.numero_operacion;
  const renGenerada = RENOVACION_EFIRMA_HABILITADA && !!empresa.renovacion_pendiente && !renEnviada;

  // Estado de la tarjeta e.firma (dot + etiqueta, estilo boceto).
  const efirmaEstado = !tieneFiel
    ? { tone: 'muted' as const, label: 'Sin e.firma registrada' }
    : renEnviada
      ? { tone: 'warn' as const, label: 'Certificado nuevo pendiente' }
      : renGenerada
        ? { tone: 'warn' as const, label: 'Renovación por reenviar' }
        : sem?.vencida
          ? { tone: 'warn' as const, label: 'Vencida' }
          : sem && sem.estado !== 'verde'
            ? { tone: 'warn' as const, label: 'Por renovar' }
            : { tone: 'ok' as const, label: 'Vigente' };

  return (
    <div className="space-y-3">
      <NavegadorStatusBanner />

      <div className="grid gap-3 sm:grid-cols-3">
        {/* e.firma */}
        <DocCardShell icon="ph:shield-check-light" titulo="e.firma">
          <EstadoDot tone={efirmaEstado.tone} label={efirmaEstado.label} />
          {tieneFiel && sem ? (
            <p className="text-xs leading-relaxed text-muted-foreground">
              {renEnviada ? (
                <>
                  La renovación ya se envió; solo falta descargar el certificado que
                  emitió el SAT.
                </>
              ) : renGenerada ? (
                <>
                  El envío al SAT falló en ese momento; tu e.firma sigue intacta.
                  Reanuda para reenviar la misma solicitud.
                </>
              ) : (
                <>
                  {sem.vencida ? 'Venció el' : 'Vence el'} {formatDate(sem.fecha)}
                  {!sem.vencida && sem.dias >= 0 && (
                    <> · {sem.dias === 0 ? 'hoy' : `en ${sem.dias} ${sem.dias === 1 ? 'día' : 'días'}`}</>
                  )}
                </>
              )}
            </p>
          ) : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Esta empresa opera con Contraseña del SAT. Registra su e.firma para la descarga masiva.
            </p>
          )}
          <div className="mt-auto flex items-center gap-1.5 pt-1">
            {tieneFiel ? (
              RENOVACION_EFIRMA_HABILITADA ? (
                <Button
                  size="sm"
                  variant={empresa.renovacion_pendiente || (sem && sem.estado !== 'verde') ? 'default' : 'outline'}
                  className="flex-1"
                  onClick={() => setRenovarOpen(true)}
                >
                  <Icon
                    icon={renEnviada ? 'ph:download-simple-light' : 'ph:arrow-clockwise-light'}
                    className="mr-1.5 size-3.5"
                  />
                  {renEnviada
                    ? 'Descargar certificado'
                    : renGenerada
                      ? 'Reanudar renovación'
                      : 'Renovar e.firma'}
                </Button>
              ) : (
                <span className="flex-1" title="Disponible próximamente">
                  <Button size="sm" variant="outline" className="w-full" disabled>
                    <Icon icon="ph:arrow-clockwise-light" className="mr-1.5 size-3.5" />
                    Renovar e.firma
                  </Button>
                </span>
              )
            ) : (
              <Button size="sm" variant="outline" className="flex-1" asChild>
                <Link href={`/empresas/detalle?rfc=${encodeURIComponent(empresa.rfc)}`}>
                  <Icon icon="ph:plus-light" className="mr-1.5 size-3.5" />
                  Registrar e.firma
                </Link>
              </Button>
            )}
            {/* Opt-in: subir las credenciales al espacio en línea (solo desde
                la desktop y solo si aquí HAY credenciales que subir). */}
            {!esWeb() && empresa.metodos.length > 0 && (
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                onClick={() => setSubirOpen(true)}
                title="Sube sus credenciales cifradas a tu espacio privado para operar desde el navegador"
              >
                <Icon icon="ph:cloud-arrow-up-light" className="mr-1.5 size-3.5" />
                Usar en la web
              </Button>
            )}
          </div>
        </DocCardShell>

        {/* Constancia de Situación Fiscal */}
        <DocCardShell icon="ph:file-text-light" titulo="Constancia de Situación Fiscal">
          {metodo && (
            <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              <Icon
                icon={metodo === 'fiel' ? 'ph:shield-check-light' : 'ph:key-light'}
                className="size-3"
              />
              Usando {etiquetaMetodo(metodo)}
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {empresa.csf_descargada_en
              ? `Última descarga · ${formatoFecha(empresa.csf_descargada_en)}`
              : 'Aún no la has descargado'}
          </p>
          {renderDescarga('constancia', 'Descargar CSF')}
          {!metodo && (
            <p className="text-xs text-muted-foreground">Agrega FIEL o Contraseña del SAT en Empresas.</p>
          )}
        </DocCardShell>

        {/* Opinión de Cumplimiento 32-D */}
        <DocCardShell icon="ph:clipboard-text-light" titulo="Opinión de Cumplimiento 32-D">
          {metodo && (
            <div className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
              <Icon
                icon={metodo === 'fiel' ? 'ph:shield-check-light' : 'ph:key-light'}
                className="size-3"
              />
              Usando {etiquetaMetodo(metodo)}
            </div>
          )}
          <p className="text-xs text-muted-foreground">
            {empresa.opinion_descargada_en
              ? `Última descarga · ${formatoFecha(empresa.opinion_descargada_en)}`
              : 'Aún no la has descargado'}
          </p>
          {empresa.opinion_status && (
            <div
              className={cn(
                'flex items-center gap-1.5 text-xs font-medium',
                semaforoOpinion(empresa).tono === 'rojo'
                  ? 'text-red-600 dark:text-red-400'
                  : semaforoOpinion(empresa).tono === 'verde'
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-amber-600 dark:text-amber-400',
              )}
            >
              <Icon
                icon={
                  semaforoOpinion(empresa).tono === 'rojo'
                    ? 'ph:warning-circle-light'
                    : semaforoOpinion(empresa).tono === 'verde'
                      ? 'ph:check-circle-light'
                      : 'ph:info-light'
                }
                className="size-3.5 shrink-0"
              />
              Opinión {semaforoOpinion(empresa).label.toLowerCase()}
              {semaforoOpinion(empresa).negativa && ' · ver detalle de la empresa'}
            </div>
          )}
          {renderDescarga('opinion', 'Descargar 32-D')}
          {!metodo && (
            <p className="text-xs text-muted-foreground">Agrega FIEL o Contraseña del SAT en Empresas.</p>
          )}
        </DocCardShell>
      </div>

      {/* Expediente fiscal: pantalla en camino — entrada deshabilitada a propósito. */}
      {!archivada && (
        <div className="flex justify-end">
          <span title="Próximamente">
            <button
              type="button"
              disabled
              className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12.5px] font-semibold text-muted-foreground/50"
            >
              Ver expediente fiscal completo
              <Icon icon="ph:caret-right-light" className="size-3.5" />
            </button>
          </span>
        </div>
      )}

      {job.estado !== 'idle' && (
        <JobProgress
          estado={job.estado}
          log={job.log}
          resultado={job.resultado}
          error={job.error}
        />
      )}

      {job.error && (
        <Alert variant="destructive">
          <AlertDescription>{job.error}</AlertDescription>
        </Alert>
      )}

      {fielError && (
        <Alert variant="destructive">
          <AlertDescription>{fielError}</AlertDescription>
        </Alert>
      )}

      <CaptchaModal captcha={job.captcha} onResolver={job.responderCaptcha} />

      <SubirEspacioDialog
        empresa={empresa}
        open={subirOpen}
        onOpenChange={setSubirOpen}
        onDone={onJobDone}
      />

      {tieneFiel && RENOVACION_EFIRMA_HABILITADA && (
        <RenovarEfirmaWizard
          empresa={empresa}
          open={renovarOpen}
          onOpenChange={setRenovarOpen}
          onDone={onJobDone}
        />
      )}
    </div>
  );
}

/** Tarjeta del grid (estilo `emp-det-card` del boceto). */
function DocCardShell({
  icon,
  titulo,
  children,
}: {
  icon: string;
  titulo: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-h-31 flex-col gap-2 rounded-xl border border-border bg-card p-3.5">
      <div className="flex items-center gap-2 text-[13px] font-bold tracking-tight">
        <Icon icon={icon} className="size-4 shrink-0 text-muted-foreground" />
        {titulo}
      </div>
      {children}
    </section>
  );
}

function EstadoDot({ tone, label }: { tone: 'ok' | 'warn' | 'muted'; label: string }) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 text-[12.5px] font-semibold',
        tone === 'ok' && 'text-success',
        tone === 'warn' && 'text-warning',
        tone === 'muted' && 'text-muted-foreground',
      )}
    >
      <span
        className={cn(
          'size-2 shrink-0 rounded-full',
          tone === 'ok' && 'bg-success',
          tone === 'warn' && 'bg-warning',
          tone === 'muted' && 'bg-muted-foreground/40',
        )}
      />
      {label}
    </div>
  );
}

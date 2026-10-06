'use client';

import { useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { semaforoVencimiento } from '@/lib/vencimiento';
import { formatDate } from '@/lib/formatting';
import { cn } from '@/lib/utils';
import { abrirODescargar } from '@/lib/descargas';
import type { Empresa, RenovarResultado } from '@/lib/types';
import { Icon } from '@/components/ui/icon';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { WizardSteps } from '@/components/shared/wizard-steps';
import { FasesProgreso, type FaseItem } from '@/components/shared/fases-progreso';

const PASOS = ['Vigencia', 'Confirmar', 'Renovar', 'Listo'];

const FASES_RENOVAR: FaseItem[] = [
  { label: 'Generando el requerimiento de renovación (RENOVA)…', fases: ['generando'] },
  { label: 'Firmando con tu e.firma vigente…', fases: ['firmando'] },
  {
    label: 'Enviando la solicitud al SAT (CertiSAT)…',
    fases: ['enviando', 'login_ok', 'subiendo', 'numero_operacion', 'acuse'],
  },
  { label: 'Descargando tu nuevo certificado…', fases: ['recuperando', 'cer', 'guardando'] },
];

const FASES_RECUPERAR: FaseItem[] = [
  {
    label: 'Buscando tu certificado nuevo en el SAT…',
    fases: ['login_ok', 'recuperando'],
  },
  { label: 'Descargando y guardando tu e.firma renovada…', fases: ['cer', 'guardando'] },
];

// Fases a partir de las cuales el .ren YA se envió: un reintento debe ir a
// /renovar/recuperar (no re-enviar el trámite, que es único e irreversible).
const FASES_POST_ENVIO = new Set(['numero_operacion', 'acuse', 'recuperando', 'cer', 'guardando']);

const URL_RENOVACION_SAT = 'https://www.sat.gob.mx/tramites/operacion/17676/renueva-el-certificado-de-tu-e.firma-(antes-firma-electronica)';

interface RenovarEfirmaWizardProps {
  empresa: Empresa;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Se llama al cerrar tras un trámite exitoso (refrescar catálogo/health). */
  onDone?: () => void;
  /** Abre la vía manual de actualizar .cer/.key (e.firma vencida renovada presencialmente). */
  onActualizarArchivos?: () => void;
}

/**
 * Asistente de renovación de e.firma EN LÍNEA (4 pasos: Vigencia → Confirmar →
 * Renovar → Listo). El agente genera el .ren, lo firma con el certificado
 * vigente, lo envía a CertiSAT y sustituye la e.firma del catálogo al
 * recuperar el .cer nuevo. Si la empresa ya tiene una renovación enviada
 * pendiente, el asistente abre en modo «descargar certificado».
 */
export function RenovarEfirmaWizard({
  empresa,
  open,
  onOpenChange,
  onDone,
  onActualizarArchivos,
}: RenovarEfirmaWizardProps) {
  const { apiClient } = useServer();
  const job = useJob();

  const [paso, setPaso] = useState(0);
  const [password, setPassword] = useState('');
  const [acepto, setAcepto] = useState(false);
  // 'enviar' = trámite completo; 'recuperar' = solo bajar el cert pendiente.
  const [modo, setModo] = useState<'enviar' | 'recuperar'>('enviar');

  const pendiente = empresa.renovacion_pendiente ?? null;
  // 'enviada' (hay número de operación) → solo falta descargar el cert.
  // 'generada' (el envío falló) → se reenvía el MISMO .ren con POST /renovar.
  const pendienteEnviada = !!pendiente?.numero_operacion;
  const pendienteGenerada = !!pendiente && !pendiente.numero_operacion;
  const sem = semaforoVencimiento(empresa.vencimiento);
  const vencida = sem?.vencida ?? false;

  const resultado = job.resultado as RenovarResultado | null;
  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';
  const exito = job.estado === 'done' && !!resultado?.renovada;

  // La UI del paso 2 avanza sola a "Listo" cuando el job termina bien.
  useEffect(() => {
    if (paso === 2 && job.estado === 'done') setPaso(3);
  }, [paso, job.estado]);

  // Reinicia el asistente cada vez que se abre (el modal se controla desde el
  // padre, así que reaccionamos al flanco de `open`). `job.reset` limpia el
  // EventSource del job previo — es la parte que exige un Effect (recurso
  // externo); las demás son setters estables. `modo` no se toca aquí: cada
  // acción (renovar/recuperar) lo fija antes de llegar al paso de progreso.
  useEffect(() => {
    if (!open) return;
    setPaso(0);
    setPassword('');
    setAcepto(false);
    job.reset();
  }, [open, job.reset]);

  function handleOpenChange(next: boolean) {
    if (!next && corriendo) return; // no cerrar a media renovación
    if (!next && exito) onDone?.();
    onOpenChange(next);
  }

  function renovar() {
    setPaso(2);
    setModo('enviar');
    void job.iniciar(
      () => apiClient.renovarEfirma({
        rfc: empresa.rfc,
        password,
        confirmar: true,
      }),
      { rfc: empresa.rfc, canal: 'fiel', notificar: false },
    );
  }

  function recuperar() {
    setPaso(2);
    setModo('recuperar');
    void job.iniciar(
      () => apiClient.renovarRecuperar({ rfc: empresa.rfc }),
      { rfc: empresa.rfc, canal: 'fiel', notificar: false },
    );
  }

  function reintentar() {
    // Si el .ren ya se envió (hay número de operación), NUNCA re-enviar:
    // el reintento va por /renovar/recuperar.
    if (modo === 'recuperar' || (job.fase && FASES_POST_ENVIO.has(job.fase))) {
      recuperar();
    } else {
      renovar();
    }
  }

  const puedeContinuar = !vencida && !pendienteEnviada;
  const confirmarListo = password.length >= 4 && acepto;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg" onInteractOutside={(e) => corriendo && e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Renovar e.firma</DialogTitle>
          {paso < 3 && (
            <DialogDescription>
              {empresa.nombre} · <span className="font-mono">{empresa.rfc}</span>
            </DialogDescription>
          )}
        </DialogHeader>

        {paso < 3 && <WizardSteps pasos={PASOS} actual={paso} />}

        {/* Paso 0 — Vigencia */}
        {paso === 0 && (
          <div className="space-y-3.5">
            <EstadoVigencia empresa={empresa} />

            {pendienteEnviada && pendiente ? (
              <Alert>
                <AlertTitle>Tu certificado nuevo está en camino</AlertTitle>
                <AlertDescription>
                  Ya enviaste la renovación (operación{' '}
                  <span className="font-mono">{pendiente.numero_operacion}</span>). Solo
                  falta descargar el certificado que emitió el SAT (suele tardar unos
                  minutos).
                </AlertDescription>
              </Alert>
            ) : pendienteGenerada ? (
              <Alert>
                <AlertTitle>Retomamos donde te quedaste</AlertTitle>
                <AlertDescription>
                  Tu solicitud de renovación quedó generada, pero el portal del SAT
                  falló al enviarla. Nada llegó al SAT y{' '}
                  <span className="font-semibold text-foreground">
                    tu e.firma actual sigue intacta
                  </span>
                  : al continuar, reenviamos la misma solicitud.
                </AlertDescription>
              </Alert>
            ) : vencida ? (
              <Alert variant="warning">
                <AlertTitle>La renovación en línea ya no es posible.</AlertTitle>
                <AlertDescription>
                  Como tu e.firma ya venció, debes renovarla presencialmente en una
                  oficina del SAT con cita. Cuando tengas los archivos nuevos,
                  actualízalos aquí.
                </AlertDescription>
              </Alert>
            ) : (
              <div className="flex items-start gap-2 rounded-lg bg-accent px-3 py-2.5 text-xs leading-relaxed text-accent-foreground">
                <Icon icon="ph:info-light" className="mt-px size-3.75 shrink-0" />
                <span>
                  Como tu e.firma <strong>sigue vigente</strong>, TodoConta la renueva{' '}
                  <strong>en línea</strong> por ti: genera la solicitud de renovación
                  (*.ren), la firma con tu certificado actual y la envía al SAT. Tardamos
                  unos minutos. Tú ve por un café.
                </span>
              </div>
            )}

            {!vencida && !pendienteEnviada && (
              <dl className="space-y-2.5 rounded-xl border border-border/60 p-3.5 text-[13px]">
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-xs text-muted-foreground">RFC</dt>
                  <dd className="font-mono text-xs font-medium">{empresa.rfc}</dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  {/* Sin fecha exacta: la vigencia corre desde que el SAT emite el
                      certificado, no desde hoy (junto al vencimiento actual, una
                      estimación al día parece error de fechas). */}
                  <dt className="text-xs text-muted-foreground">Vigencia nueva</dt>
                  <dd className="font-semibold">4 años a partir de la emisión</dd>
                </div>
              </dl>
            )}

            <DialogFooter>
              <Button variant="ghost" onClick={() => handleOpenChange(false)}>
                Cancelar
              </Button>
              {pendienteEnviada ? (
                <Button onClick={recuperar}>
                  <Icon icon="ph:download-simple-light" className="size-4" />
                  Descargar certificado
                </Button>
              ) : vencida ? (
                <>
                  {onActualizarArchivos && (
                    <Button
                      onClick={() => {
                        onOpenChange(false);
                        onActualizarArchivos();
                      }}
                    >
                      <Icon icon="ph:upload-light" className="size-4" />
                      Actualizar archivos (.cer/.key)
                    </Button>
                  )}
                  <Button variant="outline" asChild>
                    <a href={URL_RENOVACION_SAT} target="_blank" rel="noreferrer">
                      <Icon icon="ph:link-light" className="size-4" />
                      Ver cómo renovar en el SAT
                    </a>
                  </Button>
                </>
              ) : (
                <Button onClick={() => setPaso(1)} disabled={!puedeContinuar}>
                  Continuar
                  <Icon icon="ph:arrow-right-light" className="size-4" />
                </Button>
              )}
            </DialogFooter>
          </div>
        )}

        {/* Paso 1 — Confirmar */}
        {paso === 1 && (
          <div className="space-y-3.5">
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Confirma la contraseña de tu <strong className="text-foreground">clave privada (.key)</strong>{' '}
              para firmar la solicitud de renovación. Tu e.firma se usa solo en este
              equipo y no sale de tu computadora.
            </p>

            <div className="space-y-2">
              <Label htmlFor="renovar-pass">Contraseña de la clave privada</Label>
              <Input
                id="renovar-pass"
                type="password"
                placeholder="••••••••"
                value={password}
                autoFocus
                onChange={(e) => setPassword(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Es la contraseña de tu e.firma vigente, no la del SAT en línea.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-success/10 px-3 py-2.5">
              <span className="inline-flex items-center gap-1.5 font-mono text-xs font-semibold text-success">
                <Icon icon="ph:check-circle-light" className="size-3.75" /> certificado.cer
              </span>
              <span className="inline-flex items-center gap-1.5 font-mono text-xs font-semibold text-success">
                <Icon icon="ph:check-circle-light" className="size-3.75" /> clave.key
              </span>
              <span className="ml-auto text-[11px] text-muted-foreground">
                Guardados y protegidos en este equipo
              </span>
            </div>

            {/* Confirmación explícita: el trámite es único e irreversible. */}
            <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-warning/40 bg-warning/5 px-3 py-2.5 text-xs leading-relaxed">
              <input
                type="checkbox"
                checked={acepto}
                onChange={(e) => setAcepto(e.target.checked)}
                className="mt-0.5 size-3.75 shrink-0 accent-primary"
              />
              <span>
                Entiendo que mi e.firma actual quedará <strong>sustituida</strong> por la
                nueva y que este trámite <strong>no se puede deshacer</strong>.
              </span>
            </label>

            <DialogFooter>
              <Button variant="ghost" onClick={() => setPaso(0)}>
                Atrás
              </Button>
              <Button onClick={renovar} disabled={!confirmarListo}>
                <Icon icon="ph:shield-check-light" className="size-4" />
                Renovar en línea
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Paso 2 — Proceso */}
        {paso === 2 && (
          <div className="space-y-3.5">
            <FasesProgreso
              items={modo === 'recuperar' ? FASES_RECUPERAR : FASES_RENOVAR}
              faseActual={job.fase}
              estado={job.estado}
            />

            {job.estado === 'error' && (
              <>
                <Alert variant="destructive">
                  <AlertTitle>El trámite no se completó</AlertTitle>
                  <AlertDescription>{job.error}</AlertDescription>
                </Alert>
                {/* Tranquilidad ante el portal caído: el progreso queda guardado
                    y el reintento continúa desde la etapa donde se atoró. */}
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {modo === 'recuperar' || (job.fase && FASES_POST_ENVIO.has(job.fase)) ? (
                    <>
                      La solicitud <strong className="text-foreground">ya está en el SAT</strong> y
                      tu avance quedó guardado: al reintentar solo descargamos tu
                      certificado nuevo. También puedes cerrar y retomarlo después
                      desde Empresas.
                    </>
                  ) : (
                    <>
                      Nada se envió al SAT:{' '}
                      <strong className="text-foreground">tu e.firma actual sigue intacta</strong>.
                      La solicitud quedó guardada; reintenta ahora o cierra y
                      retómala después desde Empresas y se reenviará la misma.
                    </>
                  )}
                </p>
              </>
            )}

            <DialogFooter>
              {corriendo ? (
                <p className="mr-auto text-xs text-muted-foreground">
                  No cierres la ventana mientras se completa el trámite…
                </p>
              ) : job.estado === 'error' ? (
                <>
                  <Button variant="ghost" onClick={() => handleOpenChange(false)}>
                    Cerrar
                  </Button>
                  <Button onClick={reintentar}>
                    <Icon icon="ph:arrow-clockwise-light" className="size-4" />
                    Reintentar
                  </Button>
                </>
              ) : null}
            </DialogFooter>
          </div>
        )}

        {/* Paso 3 — Listo */}
        {paso === 3 && resultado && (
          <div className="space-y-4">
            <div className="flex flex-col items-center px-2 pt-2 text-center">
              <span
                className={cn(
                  'mb-3.5 inline-flex size-16 items-center justify-center rounded-full',
                  resultado.renovada ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning',
                )}
              >
                <Icon
                  icon={resultado.renovada ? 'ph:seal-check-light' : 'ph:clock-light'}
                  className="size-8.5"
                />
              </span>
              <h3 className="text-lg font-extrabold tracking-tight">
                {resultado.renovada ? 'e.firma renovada' : 'Tu certificado está en camino'}
              </h3>
              <p className="mt-1.5 max-w-[46ch] text-[13px] leading-relaxed text-muted-foreground">
                {resultado.renovada ? (
                  <>
                    El SAT emitió tu nuevo certificado y se guardó automáticamente en
                    este equipo. Ya puedes usarlo para descargas masivas y trámites.
                  </>
                ) : (
                  <>
                    La renovación se envió (operación{' '}
                    <span className="font-mono">{resultado.numero_operacion}</span>), pero
                    el SAT sigue emitiendo tu certificado. Suele tardar unos minutos;
                    puedes descargarlo ahora o más tarde desde Empresas.
                  </>
                )}
              </p>
            </div>

            {resultado.renovada && (
              <>
                <dl className="space-y-2.5 rounded-xl border border-border/60 p-3.5 text-[13px]">
                  {resultado.vencimiento && (
                    <div className="flex items-baseline justify-between gap-3">
                      <dt className="text-xs text-muted-foreground">Vigencia</dt>
                      <dd className="font-semibold">Hasta {formatDate(resultado.vencimiento)}</dd>
                    </div>
                  )}
                  <div className="flex items-baseline justify-between gap-3">
                    <dt className="text-xs text-muted-foreground">Estado</dt>
                    <dd className="font-semibold text-success">Vigente · 4 años</dd>
                  </div>
                </dl>
                <div className="flex items-start gap-2 rounded-lg bg-accent px-3 py-2.5 text-xs leading-relaxed text-accent-foreground">
                  <Icon icon="ph:info-light" className="mt-px size-3.75 shrink-0" />
                  El SAT puede tardar unos minutos en reconocer tu e.firma nueva para
                  iniciar sesión en sus portales.
                </div>
              </>
            )}

            <DialogFooter>
              {resultado.renovada ? (
                <>
                  {resultado.acuse_pdf && (
                    <Button
                      variant="outline"
                      onClick={() => void abrirODescargar(apiClient, resultado.acuse_pdf!, 'archivo')}
                    >
                      <Icon icon="ph:file-pdf-light" className="size-4" />
                      Descargar acuse
                    </Button>
                  )}
                  <Button onClick={() => handleOpenChange(false)}>
                    <Icon icon="ph:check-circle-light" className="size-4" />
                    Listo
                  </Button>
                </>
              ) : (
                <>
                  <Button variant="ghost" onClick={() => handleOpenChange(false)}>
                    Bajar después
                  </Button>
                  <Button onClick={recuperar}>
                    <Icon icon="ph:download-simple-light" className="size-4" />
                    Descargar certificado
                  </Button>
                </>
              )}
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** Caja de estado con el semáforo de vigencia (paso 0). */
function EstadoVigencia({ empresa }: { empresa: Empresa }) {
  const sem = semaforoVencimiento(empresa.vencimiento);
  if (!sem) return null;
  const tono =
    sem.estado === 'rojo'
      ? 'bg-destructive/10 text-destructive'
      : sem.estado === 'amarillo'
        ? 'bg-warning/10 text-warning'
        : 'bg-secondary text-muted-foreground';
  return (
    <div className={cn('flex items-center gap-3 rounded-xl p-3.5', sem.estado === 'verde' ? 'bg-secondary' : tono.split(' ')[0])}>
      <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-lg', tono)}>
        <Icon
          icon={sem.vencida ? 'ph:warning-circle-light' : sem.estado === 'verde' ? 'ph:key-light' : 'ph:warning-light'}
          className="size-5"
        />
      </span>
      <div className="min-w-0">
        <p className="text-sm font-bold tracking-tight">
          {sem.vencida
            ? 'Tu e.firma está vencida'
            : sem.dias === 0
              ? 'Tu e.firma vence hoy'
              : `Tu e.firma vence en ${sem.dias} ${sem.dias === 1 ? 'día' : 'días'}`}
        </p>
        <p className="text-xs text-muted-foreground">
          {sem.vencida ? 'Venció el' : 'Vence el'} {formatDate(sem.fecha)}
        </p>
      </div>
    </div>
  );
}

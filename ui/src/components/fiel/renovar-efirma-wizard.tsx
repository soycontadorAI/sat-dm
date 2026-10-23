'use client';

import { useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { semaforoVencimiento } from '@/lib/vencimiento';
import { formatDate } from '@/lib/formatting';
import { cn } from '@/lib/utils';
import { abrirODescargar, guardarBlob } from '@/lib/descargas';
import { mensajeDeError } from '@/lib/errores';
import { esWeb } from '@/lib/modo';
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
import { CaptchaModal } from '@/components/descarga/captcha-modal';

const PASOS = ['Vigencia', 'Confirmar', 'Respaldo', 'Renovar', 'Listo'];

const FASES_RENOVAR: FaseItem[] = [
  { label: 'Preparando la solicitud de renovación (RENOVA)…', fases: ['generando'] },
  { label: 'Firmando con tu e.firma vigente…', fases: ['firmando'] },
  {
    label: 'Enviando la solicitud al SAT (CertiSAT)…',
    fases: ['enviando', 'login_ok', 'subiendo', 'numero_operacion', 'acuse'],
  },
  {
    label: 'Descargando tu nuevo certificado (el SAT tarda unos minutos)…',
    fases: ['recuperando', 'cer', 'guardando'],
  },
];

const FASES_RECUPERAR: FaseItem[] = [
  {
    label: 'Buscando tu certificado nuevo en la Recuperación de certificados del SAT…',
    fases: ['consultando', 'recuperando'],
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
  /** Se llama al cerrar si el trámite avanzó (refrescar catálogo/health). */
  onDone?: () => void;
  /** Abre la vía manual de actualizar .cer/.key (e.firma vencida renovada presencialmente). */
  onActualizarArchivos?: () => void;
}

/**
 * Asistente de renovación de e.firma EN LÍNEA (5 pasos: Vigencia → Confirmar →
 * Respaldo → Renovar → Listo). El agente genera el .ren y la .key nueva, el
 * usuario baja el respaldo ANTES de que el SAT reciba nada, y luego se firma y
 * envía a CertiSAT; al recuperar el .cer nuevo se sustituye la e.firma del
 * catálogo. Si la empresa ya tiene una renovación enviada, el asistente abre en
 * modo «descargar certificado» (recuperación pública del SAT, con captcha: la
 * e.firma anterior ya quedó revocada y no sirve para entrar a CertiSAT).
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
  const web = esWeb();

  const [paso, setPaso] = useState(0);
  const [password, setPassword] = useState('');
  const [acepto, setAcepto] = useState(false);
  // 'enviar' = trámite completo; 'recuperar' = solo buscar el cert emitido.
  const [modo, setModo] = useState<'enviar' | 'recuperar'>('enviar');
  const [generando, setGenerando] = useState(false);
  const [bajandoRespaldo, setBajandoRespaldo] = useState(false);
  const [respaldoBajado, setRespaldoBajado] = useState(false);
  const [errorPaso, setErrorPaso] = useState<string | null>(null);
  // Algo cambió en el catálogo (solicitud generada, enviada o e.firma nueva):
  // al cerrar, el padre refresca.
  const [cambio, setCambio] = useState(false);

  const pendiente = empresa.renovacion_pendiente ?? null;
  // 'enviada' (hay número de operación) → solo falta descargar el cert.
  // 'generada' → el SAT no la ha recibido; se envía la MISMA con POST /renovar.
  const pendienteEnviada = !!pendiente?.numero_operacion;
  const pendienteGenerada = !!pendiente && !pendiente.numero_operacion;
  const sem = semaforoVencimiento(empresa.vencimiento);
  const vencida = sem?.vencida ?? false;

  const resultado = job.resultado as RenovarResultado | null;
  const corriendo =
    job.estado === 'iniciando' || job.estado === 'corriendo' || job.estado === 'captcha';
  const exito = job.estado === 'done' && !!resultado?.renovada;

  // La UI del paso 3 avanza sola a "Listo" cuando el job termina bien.
  useEffect(() => {
    if (paso === 3 && job.estado === 'done') setPaso(4);
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
    setRespaldoBajado(false);
    setErrorPaso(null);
    setCambio(false);
    job.reset();
  }, [open, job.reset]);

  function handleOpenChange(next: boolean) {
    if (!next && corriendo) return; // no cerrar a media renovación
    if (!next && (exito || cambio || job.estado !== 'idle')) onDone?.();
    onOpenChange(next);
  }

  async function generar() {
    setGenerando(true);
    setErrorPaso(null);
    try {
      await apiClient.renovarGenerar({ rfc: empresa.rfc, password });
      setCambio(true);
      setRespaldoBajado(false);
      setAcepto(false);
      setPaso(2);
    } catch (err) {
      setErrorPaso(mensajeDeError(err));
    } finally {
      setGenerando(false);
    }
  }

  async function bajarRespaldo() {
    setBajandoRespaldo(true);
    setErrorPaso(null);
    try {
      const blob = await apiClient.renovarRespaldo(empresa.rfc);
      guardarBlob(blob, `${empresa.rfc}_renovacion_efirma.zip`);
      setRespaldoBajado(true);
    } catch (err) {
      setErrorPaso(mensajeDeError(err));
    } finally {
      setBajandoRespaldo(false);
    }
  }

  function renovar() {
    setErrorPaso(null);
    setPaso(3);
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
    setErrorPaso(null);
    setPaso(3);
    setModo('recuperar');
    void job.iniciar(
      () => apiClient.renovarRecuperar({ rfc: empresa.rfc }),
      { rfc: empresa.rfc, canal: 'fiel', notificar: false },
    );
  }

  // Si el .ren ya se envió (hay número de operación), NUNCA re-enviar.
  const yaEnviada = modo === 'recuperar' || (!!job.fase && FASES_POST_ENVIO.has(job.fase));

  function reintentar() {
    if (yaEnviada) recuperar();
    else renovar();
  }

  const puedeContinuar = !vencida && !pendienteEnviada;
  const enviarListo = respaldoBajado && acepto;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg" onInteractOutside={(e) => corriendo && e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Renovar e.firma</DialogTitle>
          {paso < 4 && (
            <DialogDescription>
              {empresa.nombre} · <span className="font-mono">{empresa.rfc}</span>
            </DialogDescription>
          )}
        </DialogHeader>

        {paso < 4 && <WizardSteps pasos={PASOS} actual={paso} />}

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
                  falta descargar el certificado que emitió el SAT: lo buscamos en su
                  Recuperación de certificados, que te pide resolver un captcha.
                </AlertDescription>
              </Alert>
            ) : pendienteGenerada ? (
              <Alert>
                <AlertTitle>Retomamos donde te quedaste</AlertTitle>
                <AlertDescription>
                  Tu solicitud de renovación ya está generada y el SAT no ha confirmado
                  recibirla:{' '}
                  <span className="font-semibold text-foreground">
                    tu e.firma actual sigue intacta
                  </span>
                  . Al continuar la enviamos tal cual, con la misma llave nueva de tu
                  respaldo.
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

            {pendienteGenerada && (
              <button
                type="button"
                onClick={recuperar}
                className="text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
              >
                ¿Ya la habías enviado al SAT? Buscar mi certificado nuevo
              </button>
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
          <form
            className="space-y-3.5"
            onSubmit={(e) => {
              e.preventDefault();
              if (password.length >= 4 && !generando) void generar();
            }}
          >
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Confirma la contraseña de tu <strong className="text-foreground">clave privada (.key)</strong>{' '}
              para firmar la solicitud de renovación.{' '}
              {web
                ? 'Tu e.firma se usa en tu espacio en línea, donde está guardada cifrada.'
                : 'Tu e.firma se usa solo en este equipo y no sale de tu computadora.'}
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
                Es la contraseña de tu e.firma vigente, no la del SAT en línea. Tu
                e.firma nueva tendrá la misma.
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
                {web ? 'Guardados cifrados en tu espacio en línea' : 'Guardados y protegidos en este equipo'}
              </span>
            </div>

            {errorPaso && <p className="text-xs text-destructive">{errorPaso}</p>}

            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setPaso(0)}>
                Atrás
              </Button>
              <Button type="submit" disabled={password.length < 4 || generando}>
                {generando ? (
                  <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                ) : (
                  <Icon icon="ph:arrow-right-light" className="size-4" />
                )}
                {generando ? 'Generando…' : 'Continuar'}
              </Button>
            </DialogFooter>
          </form>
        )}

        {/* Paso 2 — Respaldo (antes de que el SAT reciba nada) */}
        {paso === 2 && (
          <div className="space-y-3.5">
            <div className="flex items-start gap-3 rounded-xl border border-border/60 p-3.5">
              <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-primary">
                <Icon icon="ph:key-light" className="size-5" />
              </span>
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-bold tracking-tight">Guarda el respaldo de tu llave nueva</p>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Ya generamos tu solicitud de renovación y la clave privada (.key) de tu
                  e.firma nueva, con la misma contraseña de la actual. Si esa llave se
                  pierde, el certificado que emita el SAT no sirve y tendrías que renovar
                  en una oficina del SAT. Todavía no enviamos nada.
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant={respaldoBajado ? 'outline' : 'default'}
                onClick={() => void bajarRespaldo()}
                disabled={bajandoRespaldo}
              >
                <Icon
                  icon={bajandoRespaldo ? 'ph:circle-notch-light' : 'ph:file-zip-light'}
                  className={cn('size-4', bajandoRespaldo && 'animate-spin')}
                />
                {respaldoBajado ? 'Descargar otra vez' : 'Descargar respaldo (.zip)'}
              </Button>
              {respaldoBajado && (
                <span className="inline-flex items-center gap-1.5 text-xs font-medium text-success">
                  <Icon icon="ph:check-circle-light" className="size-3.75" />
                  Respaldo descargado
                </span>
              )}
            </div>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Guárdalo fuera de esta computadora (una USB o tu nube personal).{' '}
              {web
                ? 'La llave se generó en tu espacio en línea; este archivo es tu copia.'
                : 'También queda una copia en la carpeta de descargas de TodoConta.'}
            </p>

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

            {errorPaso && <p className="text-xs text-destructive">{errorPaso}</p>}

            <DialogFooter>
              <Button variant="ghost" onClick={() => setPaso(1)}>
                Atrás
              </Button>
              <Button onClick={renovar} disabled={!enviarListo}>
                <Icon icon="ph:shield-check-light" className="size-4" />
                Renovar en línea
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Paso 3 — Proceso */}
        {paso === 3 && (
          <div className="space-y-3.5">
            <FasesProgreso
              items={modo === 'recuperar' ? FASES_RECUPERAR : FASES_RENOVAR}
              faseActual={job.fase}
              estado={job.estado}
            />

            {/* La recuperación pública del SAT pide captcha (distingue
                mayúsculas y minúsculas). */}
            <CaptchaModal
              captcha={job.captcha}
              onResolver={job.responderCaptcha}
              respetarMayusculas
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
                  {yaEnviada ? (
                    <>
                      Tu avance quedó guardado: al reintentar solo buscamos tu
                      certificado nuevo, nunca se reenvía la solicitud. También puedes
                      cerrar y retomarlo después desde Empresas.
                    </>
                  ) : (
                    <>
                      El SAT no confirmó haber recibido la solicitud. Lo más probable es
                      que no haya llegado y{' '}
                      <strong className="text-foreground">tu e.firma actual siga intacta</strong>:
                      la solicitud quedó guardada y al reintentar se reenvía la misma. Si
                      crees que sí llegó, busca tu certificado nuevo.
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
              ) : job.estado === 'error' || job.estado === 'cancelled' ? (
                <>
                  <Button variant="ghost" onClick={() => handleOpenChange(false)}>
                    Cerrar
                  </Button>
                  {!yaEnviada && (
                    <Button variant="outline" onClick={recuperar}>
                      <Icon icon="ph:magnifying-glass-light" className="size-4" />
                      Buscar mi certificado
                    </Button>
                  )}
                  <Button onClick={reintentar}>
                    <Icon icon="ph:arrow-clockwise-light" className="size-4" />
                    Reintentar
                  </Button>
                </>
              ) : null}
            </DialogFooter>
          </div>
        )}

        {/* Paso 4 — Listo */}
        {paso === 4 && resultado && (
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
                    El SAT emitió tu nuevo certificado y quedó guardado{' '}
                    {web ? 'en tu espacio en línea' : 'en este equipo'}. Ya puedes usarlo
                    para descargas masivas y trámites.
                  </>
                ) : resultado.mensaje ? (
                  resultado.mensaje
                ) : (
                  <>
                    La renovación se envió
                    {resultado.numero_operacion && (
                      <>
                        {' '}(operación{' '}
                        <span className="font-mono">{resultado.numero_operacion}</span>)
                      </>
                    )}
                    , pero el SAT sigue emitiendo tu certificado. Suele tardar unos
                    minutos: descárgalo cuando quieras desde Empresas.
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

            {errorPaso && <p className="text-xs text-destructive">{errorPaso}</p>}

            <DialogFooter>
              {resultado.renovada ? (
                <>
                  <Button variant="outline" onClick={() => void bajarRespaldo()} disabled={bajandoRespaldo}>
                    <Icon icon="ph:file-zip-light" className="size-4" />
                    Respaldo
                  </Button>
                  {resultado.acuse_pdf && (
                    <Button
                      variant="outline"
                      onClick={() => void abrirODescargar(apiClient, resultado.acuse_pdf!, 'archivo')}
                    >
                      <Icon icon="ph:file-pdf-light" className="size-4" />
                      Acuse
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

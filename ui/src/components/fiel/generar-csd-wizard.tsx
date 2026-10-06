'use client';

import { useEffect, useMemo, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { cn } from '@/lib/utils';
import { abrirODescargar, tituloAbrir, iconoAbrir } from '@/lib/descargas';
import { esWeb } from '@/lib/modo';
import type { CsdResultado, Empresa } from '@/lib/types';
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
import { Separator } from '@/components/ui/separator';
import { WizardSteps } from '@/components/shared/wizard-steps';
import { FasesProgreso, type FaseItem } from '@/components/shared/fases-progreso';

const PASOS = ['Datos', 'Contraseñas', 'Generar', 'Listo'];

const FASES_CSD: FaseItem[] = [
  { label: 'Generando la clave privada y el requerimiento (.sdg)…', fases: ['generando'] },
  { label: 'Firmando la solicitud con tu e.firma…', fases: ['firmando'] },
  {
    label: 'Enviando al SAT (Certifica)…',
    fases: ['enviando', 'login_ok', 'subiendo', 'numero_operacion', 'acuse'],
  },
  { label: 'Recuperando tu Certificado de Sello Digital…', fases: ['recuperando', 'cer'] },
];

const FASES_RECUPERAR: FaseItem[] = [
  { label: 'Buscando tu certificado en el SAT…', fases: ['login_ok', 'recuperando'] },
  { label: 'Descargando el Certificado de Sello Digital…', fases: ['cer'] },
];

interface GenerarCsdWizardProps {
  empresa: Empresa;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Se llama al cerrar tras un trámite exitoso (refrescar catálogo). */
  onDone?: () => void;
}

/**
 * Asistente de generación de CSD (4 pasos: Datos → Contraseñas → Generar →
 * Listo). El agente crea la .key y el .sdg, los firma con la e.firma, envía la
 * solicitud a Certifica y recupera el .cer emitido. «Bajar después» es
 * first-class: si el SAT no emite el cert a tiempo, queda pendiente y se
 * descarga con el mismo asistente (o desde Empresas).
 *
 * Sin punto de entrada visible por ahora: se conectará desde el Expediente
 * fiscal. Para QA manual se monta en /empresas/detalle con `?labs=csd`.
 */
export function GenerarCsdWizard({ empresa, open, onOpenChange, onDone }: GenerarCsdWizardProps) {
  const { apiClient } = useServer();
  const job = useJob();

  const [paso, setPaso] = useState(0);
  const [uso, setUso] = useState('Facturación general');
  const [passCsd, setPassCsd] = useState('');
  const [passCsd2, setPassCsd2] = useState('');
  const [passEfirma, setPassEfirma] = useState('');
  const [modo, setModo] = useState<'enviar' | 'recuperar'>('enviar');

  const csdPendiente = useMemo(
    () => (empresa.csds ?? []).find((c) => c.estado === 'pendiente') ?? null,
    [empresa.csds],
  );

  const resultado = job.resultado as CsdResultado | null;
  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';
  const exito = job.estado === 'done' && !!resultado && !resultado.cert_pendiente;

  useEffect(() => {
    if (paso === 2 && job.estado === 'done') setPaso(3);
  }, [paso, job.estado]);

  // Reinicia el asistente al abrir (modal controlado desde el padre → flanco de
  // `open`). `job.reset` limpia el EventSource del job previo (parte que exige
  // un Effect); `modo` lo fija cada acción antes del paso de progreso.
  useEffect(() => {
    if (!open) return;
    setPaso(0);
    setUso('Facturación general');
    setPassCsd('');
    setPassCsd2('');
    setPassEfirma('');
    job.reset();
  }, [open, job.reset]);

  const vigenciaNueva = useMemo(() => {
    const f = new Date();
    f.setFullYear(f.getFullYear() + 4);
    return f.toLocaleDateString('es-MX', { day: '2-digit', month: 'long', year: 'numeric' });
  }, []);

  function handleOpenChange(next: boolean) {
    if (!next && corriendo) return;
    if (!next && exito) onDone?.();
    onOpenChange(next);
  }

  function generar() {
    setPaso(2);
    setModo('enviar');
    void job.iniciar(
      () => apiClient.csdSolicitar({
        rfc: empresa.rfc,
        password: passEfirma,
        password_csd: passCsd,
        uso: uso.trim() || 'Facturación general',
      }),
      { rfc: empresa.rfc, canal: 'fiel', notificar: false },
    );
  }

  function recuperar(numeroOperacion?: string) {
    setPaso(2);
    setModo('recuperar');
    void job.iniciar(
      () => apiClient.csdRecuperar({ rfc: empresa.rfc, numero_operacion: numeroOperacion }),
      { rfc: empresa.rfc, canal: 'fiel', notificar: false },
    );
  }

  const passOk = passCsd.length >= 8 && passCsd === passCsd2 && passEfirma.length >= 4;
  const noCoinciden = passCsd2.length > 0 && passCsd !== passCsd2;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg" onInteractOutside={(e) => corriendo && e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>Generar Certificado de Sello Digital</DialogTitle>
          {paso < 3 && (
            <DialogDescription>
              {empresa.nombre} · <span className="font-mono">{empresa.rfc}</span>
            </DialogDescription>
          )}
        </DialogHeader>

        {paso < 3 && <WizardSteps pasos={PASOS} actual={paso} />}

        {/* Paso 0 — Qué es + datos */}
        {paso === 0 && (
          <div className="space-y-3.5">
            <div className="flex items-start gap-2 rounded-lg bg-accent px-3 py-2.5 text-xs leading-relaxed text-accent-foreground">
              <Icon icon="ph:info-light" className="mt-px size-3.75 shrink-0" />
              <span>
                El <strong>CSD</strong> es el sello que necesitas para{' '}
                <strong>emitir CFDI</strong> (ingresos, egresos y cualquier comprobante).
                TodoConta lo genera de extremo a extremo: crea la clave y el
                requerimiento, lo firma con tu e.firma y lo tramita ante el SAT.
              </span>
            </div>

            {csdPendiente && (
              <Alert>
                <AlertTitle>Tienes un CSD pendiente de descargar</AlertTitle>
                <AlertDescription className="space-y-2">
                  <span>
                    "{csdPendiente.uso}" ya se envió (operación{' '}
                    <span className="font-mono">{csdPendiente.numero_operacion}</span>);
                    solo falta bajar el certificado emitido.
                  </span>
                  <Button size="sm" variant="outline" onClick={() => recuperar(csdPendiente.numero_operacion)}>
                    <Icon icon="ph:download-simple-light" className="size-4" />
                    Descargar certificado
                  </Button>
                </AlertDescription>
              </Alert>
            )}

            <div className="space-y-2">
              <Label htmlFor="csd-uso">Nombre o uso del certificado</Label>
              <Input
                id="csd-uso"
                value={uso}
                autoFocus
                onChange={(e) => setUso(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Solo para identificarlo dentro de TodoConta (p. ej. Matriz, Sucursal
                Norte, Facturación 2026).
              </p>
            </div>

            <dl className="space-y-2.5 rounded-xl border border-border/60 p-3.5 text-[13px]">
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-xs text-muted-foreground">RFC</dt>
                <dd className="font-mono text-xs font-medium">{empresa.rfc}</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                {/* Sin fecha exacta: la vigencia corre desde que el SAT emite el
                    sello (misma razón que en el wizard de renovación). */}
                <dt className="text-xs text-muted-foreground">Vigencia</dt>
                <dd className="font-semibold">4 años a partir de la emisión</dd>
              </div>
            </dl>

            <DialogFooter>
              <Button variant="ghost" onClick={() => handleOpenChange(false)}>
                Cancelar
              </Button>
              <Button onClick={() => setPaso(1)} disabled={!uso.trim()}>
                Continuar
                <Icon icon="ph:arrow-right-light" className="size-4" />
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Paso 1 — Contraseñas */}
        {paso === 1 && (
          <div className="space-y-3.5">
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Define una contraseña para la{' '}
              <strong className="text-foreground">clave del CSD</strong>. La usarás al
              timbrar tus facturas. Guárdala bien: el SAT no la puede recuperar.
            </p>

            <div className="space-y-2">
              <Label htmlFor="csd-pass">Contraseña del CSD</Label>
              <Input
                id="csd-pass"
                type="password"
                placeholder="••••••••"
                value={passCsd}
                autoFocus
                onChange={(e) => setPassCsd(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">Mínimo 8 caracteres.</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="csd-pass2">Confirmar contraseña del CSD</Label>
              <Input
                id="csd-pass2"
                type="password"
                placeholder="••••••••"
                value={passCsd2}
                onChange={(e) => setPassCsd2(e.target.value)}
              />
              {noCoinciden && (
                <p className="text-xs text-destructive">Las contraseñas no coinciden.</p>
              )}
            </div>

            <Separator />

            <div className="space-y-2">
              <Label htmlFor="csd-efirma">Contraseña de tu e.firma</Label>
              <Input
                id="csd-efirma"
                type="password"
                placeholder="••••••••"
                value={passEfirma}
                onChange={(e) => setPassEfirma(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Con tu e.firma firmamos y enviamos la solicitud al SAT.
              </p>
            </div>

            <DialogFooter>
              <Button variant="ghost" onClick={() => setPaso(0)}>
                Atrás
              </Button>
              <Button onClick={generar} disabled={!passOk}>
                <Icon icon="ph:seal-check-light" className="size-4" />
                Generar CSD
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Paso 2 — Proceso */}
        {paso === 2 && (
          <div className="space-y-3.5">
            <FasesProgreso
              items={modo === 'recuperar' ? FASES_RECUPERAR : FASES_CSD}
              faseActual={job.fase}
              estado={job.estado}
            />

            {job.estado === 'error' && (
              <Alert variant="destructive">
                <AlertTitle>El trámite no se completó</AlertTitle>
                <AlertDescription>{job.error}</AlertDescription>
              </Alert>
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
                  <Button onClick={modo === 'recuperar' ? () => recuperar() : generar}>
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
                  resultado.cert_pendiente
                    ? 'bg-warning/10 text-warning'
                    : 'bg-success/10 text-success',
                )}
              >
                <Icon
                  icon={resultado.cert_pendiente ? 'ph:clock-light' : 'ph:seal-check-light'}
                  className="size-8.5"
                />
              </span>
              <h3 className="text-lg font-extrabold tracking-tight">
                {resultado.cert_pendiente ? 'Tu CSD está en camino' : 'CSD generado'}
              </h3>
              <p className="mt-1.5 max-w-[46ch] text-[13px] leading-relaxed text-muted-foreground">
                {resultado.cert_pendiente ? (
                  <>
                    La solicitud se envió (operación{' '}
                    <span className="font-mono">{resultado.numero_operacion}</span>), pero
                    el SAT sigue emitiendo el certificado. Suele tardar unos minutos;
                    puedes descargarlo ahora o más tarde.
                  </>
                ) : (
                  <>
                    Tu Certificado de Sello Digital quedó activo y se guardó en este
                    equipo, junto con su contraseña. Ya puedes timbrar CFDI con &quot;
                    {resultado.uso ?? uso}&quot;.
                  </>
                )}
              </p>
            </div>

            {!resultado.cert_pendiente && (
              <dl className="space-y-2.5 rounded-xl border border-border/60 p-3.5 text-[13px]">
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-xs text-muted-foreground">Uso</dt>
                  <dd className="font-semibold">{resultado.uso ?? uso}</dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-xs text-muted-foreground">Vigencia</dt>
                  <dd className="font-semibold text-success">Vigente · hasta {vigenciaNueva}</dd>
                </div>
              </dl>
            )}

            <DialogFooter>
              {resultado.cert_pendiente ? (
                <>
                  <Button variant="ghost" onClick={() => handleOpenChange(false)}>
                    Bajar después
                  </Button>
                  <Button onClick={() => recuperar(resultado.numero_operacion ?? undefined)}>
                    <Icon icon="ph:download-simple-light" className="size-4" />
                    Descargar certificado
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    variant="outline"
                    onClick={() => void abrirODescargar(apiClient, resultado.carpeta, 'carpeta')}
                    title={tituloAbrir('carpeta')}
                  >
                    <Icon icon={iconoAbrir('carpeta')} className="size-4" />
                    {esWeb() ? 'Descargar ZIP' : 'Abrir carpeta'}
                  </Button>
                  <Button onClick={() => handleOpenChange(false)}>
                    <Icon icon="ph:check-circle-light" className="size-4" />
                    Listo
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

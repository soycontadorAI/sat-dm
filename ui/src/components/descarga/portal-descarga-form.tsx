'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { Icon } from '@/components/ui/icon';
import { useServer } from '@/providers/server-provider';
import { useCiecJob } from '@/hooks/use-ciec-job';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { CaptchaModal } from '@/components/descarga/captcha-modal';
import { JobProgress } from '@/components/descarga/job-progress';
import { NavegadorStatusBanner } from '@/components/shared/navegador-status';
import { metodoPortalPreferido, etiquetaMetodo } from '@/lib/empresa-metodo';
import type { Empresa } from '@/lib/types';
import { usePrefill, type PrefillPortal } from '@/lib/prefill';
import { cn } from '@/lib/utils';

type TipoComprobante = 'R' | 'E' | 'RE';

function ymd(d: Date) {
  return d.toISOString().slice(0, 10);
}

interface PortalDescargaFormProps {
  /** Empresa cuya descarga se va a iniciar — siempre la activa del catálogo. */
  empresa: Empresa;
  /** Llamado cuando termina un job exitoso, para que el padre refresque la lista. */
  onJobDone?: () => void;
}

/**
 * Form de descarga rápida (scraping del portal del SAT). Escoge método
 * (e.firma vs CIEC) según las credenciales de la empresa que recibe por prop.
 * Diseñado para fijar la empresa activa — el caller resuelve qué empresa
 * y solo le pasa el objeto; aquí no hay selector.
 */
export function PortalDescargaForm({ empresa, onJobDone }: PortalDescargaFormProps) {
  const { apiClient } = useServer();
  const job = useCiecJob();

  // Orden de ⌘K: el primer Enter llena el formulario y deja el foco en
  // "Iniciar descarga"; el segundo Enter la arranca (con Contraseña, el
  // captcha aparece aquí mismo).
  const { inicial, nuevo } = usePrefill('portal');

  const hoy = useMemo(() => new Date(), []);
  const [tipo, setTipo] = useState<TipoComprobante>(() => inicial?.tipo ?? 'E');
  const [desde, setDesde] = useState(
    () => inicial?.desde ?? ymd(new Date(hoy.getFullYear(), hoy.getMonth(), 1)),
  );
  const [hasta, setHasta] = useState(
    () => inicial?.hasta ?? ymd(new Date(hoy.getFullYear(), hoy.getMonth() + 1, 0)),
  );

  // Una orden de ⌘K puede fijar el acceso ("con contraseña"); vale solo para
  // la empresa de la orden y si la empresa lo tiene.
  const [metodoOrden, setMetodoOrden] = useState<{ rfc: string; metodo: 'fiel' | 'ciec' } | null>(
    () => (inicial?.metodo ? { rfc: inicial.rfc, metodo: inicial.metodo } : null),
  );
  const metodo =
    metodoOrden && metodoOrden.rfc === empresa.rfc && empresa.metodos.includes(metodoOrden.metodo)
      ? metodoOrden.metodo
      : metodoPortalPreferido(empresa);
  const corriendo = job.estado !== 'idle' && job.estado !== 'done'
    && job.estado !== 'error' && job.estado !== 'cancelled';

  const [deOrden, setDeOrden] = useState<PrefillPortal | null>(inicial);
  const [enfocarPendiente, setEnfocarPendiente] = useState(!!inicial);
  const iniciarRef = useRef<HTMLButtonElement>(null);
  const listoDesde = useRef(0);

  // Otra orden con la pantalla ya abierta.
  useEffect(() => {
    if (!nuevo) return;
    setDesde(nuevo.desde);
    setHasta(nuevo.hasta);
    setTipo(nuevo.tipo);
    setMetodoOrden(nuevo.metodo ? { rfc: nuevo.rfc, metodo: nuevo.metodo } : null);
    setDeOrden(nuevo);
    setEnfocarPendiente(true);
  }, [nuevo]);

  useEffect(() => {
    if (!enfocarPendiente || !metodo || corriendo) return;
    listoDesde.current = Date.now() + 400;
    iniciarRef.current?.focus();
    setEnfocarPendiente(false);
  }, [enfocarPendiente, metodo, corriendo]);

  // Refresca al padre cuando el job pasa a 'done' (p. ej. para actualizar la
  // lista de descargas recientes sin recargar la página).
  useEffect(() => {
    if (onJobDone && job.estado === 'done') onJobDone();
  }, [job.estado, onJobDone]);

  function iniciar() {
    if (!metodo) return;
    if (Date.now() < listoDesde.current) return;
    setDeOrden(null);
    if (metodo === 'fiel') {
      job.iniciar(
        () =>
          apiClient.cfdiFiel({
            fecha_inicio: desde,
            fecha_fin: hasta,
            tipo_comprobante: tipo,
          }),
        { rfc: empresa.rfc },
      );
    } else {
      job.iniciar(
        () =>
          apiClient.ciecCfdi({
            rfc: empresa.rfc,
            fecha_inicio: desde,
            fecha_fin: hasta,
            tipo_comprobante: tipo,
          }),
        { rfc: empresa.rfc },
      );
    }
  }

  return (
    <>
      <NavegadorStatusBanner />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Icon icon="ph:lightning-light" className="size-5" />
            Iniciar descarga
          </CardTitle>
          <CardDescription>
            Elige el periodo y de qué facturas. La descarga corre contra el portal
            del SAT con los accesos de la empresa activa.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-6">
            {deOrden && (
              <div className="flex items-start gap-2.5 rounded-[10px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-muted-foreground">
                <Icon icon="ph:arrow-elbow-down-left-light" className="mt-0.5 size-4 shrink-0 text-foreground" />
                <span>
                  <span className="font-semibold text-foreground">Lo llenó tu orden:</span>{' '}
                  {deOrden.etiqueta}. Revisa y confirma con Enter.
                </span>
              </div>
            )}
            {/* Rango de fechas */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="desde">Fecha inicio</Label>
                <Input
                  id="desde"
                  type="date"
                  value={desde}
                  disabled={corriendo}
                  onChange={(e) => setDesde(e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="hasta">Fecha fin</Label>
                <Input
                  id="hasta"
                  type="date"
                  value={hasta}
                  disabled={corriendo}
                  onChange={(e) => setHasta(e.target.value)}
                />
              </div>
            </div>

            {/* Facturas */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-2">
                <Label>Facturas</Label>
                <Select
                  value={tipo}
                  onValueChange={(v) => setTipo(v as TipoComprobante)}
                  disabled={corriendo}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="E">Emitidas</SelectItem>
                    <SelectItem value="R">Recibidas</SelectItem>
                    <SelectItem value="RE">Ambas</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* Chip de método */}
              {metodo && (
                <div className="flex items-end pb-1">
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Icon
                      icon={metodo === 'fiel' ? 'ph:shield-check-light' : 'ph:key-light'}
                      className="size-3.5"
                    />
                    Usando {etiquetaMetodo(metodo)}
                  </div>
                </div>
              )}
            </div>

            {/* Submit */}
            <Button
              ref={iniciarRef}
              onClick={iniciar}
              disabled={!metodo || corriendo}
              // Después de una orden, el contorno marca dónde cae el segundo Enter.
              className={cn(
                'w-full sm:w-auto',
                deOrden && 'focus:outline-2 focus:outline-offset-3 focus:outline-ring',
              )}
              onKeyDown={(e) => {
                if (e.repeat && e.key === 'Enter') e.preventDefault();
              }}
            >
              <Icon
                icon={metodo === 'fiel' ? 'ph:shield-check-light' : 'ph:key-light'}
                className="size-4"
              />
              Iniciar descarga
            </Button>
          </div>
        </CardContent>
      </Card>

      <JobProgress
        estado={job.estado}
        log={job.log}
        resultado={job.resultado}
        error={job.error}
      />

      <CaptchaModal captcha={job.captcha} onResolver={job.responderCaptcha} />
    </>
  );
}

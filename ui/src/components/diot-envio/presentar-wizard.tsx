'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { useAuth } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Icon } from '@/components/ui/icon';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { FasesProgreso, type FaseItem } from '@/components/shared/fases-progreso';
import { WizardSteps } from '@/components/shared/wizard-steps';
import { AvisoEstimulos } from '@/components/diot-envio/aviso-estimulos';
import { ejerciciosDisponibles, MESES } from '@/lib/contabilidad-electronica';
import {
  avisoLayout,
  compararTotales,
  etiquetaLayout,
  etiquetaPeriodoDiot,
  veredictoPresentacion,
} from '@/lib/diot-envio';
import { guardarBlob } from '@/lib/descargas';
import { mensajeDeError } from '@/lib/errores';
import { formatCurrency } from '@/lib/formatting';
import { cn } from '@/lib/utils';
import type {
  DiotPresentacionResultado,
  DiotPresentarRequest,
  DiotSubirResultado,
} from '@/lib/types';

const PASOS = ['Periodo y archivo', 'Declaración', 'Validar', 'Presentar'];

type Modo = 'validar' | 'presentar';
type Origen = 'generado' | 'propio';

/**
 * Checklist del trámite. Los nombres de fase son los estables que emite
 * `PresentadorDiot` (portal/diot_presentacion.py); aquí solo se agrupan.
 */
function fasesDiot(modo: Modo): FaseItem[] {
  const base: FaseItem[] = [
    { label: 'Entrando al portal de la DIOT con tu e.firma', fases: ['login'] },
    { label: 'Seleccionando el periodo y el tipo de declaración', fases: ['seleccionando_declaracion'] },
    { label: 'Subiendo el TXT', fases: ['subiendo_txt'] },
    {
      label: 'Leyendo y cotejando los totales del portal',
      fases: modo === 'validar' ? ['totales_leyendo', 'estimulos', 'fin'] : ['totales_leyendo', 'estimulos'],
    },
  ];
  if (modo === 'validar') return base;
  return [
    ...base,
    { label: 'Firmando con tu e.firma', fases: ['confirmando', 'firmando'] },
    { label: 'Descargando el acuse', fases: ['acuse', 'fin'] },
  ];
}

interface PresentarWizardProps {
  rfc: string;
  /** Periodo con el que abre (viene de Generar TXT o de la URL). */
  periodoInicial: { ejercicio: number; mes: number };
  origenInicial: Origen | null;
  /** Salta a DIOT presentadas (para verificar un trámite sin acuse). */
  onVerPresentadas: (ejercicio: number, mes: number, verificar: boolean) => void;
}

export function PresentarWizard({ rfc, periodoInicial, origenInicial, onVerPresentadas }: PresentarWizardProps) {
  const { apiClient } = useServer();
  const { license } = useAuth();
  const premium = license?.premium_features_unlocked === true;
  const job = useJob();

  const [paso, setPaso] = useState(0);
  const [ejercicio, setEjercicio] = useState(periodoInicial.ejercicio);
  const [mes, setMes] = useState(periodoInicial.mes);
  const [origen, setOrigen] = useState<Origen | null>(origenInicial);
  const [tipo, setTipo] = useState<'001' | '003'>('001');
  const [sinEstimulos, setSinEstimulos] = useState(false);
  const [modo, setModo] = useState<Modo>('validar');
  const [validacion, setValidacion] = useState<DiotPresentacionResultado | null>(null);
  const [acepto, setAcepto] = useState(false);
  const [bajandoAcuse, setBajandoAcuse] = useState(false);

  // TXT generado por TodoConta: qué hay en el periodo.
  const [generado, setGenerado] = useState<{ filas: number; errores: number } | null>(null);
  const [cargandoGenerado, setCargandoGenerado] = useState(false);
  // TXT propio.
  const [subida, setSubida] = useState<DiotSubirResultado | null>(null);
  const [subiendo, setSubiendo] = useState(false);
  const [errorSubida, setErrorSubida] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const resultado = job.resultado as DiotPresentacionResultado | null;
  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';
  const veredicto = job.estado === 'done' ? veredictoPresentacion(resultado) : null;
  const terminado = modo === 'presentar' && (veredicto === 'presentado' || veredicto === 'desconocido');

  // La validación terminada se conserva aparte: el job de presentación la reemplaza.
  useEffect(() => {
    if (modo === 'validar' && job.estado === 'done' && resultado) setValidacion(resultado);
  }, [modo, job.estado, resultado]);

  // Qué hay en TodoConta para el periodo elegido (solo si ese es el origen).
  useEffect(() => {
    if (origen !== 'generado' || !premium) return;
    let vigente = true;
    setCargandoGenerado(true);
    apiClient
      .diotEstado(rfc, `${ejercicio}-${String(mes).padStart(2, '0')}`)
      .then((e) => vigente && setGenerado({ filas: e.filas.length, errores: e.errores.length }))
      .catch(() => vigente && setGenerado(null))
      .finally(() => vigente && setCargandoGenerado(false));
    return () => {
      vigente = false;
    };
  }, [apiClient, rfc, ejercicio, mes, origen, premium]);

  /** Cambiar periodo, archivo u opciones invalida lo que ya se validó. */
  function invalidar() {
    job.reset();
    setValidacion(null);
    setAcepto(false);
    setModo('validar');
  }

  function reiniciar() {
    invalidar();
    setPaso(0);
    setSubida(null);
    setSinEstimulos(false);
    setTipo('001');
    setOrigen(null);
  }

  async function subir(files: File[]) {
    const f = files.find((x) => x.name.toLowerCase().endsWith('.txt'));
    if (!f) {
      setErrorSubida('Solo se acepta un archivo .txt (el de carga masiva de la DIOT).');
      return;
    }
    setSubiendo(true);
    setErrorSubida(null);
    try {
      invalidar();
      setSubida(await apiClient.diotSubir(f));
    } catch (e) {
      setSubida(null);
      setErrorSubida(mensajeDeError(e));
    } finally {
      setSubiendo(false);
    }
  }

  function ejecutar(m: Modo) {
    if (!origen || (origen === 'propio' && !subida)) return;
    setModo(m);
    const req: DiotPresentarRequest = {
      rfc,
      ejercicio,
      periodo: mes,
      sin_estimulos: true,          // el paso 2 no deja avanzar sin confirmarlo
      tipo_declaracion: tipo,
      solo_validar: m === 'validar',
      confirmar: m === 'presentar',
      ...(origen === 'generado' ? { usar_generado: true } : { txt_path: subida!.txt_path }),
    };
    void job.iniciar(() => apiClient.diotPresentar(req), { rfc, notificar: false });
  }

  async function bajarAcuse() {
    setBajandoAcuse(true);
    try {
      const blob = await apiClient.diotAcusePresentacion(rfc, ejercicio, mes);
      guardarBlob(blob, `acuse_diot_${rfc}_${ejercicio}-${String(mes).padStart(2, '0')}.pdf`);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBajandoAcuse(false);
    }
  }

  const generadoListo = origen === 'generado' && premium && !!generado && generado.filas > 0 && generado.errores === 0;
  const puedeSeguir = [
    generadoListo || (origen === 'propio' && !!subida),
    sinEstimulos,
    !!validacion && veredictoPresentacion(validacion) === 'validado',
    false,
  ][paso];

  const periodoTexto = etiquetaPeriodoDiot(ejercicio, mes);

  return (
    <div className="space-y-5">
      <AvisoEstimulos />
      <WizardSteps pasos={PASOS} actual={paso} />

      {/* 1 · Periodo y archivo */}
      {paso === 0 && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-end gap-3">
            <Campo etiqueta="Ejercicio">
              <Select
                value={String(ejercicio)}
                onValueChange={(v) => {
                  invalidar();
                  setEjercicio(Number(v));
                }}
              >
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ejerciciosDisponibles().map((a) => (
                    <SelectItem key={a} value={String(a)}>
                      {a}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Campo>
            <Campo etiqueta="Mes">
              <Select
                value={String(mes)}
                onValueChange={(v) => {
                  invalidar();
                  setMes(Number(v));
                }}
              >
                <SelectTrigger className="w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MESES.map((nombre, i) => (
                    <SelectItem key={nombre} value={String(i + 1)}>
                      {nombre}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Campo>
          </div>

          <div className="space-y-2">
            <Label className="text-sm font-semibold">¿Qué TXT vas a presentar?</Label>
            <RadioGroup
              value={origen ?? ''}
              onValueChange={(v) => {
                invalidar();
                setOrigen(v as Origen);
              }}
              className="gap-2"
            >
              <OpcionOrigen
                valor="generado"
                deshabilitada={!premium}
                titulo="El que genera TodoConta"
                texto={
                  premium
                    ? 'Se arma con los CFDIs recibidos del periodo, tal como lo dejaste en Generar TXT.'
                    : 'Generar el TXT es una función premium.'
                }
              />
              <OpcionOrigen
                valor="propio"
                titulo="Uno propio"
                texto="El TXT de carga masiva que generaste con tu software contable o con una plantilla."
              />
            </RadioGroup>
            {!premium && (
              <p className="text-xs text-muted-foreground">
                <Link href="/suscripcion" className="font-medium text-primary underline-offset-2 hover:underline">
                  Ver planes
                </Link>{' '}
                para generar el TXT con TodoConta. Presentar uno propio no lo requiere.
              </p>
            )}
          </div>

          {origen === 'generado' && premium && (
            <EstadoGenerado cargando={cargandoGenerado} generado={generado} periodoTexto={periodoTexto} />
          )}

          {origen === 'propio' && (
            <div className="space-y-2">
              <div
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  if (!subiendo) void subir(Array.from(e.dataTransfer.files));
                }}
                className={cn(
                  'flex flex-col items-center gap-3 rounded-xl border border-dashed bg-card px-6 py-7 text-center',
                  subiendo && 'opacity-60',
                )}
              >
                <Icon
                  icon={subiendo ? 'ph:circle-notch-light' : 'ph:file-text-light'}
                  className={cn('size-6 text-primary', subiendo && 'animate-spin')}
                />
                <p className="text-sm font-semibold">
                  {subiendo ? 'Revisando el archivo…' : 'Arrastra aquí tu TXT o elígelo'}
                </p>
                <Button variant="outline" size="sm" disabled={subiendo} onClick={() => inputRef.current?.click()}>
                  <Icon icon="ph:upload-simple-light" className="size-4" />
                  {subida ? 'Cambiar archivo' : 'Elegir TXT'}
                </Button>
                <input
                  ref={inputRef}
                  type="file"
                  accept=".txt,text/plain"
                  className="hidden"
                  onChange={(e) => {
                    void subir(Array.from(e.target.files ?? []));
                    e.target.value = '';
                  }}
                />
              </div>
              {errorSubida && (
                <p role="alert" className="text-xs text-destructive">
                  {errorSubida}
                </p>
              )}
              {subida && <ResumenTxt subida={subida} ejercicio={ejercicio} />}
            </div>
          )}
        </div>
      )}

      {/* 2 · Declaración: tipo y la confirmación de estímulos */}
      {paso === 1 && (
        <div className="space-y-5">
          <div className="space-y-2">
            <Label className="text-sm font-semibold">Tipo de declaración</Label>
            <RadioGroup
              value={tipo}
              onValueChange={(v) => {
                invalidar();
                setTipo(v as '001' | '003');
              }}
              className="gap-2"
            >
              <OpcionTipo valor="001" titulo="Normal" texto={`La primera que presentas de ${periodoTexto}.`} />
              <OpcionTipo
                valor="003"
                titulo="Complementaria por modificación"
                texto="Sustituye una que ya presentaste para ese periodo. Verifica en DIOT presentadas que la original existe."
              />
            </RadioGroup>
          </div>

          <div className="flex items-start gap-3 rounded-xl border-2 border-destructive/60 bg-destructive-bg px-4 py-3.5">
            <Checkbox
              id="diot-sin-estimulos"
              checked={sinEstimulos}
              onCheckedChange={(v) => {
                invalidar();
                setSinEstimulos(v === true);
              }}
              className="mt-0.5 border-destructive"
            />
            <Label htmlFor="diot-sin-estimulos" className="block space-y-1 font-normal leading-snug">
              <span className="block text-sm font-bold text-destructive">
                Confirmo que NO apliqué estímulos fiscales en {periodoTexto}
              </span>
              <span className="block text-xs text-destructive/90">
                Si los aplicaste, esta declaración se presenta manualmente en el portal del SAT.
              </span>
            </Label>
          </div>
        </div>
      )}

      {/* 3 · Validar con el SAT (no se presenta nada) */}
      {paso === 2 && (
        <div className="space-y-4">
          {!validacion && !corriendo && job.estado !== 'error' && (
            <div className="space-y-3 rounded-xl border bg-card p-5">
              <p className="text-sm font-semibold">Primero, una validación sin presentar</p>
              <p className="text-sm text-muted-foreground">
                TodoConta entra al portal de la DIOT con la e.firma de la empresa, sube el TXT y
                compara los totales que calcula el portal contra los del archivo. Ahí se detiene:
                no firma ni presenta nada.
              </p>
              <Button onClick={() => ejecutar('validar')}>
                <Icon icon="ph:seal-check-light" className="size-4" />
                Validar con el SAT
              </Button>
            </div>
          )}

          {corriendo && modo === 'validar' && (
            <FasesProgreso items={fasesDiot('validar')} faseActual={job.fase} estado={job.estado} />
          )}

          {job.estado === 'error' && modo === 'validar' && (
            <ErrorJob mensaje={job.error} onReintentar={() => ejecutar('validar')} />
          )}

          {validacion && <ResultadoValidacion r={validacion} />}
        </div>
      )}

      {/* 4 · Confirmar y presentar */}
      {paso === 3 && (
        <div className="space-y-4">
          {job.estado === 'idle' || (modo === 'validar' && job.estado === 'done') ? (
            <div className="space-y-4 rounded-xl border bg-card p-5">
              <div className="space-y-1">
                <p className="text-sm font-semibold">Listo para presentar la DIOT en el SAT</p>
                <ul className="space-y-0.5 text-sm text-muted-foreground">
                  <li>
                    Empresa: <span className="font-mono text-foreground">{rfc}</span>
                  </li>
                  <li>
                    Periodo: <span className="text-foreground">{periodoTexto}</span> ·{' '}
                    {tipo === '001' ? 'declaración normal' : 'complementaria por modificación'}
                  </li>
                  {validacion?.totales_portal && (
                    <li>
                      {validacion.totales_portal.operaciones} operaciones · IVA acreditable{' '}
                      {formatCurrency(validacion.totales_portal.iva_acreditable)} · IVA retenido{' '}
                      {formatCurrency(validacion.totales_portal.iva_retenido)}
                    </li>
                  )}
                  <li>Sin estímulos fiscales (confirmado en el paso 2).</li>
                </ul>
              </div>
              <div className="flex items-start gap-2.5 rounded-lg bg-warning-bg px-3 py-2.5">
                <Checkbox
                  id="diot-acepto"
                  checked={acepto}
                  onCheckedChange={(v) => setAcepto(v === true)}
                  className="mt-0.5"
                />
                <Label htmlFor="diot-acepto" className="font-normal leading-snug">
                  Entiendo que presentar la DIOT es irreversible ante el SAT: si hay un error se
                  corrige con una complementaria, pero la primera queda registrada.
                </Label>
              </div>
              <Button disabled={!acepto} onClick={() => ejecutar('presentar')}>
                <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
                Presentar DIOT en el SAT
              </Button>
            </div>
          ) : null}

          {modo === 'presentar' && corriendo && (
            <FasesProgreso items={fasesDiot('presentar')} faseActual={job.fase} estado={job.estado} />
          )}

          {modo === 'presentar' && job.estado === 'error' && (
            <Alert variant="destructive">
              <Icon icon="ph:warning-light" className="size-4" />
              <AlertTitle>No se pudo completar</AlertTitle>
              <AlertDescription className="space-y-3">
                <p>{job.error ?? 'El SAT no respondió.'}</p>
                <p className="text-xs opacity-80">
                  Antes de reintentar, verifica en DIOT presentadas si el SAT alcanzó a registrarla:
                  presentarla dos veces generaría una declaración duplicada.
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => onVerPresentadas(ejercicio, mes, true)}>
                    <Icon icon="ph:stamp-light" className="size-4" />
                    Verificar en DIOT presentadas
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => ejecutar('presentar')}>
                    <Icon icon="ph:arrows-clockwise-light" className="size-4" />
                    Reintentar
                  </Button>
                </div>
              </AlertDescription>
            </Alert>
          )}

          {modo === 'presentar' && job.estado === 'done' && resultado && (
            <ResultadoPresentacion
              veredicto={veredicto}
              r={resultado}
              bajandoAcuse={bajandoAcuse}
              onBajarAcuse={() => void bajarAcuse()}
              onVerPresentadas={(verificar) => onVerPresentadas(ejercicio, mes, verificar)}
              onReintentar={() => ejecutar('presentar')}
              onOtra={reiniciar}
            />
          )}
        </div>
      )}

      {/* Navegación del wizard */}
      {!terminado && (
        <div className="flex items-center justify-between border-t pt-4">
          <Button
            variant="ghost"
            size="sm"
            disabled={paso === 0 || corriendo}
            onClick={() => setPaso((p) => p - 1)}
          >
            <Icon icon="ph:caret-left-light" className="size-4" />
            Atrás
          </Button>
          {paso < 3 && (
            <Button size="sm" disabled={!puedeSeguir || corriendo} onClick={() => setPaso((p) => p + 1)}>
              Siguiente
              <Icon icon="ph:caret-right-light" className="size-4" />
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function Campo({ etiqueta, children }: { etiqueta: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <p className="text-xs font-medium text-muted-foreground">{etiqueta}</p>
      {children}
    </div>
  );
}

function OpcionOrigen({
  valor,
  titulo,
  texto,
  deshabilitada,
}: {
  valor: string;
  titulo: string;
  texto: string;
  deshabilitada?: boolean;
}) {
  return (
    <Label
      htmlFor={`diot-origen-${valor}`}
      className={cn(
        'flex items-start gap-3 rounded-lg border bg-card px-4 py-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent',
        deshabilitada ? 'cursor-not-allowed opacity-60' : 'cursor-pointer',
      )}
    >
      <RadioGroupItem id={`diot-origen-${valor}`} value={valor} disabled={deshabilitada} className="mt-0.5" />
      <span className="space-y-0.5">
        <span className="block text-sm font-semibold">{titulo}</span>
        <span className="block text-xs leading-relaxed text-muted-foreground">{texto}</span>
      </span>
    </Label>
  );
}

function OpcionTipo({ valor, titulo, texto }: { valor: string; titulo: string; texto: string }) {
  return (
    <Label
      htmlFor={`diot-tipo-${valor}`}
      className="flex cursor-pointer items-start gap-3 rounded-lg border bg-card px-4 py-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent"
    >
      <RadioGroupItem id={`diot-tipo-${valor}`} value={valor} className="mt-0.5" />
      <span className="space-y-0.5">
        <span className="block text-sm font-semibold">{titulo}</span>
        <span className="block text-xs leading-relaxed text-muted-foreground">{texto}</span>
      </span>
    </Label>
  );
}

function EstadoGenerado({
  cargando,
  generado,
  periodoTexto,
}: {
  cargando: boolean;
  generado: { filas: number; errores: number } | null;
  periodoTexto: string;
}) {
  if (cargando) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
        Revisando la DIOT de {periodoTexto}…
      </p>
    );
  }
  if (!generado || generado.filas === 0) {
    return (
      <Alert variant="warning">
        <Icon icon="ph:warning-light" className="size-4" />
        <AlertTitle>Aún no hay DIOT de {periodoTexto} en TodoConta</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>Prellénala desde tus comprobantes en Generar TXT, y regresa para presentarla.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href="/diot/generar">Ir a Generar TXT</Link>
          </Button>
        </AlertDescription>
      </Alert>
    );
  }
  if (generado.errores > 0) {
    return (
      <Alert variant="destructive">
        <Icon icon="ph:x-circle-light" className="size-4" />
        <AlertTitle>
          {generado.errores === 1 ? '1 error' : `${generado.errores} errores`} en la DIOT de {periodoTexto}
        </AlertTitle>
        <AlertDescription className="space-y-3">
          <p>Corrígelos en Generar TXT antes de presentarla.</p>
          <Button variant="outline" size="sm" asChild>
            <Link href="/diot/generar">Ir a Generar TXT</Link>
          </Button>
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <p className="flex items-center gap-2 text-sm">
      <Icon icon="ph:check-circle-light" className="size-4.5 text-success" />
      {generado.filas === 1 ? '1 proveedor listo' : `${generado.filas} proveedores listos`} en la DIOT de{' '}
      {periodoTexto}.
    </p>
  );
}

function ResumenTxt({ subida, ejercicio }: { subida: DiotSubirResultado; ejercicio: number }) {
  const aviso = avisoLayout(ejercicio, subida.totales.layout);
  return (
    <div className="space-y-2 rounded-xl border bg-card px-4 py-3">
      <p className="flex items-center gap-2 text-sm">
        <Icon icon="ph:check-circle-light" className="size-4.5 shrink-0 text-success" />
        <span className="truncate font-mono text-[13px]">{subida.nombre}</span>
      </p>
      <p className="text-xs text-muted-foreground">
        {subida.totales.operaciones} operaciones · IVA acreditable{' '}
        {formatCurrency(subida.totales.iva_acreditable)} · IVA retenido{' '}
        {formatCurrency(subida.totales.iva_retenido)} · {etiquetaLayout(subida.totales.layout)}
      </p>
      {aviso && (
        <p role="alert" className="text-xs text-warning">
          {aviso}
        </p>
      )}
    </div>
  );
}

function TablaTotales({ r }: { r: DiotPresentacionResultado }) {
  const filas = compararTotales(r.totales_txt, r.totales_portal);
  if (filas.length === 0) return null;
  return (
    <div className="overflow-x-auto rounded-xl border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="px-4 py-2 font-medium" />
            <th className="px-4 py-2 text-right font-medium">Tu TXT</th>
            <th className="px-4 py-2 text-right font-medium">Portal del SAT</th>
            <th className="px-4 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {filas.map((f) => (
            <tr key={f.etiqueta} className="border-b last:border-0">
              <td className="px-4 py-2">{f.etiqueta}</td>
              <td className="px-4 py-2 text-right font-mono">
                {f.etiqueta === 'Operaciones' ? f.txt : formatCurrency(f.txt)}
              </td>
              <td className="px-4 py-2 text-right font-mono">
                {f.etiqueta === 'Operaciones' ? f.portal : formatCurrency(f.portal)}
              </td>
              <td className="px-4 py-2">
                <Icon
                  icon={f.coincide ? 'ph:check-circle-light' : 'ph:x-circle-light'}
                  className={cn('size-4.5', f.coincide ? 'text-success' : 'text-destructive')}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DiscrepanciasAlert({ r }: { r: DiotPresentacionResultado }) {
  return (
    <Alert variant="destructive">
      <Icon icon="ph:x-circle-light" className="size-4" />
      <AlertTitle>Los totales del portal no cuadran con tu TXT</AlertTitle>
      <AlertDescription>
        <ul className="list-disc space-y-1 pl-4">
          {(r.discrepancias ?? []).map((d) => (
            <li key={d}>{d}</li>
          ))}
        </ul>
        <p className="mt-2 text-xs opacity-80">No se envió nada. Revisa el TXT y valida otra vez.</p>
      </AlertDescription>
    </Alert>
  );
}

function ResultadoValidacion({ r }: { r: DiotPresentacionResultado }) {
  const hayDiscrepancias = (r.discrepancias?.length ?? 0) > 0;
  return (
    <div className="space-y-3">
      <TablaTotales r={r} />
      {hayDiscrepancias ? (
        <DiscrepanciasAlert r={r} />
      ) : (
        <Alert>
          <Icon icon="ph:check-circle-light" className="size-4 text-success" />
          <AlertTitle>Los totales cuadran</AlertTitle>
          <AlertDescription>El SAT no recibió nada todavía.</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function ErrorJob({ mensaje, onReintentar }: { mensaje: string | null; onReintentar: () => void }) {
  return (
    <Alert variant="destructive">
      <Icon icon="ph:warning-light" className="size-4" />
      <AlertTitle>No se pudo completar</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>{mensaje ?? 'El SAT no respondió.'}</p>
        <Button variant="outline" size="sm" onClick={onReintentar}>
          <Icon icon="ph:arrows-clockwise-light" className="size-4" />
          Reintentar
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function ResultadoPresentacion({
  veredicto,
  r,
  bajandoAcuse,
  onBajarAcuse,
  onVerPresentadas,
  onReintentar,
  onOtra,
}: {
  veredicto: ReturnType<typeof veredictoPresentacion>;
  r: DiotPresentacionResultado;
  bajandoAcuse: boolean;
  onBajarAcuse: () => void;
  onVerPresentadas: (verificar: boolean) => void;
  onReintentar: () => void;
  onOtra: () => void;
}) {
  if (veredicto === 'presentado') {
    return (
      <div className="space-y-4">
        <Alert>
          <Icon icon="ph:check-circle-light" className="size-4 text-success" />
          <AlertTitle>DIOT presentada</AlertTitle>
          <AlertDescription>El SAT la recibió y generó su acuse.</AlertDescription>
        </Alert>
        <TablaTotales r={r} />
        <div className="flex flex-wrap gap-2">
          <Button onClick={onBajarAcuse} disabled={bajandoAcuse}>
            <Icon
              icon={bajandoAcuse ? 'ph:circle-notch-light' : 'ph:file-pdf-light'}
              className={cn('size-4', bajandoAcuse && 'animate-spin')}
            />
            Descargar el acuse
          </Button>
          <Button variant="outline" onClick={() => onVerPresentadas(false)}>
            <Icon icon="ph:stamp-light" className="size-4" />
            Ver DIOT presentadas
          </Button>
          <Button variant="ghost" onClick={onOtra}>
            Presentar otra
          </Button>
        </div>
      </div>
    );
  }

  if (veredicto === 'desconocido') {
    return (
      <Alert variant="warning" className="border-2 border-warning/60">
        <Icon icon="ph:warning-light" className="size-4" />
        <AlertTitle>Se firmó, pero el SAT no devolvió el acuse</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            No sabemos si la declaración quedó presentada. <strong>No la vuelvas a presentar</strong>{' '}
            sin verificar: podría quedar duplicada. Consulta en DIOT presentadas lo que el SAT tiene
            registrado.
          </p>
          <Button onClick={() => onVerPresentadas(true)}>
            <Icon icon="ph:stamp-light" className="size-4" />
            Verificar en DIOT presentadas
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  if (veredicto === 'no_presentada') {
    return (
      <Alert variant="destructive">
        <Icon icon="ph:x-circle-light" className="size-4" />
        <AlertTitle>El envío no se concretó</AlertTitle>
        <AlertDescription className="space-y-3">
          <p>
            La declaración sigue como temporal en el portal; no quedó presentada. Puedes
            reintentar.
          </p>
          <Button variant="outline" size="sm" onClick={onReintentar}>
            <Icon icon="ph:arrows-clockwise-light" className="size-4" />
            Reintentar
          </Button>
        </AlertDescription>
      </Alert>
    );
  }

  // discrepancias (o validado sin enviar): nada salió al SAT
  return <ResultadoValidacion r={r} />;
}

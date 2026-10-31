'use client';

import { useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Icon } from '@/components/ui/icon';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { FasesProgreso, type FaseItem } from '@/components/shared/fases-progreso';
import { WizardSteps } from '@/components/shared/wizard-steps';
import { ZipsPicker } from '@/components/contabilidad/zips-picker';
import { etiquetaPeriodo, etiquetaTipo, revisarLote } from '@/lib/contabilidad-electronica';
import { cn } from '@/lib/utils';
import type { CeEnvioResultado, CeFicha } from '@/lib/types';

const PASOS = ['Archivos', 'Opciones', 'Validar', 'Enviar'];

type Modo = 'validar' | 'enviar';

/**
 * Checklist del trámite. Los nombres de fase son los estables que emite
 * `EnviadorCE` (portal/contabilidad_electronica.py); aquí solo se agrupan.
 */
function fasesEnvio(modo: Modo, sellar: boolean, datos: Record<string, unknown> | null): FaseItem[] {
  const n = typeof datos?.n === 'number' ? datos.n : null;
  const total = typeof datos?.total === 'number' ? datos.total : null;
  const avance = n && total ? ` (${n} de ${total})` : '';
  return [
    { label: 'Entrando al portal del SAT con tu e.firma', fases: ['login', 'sesion_verificada'] },
    { label: 'Revisando qué ya está presentado', fases: ['revisando_presentados'] },
    {
      label: sellar ? 'Sellando con tu e.firma' : 'Sin sellar, como elegiste',
      fases: ['sellando', 'sin_sellar'],
    },
    {
      label: (modo === 'validar' ? 'Validando los archivos en el portal' : 'Subiendo los archivos al SAT') + avance,
      fases: ['subiendo', 'archivo_ok', 'acuse_recepcion', 'archivo_error', 'fin'],
    },
  ];
}

interface EnviarPanelProps {
  rfc: string;
  /** Salta a la pestaña de acuses en el ejercicio dado. */
  onVerAcuses: (anio: number) => void;
  /** Se envió (o falló) algo: refrescar la cola de pendientes. */
  onCambio: () => void;
}

export function EnviarPanel({ rfc, onVerAcuses, onCambio }: EnviarPanelProps) {
  const { apiClient } = useServer();
  const job = useJob();

  const [paso, setPaso] = useState(0);
  const [fichas, setFichas] = useState<CeFicha[]>([]);
  // null = todavía no decide: el sellado nunca viaja por omisión.
  const [sellar, setSellar] = useState<boolean | null>(null);
  const [reenviar, setReenviar] = useState(false);
  const [modo, setModo] = useState<Modo>('validar');
  const [validacion, setValidacion] = useState<CeEnvioResultado | null>(null);
  const [acepto, setAcepto] = useState(false);

  const resultado = job.resultado as CeEnvioResultado | null;
  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';
  const revision = revisarLote(fichas, rfc);
  const enviado = modo === 'enviar' && job.estado === 'done' && resultado?.estado === 'enviado';

  // La validación terminada se conserva aparte: el job de envío la reemplaza.
  useEffect(() => {
    if (modo === 'validar' && job.estado === 'done' && resultado) setValidacion(resultado);
  }, [modo, job.estado, resultado]);

  // Al terminar el envío, la cola de pendientes pudo cambiar.
  useEffect(() => {
    if (modo === 'enviar' && (job.estado === 'done' || job.estado === 'error')) onCambio();
  }, [modo, job.estado]); // eslint-disable-line react-hooks/exhaustive-deps -- solo el flanco del job

  /** Cambiar archivos u opciones invalida lo que ya se validó. */
  function invalidar() {
    job.reset();
    setValidacion(null);
    setAcepto(false);
    setModo('validar');
  }

  function reiniciar() {
    invalidar();
    setFichas([]);
    setSellar(null);
    setReenviar(false);
    setPaso(0);
  }

  function ejecutar(m: Modo) {
    if (sellar === null) return;
    setModo(m);
    void job.iniciar(
      () =>
        apiClient.ceEnviar({
          rfc,
          archivos: fichas.map((f) => f.path),
          solo_validar: m === 'validar',
          confirmar: m === 'enviar',
          sellar,
          reenviar,
        }),
      { rfc, notificar: false },
    );
  }

  const listosParaEnviar = validacion?.enviados ?? [];
  const puedeSeguir = [
    revision.ok,
    sellar !== null,
    !!validacion && validacion.fallidos.length === 0 && listosParaEnviar.length > 0,
    false,
  ][paso];

  return (
    <div className="space-y-5">
      <WizardSteps pasos={PASOS} actual={paso} />

      {/* 1 · Archivos */}
      {paso === 0 && (
        <div className="space-y-4">
          <ZipsPicker
            hayArchivos={fichas.length > 0}
            onFichas={(f) => {
              invalidar();
              setFichas(f);
            }}
          />
          {fichas.length > 0 && <TablaFichas fichas={fichas} />}
          {fichas.length > 0 && !revision.ok && (
            <Alert variant="destructive">
              <Icon icon="ph:warning-light" className="size-4" />
              <AlertTitle>No se puede continuar con estos archivos</AlertTitle>
              <AlertDescription>
                <ul className="list-disc space-y-1 pl-4">
                  {revision.errores.map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </AlertDescription>
            </Alert>
          )}
          <p className="text-xs text-muted-foreground">
            TodoConta no genera estos archivos: los revisa y los envía tal como los entrega tu
            software contable. El catálogo de cuentas se envía antes que la balanza del mismo
            periodo.
          </p>
        </div>
      )}

      {/* 2 · Opciones: la decisión del sellado es explícita */}
      {paso === 1 && (
        <div className="space-y-5">
          <div className="space-y-2">
            <Label className="text-sm font-semibold">¿Sellar los archivos con tu e.firma?</Label>
            <RadioGroup
              value={sellar === null ? '' : sellar ? 'si' : 'no'}
              onValueChange={(v) => {
                invalidar();
                setSellar(v === 'si');
              }}
              className="gap-2"
            >
              <OpcionSellado
                valor="si"
                titulo="Sí, sellarlos con mi e.firma"
                texto="Los XML irán firmados con la e.firma de la empresa. Es lo que hace el software contable cuando sella."
              />
              <OpcionSellado
                valor="no"
                titulo="No, enviarlos sin sellar"
                texto="El portal del SAT lo permite. Elígelo solo si tu software ya los entrega como los quieres presentar."
              />
            </RadioGroup>
          </div>

          <details className="group rounded-lg border bg-card px-4 py-3 text-sm">
            <summary className="cursor-pointer font-medium">Avanzado</summary>
            <div className="mt-3 flex items-start gap-2.5">
              <Checkbox
                id="ce-reenviar"
                checked={reenviar}
                onCheckedChange={(v) => {
                  invalidar();
                  setReenviar(v === true);
                }}
              />
              <Label htmlFor="ce-reenviar" className="block space-y-0.5 font-normal leading-snug">
                <span className="font-medium">Enviar aunque el SAT ya lo tenga</span>
                <span className="block text-xs text-muted-foreground">
                  Normalmente se omite lo ya presentado, porque el SAT acepta el mismo archivo dos
                  veces sin avisar. Actívalo solo para sustituir un envío rechazado.
                </span>
              </Label>
            </div>
          </details>
        </div>
      )}

      {/* 3 · Validar con el SAT (no se envía nada) */}
      {paso === 2 && (
        <div className="space-y-4">
          {!validacion && !corriendo && job.estado !== 'error' && (
            <div className="space-y-3 rounded-xl border bg-card p-5">
              <p className="text-sm font-semibold">Primero, una validación sin enviar</p>
              <p className="text-sm text-muted-foreground">
                TodoConta entra al portal con la e.firma de la empresa, carga los archivos y llega
                hasta el resumen. Ahí cancela: el SAT no recibe nada. Así sabes que todo cuadra
                antes del paso irreversible.
              </p>
              <Button onClick={() => ejecutar('validar')}>
                <Icon icon="ph:seal-check-light" className="size-4" />
                Validar con el SAT
              </Button>
            </div>
          )}

          {corriendo && modo === 'validar' && (
            <FasesProgreso
              items={fasesEnvio('validar', sellar ?? true, job.faseDatos)}
              faseActual={job.fase}
              estado={job.estado}
            />
          )}

          {job.estado === 'error' && modo === 'validar' && (
            <ErrorJob mensaje={job.error} onReintentar={() => ejecutar('validar')} />
          )}

          {validacion && <ResumenValidacion r={validacion} />}
        </div>
      )}

      {/* 4 · Confirmar y enviar */}
      {paso === 3 && (
        <div className="space-y-4">
          {job.estado === 'idle' || (modo === 'validar' && job.estado === 'done') ? (
            <div className="space-y-4 rounded-xl border bg-card p-5">
              <div className="space-y-1">
                <p className="text-sm font-semibold">Listo para enviar al SAT</p>
                <ul className="space-y-0.5 text-sm text-muted-foreground">
                  <li>
                    Empresa: <span className="font-mono text-foreground">{rfc}</span>
                  </li>
                  <li>
                    {listosParaEnviar.length === 1
                      ? '1 archivo'
                      : `${listosParaEnviar.length} archivos`}
                    :{' '}
                    <span className="text-foreground">
                      {listosParaEnviar.map((a) => a.archivo).join(', ')}
                    </span>
                  </li>
                  <li>
                    {sellar ? 'Irán sellados con tu e.firma.' : 'Irán sin sellar.'}
                  </li>
                </ul>
              </div>
              <div className="flex items-start gap-2.5 rounded-lg bg-warning-bg px-3 py-2.5">
                <Checkbox
                  id="ce-acepto"
                  checked={acepto}
                  onCheckedChange={(v) => setAcepto(v === true)}
                  className="mt-0.5"
                />
                <Label htmlFor="ce-acepto" className="font-normal leading-snug">
                  Entiendo que el envío es irreversible ante el SAT: si un archivo sale mal, se
                  corrige y se vuelve a enviar, pero el primero queda registrado.
                </Label>
              </div>
              <Button disabled={!acepto} onClick={() => ejecutar('enviar')}>
                <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
                Enviar al SAT
              </Button>
            </div>
          ) : null}

          {modo === 'enviar' && corriendo && (
            <FasesProgreso
              items={fasesEnvio('enviar', sellar ?? true, job.faseDatos)}
              faseActual={job.fase}
              estado={job.estado}
            />
          )}

          {modo === 'enviar' && job.estado === 'error' && (
            <ErrorJob
              mensaje={job.error}
              onReintentar={() => ejecutar('enviar')}
              nota="Si el SAT alcanzó a recibir algo, el reintento lo omite: se consulta el portal antes de subir."
            />
          )}

          {enviado && resultado && (
            <ResultadoEnvio
              r={resultado}
              onVerAcuses={() => {
                const anio = Number(fichas[0]?.anio) || new Date().getFullYear();
                onVerAcuses(anio);
              }}
              onOtro={reiniciar}
            />
          )}
        </div>
      )}

      {/* Navegación del wizard */}
      {!enviado && (
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

function TablaFichas({ fichas }: { fichas: CeFicha[] }) {
  return (
    <ul className="divide-y rounded-xl border bg-card">
      {fichas.map((f) => {
        const mal = f.problemas.length > 0;
        return (
          <li key={f.path} className="flex items-start gap-3 px-4 py-3">
            <Icon
              icon={mal ? 'ph:x-circle-light' : 'ph:check-circle-light'}
              className={cn('mt-0.5 size-4.5 shrink-0', mal ? 'text-destructive' : 'text-success')}
            />
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-[13px]">{f.archivo}</p>
              {mal ? (
                <ul className="mt-1 space-y-0.5 text-xs text-destructive">
                  {f.problemas.map((p) => (
                    <li key={p}>· {p}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground">
                  {etiquetaTipo(f.tipo)} · {etiquetaPeriodo(f.anio, f.mes)}
                  {f.version ? ` · versión ${f.version}` : ''}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function OpcionSellado({ valor, titulo, texto }: { valor: string; titulo: string; texto: string }) {
  return (
    <Label
      htmlFor={`ce-sellar-${valor}`}
      className="flex cursor-pointer items-start gap-3 rounded-lg border bg-card px-4 py-3 font-normal has-[[data-state=checked]]:border-primary has-[[data-state=checked]]:bg-accent"
    >
      <RadioGroupItem id={`ce-sellar-${valor}`} value={valor} className="mt-0.5" />
      <span className="space-y-0.5">
        <span className="block text-sm font-semibold">{titulo}</span>
        <span className="block text-xs leading-relaxed text-muted-foreground">{texto}</span>
      </span>
    </Label>
  );
}

function ErrorJob({
  mensaje,
  onReintentar,
  nota,
}: {
  mensaje: string | null;
  onReintentar: () => void;
  nota?: string;
}) {
  return (
    <Alert variant="destructive">
      <Icon icon="ph:warning-light" className="size-4" />
      <AlertTitle>No se pudo completar</AlertTitle>
      <AlertDescription className="space-y-3">
        <p>{mensaje ?? 'El SAT no respondió.'}</p>
        {nota && <p className="text-xs opacity-80">{nota}</p>}
        <Button variant="outline" size="sm" onClick={onReintentar}>
          <Icon icon="ph:arrows-clockwise-light" className="size-4" />
          Reintentar
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function ResumenValidacion({ r }: { r: CeEnvioResultado }) {
  const ok = r.enviados.length;
  const omitidos = r.omitidos.length;
  const fallidos = r.fallidos.length;
  return (
    <div className="space-y-3">
      {fallidos > 0 && (
        <Alert variant="destructive">
          <Icon icon="ph:x-circle-light" className="size-4" />
          <AlertTitle>
            {fallidos === 1 ? '1 archivo no pasó' : `${fallidos} archivos no pasaron`} la validación
          </AlertTitle>
          <AlertDescription>
            <ul className="space-y-1">
              {r.fallidos.map((f) => (
                <li key={f.archivo}>
                  <span className="font-mono">{f.archivo}</span>: {f.mensaje ?? 'sin detalle'}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs opacity-80">
              Vuelve atrás, cambia los archivos y valida otra vez.
            </p>
          </AlertDescription>
        </Alert>
      )}
      {ok > 0 && (
        <Alert>
          <Icon icon="ph:check-circle-light" className="size-4 text-success" />
          <AlertTitle>
            {ok === 1 ? '1 archivo listo' : `${ok} archivos listos`} para enviar
          </AlertTitle>
          <AlertDescription>El SAT no recibió nada todavía.</AlertDescription>
        </Alert>
      )}
      {omitidos > 0 && (
        <Alert>
          <Icon icon="ph:info-light" className="size-4" />
          <AlertTitle>
            {omitidos === 1 ? '1 archivo ya estaba presentado' : `${omitidos} archivos ya estaban presentados`}
          </AlertTitle>
          <AlertDescription>
            {r.omitidos.map((o) => `${o.archivo} (${o.estatus || 'presentado'})`).join(', ')}.{' '}
            {ok === 0
              ? 'No hay nada nuevo que enviar. Para volver a mandarlo, activa "Enviar aunque el SAT ya lo tenga" en Opciones.'
              : 'Se omiten para no duplicarlos.'}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function ResultadoEnvio({
  r,
  onVerAcuses,
  onOtro,
}: {
  r: CeEnvioResultado;
  onVerAcuses: () => void;
  onOtro: () => void;
}) {
  return (
    <div className="space-y-4">
      {r.enviados.length > 0 && (
        <Alert>
          <Icon icon="ph:check-circle-light" className="size-4 text-success" />
          <AlertTitle>
            {r.enviados.length === 1 ? '1 archivo enviado' : `${r.enviados.length} archivos enviados`}
          </AlertTitle>
          <AlertDescription>
            <ul className="space-y-0.5">
              {r.enviados.map((e) => (
                <li key={e.archivo}>
                  <span className="font-mono">{e.archivo}</span>
                  {e.folio ? <> · folio <span className="font-mono">{e.folio}</span></> : null}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
      {r.fallidos.length > 0 && (
        <Alert variant="destructive">
          <Icon icon="ph:x-circle-light" className="size-4" />
          <AlertTitle>
            {r.fallidos.length === 1 ? '1 archivo no se pudo enviar' : `${r.fallidos.length} archivos no se pudieron enviar`}
          </AlertTitle>
          <AlertDescription>
            <ul className="space-y-1">
              {r.fallidos.map((f) => (
                <li key={f.archivo}>
                  <span className="font-mono">{f.archivo}</span>: {f.mensaje ?? 'sin detalle'}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs opacity-80">
              Si fue un fallo del SAT (lento o en mantenimiento), el archivo quedó en cola y se
              reintenta solo.
            </p>
          </AlertDescription>
        </Alert>
      )}
      {r.omitidos.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Se omitieron {r.omitidos.length} ya presentados: {r.omitidos.map((o) => o.archivo).join(', ')}.
        </p>
      )}

      <Alert variant="warning">
        <Icon icon="ph:warning-light" className="size-4" />
        <AlertTitle>Falta el acuse de aceptación</AlertTitle>
        <AlertDescription>
          {/* En un <p>: AlertDescription es un grid y cada hijo directo sería una fila. */}
          <p>
            El acuse de <strong>recepción</strong> no ampara el cumplimiento: el SAT todavía valida
            el archivo. Solo el de <strong>aceptación</strong> lo ampara. Consúltalo en Acuses en
            unos minutos.
          </p>
        </AlertDescription>
      </Alert>

      <div className="flex flex-wrap gap-2">
        <Button onClick={onVerAcuses}>
          <Icon icon="ph:stamp-light" className="size-4" />
          Ver acuses
        </Button>
        <Button variant="outline" onClick={onOtro}>
          Enviar otros archivos
        </Button>
      </div>
    </div>
  );
}

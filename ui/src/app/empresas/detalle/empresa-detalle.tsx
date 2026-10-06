'use client';

// Componente cliente del detalle de empresa. La ruta es ESTÁTICA
// (`/empresas/detalle`) y el RFC viaja como query param (`?rfc=...`), leído con
// `useSearchParams`. Se evita un segmento dinámico `[rfc]` porque bajo
// `output: 'export'` cualquier valor no pre-generado es 404 (ver ui/CLAUDE.md).
// Debe renderizarse dentro de un <Suspense> (lo hace el page.tsx hermano), que
// es requisito de `useSearchParams` en export estático.

import { useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';

import { useEmpresas } from '@/hooks/use-empresas';
import { Icon } from '@/components/ui/icon';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { VencimientoBadge } from '@/components/fiel/vencimiento-badge';
import { RenovarEfirmaWizard } from '@/components/fiel/renovar-efirma-wizard';
import { GenerarCsdWizard } from '@/components/fiel/generar-csd-wizard';
import { ConfiguracionFiscalCard } from '@/components/empresas/configuracion-fiscal-card';
import { useServer } from '@/providers/server-provider';
import { cn } from '@/lib/utils';
import { RENOVACION_EFIRMA_HABILITADA } from '@/lib/features';
import { colorEmpresa, tipoPersona } from '@/lib/empresa-visual';
import { semaforoVencimiento } from '@/lib/vencimiento';
import { semaforoOpinion } from '@/lib/opinion';
import type { Empresa } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

export function EmpresaDetalle() {
  const searchParams = useSearchParams();
  const rfc = searchParams.get('rfc') ?? '';
  // QA del wizard de CSD sin trigger visible: /empresas/detalle?rfc=…&labs=csd
  // (se conectará de verdad cuando exista la pantalla de Expediente fiscal).
  const labsCsd = searchParams.get('labs') === 'csd';
  const { empresas, loading, refresh, addCiec, addFiel, removeEfirma, activarSesion, update } =
    useEmpresas();
  const { refreshHealth } = useServer();
  const empresa = empresas.find((e) => e.rfc === rfc);

  const volver = (
    <Link href="/empresas" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <Icon icon="ph:arrow-left-light" className="size-4" /> Empresas
    </Link>
  );

  if (loading && !empresa) {
    return (
      <div className="space-y-4">
        {volver}
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" /> Cargando…
        </div>
      </div>
    );
  }

  if (!empresa) {
    return (
      <div className="space-y-4">
        {volver}
        <Alert>
          <AlertDescription>No se encontró la empresa {rfc}.</AlertDescription>
        </Alert>
      </div>
    );
  }

  const tieneCiec = empresa.metodos.includes('ciec');
  const tieneFiel = empresa.metodos.includes('fiel');

  return (
    <div className="max-w-220 space-y-6">
      {volver}

      {/* Cabecera: cuadro PF/PM + nombre + RFC + pills de estado */}
      <div className="space-y-4">
        <div className="flex items-start gap-4">
          <span
            className="flex size-11.5 shrink-0 items-center justify-center rounded-[11px] font-mono text-[15px] font-bold text-background"
            style={{ background: colorEmpresa(empresa.rfc) }}
          >
            {tipoPersona(empresa.rfc)}
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-2xl font-extrabold leading-tight tracking-tight">
              {empresa.nombre}
            </h1>
            <div className="mt-0.5 font-mono text-sm font-semibold text-muted-foreground">
              {empresa.rfc}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {tieneFiel && (
            <Badge variant="secondary" className="gap-1">
              <Icon icon="ph:shield-check-light" className="size-3" /> e.firma
            </Badge>
          )}
          {tieneCiec && (
            <Badge variant="secondary" className="gap-1">
              <Icon icon="ph:key-light" className="size-3" /> Contraseña
            </Badge>
          )}
          {tieneFiel && <VencimientoBadge vencimiento={empresa.vencimiento} />}
        </div>
      </div>

      <ConfiguracionFiscalCard
        empresa={empresa}
        onGuardar={(patch) => update(empresa.rfc, patch)}
        onDatosAplicados={refresh}
      />

      <OpinionSection empresa={empresa} onReparsed={refresh} />

      <CiecSection
        empresa={empresa}
        onGuardar={(ciec) => addCiec(empresa.rfc, ciec, empresa.nombre)}
      />
      <FielSection
        empresa={empresa}
        onGuardar={async (cer, key, password) => {
          await addFiel(cer, key, password, empresa.nombre, empresa.rfc);
          // Cargar la e.firma recién agregada/renovada en la sesión (cabecera/Inicio).
          await activarSesion(empresa.rfc);
        }}
        onQuitar={() => removeEfirma(empresa.rfc)}
        onRenovada={() => {
          refresh();
          refreshHealth();
        }}
      />

      {labsCsd && empresa.metodos.includes('fiel') && (
        <CsdLabsSection empresa={empresa} onDone={refresh} />
      )}
    </div>
  );
}

/** Punto de entrada de QA del wizard de CSD (solo con ?labs=csd). */
function CsdLabsSection({ empresa, onDone }: { empresa: Empresa; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const pendiente = (empresa.csds ?? []).some((c) => c.estado === 'pendiente');
  return (
    <Card className="space-y-3 p-5">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon icon="ph:seal-check-light" className="size-4 text-primary" />
          <span className="text-sm font-medium">Certificados de Sello Digital</span>
          <Badge variant="secondary">labs</Badge>
        </div>
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          <Icon icon="ph:plus-light" className="size-3.5" />
          {pendiente ? 'CSD pendiente…' : 'Generar CSD'}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        Asistente en pruebas: genera la .key y el .sdg, los firma con la e.firma y
        tramita el sello ante el SAT.
      </p>
      <GenerarCsdWizard empresa={empresa} open={open} onOpenChange={setOpen} onDone={onDone} />
    </Card>
  );
}

/** "YYYY-MM-DD" → "16 de diciembre de 2028" (sin sorpresas de zona horaria). */
function fechaLarga(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  return new Date(y, m - 1, d).toLocaleDateString('es-MX', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
}

function Guardado() {
  return (
    <span className="inline-flex items-center gap-1 text-xs font-medium text-success">
      <Icon icon="ph:check-circle-light" className="size-3.5" /> Guardado
    </span>
  );
}

/**
 * Opinión de Cumplimiento 32-D: semáforo (positiva/negativa) y, cuando es
 * negativa, los motivos que el SAT marca en la situación fiscal de la empresa.
 * El sentido lo determina el agente al parsear el PDF descargado; aquí solo se
 * muestra y se ofrece re-analizar una opinión ya descargada.
 */
function OpinionSection({
  empresa,
  onReparsed,
}: {
  empresa: Empresa;
  onReparsed: () => void;
}) {
  const { apiClient } = useServer();
  const sem = semaforoOpinion(empresa);
  const [reanalizando, setReanalizando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Empresa sin ninguna opinión descargada: card informativa (la descarga vive
  // en la lista de Empresas, fila expandida).
  const sinOpinion = !empresa.opinion_path && !empresa.opinion_status;

  const colorTono =
    sem.tono === 'rojo'
      ? 'text-red-600 dark:text-red-400'
      : sem.tono === 'verde'
        ? 'text-emerald-600 dark:text-emerald-400'
        : sem.tono === 'amarillo'
          ? 'text-amber-600 dark:text-amber-400'
          : 'text-muted-foreground';

  async function reanalizar() {
    setReanalizando(true);
    setError(null);
    try {
      await apiClient.parsearOpinion(empresa.rfc);
      onReparsed();
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setReanalizando(false);
    }
  }

  return (
    <Card className="space-y-3 p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Icon icon="ph:clipboard-text-light" className="size-4 text-primary" />
          <span className="text-sm font-medium">Opinión de Cumplimiento 32-D</span>
        </div>
        {empresa.opinion_path && (
          <span title="Vuelve a leer el PDF ya descargado para actualizar el sentido y los motivos.">
            <Button variant="outline" size="sm" onClick={reanalizar} disabled={reanalizando}>
              <Icon
                icon={reanalizando ? 'ph:circle-notch-light' : 'ph:arrows-clockwise-light'}
                className={cn('size-3.5', reanalizando && 'animate-spin')}
              />
              Re-analizar opinión
            </Button>
          </span>
        )}
      </div>

      {sinOpinion ? (
        <p className="text-xs text-muted-foreground">
          Aún no has descargado la opinión de esta empresa. Descárgala desde la
          lista de Empresas (abre la fila de la empresa) y aquí verás su sentido y,
          si es negativa, los motivos.
        </p>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <Icon
              icon={
                sem.tono === 'rojo'
                  ? 'ph:warning-circle-light'
                  : sem.tono === 'verde'
                    ? 'ph:check-circle-light'
                    : 'ph:info-light'
              }
              className={cn('size-5 shrink-0', colorTono)}
            />
            <span className={cn('text-base font-semibold', colorTono)}>
              Opinión {sem.label.toLowerCase()}
            </span>
          </div>

          {empresa.opinion_status === 'negativa' && (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                El SAT marca la situación fiscal de esta empresa por lo siguiente:
              </p>
              {(empresa.opinion_motivos ?? []).length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No se pudieron leer los motivos del PDF. Ábrelo desde la lista de
                  Empresas para ver el detalle.
                </p>
              ) : (
                <ul className="space-y-2.5">
                  {(empresa.opinion_motivos ?? []).map((m, i) => (
                    <li
                      key={`${m.titulo}-${i}`}
                      className="rounded-md border border-destructive/30 bg-destructive/5 p-3"
                    >
                      <div className="flex items-center gap-1.5 text-sm font-semibold text-red-700 dark:text-red-400">
                        <Icon icon="ph:warning-circle-light" className="size-4 shrink-0" />
                        {m.titulo}
                      </div>
                      {m.descripcion && (
                        <p className="mt-1 text-xs text-muted-foreground">{m.descripcion}</p>
                      )}
                      {m.detalles.length > 0 && (
                        <ul className="mt-1.5 space-y-1">
                          {m.detalles.map((d, j) => (
                            <li key={j} className="flex gap-1.5 text-xs text-foreground">
                              <span className="text-muted-foreground">•</span>
                              <span>{d}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {sem.tono === 'amarillo' && (
            <p className="text-xs text-muted-foreground">
              {empresa.opinion_status === 'otro'
                ? 'El sentido de esta opinión no es positiva ni negativa. Abre el PDF para revisarla.'
                : 'Esta opinión se descargó antes del análisis automático. Usa «Re-analizar opinión» para conocer su sentido.'}
            </p>
          )}
        </>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}
    </Card>
  );
}

function CiecSection({
  empresa,
  onGuardar,
}: {
  empresa: Empresa;
  onGuardar: (ciec: string) => Promise<void>;
}) {
  const tiene = empresa.metodos.includes('ciec');
  const [mostrarForm, setMostrarForm] = useState(!tiene);
  const [ciec, setCiec] = useState('');
  const [saving, setSaving] = useState(false);
  const [ok, setOk] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function guardar(e: React.FormEvent) {
    e.preventDefault();
    if (!ciec) return;
    setSaving(true);
    setError(null);
    setOk(false);
    try {
      await onGuardar(ciec);
      setCiec('');
      setOk(true);
      // Si ya tenía CIEC, colapsa el form de vuelta al resumen.
      if (tiene) setMostrarForm(false);
    } catch (err) {
      setError(mensajeDeError(err));
    } finally {
      setSaving(false);
    }
  }

  // Empresa ya tiene CIEC y el form está colapsado → resumen + botón.
  if (tiene && !mostrarForm) {
    return (
      <Card className="space-y-3 p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Icon icon="ph:key-light" className="size-4 text-primary" />
            <span className="text-sm font-medium">Acceso con Contraseña del SAT</span>
            {ok && <Guardado />}
          </div>
          <Button variant="outline" size="sm" onClick={() => setMostrarForm(true)}>
            <Icon icon="ph:key-light" className="size-3.5" />
            Cambiar Contraseña
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Tu Contraseña del SAT (antes CIEC) se guarda protegida y solo en este
          equipo. Nunca se muestra a la vista.
        </p>
      </Card>
    );
  }

  return (
    <Card className="space-y-3 p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon icon="ph:key-light" className="size-4 text-primary" />
          <span className="text-sm font-medium">
            {tiene ? 'Cambiar Contraseña del SAT' : 'Agregar Contraseña del SAT'}
          </span>
        </div>
        {ok && <Guardado />}
      </div>
      <form className="flex gap-2" onSubmit={guardar}>
        <Input
          type="password"
          value={ciec}
          placeholder="Nueva Contraseña del SAT"
          onChange={(e) => {
            setCiec(e.target.value);
            setOk(false);
          }}
        />
        <Button type="submit" disabled={!ciec || saving}>
          {saving ? <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" /> : 'Guardar'}
        </Button>
        {tiene && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setMostrarForm(false);
              setCiec('');
              setError(null);
            }}
          >
            Cancelar
          </Button>
        )}
      </form>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </Card>
  );
}

function FielSection({
  empresa,
  onGuardar,
  onQuitar,
  onRenovada,
}: {
  empresa: Empresa;
  onGuardar: (cer: File, key: File, password: string) => Promise<void>;
  onQuitar: () => Promise<void>;
  /** Refresca catálogo/health tras una renovación en línea exitosa. */
  onRenovada: () => void;
}) {
  const tiene = empresa.metodos.includes('fiel');
  const tieneCiec = empresa.metodos.includes('ciec');
  const sem = tiene ? semaforoVencimiento(empresa.vencimiento) : null;
  const avisaRenovar = sem !== null && sem.estado !== 'verde';
  // Con la renovación en línea deshabilitada no se exponen los estados de
  // trámite (no hay forma de avanzarlos); la vía manual de actualizar
  // archivos .cer/.key sigue disponible (no toca el portal del SAT).
  const pendiente = RENOVACION_EFIRMA_HABILITADA && !!empresa.renovacion_pendiente;
  // 'enviada' (falta bajar el cert) vs 'generada' (reenviar el mismo .ren).
  const pendienteEnviada = RENOVACION_EFIRMA_HABILITADA && !!empresa.renovacion_pendiente?.numero_operacion;
  const [mostrarForm, setMostrarForm] = useState(!tiene);
  const [renovarOpen, setRenovarOpen] = useState(false);
  const [confirmQuitar, setConfirmQuitar] = useState(false);
  const [quitando, setQuitando] = useState(false);
  const [cer, setCer] = useState<File | null>(null);
  const [key, setKey] = useState<File | null>(null);
  const [password, setPassword] = useState('');
  const [saving, setSaving] = useState(false);
  const [ok, setOk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cerRef = useRef<HTMLInputElement>(null);
  const keyRef = useRef<HTMLInputElement>(null);

  async function quitar() {
    setQuitando(true);
    setError(null);
    try {
      await onQuitar();
      setConfirmQuitar(false);
      setMostrarForm(false);
    } catch (err) {
      setError(mensajeDeError(err));
    } finally {
      setQuitando(false);
    }
  }

  async function guardar(e: React.FormEvent) {
    e.preventDefault();
    if (!cer || !key || !password) return;
    setSaving(true);
    setError(null);
    setOk(false);
    try {
      await onGuardar(cer, key, password);
      setCer(null);
      setKey(null);
      setPassword('');
      if (cerRef.current) cerRef.current.value = '';
      if (keyRef.current) keyRef.current.value = '';
      setOk(true);
      if (tiene) setMostrarForm(false);
    } catch (err) {
      setError(mensajeDeError(err));
    } finally {
      setSaving(false);
    }
  }

  // Empresa ya tiene FIEL y el form está colapsado → resumen + botones.
  if (tiene && !mostrarForm) {
    // Resaltado del boceto: la card «grita» cuando la e.firma está por vencer.
    const resaltada =
      avisaRenovar && sem && !sem.vencida
        ? sem.estado === 'rojo'
          ? 'border-destructive/60 ring-2 ring-destructive/15'
          : 'border-warning/60 ring-2 ring-warning/15'
        : undefined;
    return (
      <Card className={cn('space-y-3 p-5', resaltada)}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Icon icon="ph:shield-check-light" className="size-4 text-primary" />
            <span className="text-sm font-medium">e.firma</span>
            {ok && <Guardado />}
          </div>
          <div className="flex items-center gap-2">
            {sem?.vencida ? (
              // Vencida: la renovación en línea ya no aplica; la vía es subir
              // los archivos nuevos del trámite presencial.
              <Button variant="default" size="sm" onClick={() => setMostrarForm(true)}>
                <Icon icon="ph:upload-light" className="size-3.5" />
                Actualizar archivos (.cer/.key)
              </Button>
            ) : RENOVACION_EFIRMA_HABILITADA ? (
              <Button
                variant={pendiente || avisaRenovar ? 'default' : 'outline'}
                size="sm"
                onClick={() => setRenovarOpen(true)}
              >
                <Icon
                  icon={pendienteEnviada ? 'ph:download-simple-light' : 'ph:arrow-clockwise-light'}
                  className="size-3.5"
                />
                {pendienteEnviada
                  ? 'Descargar certificado'
                  : pendiente
                    ? 'Reanudar renovación'
                    : 'Renovar e.firma'}
              </Button>
            ) : (
              <span title="Disponible próximamente">
                <Button variant={avisaRenovar ? 'default' : 'outline'} size="sm" disabled>
                  <Icon icon="ph:arrow-clockwise-light" className="size-3.5" />
                  Renovar e.firma
                </Button>
              </span>
            )}
            <Button
              variant="ghost"
              size="sm"
              className="text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={() => setConfirmQuitar(true)}
            >
              Quitar e.firma
            </Button>
          </div>
        </div>
        {pendienteEnviada || pendiente || !sem ? (
          <p className="text-xs text-muted-foreground">
            {pendienteEnviada
              ? 'Renovación enviada: solo falta descargar el certificado que emitió el SAT.'
              : pendiente
                ? 'El envío de la renovación falló en ese momento; tu e.firma sigue intacta. Reanuda para reenviar la misma solicitud.'
                : 'Certificado registrado.'}
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-2.5">
            <VencimientoBadge vencimiento={empresa.vencimiento} />
            <span className="text-xs text-muted-foreground">
              Vence el {fechaLarga(sem.fecha)}
            </span>
          </div>
        )}
        {avisaRenovar && sem && !pendiente && (
          <Alert
            variant={sem.estado === 'rojo' ? 'destructive' : 'default'}
            className={
              sem.estado === 'amarillo'
                ? 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300'
                : undefined
            }
          >
            <AlertDescription className="text-xs">
              {sem.vencida
                ? `Esta e.firma venció el ${fechaLarga(sem.fecha)}. Renuévala con el nuevo .cer y .key — o quítala y sigue trabajando con tu Contraseña del SAT mientras la renuevas.`
                : RENOVACION_EFIRMA_HABILITADA
                  ? `${sem.estado === 'rojo' ? 'Vence muy pronto.' : 'Está por vencer.'} Renuévala en línea desde aquí — no necesitas ir al SAT.`
                  : `${sem.estado === 'rojo' ? 'Vence muy pronto.' : 'Está por vencer.'} Renuévala en el SAT y actualiza aquí los archivos nuevos (.cer/.key).`}
            </AlertDescription>
          </Alert>
        )}
        {!sem?.vencida && (
          <button
            type="button"
            onClick={() => setMostrarForm(true)}
            className="text-xs text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
          >
            ¿Ya renovaste en el SAT? Actualizar archivos (.cer/.key)
          </button>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}

        {RENOVACION_EFIRMA_HABILITADA && (
          <RenovarEfirmaWizard
            empresa={empresa}
            open={renovarOpen}
            onOpenChange={setRenovarOpen}
            onDone={onRenovada}
            onActualizarArchivos={() => setMostrarForm(true)}
          />
        )}

        <Dialog open={confirmQuitar} onOpenChange={(o) => !o && setConfirmQuitar(false)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Quitar e.firma</DialogTitle>
              <DialogDescription>
                {tieneCiec
                  ? `Se quitará la e.firma de "${empresa.nombre}" de este equipo (archivos y contraseña). La empresa seguirá funcionando con su Contraseña del SAT; podrás cargar una e.firma nueva cuando la renueves.`
                  : `Se quitará la e.firma de "${empresa.nombre}" de este equipo (archivos y contraseña). Esta empresa no tiene Contraseña del SAT registrada, así que quedará sin acceso al SAT hasta que agregues una e.firma o una Contraseña.`}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirmQuitar(false)}>
                Cancelar
              </Button>
              <Button variant="destructive" disabled={quitando} onClick={quitar}>
                {quitando ? (
                  <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                ) : null}
                Quitar e.firma
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </Card>
    );
  }

  return (
    <Card className="space-y-3 p-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon icon="ph:shield-check-light" className="size-4 text-primary" />
          <span className="text-sm font-medium">
            {tiene ? 'Renovar e.firma' : 'Agregar e.firma'}
          </span>
        </div>
        {ok && <Guardado />}
      </div>
      <p className="text-xs text-muted-foreground">
        Sube el .cer y .key de la e.firma de este RFC ({empresa.rfc}).
      </p>
      {avisaRenovar && sem && (
        <Alert
          variant={sem.estado === 'rojo' ? 'destructive' : 'default'}
          className={
            sem.estado === 'amarillo'
              ? 'border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300'
              : undefined
          }
        >
          <AlertDescription className="text-xs">
            {sem.vencida
              ? `Esta e.firma venció el ${fechaLarga(sem.fecha)}. Renuévala subiendo el nuevo .cer y .key.`
              : `Esta e.firma ${sem.label.toLowerCase()} (vence el ${fechaLarga(sem.fecha)}). Conviene renovarla.`}
          </AlertDescription>
        </Alert>
      )}
      <form className="space-y-3" onSubmit={guardar}>
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="cer">Certificado (.cer)</Label>
            <Input ref={cerRef} id="cer" type="file" accept=".cer"
                   onChange={(e) => { setCer(e.target.files?.[0] ?? null); setOk(false); }} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="key">Llave (.key)</Label>
            <Input ref={keyRef} id="key" type="file" accept=".key"
                   onChange={(e) => { setKey(e.target.files?.[0] ?? null); setOk(false); }} />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="pass">Contraseña de la clave privada</Label>
          <Input id="pass" type="password" value={password}
                 onChange={(e) => { setPassword(e.target.value); setOk(false); }} />
        </div>
        <div className="flex gap-2">
          <Button type="submit" disabled={!cer || !key || !password || saving}>
            {saving ? <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" /> : <Icon icon="ph:shield-check-light" className="size-4" />}
            {tiene ? 'Renovar e.firma' : 'Agregar e.firma'}
          </Button>
          {tiene && (
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setMostrarForm(false);
                setCer(null);
                setKey(null);
                setPassword('');
                if (cerRef.current) cerRef.current.value = '';
                if (keyRef.current) keyRef.current.value = '';
                setError(null);
              }}
            >
              Cancelar
            </Button>
          )}
        </div>
      </form>
      {error && <p className="text-xs text-destructive">{error}</p>}
    </Card>
  );
}

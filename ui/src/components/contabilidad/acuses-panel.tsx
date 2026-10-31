'use client';

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { EmptyState } from '@/components/shared/empty-state';
import { FasesProgreso, type FaseItem } from '@/components/shared/fases-progreso';
import { StatusBadge, type StatusTone } from '@/components/shared/status-badge';
import { guardarBlob } from '@/lib/descargas';
import {
  ejerciciosDisponibles,
  resumenAcuses,
  tonoEstatus,
} from '@/lib/contabilidad-electronica';
import { mensajeDeError } from '@/lib/errores';
import { formatDateTime } from '@/lib/formatting';
import type { CeAcuseFila, CeAcusesGuardados } from '@/lib/types';

const FASES_CONSULTA: FaseItem[] = [
  { label: 'Entrando al portal del SAT con tu e.firma', fases: ['login'] },
  { label: 'Consultando los envíos del ejercicio', fases: ['consultando', 'resultados'] },
  { label: 'Descargando los acuses (PDF)', fases: ['bajando_acuses', 'fin'] },
];

const ICONO_ESTATUS: Record<StatusTone, string> = {
  success: 'ph:check-circle-light',
  warning: 'ph:clock-light',
  error: 'ph:x-circle-light',
  info: 'ph:info-light',
  neutral: 'ph:info-light',
  ai: 'ph:info-light',
};

interface AcusesPanelProps {
  rfc: string;
  anio: number;
  onAnioChange: (anio: number) => void;
  /** Rechazado → llevar a la pestaña de envío para corregir y reenviar. */
  onCorregir: () => void;
  /** Cambia cuando se envió algo: vuelve a leer lo guardado. */
  refreshKey: number;
}

export function AcusesPanel({ rfc, anio, onAnioChange, onCorregir, refreshKey }: AcusesPanelProps) {
  const { apiClient, isConnected } = useServer();
  const job = useJob();
  const [guardado, setGuardado] = useState<CeAcusesGuardados | null>(null);
  const [bajando, setBajando] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      setGuardado(await apiClient.ceAcusesGuardados(rfc, anio));
    } catch {
      setGuardado({ consultado_en: null, filas: [] });
    }
  }, [apiClient, rfc, anio]);

  useEffect(() => {
    setGuardado(null);
    if (isConnected) void cargar();
  }, [isConnected, cargar, refreshKey]);

  // Terminada la consulta, los PDF ya están en disco: relee lo guardado.
  useEffect(() => {
    if (job.estado === 'done') void cargar();
  }, [job.estado]); // eslint-disable-line react-hooks/exhaustive-deps -- solo el flanco del job

  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';
  const filas = guardado?.filas ?? [];
  const resumen = resumenAcuses(filas);

  async function bajar(fila: CeAcuseFila, tipo: 'AR' | 'AP') {
    const clave = `${tipo}_${fila.folio}`;
    setBajando(clave);
    try {
      const blob = await apiClient.ceAcusePdf(rfc, anio, fila.folio, tipo);
      guardarBlob(blob, `${clave}.pdf`);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBajando(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">Ejercicio</p>
          <Select
            value={String(anio)}
            onValueChange={(v) => onAnioChange(Number(v))}
            disabled={corriendo}
          >
            <SelectTrigger className="w-32">
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
        </div>
        <div className="flex items-center gap-3">
          {guardado?.consultado_en && !corriendo && (
            <span className="text-xs text-muted-foreground">
              Consultado el {formatDateTime(guardado.consultado_en)}
            </span>
          )}
          <Button
            size="sm"
            disabled={corriendo}
            onClick={() =>
              void job.iniciar(() => apiClient.ceAcuses(rfc, anio), { rfc, notificar: false })
            }
          >
            <Icon
              icon={corriendo ? 'ph:circle-notch-light' : 'ph:arrows-clockwise-light'}
              className={corriendo ? 'size-4 animate-spin' : 'size-4'}
            />
            {corriendo ? 'Consultando…' : 'Actualizar desde el SAT'}
          </Button>
        </div>
      </div>

      {corriendo && (
        <FasesProgreso items={FASES_CONSULTA} faseActual={job.fase} estado={job.estado} />
      )}

      {job.estado === 'error' && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-light" className="size-4" />
          <AlertTitle>No se pudo consultar al SAT</AlertTitle>
          <AlertDescription>{job.error ?? 'El SAT no respondió.'}</AlertDescription>
        </Alert>
      )}

      {!corriendo && resumen.total > 0 && (
        <div className="space-y-3">
          {resumen.rechazados > 0 && (
            <Alert variant="destructive">
              <Icon icon="ph:x-circle-light" className="size-4" />
              <AlertTitle>
                {resumen.rechazados === 1 ? '1 envío rechazado' : `${resumen.rechazados} envíos rechazados`}
              </AlertTitle>
              <AlertDescription className="space-y-3">
                <p>
                  El SAT lo validó y no lo aceptó. Abre el acuse para ver el motivo, corrige el
                  archivo en tu software contable y vuelve a enviarlo.
                </p>
                <Button variant="outline" size="sm" onClick={onCorregir}>
                  <Icon icon="ph:paper-plane-tilt-light" className="size-4" />
                  Corregir y reenviar
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {resumen.recibidos > 0 && (
            <Alert variant="warning">
              <Icon icon="ph:clock-light" className="size-4" />
              <AlertTitle>
                {resumen.recibidos === 1 ? '1 envío en "Recibido"' : `${resumen.recibidos} envíos en "Recibido"`}
              </AlertTitle>
              <AlertDescription>
                El SAT aún los valida. Solo "Aceptado" ampara el cumplimiento: vuelve a actualizar
                en unos minutos.
              </AlertDescription>
            </Alert>
          )}
          {resumen.rechazados === 0 && resumen.recibidos === 0 && (
            <Alert>
              <Icon icon="ph:check-circle-light" className="size-4 text-success" />
              <AlertTitle>
                {resumen.total === 1 ? 'El envío está aceptado' : `Los ${resumen.total} envíos están aceptados`}
              </AlertTitle>
            </Alert>
          )}
        </div>
      )}

      {guardado && filas.length === 0 && !corriendo ? (
        <EmptyState
          icon="ph:stamp-light"
          title={guardado.consultado_en ? 'El SAT no reporta envíos en ese ejercicio' : 'Aún no has consultado este ejercicio'}
          description={
            guardado.consultado_en
              ? 'Si acabas de enviar, espera unos minutos y actualiza.'
              : 'Actualiza desde el SAT para ver el estatus de cada envío y bajar sus acuses.'
          }
        />
      ) : (
        filas.length > 0 && (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Periodo</TableHead>
                  <TableHead>Archivo</TableHead>
                  <TableHead>Folio</TableHead>
                  <TableHead>Fecha</TableHead>
                  <TableHead>Estatus</TableHead>
                  <TableHead className="text-right">Acuses</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((f) => {
                  const tono = tonoEstatus(f.estatus);
                  return (
                    <TableRow key={f.folio}>
                      <TableCell>{f.periodo}</TableCell>
                      <TableCell className="font-mono text-xs">{f.archivo}</TableCell>
                      <TableCell className="font-mono text-xs">{f.folio}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">{f.fecha}</TableCell>
                      <TableCell>
                        <StatusBadge tone={tono} icon={ICONO_ESTATUS[tono]}>
                          {f.estatus || 'Sin estatus'}
                        </StatusBadge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1.5">
                          <BotonAcuse
                            texto="Recepción"
                            disponible={!!f.tiene_ar}
                            cargando={bajando === `AR_${f.folio}`}
                            onClick={() => void bajar(f, 'AR')}
                          />
                          <BotonAcuse
                            texto={f.estatus === 'Rechazado' ? 'Rechazo' : 'Aceptación'}
                            disponible={!!f.tiene_ap}
                            cargando={bajando === `AP_${f.folio}`}
                            onClick={() => void bajar(f, 'AP')}
                          />
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )
      )}
    </div>
  );
}

function BotonAcuse({
  texto,
  disponible,
  cargando,
  onClick,
}: {
  texto: string;
  disponible: boolean;
  cargando: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={!disponible || cargando}
      onClick={onClick}
      title={disponible ? `Descargar el acuse de ${texto.toLowerCase()} (PDF)` : 'Aún no disponible'}
    >
      <Icon
        icon={cargando ? 'ph:circle-notch-light' : 'ph:file-pdf-light'}
        className={cargando ? 'size-4 animate-spin' : 'size-4'}
      />
      {texto}
    </Button>
  );
}

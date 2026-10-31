'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
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
import { ejerciciosDisponibles, MESES } from '@/lib/contabilidad-electronica';
import { etiquetaPeriodoDiot, rangoMeses, tonoEstatusDiot } from '@/lib/diot-envio';
import { guardarBlob } from '@/lib/descargas';
import { mensajeDeError } from '@/lib/errores';
import { formatDateTime } from '@/lib/formatting';
import type { DiotPresentadaFila, DiotPresentadasGuardadas } from '@/lib/types';

const FASES_CONSULTA: FaseItem[] = [
  { label: 'Entrando al portal de la DIOT con tu e.firma', fases: ['login'] },
  { label: 'Consultando las declaraciones presentadas', fases: ['consultando'] },
  { label: 'Descargando los archivos (PDF, Excel y acuse)', fases: ['descargando', 'fin'] },
];

const ICONO_ESTATUS: Record<StatusTone, string> = {
  success: 'ph:check-circle-light',
  warning: 'ph:clock-light',
  error: 'ph:x-circle-light',
  info: 'ph:info-light',
  neutral: 'ph:info-light',
  ai: 'ph:info-light',
};

type ArchivoDiot = 'declaracion' | 'excel' | 'acuse';

interface PresentadasPanelProps {
  rfc: string;
  ejercicio: number;
  onEjercicioChange: (e: number) => void;
  mes: number | 'todos';
  onMesChange: (m: number | 'todos') => void;
  /** Llegó de "Verificar" (trámite sin acuse): consulta al abrir. */
  verificar: boolean;
}

export function PresentadasPanel({
  rfc,
  ejercicio,
  onEjercicioChange,
  mes,
  onMesChange,
  verificar,
}: PresentadasPanelProps) {
  const { apiClient, isConnected } = useServer();
  const job = useJob();
  const [guardado, setGuardado] = useState<DiotPresentadasGuardadas | null>(null);
  const [bajando, setBajando] = useState<string | null>(null);
  const yaConsultoPorVerificar = useRef(false);

  const cargar = useCallback(async () => {
    try {
      setGuardado(await apiClient.diotPresentadasGuardadas(rfc, ejercicio));
    } catch {
      setGuardado({ consultado_en: null, filas: [] });
    }
  }, [apiClient, rfc, ejercicio]);

  useEffect(() => {
    setGuardado(null);
    if (isConnected) void cargar();
  }, [isConnected, cargar]);

  // Terminada la consulta, los archivos ya están en disco: relee lo guardado.
  useEffect(() => {
    if (job.estado === 'done') void cargar();
  }, [job.estado]); // eslint-disable-line react-hooks/exhaustive-deps -- solo el flanco del job

  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';

  const consultar = useCallback(() => {
    const { mesIni, mesFin } = rangoMeses(mes);
    void job.iniciar(() => apiClient.diotPresentadas(rfc, ejercicio, mesIni, mesFin), {
      rfc,
      notificar: false,
    });
  }, [apiClient, job, rfc, ejercicio, mes]);

  // "Verificar": quien llega aquí con un trámite sin acuse ya pidió consultar.
  useEffect(() => {
    if (verificar && isConnected && !yaConsultoPorVerificar.current) {
      yaConsultoPorVerificar.current = true;
      consultar();
    }
  }, [verificar, isConnected, consultar]);

  async function bajar(fila: DiotPresentadaFila, tipo: ArchivoDiot) {
    const clave = `${tipo}_${fila.numero_operacion}`;
    setBajando(clave);
    try {
      const blob = await apiClient.diotArchivo(rfc, fila.numero_operacion, tipo);
      const ext = tipo === 'excel' ? 'xlsx' : 'pdf';
      guardarBlob(blob, `DIOT_${rfc}_${fila.periodo}_${tipo}_${fila.numero_operacion}.${ext}`);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBajando(null);
    }
  }

  const filas = (guardado?.filas ?? []).filter((f) => mes === 'todos' || f.mes === mes);
  const faseDatos = job.faseDatos as { periodo?: string } | null;

  return (
    <div className="space-y-5">
      {verificar && (
        <Alert variant="warning">
          <Icon icon="ph:info-light" className="size-4" />
          <AlertTitle>Verificando una declaración sin acuse</AlertTitle>
          <AlertDescription>
            Busca el periodo que firmaste: si aparece una declaración con la fecha de hoy, el SAT sí
            la registró y no hay que repetirla. Si no aparece, no quedó presentada.
          </AlertDescription>
        </Alert>
      )}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Ejercicio</p>
            <Select
              value={String(ejercicio)}
              onValueChange={(v) => onEjercicioChange(Number(v))}
              disabled={corriendo}
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
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Mes</p>
            <Select
              value={String(mes)}
              onValueChange={(v) => onMesChange(v === 'todos' ? 'todos' : Number(v))}
              disabled={corriendo}
            >
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="todos">Todo el ejercicio</SelectItem>
                {MESES.map((nombre, i) => (
                  <SelectItem key={nombre} value={String(i + 1)}>
                    {nombre}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {guardado?.consultado_en && !corriendo && (
            <span className="text-xs text-muted-foreground">
              Consultado el {formatDateTime(guardado.consultado_en)}
            </span>
          )}
          <Button size="sm" disabled={corriendo} onClick={consultar}>
            <Icon
              icon={corriendo ? 'ph:circle-notch-light' : 'ph:arrows-clockwise-light'}
              className={corriendo ? 'size-4 animate-spin' : 'size-4'}
            />
            {corriendo ? 'Consultando…' : 'Actualizar desde el SAT'}
          </Button>
        </div>
      </div>

      {mes === 'todos' && !corriendo && (
        <p className="text-xs text-muted-foreground">
          Consultar todo el ejercicio recorre los 12 meses y puede tardar varios minutos. Para una
          verificación puntual, elige el mes.
        </p>
      )}

      {corriendo && (
        <div className="space-y-1">
          <FasesProgreso items={FASES_CONSULTA} faseActual={job.fase} estado={job.estado} />
          {faseDatos?.periodo && (
            <p className="px-3 text-xs text-muted-foreground">
              Revisando {etiquetaPeriodoDiot(Number(faseDatos.periodo.slice(0, 4)), Number(faseDatos.periodo.slice(5, 7)))}…
            </p>
          )}
        </div>
      )}

      {job.estado === 'error' && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-light" className="size-4" />
          <AlertTitle>No se pudo consultar al SAT</AlertTitle>
          <AlertDescription>{job.error ?? 'El SAT no respondió.'}</AlertDescription>
        </Alert>
      )}

      {guardado && filas.length === 0 && !corriendo ? (
        <EmptyState
          icon="ph:stamp-light"
          title={
            guardado.consultado_en
              ? 'El SAT no reporta DIOT presentadas en esa consulta'
              : 'Aún no has consultado este ejercicio'
          }
          description={
            guardado.consultado_en
              ? 'Si acabas de presentar, espera unos minutos y actualiza.'
              : 'Actualiza desde el SAT para ver las DIOT presentadas y bajar sus archivos.'
          }
        />
      ) : (
        filas.length > 0 && (
          <div className="overflow-x-auto rounded-xl border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Periodo</TableHead>
                  <TableHead>No. de operación</TableHead>
                  <TableHead>Tipo</TableHead>
                  <TableHead>Presentada</TableHead>
                  <TableHead>Estatus</TableHead>
                  <TableHead className="text-right">Archivos</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filas.map((f) => {
                  const tono = tonoEstatusDiot(f.estado);
                  return (
                    <TableRow key={`${f.periodo}-${f.numero_operacion}`}>
                      <TableCell>{etiquetaPeriodoDiot(Number(f.periodo.slice(0, 4)), f.mes)}</TableCell>
                      <TableCell className="font-mono text-xs">{f.numero_operacion}</TableCell>
                      <TableCell className="text-xs">
                        {f.tipo_declaracion || 'Normal'}
                        {f.tipo_complementaria ? ` · ${f.tipo_complementaria}` : ''}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">{f.fecha_presentacion}</TableCell>
                      <TableCell>
                        <StatusBadge tone={tono} icon={ICONO_ESTATUS[tono]}>
                          {f.estado || 'Sin estatus'}
                        </StatusBadge>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-1.5">
                          <BotonArchivo
                            texto="Declaración"
                            icono="ph:file-pdf-light"
                            disponible={f.tiene_declaracion}
                            cargando={bajando === `declaracion_${f.numero_operacion}`}
                            onClick={() => void bajar(f, 'declaracion')}
                          />
                          <BotonArchivo
                            texto="Excel"
                            icono="ph:file-xls-light"
                            disponible={f.tiene_excel}
                            cargando={bajando === `excel_${f.numero_operacion}`}
                            onClick={() => void bajar(f, 'excel')}
                          />
                          <BotonArchivo
                            texto="Acuse"
                            icono="ph:stamp-light"
                            disponible={f.tiene_acuse}
                            cargando={bajando === `acuse_${f.numero_operacion}`}
                            onClick={() => void bajar(f, 'acuse')}
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

function BotonArchivo({
  texto,
  icono,
  disponible,
  cargando,
  onClick,
}: {
  texto: string;
  icono: string;
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
      title={disponible ? `Descargar: ${texto.toLowerCase()}` : 'Aún no disponible'}
    >
      <Icon
        icon={cargando ? 'ph:circle-notch-light' : icono}
        className={cargando ? 'size-4 animate-spin' : 'size-4'}
      />
      {texto}
    </Button>
  );
}

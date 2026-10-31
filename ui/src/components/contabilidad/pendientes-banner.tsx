'use client';

import { useCallback, useEffect, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useJob } from '@/hooks/use-job';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import type { CePendiente } from '@/lib/types';

interface PendientesBannerProps {
  rfc: string;
  /** Cambia cuando otra parte de la pantalla envió algo: vuelve a leer la cola. */
  refreshKey: number;
  /** El reintento terminó (hay que refrescar los acuses). */
  onCambio: () => void;
}

/**
 * Envíos que el SAT dejó en cola (lento o en mantenimiento, nunca lo anuncia).
 * El agente los reintenta solo cada 30 min; aquí se ve que existen y se puede
 * forzar el reintento. Reanudar es idempotente: consulta el portal antes de
 * subir, así que no duplica nada.
 */
export function PendientesBanner({ rfc, refreshKey, onCambio }: PendientesBannerProps) {
  const { apiClient, isConnected } = useServer();
  const job = useJob();
  const [pendientes, setPendientes] = useState<CePendiente[]>([]);

  const cargar = useCallback(async () => {
    try {
      const r = await apiClient.cePendientes(rfc);
      setPendientes(r.pendientes);
    } catch {
      setPendientes([]); // el aviso es secundario: sin cola visible, no estorba
    }
  }, [apiClient, rfc]);

  useEffect(() => {
    if (isConnected) void cargar();
  }, [isConnected, cargar, refreshKey]);

  // Al terminar el reintento, la cola cambió y los acuses también.
  useEffect(() => {
    if (job.estado === 'done' || job.estado === 'error') {
      void cargar();
      if (job.estado === 'done') onCambio();
    }
  }, [job.estado]); // eslint-disable-line react-hooks/exhaustive-deps -- solo el flanco del job

  if (pendientes.length === 0) return null;

  const archivos = pendientes.reduce((n, p) => n + p.archivos.length, 0);
  const corriendo = job.estado === 'iniciando' || job.estado === 'corriendo';

  return (
    <Alert variant="warning">
      <Icon icon="ph:clock-light" className="size-4" />
      <AlertTitle>
        {archivos === 1 ? '1 archivo en cola' : `${archivos} archivos en cola`}
      </AlertTitle>
      <AlertDescription className="space-y-3">
        <p>
          El SAT estaba lento o en mantenimiento y no alcanzó a recibirlos. TodoConta los
          reintenta solo cada 30 minutos, sin duplicar lo que ya esté presentado.
        </p>
        {pendientes[0]?.ultimo_error && (
          <p className="text-xs opacity-80">Último aviso del SAT: {pendientes[0].ultimo_error}</p>
        )}
        {job.estado === 'error' && job.error && <p className="text-xs">{job.error}</p>}
        <Button
          variant="outline"
          size="sm"
          disabled={corriendo}
          onClick={() =>
            void job.iniciar(() => apiClient.ceReanudar(rfc), { rfc, notificar: false })
          }
        >
          <Icon
            icon={corriendo ? 'ph:circle-notch-light' : 'ph:arrows-clockwise-light'}
            className={corriendo ? 'size-4 animate-spin' : 'size-4'}
          />
          {corriendo ? 'Reintentando…' : 'Reintentar ahora'}
        </Button>
      </AlertDescription>
    </Alert>
  );
}

'use client';

import { useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Icon } from '@/components/ui/icon';
import { ResourceList, type ResourceListColumn } from '@/components/shared/resource-list';
import { ResourceActions, type ResourceAction } from '@/components/shared/resource-actions';
import { StatusBadge, type StatusTone } from '@/components/shared/status-badge';
import { SolicitudRowExpanded } from '@/components/descarga/solicitud-row-expanded';
import type { Solicitud } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

// Mapeo del estado SAT (o "solicitada"/"vencida"/"descargada") → tono + ícono.
// Códigos SAT: 1=En cola · 2=Procesando · 3=Lista · 4=Error · 5=Rechazada ·
// 6=Vencida. "vencida" también se marca localmente cuando una solicitud lleva
// más de 72 h (el SLA del SAT) sin resolverse.
const ESTADO_META: Record<
  string,
  { label: string; tone: StatusTone; icon?: string; pulse?: boolean }
> = {
  solicitada: { label: 'Solicitada', tone: 'neutral' },
  '1': { label: 'En cola', tone: 'info' },
  '2': { label: 'Procesando', tone: 'info', icon: 'ph:circle-notch-light', pulse: true },
  '3': { label: 'Lista', tone: 'success', icon: 'ph:check-circle-light' },
  '4': { label: 'Error', tone: 'error', icon: 'ph:x-circle-light' },
  '5': { label: 'Rechazada', tone: 'error', icon: 'ph:x-circle-light' },
  vencida: { label: 'Vencida', tone: 'error', icon: 'ph:hourglass-medium-light' },
  descargada: { label: 'Descargada', tone: 'success', icon: 'ph:download-simple-light' },
};

function fechaCorta(iso: string): string {
  // "YYYY-MM-DD" → "DD MMM YYYY" en es-MX, sin tocar timezone (string puro).
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString('es-MX', { day: '2-digit', month: 'short', year: 'numeric' });
}

interface SolicitudesListProps {
  solicitudes: Solicitud[];
  loading: boolean;
  /** Descarga el paquete de una solicitud "Lista" o "Descargada" (mientras siga vigente en SAT). */
  onDescargar?: (idSolicitud: string) => Promise<void>;
  /** Borra la solicitud del catálogo local. */
  onEliminar?: (idSolicitud: string) => Promise<void>;
}

export function SolicitudesList({
  solicitudes,
  loading,
  onDescargar,
  onEliminar,
}: SolicitudesListProps) {
  const [accionError, setAccionError] = useState<string | null>(null);

  const columns: ResourceListColumn<Solicitud>[] = [
    {
      key: 'tipo',
      header: 'Tipo',
      width: 'w-44',
      render: (s) => <span>{s.tipo || '–'}</span>,
    },
    {
      key: 'periodo',
      header: 'Período',
      render: (s) => (
        <span className="whitespace-nowrap text-muted-foreground">
          {fechaCorta(s.fecha_inicio)} – {fechaCorta(s.fecha_fin)}
        </span>
      ),
    },
    {
      key: 'cfdis',
      header: 'CFDIs',
      width: 'w-20',
      align: 'right',
      render: (s) => (
        <span className="font-mono">
          {s.numero_cfdis != null ? s.numero_cfdis.toLocaleString('es-MX') : '–'}
        </span>
      ),
    },
    {
      key: 'estado',
      header: 'Estado',
      width: 'w-32',
      render: (s) => {
        const meta = ESTADO_META[s.estado] ?? { label: s.estado || 'Desconocido', tone: 'neutral' as StatusTone };
        return (
          <StatusBadge tone={meta.tone} icon={meta.icon} pulse={meta.pulse} size="sm">
            {meta.label}
          </StatusBadge>
        );
      },
    },
  ];

  if (loading && solicitudes.length === 0) {
    return (
      <Card title="Solicitudes recientes">
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
          Cargando solicitudes…
        </div>
      </Card>
    );
  }

  if (solicitudes.length === 0) {
    return (
      <Card title="Solicitudes recientes">
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <Icon icon="ph:cloud-arrow-down-light" className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Sin solicitudes de descarga</p>
          <p className="text-sm text-muted-foreground">
            Usa el formulario de arriba para solicitar tu primera descarga masiva al SAT.
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card title="Solicitudes recientes">
      {accionError && (
        <Alert variant="destructive" className="mb-3">
          <AlertDescription>{accionError}</AlertDescription>
        </Alert>
      )}
      <ResourceList<Solicitud>
        items={solicitudes}
        getKey={(s) => s.id_solicitud}
        columns={columns}
        pageSize={25}
        actionsHeader="Acciones"
        actions={(s) => (
          <RowActions
            s={s}
            onDescargar={onDescargar}
            onEliminar={onEliminar}
            onError={setAccionError}
          />
        )}
        expandable={{ render: (s) => <SolicitudRowExpanded solicitud={s} /> }}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Helpers internos
// ---------------------------------------------------------------------------

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="text-lg font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function RowActions({
  s,
  onDescargar,
  onEliminar,
  onError,
}: {
  s: Solicitud;
  onDescargar?: (id: string) => Promise<void>;
  onEliminar?: (id: string) => Promise<void>;
  onError: (msg: string | null) => void;
}) {
  const [busy, setBusy] = useState<'descargar' | 'eliminar' | null>(null);

  // El paquete sigue vigente en SAT cuando ya está Lista (3) o ya se descargó.
  const puedeDescargar = s.estado === '3' || s.estado === 'descargada';

  async function run(kind: 'descargar' | 'eliminar', fn: () => Promise<void>) {
    setBusy(kind);
    onError(null);
    try {
      await fn();
    } catch (e) {
      onError(mensajeDeError(e));
    } finally {
      setBusy(null);
    }
  }

  const acciones: ResourceAction[] = [];

  if (onDescargar && puedeDescargar) {
    acciones.push({
      icon: busy === 'descargar' ? 'ph:circle-notch-light' : 'ph:download-simple-light',
      label: s.estado === 'descargada' ? 'Volver a descargar' : 'Descargar',
      onClick: () => run('descargar', () => onDescargar(s.id_solicitud)),
      disabled: busy !== null,
      iconOnly: true,
    });
  }

  if (onEliminar) {
    acciones.push({
      icon: busy === 'eliminar' ? 'ph:circle-notch-light' : 'ph:trash-light',
      label: 'Eliminar',
      onClick: () => {
        if (!window.confirm('¿Eliminar esta solicitud del catálogo? (No afecta al SAT.)')) return;
        void run('eliminar', () => onEliminar(s.id_solicitud));
      },
      disabled: busy !== null,
      destructive: true,
      iconOnly: true,
    });
  }

  return <ResourceActions actions={acciones} />;
}

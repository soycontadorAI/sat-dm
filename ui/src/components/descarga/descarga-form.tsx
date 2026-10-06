'use client';

import { useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { usePrefill, type PrefillDescarga } from '@/lib/prefill';

// ---------------------------------------------------------------------------
// Parámetros que emite el form (la página expande "A" en dos solicitudes E + R).
// ---------------------------------------------------------------------------

export type ComprobanteSeleccion = 'E' | 'R' | 'A';

export interface DescargaFormParams {
  fecha_inicio: string;
  fecha_fin: string;
  tipo_solicitud: 'CFDI' | 'Metadata';
  tipo_comprobante: ComprobanteSeleccion;
}

// ---------------------------------------------------------------------------
// Date helpers
// ---------------------------------------------------------------------------

function firstDayOfMonth(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${year}-${month}-01`;
}

function lastDayOfMonth(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = now.getMonth() + 1;
  const lastDay = new Date(year, month, 0).getDate();
  return `${year}-${String(month).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface DescargaFormProps {
  onSubmit: (params: DescargaFormParams) => void;
  isLoading: boolean;
  disabled: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function DescargaForm({ onSubmit, isLoading, disabled }: DescargaFormProps) {
  const [fechaInicio, setFechaInicio] = useState(firstDayOfMonth);
  const [fechaFin, setFechaFin] = useState(lastDayOfMonth);
  const [tipoSolicitud, setTipoSolicitud] = useState<'CFDI' | 'Metadata'>('CFDI');
  const [tipoComprobante, setTipoComprobante] = useState<ComprobanteSeleccion>('E');

  // Orden de ⌘K ("descargar recibidos de septiembre de ..."): el primer Enter
  // llena el formulario y deja el foco en "Solicitar descarga"; el segundo
  // Enter la manda. Nada sale al SAT sin ese segundo Enter (el SAT limita las
  // solicitudes repetidas con el mismo criterio).
  const prefill = usePrefill('descarga');
  const [deOrden, setDeOrden] = useState<PrefillDescarga | null>(null);
  const [enfocarPendiente, setEnfocarPendiente] = useState(false);
  const submitRef = useRef<HTMLButtonElement>(null);
  // Un Enter sostenido no debe mandar la solicitud: ignorar el submit en los
  // primeros instantes después de llenar.
  const listoDesde = useRef(0);

  useEffect(() => {
    if (!prefill) return;
    setFechaInicio(prefill.desde);
    setFechaFin(prefill.hasta);
    setTipoSolicitud('CFDI');
    setTipoComprobante(prefill.comprobante);
    setDeOrden(prefill);
    setEnfocarPendiente(true);
  }, [prefill]);

  const isDisabledPrefill = disabled || isLoading;
  useEffect(() => {
    if (!enfocarPendiente || isDisabledPrefill) return;
    listoDesde.current = Date.now() + 400;
    submitRef.current?.focus();
    setEnfocarPendiente(false);
  }, [enfocarPendiente, isDisabledPrefill]);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (Date.now() < listoDesde.current) return;
    setDeOrden(null);
    onSubmit({
      fecha_inicio: fechaInicio,
      fecha_fin: fechaFin,
      tipo_solicitud: tipoSolicitud,
      tipo_comprobante: tipoComprobante,
    });
  }

  const isDisabled = disabled || isLoading;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Icon icon="ph:download-simple-light" className="size-5" />
          Solicitar descarga
        </CardTitle>
        <CardDescription>
          Elige el periodo, el tipo de descarga y de qué facturas. "Ambas" pide
          las emitidas y las recibidas al mismo tiempo.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-6">
          {deOrden && (
            <div className="flex items-start gap-2.5 rounded-[10px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-muted-foreground">
              <Icon icon="ph:arrow-elbow-down-left-light" className="mt-0.5 size-4 shrink-0 text-foreground" />
              <span>
                <span className="font-semibold text-foreground">Lo llenó tu orden:</span>{' '}
                {deOrden.etiqueta}. Revisa y confirma con Enter.
              </span>
            </div>
          )}
          {/* Date range — se queda como está, nativo */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="fecha-inicio">Fecha inicio</Label>
              <Input
                id="fecha-inicio"
                type="date"
                value={fechaInicio}
                onChange={(e) => setFechaInicio(e.target.value)}
                disabled={isDisabled}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="fecha-fin">Fecha fin</Label>
              <Input
                id="fecha-fin"
                type="date"
                value={fechaFin}
                onChange={(e) => setFechaFin(e.target.value)}
                disabled={isDisabled}
              />
            </div>
          </div>

          {/* Selects */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label>Tipo de descarga</Label>
              <Select
                value={tipoSolicitud}
                onValueChange={(v) => setTipoSolicitud(v as 'CFDI' | 'Metadata')}
                disabled={isDisabled}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="CFDI">Facturas completas (un par de horas)</SelectItem>
                  <SelectItem value="Metadata">Solo el listado (más rápido)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Facturas</Label>
              <Select
                value={tipoComprobante}
                onValueChange={(v) => setTipoComprobante(v as ComprobanteSeleccion)}
                disabled={isDisabled}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="E">Emitidas</SelectItem>
                  <SelectItem value="R">Recibidas</SelectItem>
                  <SelectItem value="A">Ambas</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Submit */}
          <Button
            ref={submitRef}
            type="submit"
            disabled={isDisabled}
            className="w-full sm:w-auto"
            onKeyDown={(e) => {
              if (e.repeat && e.key === 'Enter') e.preventDefault();
            }}
          >
            {isLoading ? (
              <>
                <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                Solicitando…
              </>
            ) : (
              <>
                <Icon icon="ph:download-simple-light" className="size-4" />
                Solicitar descarga
              </>
            )}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

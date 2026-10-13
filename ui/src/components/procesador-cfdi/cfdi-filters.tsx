'use client';

import { cn } from '@/lib/utils';
import { PanelFiltros } from '@/components/shared/panel-filtros';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { CfdiEstadoDiot, CfdiFiltros, CfdiTipo } from '@/lib/types';

interface Props {
  filtros: CfdiFiltros;
  setFiltro: <K extends keyof CfdiFiltros>(key: K, value: CfdiFiltros[K]) => void;
  reset: () => void;
  filtrosActivos: number;
  /** false = la empresa no presenta DIOT (p. ej. RESICO): sin filtro «Estado DIOT». */
  mostrarDiot?: boolean;
}

const TIPOS: { value: CfdiTipo | 'todos'; label: string }[] = [
  { value: 'todos', label: 'Todos' },
  { value: 'I', label: 'Ingreso' },
  { value: 'E', label: 'Egreso' },
  { value: 'P', label: 'Pago' },
  { value: 'N', label: 'Nómina' },
  { value: 'T', label: 'Traslado' },
];

const DIRECCIONES: { value: 'todos' | 'E' | 'R'; label: string }[] = [
  { value: 'todos', label: 'Ambos' },
  { value: 'R', label: 'Recibidos' },
  { value: 'E', label: 'Emitidos' },
];

const ESTADOS_DIOT: { value: CfdiEstadoDiot | 'todos'; label: string }[] = [
  { value: 'todos', label: 'Todos' },
  { value: 'pasa', label: 'Pasa a DIOT' },
  { value: 'excluido', label: 'Excluidos' },
  { value: 'noaplica', label: 'No aplica' },
];

/** Bloque de filtros con su etiqueta (Clasificación / Periodo / Importe). */
function FiltroGrupo({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2.5">
      <div className="text-xs font-semibold text-ghost">
        {label}
      </div>
      {children}
    </div>
  );
}

export function CfdiFiltersPanel({
  filtros,
  setFiltro,
  reset,
  filtrosActivos,
  mostrarDiot = true,
}: Props) {
  return (
    <PanelFiltros
      filtrosActivos={filtrosActivos}
      onLimpiar={reset}
      sinFiltros="Mostrando todas las facturas"
    >
      {/* Búsqueda (ancho completo) */}
      <div className="space-y-2">
        <Label htmlFor="busqueda">Búsqueda</Label>
        <Input
          id="busqueda"
          type="search"
          placeholder="UUID, RFC, nombre o folio…"
          value={filtros.busqueda ?? ''}
          onChange={(e) => setFiltro('busqueda', e.target.value || null)}
        />
      </div>

      <FiltroGrupo label="Clasificación">
        <div
          className={cn(
            'grid grid-cols-1 gap-3.5',
            mostrarDiot ? 'sm:grid-cols-3' : 'sm:grid-cols-2',
          )}
        >
          <div className="space-y-2">
            <Label>Tipo</Label>
            <Select
              value={filtros.tipo ?? 'todos'}
              onValueChange={(v) =>
                setFiltro('tipo', v === 'todos' ? null : (v as CfdiTipo))
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TIPOS.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label>Dirección</Label>
            <Select
              value={filtros.direccion ?? 'todos'}
              onValueChange={(v) =>
                setFiltro('direccion', v === 'todos' ? null : (v as 'E' | 'R'))
              }
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DIRECCIONES.map((d) => (
                  <SelectItem key={d.value} value={d.value}>
                    {d.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {mostrarDiot && (
            <div className="space-y-2">
              <Label>Estado DIOT</Label>
              <Select
                value={filtros.diot ?? 'todos'}
                onValueChange={(v) =>
                  setFiltro('diot', v === 'todos' ? null : (v as CfdiEstadoDiot))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {ESTADOS_DIOT.map((d) => (
                    <SelectItem key={d.value} value={d.value}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
      </FiltroGrupo>

      <FiltroGrupo label="Periodo">
        <div className="grid grid-cols-2 gap-3.5">
          <div className="space-y-2">
            <Label htmlFor="desde">Desde</Label>
            <Input
              id="desde"
              type="date"
              value={filtros.desde ?? ''}
              onChange={(e) => setFiltro('desde', e.target.value || null)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="hasta">Hasta</Label>
            <Input
              id="hasta"
              type="date"
              value={filtros.hasta ?? ''}
              onChange={(e) => setFiltro('hasta', e.target.value || null)}
            />
          </div>
        </div>
      </FiltroGrupo>

      <FiltroGrupo label="Importe">
        <div className="grid grid-cols-2 gap-3.5">
          <div className="space-y-2">
            <Label htmlFor="monto-min">Monto mínimo</Label>
            <Input
              id="monto-min"
              type="number"
              step="0.01"
              placeholder="0.00"
              value={filtros.monto_min ?? ''}
              onChange={(e) =>
                setFiltro('monto_min', e.target.value === '' ? null : Number(e.target.value))
              }
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="monto-max">Monto máximo</Label>
            <Input
              id="monto-max"
              type="number"
              step="0.01"
              placeholder="0.00"
              value={filtros.monto_max ?? ''}
              onChange={(e) =>
                setFiltro('monto_max', e.target.value === '' ? null : Number(e.target.value))
              }
            />
          </div>
        </div>
      </FiltroGrupo>

      {/* Advertencias */}
      <div className="flex items-center gap-2.5 pt-1">
        <Switch
          id="solo-errores"
          checked={filtros.solo_con_errores}
          onCheckedChange={(v) => setFiltro('solo_con_errores', v)}
        />
        <Label htmlFor="solo-errores" className="text-sm font-normal text-foreground/80">
          Mostrar solo las facturas con advertencias
        </Label>
      </div>
    </PanelFiltros>
  );
}

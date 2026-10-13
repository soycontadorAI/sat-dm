'use client';

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
import type { PagoStatus, PagosFiltros } from '@/lib/types';

interface Props {
  filtros: PagosFiltros;
  setFiltro: <K extends keyof PagosFiltros>(key: K, value: PagosFiltros[K]) => void;
  reset: () => void;
  filtrosActivos: number;
}

const STATUS_OPTIONS: { value: PagoStatus | 'todos'; label: string }[] = [
  { value: 'todos', label: 'Todos' },
  { value: 'sin_complemento', label: 'Sin complemento' },
  { value: 'pago_parcial', label: 'Pago parcial' },
  { value: 'pagado_completo', label: 'Pagado completo' },
  { value: 'sobrante', label: 'Sobrante' },
];

export function PagosFiltersPanel({ filtros, setFiltro, reset, filtrosActivos }: Props) {
  const statusValue: string = filtros.status?.[0] ?? 'todos';

  return (
    <PanelFiltros
      filtrosActivos={filtrosActivos}
      onLimpiar={reset}
      sinFiltros="Mostrando todas las facturas PPD"
    >
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
        <div className="space-y-2 lg:col-span-2">
          <Label htmlFor="busqueda">Búsqueda</Label>
          <Input
            id="busqueda"
            type="search"
            placeholder="UUID, RFC, nombre o folio…"
            value={filtros.busqueda ?? ''}
            onChange={(e) => setFiltro('busqueda', e.target.value || null)}
          />
        </div>

        <div className="space-y-2">
          <Label>Status</Label>
          <Select
            value={statusValue}
            onValueChange={(v) =>
              setFiltro('status', v === 'todos' ? null : [v as PagoStatus])
            }
          >
            <SelectTrigger className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

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
    </PanelFiltros>
  );
}

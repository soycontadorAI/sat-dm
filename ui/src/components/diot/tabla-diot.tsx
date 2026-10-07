'use client';

import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
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
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';
import { MontoInput, formatoEntero } from '@/components/diot/monto-input';
import type { CatalogosDiot, FilaDiot, HallazgoDiot } from '@/lib/types';

// Columnas de trabajo: los montos que el prellenado llena desde los CFDIs.
// El resto de los 54 campos se edita en el panel de detalle (drawer).
const COLUMNAS_MONTO = [
  { clave: 'valor_16', label: 'Valor 16%' },
  { clave: 'dev_16', label: 'Devoluciones' },
  { clave: 'acred_excl_16', label: 'IVA acreditable' },
  { clave: 'iva_retenido', label: 'IVA retenido' },
] as const;

interface Props {
  filas: FilaDiot[];
  catalogos: CatalogosDiot | null;
  errores: HallazgoDiot[];
  advertencias: HallazgoDiot[];
  activeIndex: number | null;
  onCampo: (index: number, campo: string, valor: string | number) => void;
  onEliminar: (index: number) => void;
  onAbrirDetalle: (index: number) => void;
}

/**
 * Tabla editable de renglones DIOT: una fila por proveedor con los montos de
 * trabajo inline; el chevron abre el panel de detalle con los 54 campos.
 */
export function TablaDiot({
  filas,
  catalogos,
  errores,
  advertencias,
  activeIndex,
  onCampo,
  onEliminar,
  onAbrirDetalle,
}: Props) {
  const porFila = (lista: HallazgoDiot[], i: number) => lista.filter((h) => h.fila === i);
  const camposInvalidos = (i: number) =>
    new Set(porFila(errores, i).map((e) => e.campo).filter(Boolean) as string[]);

  const totales = COLUMNAS_MONTO.map(({ clave }) =>
    filas.reduce((acc, f) => acc + Number(f[clave] ?? 0), 0),
  );

  const operacionesDe = (tercero: string): string[] =>
    catalogos?.operaciones_por_tercero[tercero] ?? [];

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-8" />
            <TableHead>RFC / Proveedor</TableHead>
            <TableHead>Tercero</TableHead>
            <TableHead>Operación</TableHead>
            {COLUMNAS_MONTO.map((c) => (
              <TableHead key={c.clave} className="text-right">
                {c.label}
              </TableHead>
            ))}
            <TableHead className="w-8" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {filas.map((fila, i) => {
            const invalidos = camposInvalidos(i);
            const conError = porFila(errores, i).length > 0;
            const avisos = porFila(advertencias, i);
            return (
              <TableRow
                key={i}
                className={cn(
                  conError && 'bg-destructive/5',
                  activeIndex === i && 'bg-blue-50 dark:bg-blue-950/40',
                )}
              >
                <TableCell className="pr-0">
                  <button
                    type="button"
                    onClick={() => onAbrirDetalle(i)}
                    aria-label={`Ver detalle del renglón ${i + 1}`}
                    className={cn(
                      'text-muted-foreground transition-colors hover:text-foreground',
                      activeIndex === i && 'text-foreground',
                    )}
                  >
                    <Icon icon="ph:caret-right-light" className="size-4" />
                  </button>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <div>
                      <Input
                        aria-label="RFC del proveedor"
                        placeholder={fila.tipo_tercero === '05' ? 'RFC (opcional)' : 'RFC'}
                        className={cn(
                          'h-8 w-40 font-mono uppercase',
                          invalidos.has('rfc') && 'border-destructive',
                        )}
                        value={fila.rfc}
                        onChange={(e) => onCampo(i, 'rfc', e.target.value.toUpperCase())}
                      />
                      {(fila.nombre || fila.num_cfdis) && (
                        <p className="mt-0.5 max-w-40 truncate text-xs text-muted-foreground">
                          {fila.nombre}
                          {fila.num_cfdis ? `, ${fila.num_cfdis} CFDIs` : ''}
                        </p>
                      )}
                    </div>
                    {(conError || avisos.length > 0 || fila.estimado) && (
                      <span
                        title={[
                          ...porFila(errores, i).map((e) => e.mensaje),
                          ...avisos.map((a) => a.mensaje),
                        ].join('\n')}
                        aria-label="Ver avisos del renglón"
                      >
                        <Icon
                          icon={conError ? 'ph:warning-circle-light' : 'ph:warning-light'}
                          className={cn('size-4', conError ? 'text-destructive' : 'text-amber-500')}
                        />
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell>
                  <Select
                    value={fila.tipo_tercero}
                    onValueChange={(v) => {
                      onCampo(i, 'tipo_tercero', v);
                      // La operación válida depende del tercero: resetea al default.
                      const ops = operacionesDe(v);
                      if (!ops.includes(fila.tipo_operacion)) {
                        onCampo(i, 'tipo_operacion', ops[ops.length - 1] ?? '');
                      }
                      if (v === '15') onCampo(i, 'rfc', 'XAXX010101000');
                    }}
                  >
                    <SelectTrigger className="h-8 w-32" aria-label="Tipo de tercero">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {Object.entries(catalogos?.tipo_tercero ?? {}).map(([clave, label]) => (
                        <SelectItem key={clave} value={clave}>
                          {clave} · {label.replace('Proveedor ', '')}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                <TableCell>
                  <Select
                    value={fila.tipo_operacion}
                    onValueChange={(v) => onCampo(i, 'tipo_operacion', v)}
                  >
                    <SelectTrigger
                      className={cn('h-8 w-44', invalidos.has('tipo_operacion') && 'border-destructive')}
                      aria-label="Tipo de operación"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {operacionesDe(fila.tipo_tercero).map((clave) => (
                        <SelectItem key={clave} value={clave}>
                          {clave} · {catalogos?.tipo_operacion[clave] ?? clave}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </TableCell>
                {COLUMNAS_MONTO.map(({ clave, label }) => (
                  <TableCell key={clave} className="text-right">
                    <MontoInput
                      ariaLabel={`${label} del renglón ${i + 1}`}
                      valor={fila[clave]}
                      invalido={invalidos.has(clave)}
                      onChange={(v) => onCampo(i, clave, v)}
                      className="w-28"
                    />
                  </TableCell>
                ))}
                <TableCell>
                  <button
                    type="button"
                    onClick={() => onEliminar(i)}
                    aria-label={`Eliminar renglón ${i + 1}`}
                    className="text-muted-foreground hover:text-destructive"
                  >
                    <Icon icon="ph:trash-light" className="size-4" />
                  </button>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
        {filas.length > 0 && (
          <TableFooter>
            <TableRow>
              <TableCell colSpan={4}>
                {filas.length} proveedor{filas.length === 1 ? '' : 'es'}
              </TableCell>
              {totales.map((t, i) => (
                <TableCell key={COLUMNAS_MONTO[i].clave} className="text-right tabular-nums">
                  {formatoEntero(t)}
                </TableCell>
              ))}
              <TableCell />
            </TableRow>
          </TableFooter>
        )}
      </Table>
    </div>
  );
}

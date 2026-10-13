'use client';

import { useMemo, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import type {
  CampoExport,
  CatalogoCamposExport,
  ColumnaPlantilla,
  NivelCampoExport,
} from '@/lib/types';

const PREFIJO_RUTA: Record<NivelCampoExport, string> = {
  cfdi: 'ruta:',
  concepto: 'ruta_concepto:',
};
const RUTA_RE = /^[A-Za-z_@#][\w@#-]*(\.[A-Za-z_@#][\w@#-]*)*$/;

interface Props {
  titulo: string;
  descripcion: string;
  nivel: NivelCampoExport;
  columnas: ColumnaPlantilla[];
  catalogo: CatalogoCamposExport;
  /** Sin `onChange` la lista es de solo lectura (plantillas del sistema). */
  onChange?: (columnas: ColumnaPlantilla[]) => void;
}

/** Nombre legible del campo de una columna (del catálogo o de una ruta del XML). */
export function nombreDeCampo(campo: string, porId: Map<string, CampoExport>): string {
  const c = porId.get(campo);
  if (c) return c.etiqueta;
  const ruta = campo.replace(/^ruta(_concepto)?:/, '');
  return `XML: ${ruta}`;
}

/**
 * Lista ordenada de columnas de una plantilla (una de las dos: las del CFDI
 * o el detalle por concepto) con su buscador de campos para agregar.
 */
export function ColumnasEditor({ titulo, descripcion, nivel, columnas, catalogo, onChange }: Props) {
  const soloLectura = !onChange;
  const [busqueda, setBusqueda] = useState('');
  const [ruta, setRuta] = useState('');

  const porId = useMemo(
    () => new Map(catalogo.campos.map((c) => [c.id, c] as const)),
    [catalogo],
  );
  const usados = useMemo(() => new Set(columnas.map((c) => c.campo)), [columnas]);

  const disponibles = useMemo(() => {
    const q = busqueda.trim().toLowerCase();
    return catalogo.grupos
      .map((grupo) => ({
        grupo,
        campos: catalogo.campos.filter(
          (c) =>
            c.grupo === grupo &&
            c.nivel === nivel &&
            !usados.has(c.id) &&
            (!q || c.etiqueta.toLowerCase().includes(q) || c.descripcion.toLowerCase().includes(q)),
        ),
      }))
      .filter((g) => g.campos.length > 0);
  }, [catalogo, nivel, usados, busqueda]);

  function cambiar(nuevas: ColumnaPlantilla[]) {
    onChange?.(nuevas);
  }

  function mover(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= columnas.length) return;
    const nuevas = [...columnas];
    [nuevas[i], nuevas[j]] = [nuevas[j], nuevas[i]];
    cambiar(nuevas);
  }

  const rutaLimpia = ruta.trim();
  const rutaValida = RUTA_RE.test(rutaLimpia);

  function agregarRuta() {
    if (!rutaValida) return;
    const campo = PREFIJO_RUTA[nivel] + rutaLimpia;
    if (usados.has(campo)) return;
    cambiar([...columnas, { campo, encabezado: rutaLimpia.split('.').pop() ?? rutaLimpia }]);
    setRuta('');
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">{titulo}</h2>
        <p className="text-xs text-muted-foreground">{descripcion}</p>
      </div>

      <div className={soloLectura ? '' : 'grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]'}>
        {/* Columnas del reporte, en orden */}
        <div className="space-y-1.5">
          {columnas.length === 0 && (
            <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
              Sin columnas. Agrégalas desde la lista de campos.
            </p>
          )}
          <ol className="space-y-1.5">
            {columnas.map((col, i) => (
              <li
                key={`${col.campo}-${i}`}
                className="flex items-center gap-2 rounded-md border bg-card px-2 py-1.5"
              >
                <span className="w-6 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {i + 1}
                </span>
                {soloLectura ? (
                  <span className="min-w-0 flex-1 truncate text-sm">{col.encabezado}</span>
                ) : (
                  <Input
                    value={col.encabezado}
                    aria-label={`${titulo}: encabezado de la columna ${i + 1}`}
                    onChange={(e) => {
                      const nuevas = [...columnas];
                      nuevas[i] = { ...col, encabezado: e.target.value };
                      cambiar(nuevas);
                    }}
                    className="h-8 min-w-0 flex-1"
                  />
                )}
                {/* Ancho fijo para que los encabezados queden alineados; el
                    nombre del campo solo aparece si el encabezado ya es otro. */}
                <span
                  className="hidden w-40 shrink-0 truncate text-right text-xs text-muted-foreground sm:block"
                  title={porId.get(col.campo)?.descripcion || col.campo}
                >
                  {nombreDeCampo(col.campo, porId) !== col.encabezado &&
                    nombreDeCampo(col.campo, porId)}
                </span>
                {!soloLectura && (
                  <div className="flex shrink-0 items-center">
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      aria-label="Subir"
                      disabled={i === 0}
                      onClick={() => mover(i, -1)}
                    >
                      <Icon icon="ph:arrow-up-light" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      aria-label="Bajar"
                      disabled={i === columnas.length - 1}
                      onClick={() => mover(i, 1)}
                    >
                      <Icon icon="ph:arrow-down-light" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon-xs"
                      aria-label="Quitar"
                      onClick={() => cambiar(columnas.filter((_, n) => n !== i))}
                    >
                      <Icon icon="ph:x-light" />
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ol>
        </div>

        {/* Campos para agregar */}
        {!soloLectura && (
          <div className="space-y-3 rounded-md border bg-muted/30 p-3">
            <div className="relative">
              <Icon
                icon="ph:magnifying-glass-light"
                className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
              />
              <Input
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                placeholder="Buscar campo"
                className="h-8 pl-8"
              />
            </div>
            <div className="max-h-80 space-y-3 overflow-y-auto pr-1">
              {disponibles.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  {busqueda ? 'Ningún campo coincide.' : 'Ya agregaste todos los campos.'}
                </p>
              )}
              {disponibles.map(({ grupo, campos }) => (
                <div key={grupo} className="space-y-1">
                  <p className="text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                    {grupo}
                  </p>
                  {campos.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      title={c.descripcion || undefined}
                      onClick={() => cambiar([...columnas, { campo: c.id, encabezado: c.etiqueta }])}
                      className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-sm hover:bg-muted"
                    >
                      <Icon icon="ph:plus-light" className="size-3.5 shrink-0 text-muted-foreground" />
                      <span className="truncate">{c.etiqueta}</span>
                    </button>
                  ))}
                </div>
              ))}
            </div>
            <div className="space-y-1.5 border-t pt-3">
              <p className="text-xs text-muted-foreground">
                Cualquier dato del XML, por su ruta
                {nivel === 'concepto' ? ' dentro del concepto' : ''}.
              </p>
              <div className="flex gap-2">
                <Input
                  value={ruta}
                  onChange={(e) => setRuta(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && agregarRuta()}
                  placeholder={
                    nivel === 'concepto'
                      ? 'InformacionAduanera.NumeroPedimento'
                      : 'Comprobante.Complemento.CartaPorte.Version'
                  }
                  className="h-8 min-w-0 flex-1 font-mono text-xs"
                />
                <Button size="sm" variant="outline" disabled={!rutaValida} onClick={agregarRuta}>
                  Agregar
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

'use client';

import { useRef, useState } from 'react';

import { Icon } from '@/components/ui/icon';
import { PREFIJO_TEXTO, type SegmentoCatalogo } from '@/lib/constants';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Helpers compartidos por los builders del organizador (estructura y nombre).
// Un "segmento" es un token del catálogo o un literal "txt:Texto".
// ---------------------------------------------------------------------------

export function esTexto(seg: string): boolean {
  return seg.startsWith(PREFIJO_TEXTO);
}

/** Entrada de catálogo que describe a un segmento (los txt: mapean a `custom`). */
export function catalogoDe(
  seg: string,
  catalogo: SegmentoCatalogo[],
): SegmentoCatalogo | undefined {
  if (esTexto(seg)) return catalogo.find((c) => c.custom);
  return catalogo.find((c) => c.value === seg);
}

/**
 * Valor de ejemplo que un segmento aporta a la vista previa. El RFC de la
 * empresa y el del emisor se personalizan con la empresa activa (el ejemplo
 * típico es un CFDI emitido por ella); el receptor queda genérico.
 */
export function valorSegmento(
  seg: string,
  catalogo: SegmentoCatalogo[],
  rfcEmpresa?: string,
): string {
  if (esTexto(seg)) return seg.slice(PREFIJO_TEXTO.length) || 'Texto';
  if ((seg === 'rfc' || seg === 'rfc_emisor') && rfcEmpresa) return rfcEmpresa;
  return catalogoDe(seg, catalogo)?.ejemplo ?? seg;
}

/** Caracteres que no pueden ir en nombres de carpeta/archivo (Windows). */
function sanearTexto(v: string): string {
  return v.replace(/[<>:"/\\|?*]/g, '');
}

// ---------------------------------------------------------------------------
// Reordenamiento por arrastre (HTML5 nativo, sin libs)
// ---------------------------------------------------------------------------

function useDndReorder(items: string[], onChange: (items: string[]) => void) {
  const desde = useRef<number | null>(null);
  const [sobre, setSobre] = useState<number | null>(null);
  const [arrastrando, setArrastrando] = useState<number | null>(null);

  const props = (i: number) => ({
    draggable: true,
    onDragStart: (e: React.DragEvent) => {
      desde.current = i;
      setArrastrando(i);
      e.dataTransfer.effectAllowed = 'move';
    },
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
      setSobre((prev) => (prev === i ? prev : i));
    },
    onDragLeave: () => setSobre((prev) => (prev === i ? null : prev)),
    onDragEnd: () => {
      desde.current = null;
      setSobre(null);
      setArrastrando(null);
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      const f = desde.current;
      desde.current = null;
      setSobre(null);
      setArrastrando(null);
      if (f == null || f === i) return;
      const copia = [...items];
      const [movido] = copia.splice(f, 1);
      copia.splice(i, 0, movido);
      onChange(copia);
    },
  });

  return { props, sobre, arrastrando };
}

// ---------------------------------------------------------------------------
// Builder genérico: filas arrastrables + paleta de chips + vista previa
// ---------------------------------------------------------------------------

interface PartesBuilderProps {
  /** Segmentos en orden (tokens del catálogo o "txt:Texto"). */
  items: string[];
  onChange: (items: string[]) => void;
  catalogo: SegmentoCatalogo[];
  titulo: string;
  /** Texto del contador, p. ej. "3 niveles · de afuera hacia adentro". */
  contador: (n: number) => string;
  hint: string;
  paletaLabel: string;
  /** Icono de las filas y los ejemplos ("ph:folder-light" / "ph:file-text-light"). */
  iconoFila: string;
  vacioTexto: string;
  /** Controles extra entre el hint y la lista (p. ej. selector de separador). */
  extras?: React.ReactNode;
  /** Vista previa renderizada al final del bloque. */
  preview: React.ReactNode;
  /** RFC de la empresa activa; personaliza los ejemplos de RFC. */
  rfcEmpresa?: string;
}

export function PartesBuilder({
  items,
  onChange,
  catalogo,
  titulo,
  contador,
  hint,
  paletaLabel,
  iconoFila,
  vacioTexto,
  extras,
  preview,
  rfcEmpresa,
}: PartesBuilderProps) {
  const { props, sobre, arrastrando } = useDndReorder(items, onChange);
  const usados = new Set(items.filter((s) => !esTexto(s)));

  function agregar(entrada: SegmentoCatalogo) {
    onChange([
      ...items,
      entrada.custom ? `${PREFIJO_TEXTO}${entrada.ejemplo}` : entrada.value,
    ]);
  }

  function quitar(idx: number) {
    onChange(items.filter((_, i) => i !== idx));
  }

  function cambiarTexto(idx: number, v: string) {
    onChange(
      items.map((s, i) => (i === idx ? `${PREFIJO_TEXTO}${sanearTexto(v)}` : s)),
    );
  }

  return (
    <div className="space-y-3 rounded-xl border bg-secondary p-4">
      <div>
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-[13.5px] font-bold">{titulo}</span>
          <span className="text-[11.5px] tabular-nums text-muted-foreground">
            {contador(items.length)}
          </span>
        </div>
        <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
          {hint}
        </p>
      </div>

      {extras}

      {items.length === 0 ? (
        <div className="flex flex-col items-center gap-1.5 rounded-lg border-[1.5px] border-dashed bg-card px-4 py-5 text-center">
          <Icon icon={iconoFila} className="size-6 text-muted-foreground/50" />
          <span className="text-xs text-muted-foreground">{vacioTexto}</span>
        </div>
      ) : (
        <div className="space-y-1.5">
          {items.map((seg, idx) => {
            const entrada = catalogoDe(seg, catalogo);
            return (
              <div
                key={idx}
                {...props(idx)}
                className={cn(
                  'flex items-center gap-2.5 rounded-lg border bg-card px-2.5 py-2 transition-[border-color,box-shadow,opacity]',
                  arrastrando === idx && 'opacity-35',
                  sobre === idx && 'border-primary ring-[3px] ring-accent',
                )}
              >
                <span className="flex cursor-grab p-0.5 text-muted-foreground/50 active:cursor-grabbing">
                  <Icon icon="ph:dots-six-vertical-light" className="size-4" />
                </span>
                <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-secondary text-[11px] font-bold tabular-nums text-muted-foreground">
                  {idx + 1}
                </span>
                <Icon icon={iconoFila} className="size-4 shrink-0 text-primary" />
                <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">
                  {entrada?.label ?? seg}
                </span>
                {esTexto(seg) ? (
                  <input
                    value={seg.slice(PREFIJO_TEXTO.length)}
                    onChange={(e) => cambiarTexto(idx, e.target.value)}
                    placeholder="Escribe…"
                    draggable
                    onDragStart={(e) => e.preventDefault()}
                    className="w-32 rounded-md border border-input bg-card px-2 py-1 font-mono text-[11.5px] focus:border-primary focus:outline-none focus:ring-[3px] focus:ring-accent"
                  />
                ) : (
                  <span className="whitespace-nowrap rounded-md bg-secondary px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
                    {valorSegmento(seg, catalogo, rfcEmpresa)}
                  </span>
                )}
                <button
                  type="button"
                  onClick={() => quitar(idx)}
                  title="Quitar"
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/60 transition-colors hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-950/40 dark:hover:text-red-400"
                >
                  <Icon icon="ph:trash-light" className="size-4" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div>
        <div className="mb-2 text-xs font-semibold text-ghost">
          {paletaLabel}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {catalogo.map((entrada) => {
            const deshabilitado = !entrada.custom && usados.has(entrada.value);
            return (
              <button
                key={entrada.value}
                type="button"
                disabled={deshabilitado}
                onClick={() => agregar(entrada)}
                title={deshabilitado ? 'Ya está en la lista' : undefined}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-lg border bg-card px-2.5 py-1.5 text-xs font-semibold text-foreground/80 transition-colors',
                  deshabilitado
                    ? 'cursor-default bg-secondary text-muted-foreground opacity-60'
                    : 'hover:border-primary hover:bg-accent hover:text-primary',
                )}
              >
                <Icon
                  icon={entrada.custom ? 'ph:clipboard-text-light' : iconoFila}
                  className="size-3.5"
                />
                {entrada.label}
                <Icon
                  icon={deshabilitado ? 'ph:check-light' : 'ph:plus-light'}
                  className={cn('size-3', deshabilitado ? 'text-green-600' : 'opacity-60')}
                />
              </button>
            );
          })}
        </div>
      </div>

      {preview}
    </div>
  );
}

/** Etiqueta "Vista previa" + contenido, estilo compartido de ambos builders. */
export function VistaPrevia({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold text-ghost">
        Vista previa
      </div>
      {children}
    </div>
  );
}

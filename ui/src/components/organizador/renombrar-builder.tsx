'use client';

import {
  PartesBuilder,
  VistaPrevia,
  valorSegmento,
} from '@/components/organizador/builder-partes';
import { Icon } from '@/components/ui/icon';
import { PARTES_NOMBRE, SEPARADORES_NOMBRE } from '@/lib/constants';
import { cn } from '@/lib/utils';

interface RenombrarBuilderProps {
  /** Partes en orden, de izquierda a derecha (tokens o "txt:Texto"). */
  partes: string[];
  onChange: (partes: string[]) => void;
  separador: string;
  onSeparadorChange: (separador: string) => void;
  /** RFC de la empresa activa; personaliza los ejemplos de RFC emisor. */
  rfcEmpresa?: string;
}

/**
 * Builder del nombre de archivo personalizado: partes del CFDI reordenables
 * por arrastre, selector de separador y vista previa del nombre resultante.
 */
export function RenombrarBuilder({
  partes,
  onChange,
  separador,
  onSeparadorChange,
  rfcEmpresa,
}: RenombrarBuilderProps) {
  return (
    <PartesBuilder
      items={partes}
      onChange={onChange}
      catalogo={PARTES_NOMBRE}
      rfcEmpresa={rfcEmpresa}
      titulo="Partes del nombre"
      contador={(n) => `${n} ${n === 1 ? 'parte' : 'partes'} · de izquierda a derecha`}
      hint="Toca una parte para agregarla. Arrastra las filas para reordenar."
      paletaLabel="Agrega partes"
      iconoFila="ph:file-text-light"
      vacioTexto="Aún no hay partes. Agrega una abajo."
      extras={
        <div className="flex items-center gap-2.5">
          <span className="text-xs font-semibold text-ghost">
            Separador
          </span>
          <div className="inline-flex overflow-hidden rounded-lg border bg-card">
            {SEPARADORES_NOMBRE.map((s) => (
              <button
                key={s.label}
                type="button"
                onClick={() => onSeparadorChange(s.value)}
                className={cn(
                  'min-w-8 border-r px-2 py-1 font-mono text-xs transition-colors last:border-r-0',
                  separador === s.value
                    ? 'bg-accent font-bold text-primary'
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      }
      preview={
        <VistaPrevia>
          <NombrePreview
            partes={partes}
            separador={separador}
            rfcEmpresa={rfcEmpresa}
          />
        </VistaPrevia>
      }
    />
  );
}

interface NombrePreviewProps {
  partes: string[];
  separador: string;
  rfcEmpresa?: string;
}

function NombrePreview({ partes, separador, rfcEmpresa }: NombrePreviewProps) {
  if (partes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed bg-card px-3 py-2.5 text-xs text-muted-foreground/70">
        Agrega al menos una parte para ver el nombre resultante.
      </div>
    );
  }
  const nombre = partes
    .map((p) => valorSegmento(p, PARTES_NOMBRE, rfcEmpresa))
    .join(separador);
  return <NombreArchivo nombre={nombre} />;
}

/** Nombre de archivo de ejemplo en mono, con la extensión .xml atenuada. */
export function NombreArchivo({ nombre }: { nombre: string }) {
  return (
    <div className="flex items-center gap-1.5 break-all rounded-lg border bg-card px-3 py-2.5 font-mono text-xs">
      <Icon icon="ph:file-text-light" className="size-3.5 shrink-0 text-primary" />
      <span>
        {nombre}
        <span className="text-muted-foreground">.xml</span>
      </span>
    </div>
  );
}

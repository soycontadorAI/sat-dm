import { Icon } from '@/components/ui/icon';
import type { DesglosePaso } from '@/lib/types';

const formateadorNumero = new Intl.NumberFormat('es-MX', {
  maximumFractionDigits: 4,
});

/** Números en es-MX (hasta 4 decimales); strings/fechas tal cual. */
function formatearValor(valor: unknown): string {
  if (typeof valor === 'number') return formateadorNumero.format(valor);
  if (valor == null) return '–';
  return String(valor);
}

/**
 * Render del `desglose.pasos` que generan las calculadoras del backend:
 * lista numerada con descripción, fórmula, valores clave→valor y el
 * resultado del paso. Colapsable con `<details>` nativo (convención del repo).
 */
export function DesglosePasos({
  pasos,
  titulo = 'Desglose del cálculo',
}: {
  pasos: DesglosePaso[];
  titulo?: string;
}) {
  if (!pasos || pasos.length === 0) return null;
  return (
    <details className="group rounded-xl border bg-card shadow-sm">
      <summary className="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
        <Icon
          icon="ph:caret-right-light"
          className="size-4 transition-transform group-open:rotate-90"
        />
        {titulo}
      </summary>
      <ol className="space-y-4 border-t px-4 py-4">
        {pasos.map((paso) => (
          <li key={paso.numero} className="flex gap-3">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-semibold">
              {paso.numero}
            </span>
            <div className="min-w-0 flex-1 space-y-1">
              <p className="text-sm font-bold tracking-tight">{paso.descripcion}</p>
              <p className="text-xs text-muted-foreground">{paso.formula}</p>
              {Object.keys(paso.valores).length > 0 && (
                <dl className="flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                  {Object.entries(paso.valores).map(([clave, valor]) => (
                    <div key={clave} className="flex gap-1">
                      <dt className="font-medium text-foreground/80">{clave}:</dt>
                      <dd className="tabular-nums">{formatearValor(valor)}</dd>
                    </div>
                  ))}
                </dl>
              )}
              <p className="pt-0.5 font-mono text-base font-bold tracking-tight tabular-nums">
                = {formatearValor(paso.resultado)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </details>
  );
}

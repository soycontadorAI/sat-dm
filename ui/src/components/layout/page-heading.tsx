'use client';

import { Fragment, type ReactNode } from 'react';

import { useEspaciosShell } from '@/components/layout/espacios-shell';
import { Icon } from '@/components/ui/icon';

interface PageHeadingProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

/**
 * Encabezado de pantalla. Con la navegación por espacios lleva arriba dónde
 * vive la pantalla ("SAT", "Revisar > Comprobantes"), como en el prototipo:
 * la pantalla no cambia por dentro, solo se sabe en qué espacio estás.
 */
export function PageHeading({ title, description, action }: PageHeadingProps) {
  const shell = useEspaciosShell();
  const u = shell?.destinoActivo ?? null;
  const migas = u?.espacio ? [u.espacio.label, u.padre?.label].filter(Boolean) : [];

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-1">
        {migas.length > 0 && (
          <p className="flex items-center gap-1 pb-0.5 text-[12.5px] font-medium text-ghost">
            {migas.map((m, i) => (
              <Fragment key={m}>
                {i > 0 && <Icon icon="ph:caret-right-light" className="size-3" />}
                <span>{m}</span>
              </Fragment>
            ))}
          </p>
        )}
        <h1 className="text-2xl font-extrabold tracking-tight">{title}</h1>
        {description && (
          <p className="text-muted-foreground">{description}</p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

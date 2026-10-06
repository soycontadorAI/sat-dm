'use client';

import { useEffect, useState } from 'react';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';
import { ESPACIOS, normalizarRuta } from '@/lib/navegacion';
import { esMac, formatearAtajo } from '@/lib/atajos';
import { AccountMenu } from '@/components/layout/account-menu';
import { BrandMark } from '@/components/layout/brand-mark';
import { useEspaciosShell } from '@/components/layout/espacios-shell';
import { Icon } from '@/components/ui/icon';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

function BotonRiel({
  icon,
  label,
  activo,
  tip,
  onClick,
}: {
  icon: string;
  label: string;
  activo: boolean;
  tip: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          aria-current={activo ? 'page' : undefined}
          className={cn(
            'relative flex w-17 flex-col items-center gap-1 rounded-lg pb-1.5 pt-2.25 text-[10.5px] font-semibold tracking-[-0.005em] transition-colors duration-[120ms]',
            activo
              ? 'bg-muted text-foreground'
              : 'text-muted-foreground hover:bg-muted/70 hover:text-foreground',
            // Marca del espacio activo, pegada al borde del riel (tinta).
            activo &&
              'before:absolute before:-left-1.5 before:top-1/2 before:h-6 before:w-[3px] before:-translate-y-1/2 before:rounded-r before:bg-foreground before:content-[""]',
          )}
        >
          <Icon icon={icon} className="size-5.5" />
          <span className="max-w-full truncate px-0.5">{label}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="right">{tip}</TooltipContent>
    </Tooltip>
  );
}

/**
 * Riel de espacios: los 5 espacios con su nombre visible (⌘1..⌘5), y abajo
 * Ayuda y tu cuenta. Nunca crece: lo nuevo entra al panel del espacio.
 */
export function RailEspacios() {
  const shell = useEspaciosShell();
  const pathname = usePathname() ?? '/';
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(esMac());
  }, []);

  if (!shell) return null;
  const enAyuda = normalizarRuta(pathname) === '/ayuda';

  return (
    <nav
      aria-label="Espacios"
      className="hidden w-[78px] shrink-0 flex-col items-center gap-1 border-r bg-card pb-2.5 pt-3 md:flex"
    >
      <div className="pb-2">
        <BrandMark iconOnly size={32} />
      </div>
      {ESPACIOS.map((e, i) => {
        const activo = !enAyuda && shell.espacioActivo === e.id;
        const tip = activo
          ? `${shell.panelAbierto ? 'Ocultar' : 'Mostrar'} el panel (${formatearAtajo({ tecla: 'B' }, mac)})`
          : `${e.label} (${formatearAtajo({ tecla: String(i + 1) }, mac)})`;
        return (
          <BotonRiel
            key={e.id}
            icon={e.icon}
            label={e.label}
            activo={activo}
            tip={tip}
            onClick={() => shell.irAEspacio(e.id, 'riel')}
          />
        );
      })}
      <div className="flex-1" />
      <BotonRiel
        icon="ph:question-light"
        label="Ayuda"
        activo={enAyuda}
        tip={`Ayuda (${formatearAtajo({ tecla: 'F1', mod: false }, mac)})`}
        onClick={() => shell.navegar('/ayuda', 'riel')}
      />
      <div className="pt-1.5">
        <AccountMenu collapsed variant="rail" />
      </div>
    </nav>
  );
}

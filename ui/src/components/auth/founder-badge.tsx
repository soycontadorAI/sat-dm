'use client';

import { useAuth } from '@/providers/auth-provider';
import { Badge } from '@/components/ui/badge';
import { Icon } from '@/components/ui/icon';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/**
 * Badge "Fundador" del titlebar. Solo visible si `is_founder=true`. Al pasar
 * el cursor muestra una tarjeta de agradecimiento (los Fundadores son un grupo
 * cerrado de 30 personas — el tooltip refuerza la exclusividad).
 */
export function FounderBadge() {
  const { license } = useAuth();
  if (!license?.is_founder) return null;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Badge
          variant="chip"
          className="gap-1"
          tabIndex={0}
        >
          <Icon icon="ph:crown-simple-fill" className="size-3" />
          Fundador
        </Badge>
      </TooltipTrigger>
      {/* Momento celebratorio → tarjeta navy (bg-foreground del primitive). */}
      <TooltipContent side="bottom" align="end" className="w-67 rounded-xl p-3.5 text-left">
        <span className="flex items-center gap-1.5 text-[13.5px] font-extrabold tracking-tight">
          <Icon icon="ph:crown-simple-fill" className="size-3.5" />
          Miembro Fundador
        </span>
        <span className="mt-1.5 block text-xs leading-relaxed text-background/80">
          Eres parte importante de este proyecto. Gracias por confiar y
          construir esto con nosotros desde el inicio.
        </span>
        <span className="mt-2 block border-t border-background/20 pt-1.5 text-[11px] font-semibold text-background/70">
          Uno de los primeros 30, con acceso de por vida
        </span>
      </TooltipContent>
    </Tooltip>
  );
}

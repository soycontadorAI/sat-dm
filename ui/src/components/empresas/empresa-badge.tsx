import { cn } from '@/lib/utils';
import { tipoPersona } from '@/lib/empresa-visual';

/**
 * Cuadro PF/PM de la empresa (Señal: sin colores de identidad). Como el Libro
 * Mayor del logo: la persona moral es el bloque sólido en tinta y la persona
 * física el bloque delineado.
 */
export function EmpresaBadge({
  rfc,
  size = 'md',
}: {
  rfc: string;
  size?: 'xs' | 'sm' | 'md';
}) {
  const tipo = tipoPersona(rfc);
  return (
    <span
      className={cn(
        'flex shrink-0 items-center justify-center font-mono font-bold tracking-normal',
        size === 'md' && 'size-8 rounded-md text-[11px]',
        size === 'sm' && 'size-6.5 rounded text-[10px]',
        size === 'xs' && 'size-5 rounded-[4px] text-[8.5px]',
        tipo === 'PM'
          ? 'bg-foreground text-background'
          : 'border-[1.5px] border-foreground bg-card text-foreground',
      )}
      aria-label={tipo === 'PM' ? 'Persona moral' : 'Persona física'}
    >
      {tipo}
    </span>
  );
}

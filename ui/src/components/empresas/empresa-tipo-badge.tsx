import { tipoPersona } from '@/lib/empresa-visual';

/** Chip "Moral"/"Física" derivado del RFC (12 = PM, 13 = PF), neutro en Señal. */
export function EmpresaTipoBadge({ rfc }: { rfc: string }) {
  const tipo = tipoPersona(rfc);
  return (
    <span className="inline-flex rounded-full border border-border bg-card px-2 py-0.5 text-[11px] font-semibold text-foreground">
      {tipo === 'PM' ? 'Moral' : 'Física'}
    </span>
  );
}

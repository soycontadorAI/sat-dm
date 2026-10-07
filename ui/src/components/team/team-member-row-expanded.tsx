'use client';

import { format } from 'date-fns';
import { es } from 'date-fns/locale';

import { Icon } from '@/components/ui/icon';
import type { TeamMember, TeamEmpresa } from '@/lib/api-client';

interface TeamMemberRowExpandedProps {
  member: TeamMember;
  empresas: TeamEmpresa[];
}

export function TeamMemberRowExpanded({ member, empresas }: TeamMemberRowExpandedProps) {
  const accessEmpresas = empresas.filter((e) => member.empresa_ids.includes(e.id));

  return (
    <div className="grid gap-4 text-sm sm:grid-cols-2">
      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-ghost">
          Historial
        </h4>
        <dl className="space-y-1">
          <Row
            label="Invitado"
            value={format(new Date(member.invited_at), 'dd MMM yyyy HH:mm', { locale: es })}
          />
          {member.accepted_at && (
            <Row
              label="Aceptó"
              value={format(new Date(member.accepted_at), 'dd MMM yyyy HH:mm', { locale: es })}
            />
          )}
        </dl>
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-ghost">
          Acceso a empresas
        </h4>
        {member.role === 'admin' ? (
          <p className="text-xs text-muted-foreground">Admin: acceso total al equipo.</p>
        ) : member.access_mode === 'all' ? (
          <p className="text-xs text-muted-foreground">Todas las empresas del equipo.</p>
        ) : accessEmpresas.length === 0 ? (
          <p className="text-xs text-muted-foreground">Sin empresas asignadas.</p>
        ) : (
          <ul className="space-y-1">
            {accessEmpresas.map((e) => (
              <li key={e.id} className="flex items-center gap-2 text-xs">
                <Icon icon="ph:buildings-light" className="size-3 shrink-0 text-muted-foreground" />
                <span className="font-mono font-medium">{e.rfc}</span>
                {e.nombre && (
                  <span className="truncate text-muted-foreground">· {e.nombre}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 text-xs">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{value}</dd>
    </div>
  );
}

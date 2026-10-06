'use client';

// Ruta ESTÁTICA `/ajustes/equipo` — gestión del equipo (despachos/empresarial).
//
// No usa `[param]` ni `useSearchParams` → emite su propio `ajustes/equipo/index.html`
// bajo `output: 'export'` (ver ui/CLAUDE.md). Datos vía el agente (proxy Bearer a
// `/api/desktop/teams/*`); el allow-list por empresa usa las empresas del equipo
// desde Supabase (`getTeamEmpresas`), NO el catálogo local del agente (que va por RFC
// y no conoce el `id` de la empresa del equipo). Funciona en Desktop y Web.

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Icon } from '@/components/ui/icon';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { StatusBadge } from '@/components/shared/status-badge';
import { ResourceList, type ResourceListColumn } from '@/components/shared/resource-list';
import { ResourceActions, type ResourceAction } from '@/components/shared/resource-actions';
import { EmptyState } from '@/components/shared/empty-state';
import { TeamMemberRowExpanded } from '@/components/team/team-member-row-expanded';
import { ApiError } from '@/lib/api-client';
import type {
  TeamResponse,
  TeamMember,
  TeamEmpresa,
  TeamAccessMode,
} from '@/lib/api-client';

function mensajeError(e: unknown, fallback: string): string {
  return e instanceof ApiError ? e.detail : fallback;
}

export default function AjustesEquipoPage() {
  const { apiClient } = useServer();
  const [data, setData] = useState<TeamResponse | null>(null);
  const [empresas, setEmpresas] = useState<TeamEmpresa[]>([]);
  const [loading, setLoading] = useState(true);

  const [inviteEmail, setInviteEmail] = useState('');
  const [inviting, setInviting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [memberToRemove, setMemberToRemove] = useState<{ id: string; email: string } | null>(null);
  const [removing, setRemoving] = useState(false);

  const [permissionsMember, setPermissionsMember] = useState<TeamMember | null>(null);
  const [permissionsMode, setPermissionsMode] = useState<TeamAccessMode>('all');
  const [permissionsEmpresaIds, setPermissionsEmpresaIds] = useState<Set<string>>(new Set());
  const [permissionsSaving, setPermissionsSaving] = useState(false);
  const [permissionsError, setPermissionsError] = useState<string | null>(null);

  const fetchTeam = useCallback(async () => {
    try {
      const [team, emp] = await Promise.all([
        apiClient.getTeam(),
        apiClient.getTeamEmpresas().catch(() => ({ empresas: [] })),
      ]);
      setData(team);
      setEmpresas(emp.empresas);
    } catch {
      // No romper la pantalla: se queda en "cargando/sin equipo".
    } finally {
      setLoading(false);
    }
  }, [apiClient]);

  useEffect(() => {
    void fetchTeam();
  }, [fetchTeam]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    const email = inviteEmail.trim();
    if (!email) return;

    setInviting(true);
    setError(null);
    setSuccess(null);
    try {
      const r = await apiClient.inviteTeamMember(email);
      setSuccess(
        r.autoActivated
          ? `${email} agregado al equipo con acceso premium.`
          : `Invitación enviada a ${email}. Se activará cuando inicie sesión.`,
      );
      setInviteEmail('');
      void fetchTeam();
    } catch (e) {
      setError(mensajeError(e, 'No se pudo invitar al miembro.'));
    } finally {
      setInviting(false);
    }
  };

  const openPermissionsDialog = (member: TeamMember) => {
    setPermissionsMember(member);
    setPermissionsMode(member.access_mode);
    setPermissionsEmpresaIds(new Set(member.empresa_ids));
    setPermissionsError(null);
  };

  const closePermissionsDialog = () => {
    setPermissionsMember(null);
    setPermissionsError(null);
  };

  const togglePermissionsEmpresa = (empresaId: string) => {
    setPermissionsEmpresaIds((prev) => {
      const next = new Set(prev);
      if (next.has(empresaId)) next.delete(empresaId);
      else next.add(empresaId);
      return next;
    });
  };

  const handleSavePermissions = async () => {
    if (!permissionsMember) return;
    setPermissionsSaving(true);
    setPermissionsError(null);
    try {
      await apiClient.setTeamMemberPermissions(
        permissionsMember.id,
        permissionsMode,
        permissionsMode === 'restricted' ? Array.from(permissionsEmpresaIds) : [],
      );
      closePermissionsDialog();
      void fetchTeam();
    } catch (e) {
      setPermissionsError(mensajeError(e, 'No se pudieron guardar los permisos.'));
    } finally {
      setPermissionsSaving(false);
    }
  };

  const handleRemoveConfirm = async () => {
    if (!memberToRemove) return;
    setRemoving(true);
    try {
      await apiClient.removeTeamMember(memberToRemove.id);
      void fetchTeam();
    } catch (e) {
      toast.error(mensajeError(e, 'No se pudo remover al miembro.'));
    } finally {
      setRemoving(false);
      setMemberToRemove(null);
    }
  };

  const backLink = (
    <Link
      href="/ajustes"
      className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
    >
      <Icon icon="ph:arrow-left-light" className="size-4" /> Preferencias
    </Link>
  );

  if (loading) {
    return (
      <div className="max-w-4xl space-y-6">
        {backLink}
        <PageHeading title="Equipo" description="Gestiona los miembros de tu equipo" />
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
          Cargando equipo…
        </div>
      </div>
    );
  }

  const canManageTeam = data?.isAdmin === true;
  const activeMembers = data?.members.filter((m) => m.status !== 'removed') ?? [];
  const maxMembers = data?.team?.max_members ?? 5;
  const empresasActivas = empresas.filter((e) => !e.archived_at);

  if (!data?.team) {
    return (
      <div className="max-w-4xl space-y-6">
        {backLink}
        <PageHeading title="Equipo" description="Gestiona los miembros de tu equipo" />
        <EmptyState
          icon="ph:users-light"
          title="Sin equipo"
          description="El equipo se crea automáticamente al suscribirte al plan Despachos o Empresarial."
        />
      </div>
    );
  }

  const buildActions = (member: TeamMember): ResourceAction[] => {
    if (!canManageTeam || member.role === 'admin') return [];
    const actions: ResourceAction[] = [];

    if (member.status === 'active') {
      actions.push({
        icon: 'ph:gear-light',
        label:
          member.access_mode === 'restricted'
            ? `Acceso restringido a ${member.empresa_ids.length} empresas`
            : 'Acceso a todas las empresas',
        onClick: () => openPermissionsDialog(member),
        iconOnly: true,
      });
    }

    actions.push({
      icon: 'ph:trash-light',
      label: 'Remover',
      onClick: () => setMemberToRemove({ id: member.id, email: member.email }),
      destructive: true,
      iconOnly: true,
    });

    return actions;
  };

  const columns: ResourceListColumn<TeamMember>[] = [
    {
      key: 'email',
      header: 'Miembro',
      render: (m) => (
        <div className="flex min-w-0 items-center gap-2">
          {m.role === 'admin' ? (
            <Icon icon="ph:shield-light" className="size-4 shrink-0 text-primary" />
          ) : (
            <Icon icon="ph:envelope-light" className="size-4 shrink-0 text-muted-foreground" />
          )}
          <span className="block truncate font-medium">{m.email}</span>
        </div>
      ),
    },
    {
      key: 'role',
      header: 'Rol',
      width: 'w-28',
      render: (m) =>
        m.role === 'admin' ? (
          <StatusBadge tone="info" size="sm">Admin</StatusBadge>
        ) : (
          <StatusBadge tone="neutral" size="sm">Miembro</StatusBadge>
        ),
    },
    {
      key: 'status',
      header: 'Estado',
      width: 'w-32',
      render: (m) =>
        m.status === 'active' ? (
          <StatusBadge tone="success" icon="ph:check-circle-light" size="sm">Activo</StatusBadge>
        ) : m.status === 'pending' ? (
          <StatusBadge tone="warning" icon="ph:clock-light" size="sm">Pendiente</StatusBadge>
        ) : (
          <StatusBadge tone="neutral" size="sm">Removido</StatusBadge>
        ),
    },
    {
      key: 'acceso',
      header: 'Acceso',
      width: 'w-40',
      hideOnMobile: true,
      render: (m) => (
        <span className="text-xs text-muted-foreground">
          {m.role === 'admin'
            ? 'Total (admin)'
            : m.access_mode === 'restricted'
              ? `${m.empresa_ids.length} empresa${m.empresa_ids.length === 1 ? '' : 's'}`
              : 'Todas las empresas'}
        </span>
      ),
    },
  ];

  return (
    <div className="max-w-4xl space-y-6">
      {backLink}
      <PageHeading
        title={data.team.name ? `Equipo: ${data.team.name}` : 'Equipo'}
        description="Gestiona los miembros de tu equipo"
      />

      <div className="space-y-6">
        {/* Miembros */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <Icon icon="ph:users-light" className="size-5" />
              Miembros
            </h2>
            <Badge variant="outline">
              {activeMembers.length} de {maxMembers}
            </Badge>
          </div>

          {activeMembers.length === 0 ? (
            <EmptyState
              icon="ph:users-light"
              title="Sin miembros"
              description="Aún no hay miembros en el equipo. Usa el formulario de abajo para invitar al primero."
            />
          ) : (
            <ResourceList
              items={activeMembers}
              getKey={(m) => m.id}
              columns={columns}
              actionsHeader={canManageTeam ? 'Acciones' : undefined}
              actions={canManageTeam ? (m) => <ResourceActions actions={buildActions(m)} /> : undefined}
              expandable={{
                render: (m) => <TeamMemberRowExpanded member={m} empresas={empresas} />,
              }}
            />
          )}
        </section>

        {/* Invitar */}
        {canManageTeam && activeMembers.length < maxMembers && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Icon icon="ph:user-plus-light" className="size-5" />
                Invitar miembro
              </CardTitle>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleInvite} className="flex gap-3">
                <Input
                  type="email"
                  placeholder="email@ejemplo.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  required
                  className="flex-1"
                />
                <Button type="submit" disabled={inviting}>
                  {inviting ? 'Agregando…' : 'Agregar'}
                </Button>
              </form>
              {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
              {success && <p className="mt-3 text-sm text-success">{success}</p>}
            </CardContent>
          </Card>
        )}

        {canManageTeam && activeMembers.length >= maxMembers && (
          <p className="text-center text-sm text-muted-foreground">
            Has alcanzado el límite de {maxMembers} miembros. Contacta a soporte para aumentar tu
            capacidad.
          </p>
        )}
      </div>

      {/* Diálogo de permisos */}
      <Dialog
        open={!!permissionsMember}
        onOpenChange={(open) => {
          if (!open) closePermissionsDialog();
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Permisos de acceso</DialogTitle>
            <DialogDescription>{permissionsMember?.email}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <RadioGroup
              value={permissionsMode}
              onValueChange={(v) => setPermissionsMode(v as TeamAccessMode)}
            >
              <div className="flex items-start gap-2">
                <RadioGroupItem value="all" id="perm-mode-all" className="mt-1" />
                <Label htmlFor="perm-mode-all" className="flex-1 cursor-pointer">
                  <div className="font-medium">Acceso a todas las empresas</div>
                  <div className="text-xs text-muted-foreground">
                    Puede ver y operar todas las empresas del equipo, incluidas las que se
                    agreguen en el futuro.
                  </div>
                </Label>
              </div>
              <div className="flex items-start gap-2">
                <RadioGroupItem value="restricted" id="perm-mode-restricted" className="mt-1" />
                <Label htmlFor="perm-mode-restricted" className="flex-1 cursor-pointer">
                  <div className="font-medium">Acceso restringido</div>
                  <div className="text-xs text-muted-foreground">
                    Selecciona específicamente a qué empresas tiene acceso.
                  </div>
                </Label>
              </div>
            </RadioGroup>

            {permissionsMode === 'restricted' && (
              <div className="rounded-md border">
                {empresasActivas.length === 0 ? (
                  <p className="p-4 text-center text-sm text-muted-foreground">
                    No hay empresas activas en el equipo.
                  </p>
                ) : (
                  <ScrollArea className="h-64 p-3">
                    <div className="space-y-2">
                      {empresasActivas.map((empresa) => (
                        <label
                          key={empresa.id}
                          className="flex cursor-pointer items-start gap-3 rounded p-2 hover:bg-muted"
                        >
                          <Checkbox
                            checked={permissionsEmpresaIds.has(empresa.id)}
                            onCheckedChange={() => togglePermissionsEmpresa(empresa.id)}
                            className="mt-0.5"
                          />
                          <div className="min-w-0 flex-1">
                            <p className="font-mono text-sm font-medium">{empresa.rfc}</p>
                            {empresa.nombre && (
                              <p className="truncate text-xs text-muted-foreground">
                                {empresa.nombre}
                              </p>
                            )}
                          </div>
                        </label>
                      ))}
                    </div>
                  </ScrollArea>
                )}
                <div className="border-t px-3 py-2 text-xs text-muted-foreground">
                  {permissionsEmpresaIds.size} de {empresasActivas.length} empresas seleccionadas
                </div>
              </div>
            )}

            {permissionsError && <p className="text-sm text-destructive">{permissionsError}</p>}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={closePermissionsDialog} disabled={permissionsSaving}>
              Cancelar
            </Button>
            <Button onClick={handleSavePermissions} disabled={permissionsSaving}>
              {permissionsSaving ? (
                <>
                  <Icon icon="ph:circle-notch-light" className="mr-2 size-4 animate-spin" />
                  Guardando…
                </>
              ) : (
                'Guardar permisos'
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Confirmación de remover */}
      <Dialog
        open={!!memberToRemove}
        onOpenChange={(open) => {
          if (!open) setMemberToRemove(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Icon icon="ph:warning-light" className="size-5 text-destructive" />
              Remover miembro
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <p className="text-sm">
              ¿Remover a <strong>{memberToRemove?.email}</strong> del equipo?
            </p>
            <p className="text-sm text-muted-foreground">
              Perderá acceso premium inmediatamente y será degradado al plan gratuito.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setMemberToRemove(null)} disabled={removing}>
              Cancelar
            </Button>
            <Button variant="destructive" onClick={handleRemoveConfirm} disabled={removing}>
              {removing ? 'Removiendo…' : 'Remover'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

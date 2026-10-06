'use client';

import { Suspense, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';

import { useEmpresas } from '@/hooks/use-empresas';
import { usePlanesV3, usePlanLicencia } from '@/providers/auth-provider';
import { PageHeading } from '@/components/layout/page-heading';
import { EmpresaAddDialog } from '@/components/empresas/empresa-add-dialog';
import { TopeEmpresasBarra, TopeEmpresasDialog } from '@/components/planes/tope-empresas';
import { EmpresaStatusGroup } from '@/components/empresas/empresa-status-group';
import { EmpresaRowExpanded } from '@/components/empresas/empresa-row-expanded';
import { EmpresaTipoBadge } from '@/components/empresas/empresa-tipo-badge';
import { EmpresasStats } from '@/components/empresas/empresas-stats';
import { EmpresasToolbar } from '@/components/empresas/empresas-toolbar';
import {
  ResourceList,
  type ResourceListColumn,
} from '@/components/shared/resource-list';
import { Icon } from '@/components/ui/icon';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import {
  filtrarEmpresas,
  ordenarEmpresas,
  type FiltroEstado,
  type FiltroTipo,
  type OrdenEmpresas,
} from '@/lib/empresas-filtro';
import type { Empresa } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';
import { topeEmpresasDeError, type TopeEmpresas } from '@/lib/api-client';
import { estadoTope, topeLleno } from '@/lib/planes-v3';

type Confirmacion = 'archive' | 'unarchive' | 'delete';
type Vista = 'activas' | 'archivadas';

// `useSearchParams` (lo usa EmpresasContenido para el alta por ⌘N) requiere
// un <Suspense> envolvente bajo export estático — misma convención que
// /empresas/detalle.
export default function EmpresasPage() {
  return (
    <Suspense fallback={null}>
      <EmpresasContenido />
    </Suspense>
  );
}

function EmpresasContenido() {
  const {
    empresas,
    loading,
    error,
    refresh,
    addFiel,
    addCiec,
    remove,
    seleccionar,
    archive,
    unarchive,
  } = useEmpresas();
  const [addOpen, setAddOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [accionError, setAccionError] = useState<string | null>(null);
  // Diálogo del tope de empresas (Archivar / Cambiar de plan); null = cerrado.
  const [topeDialog, setTopeDialog] = useState<TopeEmpresas | null>(null);
  const planesV3 = usePlanesV3();
  const planLicencia = usePlanLicencia();

  // Vista + filtros de la lista (todo client-side).
  const [vista, setVista] = useState<Vista>('activas');
  const [q, setQ] = useState('');
  const [tipo, setTipo] = useState<FiltroTipo>('todas');
  const [estadoFiltro, setEstadoFiltro] = useState<FiltroEstado>('todos');
  const [orden, setOrden] = useState<OrdenEmpresas>('nombre');

  const router = useRouter();
  const searchParams = useSearchParams();

  const activas = empresas.filter((e) => !e.archived_at);
  const archivadas = empresas.filter((e) => !!e.archived_at);
  const activeRfc = activas.find((e) => e.default)?.rfc ?? null;

  // Tope del plan (planes v3): contador, aviso al 80% y diálogo al 100%. Con
  // el interruptor apagado o sin datos del plan es null y nada cambia.
  const tope = estadoTope(planLicencia, activas.length, planesV3);

  // Alta: con el plan lleno se abre el diálogo del tope en vez del modal.
  function abrirAlta() {
    if (tope && topeLleno(tope)) setTopeDialog(tope);
    else setAddOpen(true);
  }

  // ⌘N (GlobalShortcuts) y "Agregar empresa…" del palette llegan como
  // /empresas?alta=1: abre el alta y limpia el query para que back/reload
  // no lo re-dispare.
  useEffect(() => {
    if (searchParams.get('alta') === '1') {
      abrirAlta();
      router.replace('/empresas');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, router]);

  async function withBusy(rfc: string, fn: () => Promise<void>) {
    setBusy(rfc);
    setAccionError(null);
    try {
      await fn();
    } catch (e) {
      // 402 del agente (tope del plan): diálogo de Archivar / Cambiar de plan.
      const t = topeEmpresasDeError(e);
      if (t) setTopeDialog(t);
      else setAccionError(mensajeDeError(e));
    } finally {
      setBusy(null);
    }
  }

  function desarchivar(rfc: string) {
    if (tope && topeLleno(tope)) {
      setTopeDialog(tope);
      return;
    }
    void withBusy(rfc, () => unarchive(rfc));
  }

  function cambiarVista(v: Vista) {
    setVista(v);
    setTipo('todas');
  }

  const enVista = vista === 'activas' ? activas : archivadas;
  const filtradas = useMemo(
    () =>
      ordenarEmpresas(
        filtrarEmpresas(enVista, { q, tipo, estado: vista === 'activas' ? estadoFiltro : 'todos' }),
        orden,
      ),
    [enVista, q, tipo, estadoFiltro, orden, vista],
  );

  const columnas: ResourceListColumn<Empresa>[] = [
    {
      key: 'rfc',
      header: 'RFC',
      width: 'w-40',
      render: (e) => (
        <span className="font-mono text-xs font-medium">{e.rfc}</span>
      ),
    },
    {
      key: 'nombre',
      header: 'Nombre',
      hideOnMobile: true,
      render: (e) => (
        <span className="truncate text-sm text-muted-foreground">{e.nombre}</span>
      ),
    },
    {
      key: 'tipo',
      header: 'Tipo',
      width: 'w-20',
      hideOnMobile: true,
      render: (e) => <EmpresaTipoBadge rfc={e.rfc} />,
    },
    ...(vista === 'activas'
      ? [
          {
            key: 'estado',
            header: 'Estado',
            width: 'w-40',
            render: (e) => <EmpresaStatusGroup empresa={e} />,
          } satisfies ResourceListColumn<Empresa>,
        ]
      : []),
  ];

  return (
    <div className="space-y-5">
      <PageHeading
        title="Empresas"
        description="Gestiona las empresas y sus RFCs"
        action={
          <Button onClick={abrirAlta}>
            <Icon icon="ph:plus-light" className="size-4" /> Agregar empresa
          </Button>
        }
      />

      {tope && <TopeEmpresasBarra tope={tope} />}

      {(error || accionError) && (
        <Alert variant="destructive">
          <AlertDescription>{accionError || error}</AlertDescription>
        </Alert>
      )}

      {loading && empresas.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" /> Cargando empresas…
        </div>
      ) : empresas.length === 0 ? (
        <EmptyState onAdd={abrirAlta} />
      ) : (
        <>
          {/* Vista: activas / archivadas */}
          <div className="flex gap-1 border-b border-border">
            <VistaTab
              on={vista === 'activas'}
              onClick={() => cambiarVista('activas')}
              icon="ph:buildings-light"
              label="Activas"
              count={activas.length}
            />
            <VistaTab
              on={vista === 'archivadas'}
              onClick={() => cambiarVista('archivadas')}
              icon="ph:archive-light"
              label="Archivadas"
              count={archivadas.length}
            />
          </div>

          {vista === 'activas' ? (
            <EmpresasStats empresas={activas} />
          ) : (
            <Alert>
              <Icon icon="ph:archive-light" className="size-4" />
              <AlertDescription>
                No aparecen en descargas ni en el resto de la app. Guardamos su
                información{' '}
                <span className="font-semibold text-foreground">por si regresan</span> y
                puedes restaurarlas cuando quieras.
              </AlertDescription>
            </Alert>
          )}

          <EmpresasToolbar
            empresas={enVista}
            q={q}
            onQ={setQ}
            tipo={tipo}
            onTipo={setTipo}
            estado={estadoFiltro}
            onEstado={setEstadoFiltro}
            orden={orden}
            onOrden={setOrden}
            conEstado={vista === 'activas'}
          />

          {filtradas.length === 0 ? (
            <EmptyFiltro vista={vista} q={q} />
          ) : (
            <ResourceList
              items={filtradas}
              getKey={(e) => e.rfc}
              activeId={vista === 'activas' ? activeRfc : undefined}
              dimmed={vista === 'archivadas'}
              onRowClick={
                vista === 'activas'
                  ? (e) => withBusy(e.rfc, () => seleccionar(e.rfc, e.metodos))
                  : undefined
              }
              columns={columnas}
              actionsHeader="Acciones"
              actions={(e) => (
                <EmpresaRowActions
                  empresa={e}
                  archived={vista === 'archivadas'}
                  busy={busy === e.rfc}
                  onArchive={() => withBusy(e.rfc, () => archive(e.rfc))}
                  onUnarchive={() => desarchivar(e.rfc)}
                  onDelete={() => withBusy(e.rfc, () => remove(e.rfc))}
                />
              )}
              expandable={{
                render: (e) => (
                  <EmpresaRowExpanded empresa={e} onJobDone={refresh} />
                ),
              }}
            />
          )}
        </>
      )}

      <div className="flex items-center gap-2.5 rounded-lg border bg-card px-4 py-3.5 text-[13px] text-muted-foreground">
        <Icon icon="ph:key-light" className="size-4.5 shrink-0" />
        <span>
          e.firma y Contraseña del SAT se guardan{' '}
          <span className="font-semibold text-foreground">
            protegidas y solo en este equipo
          </span>
          . Nunca se muestran a la vista ni se envían a internet.
        </span>
      </div>

      <EmpresaAddDialog
        open={addOpen}
        onOpenChange={setAddOpen}
        addFiel={addFiel}
        addCiec={addCiec}
        onTope={setTopeDialog}
      />

      <TopeEmpresasDialog
        tope={topeDialog}
        onOpenChange={(o) => !o && setTopeDialog(null)}
        activas={activas}
        onArchivar={archive}
      />
    </div>
  );
}

function VistaTab({
  on,
  onClick,
  icon,
  label,
  count,
}: {
  on: boolean;
  onClick: () => void;
  icon: string;
  label: string;
  count: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        '-mb-px inline-flex items-center gap-1.5 border-b-2 px-1.5 py-2 text-[13px] font-semibold transition-colors',
        on
          ? 'border-primary text-primary'
          : 'border-transparent text-muted-foreground hover:text-foreground',
      )}
    >
      <Icon icon={icon} className="size-3.75" />
      {label}
      <span
        className={cn(
          'rounded-full px-1.5 text-[11px] font-bold tabular-nums',
          on ? 'bg-accent text-primary' : 'bg-secondary text-muted-foreground',
        )}
      >
        {count}
      </span>
    </button>
  );
}

function EmptyFiltro({ vista, q }: { vista: Vista; q: string }) {
  const sinArchivadas = vista === 'archivadas' && !q;
  return (
    <div className="flex flex-col items-center gap-2.5 rounded-lg border border-border bg-card px-5 py-12 text-center text-muted-foreground">
      <Icon
        icon={sinArchivadas ? 'ph:archive-light' : 'ph:magnifying-glass-light'}
        className="size-6.5 opacity-40"
      />
      <p className="text-[13.5px]">
        {sinArchivadas
          ? 'No tienes empresas archivadas.'
          : q ? `Ninguna empresa coincide con "${q}".` : 'Ninguna empresa coincide con los filtros.'}
      </p>
    </div>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-border bg-card p-10 text-center">
      <Icon icon="ph:buildings-light" className="size-8 text-muted-foreground" />
      <div className="space-y-1">
        <p className="font-medium">Aún no tienes empresas</p>
        <p className="text-sm text-muted-foreground">
          Registra tu primera empresa (e.firma o Contraseña del SAT) para empezar a descargar.
        </p>
      </div>
      <Button onClick={onAdd}>
        <Icon icon="ph:plus-light" className="size-4" /> Agregar empresa
      </Button>
    </div>
  );
}

interface EmpresaRowActionsProps {
  empresa: Empresa;
  archived: boolean;
  busy: boolean;
  onArchive?: () => void;
  onUnarchive?: () => void;
  onDelete: () => void;
}

function EmpresaRowActions({
  empresa,
  archived,
  busy,
  onArchive,
  onUnarchive,
  onDelete,
}: EmpresaRowActionsProps) {
  const [confirm, setConfirm] = useState<Confirmacion | null>(null);

  function ejecutar() {
    if (confirm === 'archive') onArchive?.();
    else if (confirm === 'unarchive') onUnarchive?.();
    else if (confirm === 'delete') onDelete();
    setConfirm(null);
  }

  return (
    <div className="inline-flex items-center gap-1">
      {!archived ? (
        <>
          {/* Expediente fiscal: pantalla en camino — deshabilitado a propósito. */}
          <span title="Expediente fiscal (próximamente)">
            <Button variant="ghost" size="icon" disabled aria-label="Expediente fiscal (próximamente)">
              <Icon icon="ph:folder-light" className="size-4" />
            </Button>
          </span>
          <Button
            asChild
            variant="ghost"
            size="icon"
            title="Configurar empresa"
          >
            <Link href={`/empresas/detalle?rfc=${encodeURIComponent(empresa.rfc)}`}>
              <Icon icon="ph:gear-light" className="size-4" />
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            disabled={busy}
            onClick={() => setConfirm('archive')}
            title="Archivar"
          >
            <Icon icon="ph:archive-light" className="size-4" />
          </Button>
        </>
      ) : (
        <Button
          variant="ghost"
          size="icon"
          disabled={busy}
          onClick={() => setConfirm('unarchive')}
          title="Restaurar (desarchivar)"
        >
          <Icon
            icon="ph:archive-tray-light"
            className={cn('size-4 text-blue-500')}
          />
        </Button>
      )}
      <Button
        variant="ghost"
        size="icon"
        disabled={busy}
        onClick={() => setConfirm('delete')}
        title={archived ? 'Eliminar definitivamente' : 'Eliminar'}
      >
        <Icon icon="ph:trash-light" className="size-4" />
      </Button>

      <Dialog
        open={confirm !== null}
        onOpenChange={(o) => !o && setConfirm(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirm === 'delete'
                ? 'Eliminar empresa'
                : confirm === 'archive'
                  ? 'Archivar empresa'
                  : 'Desarchivar empresa'}
            </DialogTitle>
            <DialogDescription>
              {confirm === 'delete'
                ? `Esto borrará "${empresa.nombre}" del catálogo junto con sus accesos guardados en este equipo. Los archivos descargados no se borran.`
                : confirm === 'archive'
                  ? `"${empresa.nombre}" se ocultará de la lista principal. Podrás desarchivarla cuando la necesites.`
                  : `"${empresa.nombre}" volverá a la lista principal.`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              Cancelar
            </Button>
            <Button
              variant={confirm === 'delete' ? 'destructive' : 'default'}
              onClick={ejecutar}
            >
              {confirm === 'delete'
                ? 'Eliminar'
                : confirm === 'archive'
                  ? 'Archivar'
                  : 'Desarchivar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

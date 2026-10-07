'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';

import { PageHeading } from '@/components/layout/page-heading';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { EditarTareaDrawer } from '@/components/tareas/editar-tarea-drawer';
import { NuevaTareaDialog } from '@/components/tareas/nueva-tarea-dialog';
import { SugerenciasTareas } from '@/components/tareas/sugerencias-tareas';
import { TableroTareas } from '@/components/tareas/tablero-tareas';
import { TareaRow } from '@/components/tareas/tarea-row';
import { useEmpresas } from '@/hooks/use-empresas';
import { useTareas } from '@/hooks/use-tareas';
import { mensajeDeError } from '@/lib/errores';
import {
  derivarSugerencias,
  diasDesdeHoy,
  nombreCortoEmpresa,
} from '@/lib/tareas';
import type { Empresa, Tarea } from '@/lib/types';
import { cn } from '@/lib/utils';

type Vista = 'lista' | 'tablero';
type Agrupar = 'fecha' | 'empresa';

const FILTRO_TODAS = 'todas';
const FILTRO_GENERAL = 'general';

interface Grupo {
  key: string;
  label: string;
  dotClass?: string;
  items: Tarea[];
}

function ordenarPorVencimiento(items: Tarea[]): Tarea[] {
  return [...items].sort(
    (a, b) =>
      (a.fecha ? diasDesdeHoy(a.fecha) : Infinity) -
      (b.fecha ? diasDesdeHoy(b.fecha) : Infinity),
  );
}

function agruparPorFecha(pendientes: Tarea[]): Grupo[] {
  const buckets: Record<string, Tarea[]> = {
    vencidas: [],
    hoy: [],
    semana: [],
    adelante: [],
    sinFecha: [],
  };
  for (const t of pendientes) {
    if (!t.fecha) {
      buckets.sinFecha.push(t);
      continue;
    }
    const dias = diasDesdeHoy(t.fecha);
    if (dias < 0) buckets.vencidas.push(t);
    else if (dias === 0) buckets.hoy.push(t);
    else if (dias <= 7) buckets.semana.push(t);
    else buckets.adelante.push(t);
  }
  return [
    { key: 'vencidas', label: 'Vencidas', dotClass: 'bg-destructive', items: ordenarPorVencimiento(buckets.vencidas) },
    { key: 'hoy', label: 'Hoy', dotClass: 'bg-warning', items: buckets.hoy },
    { key: 'semana', label: 'Esta semana', dotClass: 'bg-primary', items: ordenarPorVencimiento(buckets.semana) },
    { key: 'adelante', label: 'Más adelante', items: ordenarPorVencimiento(buckets.adelante) },
    { key: 'sinFecha', label: 'Sin fecha', items: buckets.sinFecha },
  ].filter((g) => g.items.length > 0);
}

function agruparPorEmpresa(pendientes: Tarea[], empresas: Empresa[]): Grupo[] {
  const porClave = new Map<string, Tarea[]>();
  for (const t of pendientes) {
    const clave = t.rfc ?? FILTRO_GENERAL;
    const lista = porClave.get(clave) ?? [];
    lista.push(t);
    porClave.set(clave, lista);
  }
  return [...porClave.entries()]
    .map(([clave, items]) => {
      const empresa = empresas.find((e) => e.rfc === clave);
      return {
        key: clave,
        label: empresa
          ? nombreCortoEmpresa(empresa.nombre)
          : 'Sin empresa (generales)',
        items: ordenarPorVencimiento(items),
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label, 'es'));
}

export default function TareasPage() {
  const { empresas } = useEmpresas();
  const {
    tareas,
    descartadas,
    loading,
    error,
    crear,
    actualizar,
    eliminar,
    toggleHecha,
    aceptarSugerencia,
    descartarSugerencia,
  } = useTareas();

  const [vista, setVista] = useState<Vista>('lista');
  const [agrupar, setAgrupar] = useState<Agrupar>('fecha');
  const [busqueda, setBusqueda] = useState('');
  const [filtroEmpresa, setFiltroEmpresa] = useState(FILTRO_TODAS);
  const [rapida, setRapida] = useState('');
  const [nuevaAbierta, setNuevaAbierta] = useState(false);
  const [editando, setEditando] = useState<Tarea | null>(null);

  const sugerencias = useMemo(
    () => derivarSugerencias(empresas, tareas, descartadas),
    [empresas, tareas, descartadas],
  );

  const filtradas = useMemo(() => {
    const termino = busqueda.trim().toLowerCase();
    return tareas.filter((t) => {
      if (filtroEmpresa === FILTRO_GENERAL && t.rfc) return false;
      if (
        filtroEmpresa !== FILTRO_TODAS &&
        filtroEmpresa !== FILTRO_GENERAL &&
        t.rfc !== filtroEmpresa
      ) {
        return false;
      }
      if (termino) {
        const empresa = t.rfc ? empresas.find((e) => e.rfc === t.rfc) : null;
        const texto = `${t.titulo} ${empresa?.nombre ?? ''}`.toLowerCase();
        if (!texto.includes(termino)) return false;
      }
      return true;
    });
  }, [tareas, busqueda, filtroEmpresa, empresas]);

  const pendientes = filtradas.filter((t) => t.estado !== 'hecho');
  const hechas = filtradas.filter((t) => t.estado === 'hecho');
  const abiertas = tareas.filter((t) => t.estado !== 'hecho').length;

  const grupos =
    agrupar === 'fecha'
      ? agruparPorFecha(pendientes)
      : agruparPorEmpresa(pendientes, empresas);

  // Empresas que aparecen en alguna tarea (para el filtro).
  const empresasUsadas = useMemo(() => {
    const rfcs = new Set(tareas.map((t) => t.rfc).filter(Boolean) as string[]);
    return empresas
      .filter((e) => rfcs.has(e.rfc))
      .sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'));
  }, [tareas, empresas]);

  async function crearRapida(e: React.FormEvent) {
    e.preventDefault();
    const titulo = rapida.trim();
    if (!titulo) return;
    try {
      await crear({
        titulo,
        rfc:
          filtroEmpresa !== FILTRO_TODAS && filtroEmpresa !== FILTRO_GENERAL
            ? filtroEmpresa
            : null,
      });
      setRapida('');
    } catch (err) {
      toast.error(mensajeDeError(err));
    }
  }

  return (
    <div className="space-y-5">
      <PageHeading
        title="Tareas"
        description="Tu centro de mando: pendientes fiscales, recordatorios y lo que tengas en mente, con o sin empresa."
        action={
          <Button onClick={() => setNuevaAbierta(true)}>
            <Icon icon="ph:plus-light" className="size-4" />
            Nueva tarea
          </Button>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <SugerenciasTareas
        sugerencias={sugerencias}
        onAceptar={aceptarSugerencia}
        onDescartar={descartarSugerencia}
      />

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="flex h-9 min-w-[200px] flex-1 basis-56 items-center gap-2 rounded-lg border border-input bg-card px-2.5 text-muted-foreground transition-colors focus-within:border-ring">
          <Icon icon="ph:magnifying-glass-light" className="size-4 shrink-0" />
          <input
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            placeholder="Buscar tareas…"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-foreground outline-none placeholder:text-muted-foreground/70"
          />
        </div>

        <Select value={filtroEmpresa} onValueChange={setFiltroEmpresa}>
          <SelectTrigger className="h-9 w-auto min-w-[170px] text-[12.5px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={FILTRO_TODAS}>Todas las empresas</SelectItem>
            <SelectItem value={FILTRO_GENERAL}>Sin empresa (generales)</SelectItem>
            {empresasUsadas.map((e) => (
              <SelectItem key={e.rfc} value={e.rfc}>
                {nombreCortoEmpresa(e.nombre)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {vista === 'lista' && (
          <div className="inline-flex gap-0.5 rounded-lg bg-secondary p-[3px]">
            <SegBtn on={agrupar === 'fecha'} onClick={() => setAgrupar('fecha')}>
              Por fecha
            </SegBtn>
            <SegBtn on={agrupar === 'empresa'} onClick={() => setAgrupar('empresa')}>
              Por empresa
            </SegBtn>
          </div>
        )}

        <div className="ml-auto inline-flex gap-0.5 rounded-lg bg-secondary p-[3px]">
          <SegBtn on={vista === 'lista'} onClick={() => setVista('lista')}>
            <Icon icon="ph:list-numbers-light" className="size-3.5" />
            Lista
          </SegBtn>
          <SegBtn on={vista === 'tablero'} onClick={() => setVista('tablero')}>
            <Icon icon="ph:squares-four-light" className="size-3.5" />
            Tablero
          </SegBtn>
        </div>
      </div>

      {loading && tareas.length === 0 ? (
        <div className="h-40 animate-pulse rounded-xl bg-secondary/60" />
      ) : filtradas.length === 0 ? (
        <div className="py-10 text-center">
          <div className="mx-auto mb-3 flex size-12 items-center justify-center rounded-full bg-success/10 text-success">
            <Icon icon="ph:check-circle-light" className="size-6" />
          </div>
          <div className="text-[15px] font-bold">
            {tareas.length === 0 ? 'Todo al día' : 'Nada por aquí'}
          </div>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {tareas.length === 0
              ? 'No tienes tareas todavía. Crea la primera o acepta una sugerencia.'
              : 'No hay tareas que coincidan con tu búsqueda o filtro.'}
          </p>
        </div>
      ) : vista === 'lista' ? (
        <div className="space-y-5">
          <form
            onSubmit={crearRapida}
            className="flex h-11 items-center gap-2.5 rounded-xl border border-dashed border-input bg-card px-4 transition-colors focus-within:border-solid focus-within:border-primary"
          >
            <span className="flex size-[21px] shrink-0 items-center justify-center rounded-full border-[1.8px] border-dashed border-muted-foreground/50 text-muted-foreground/50">
              <Icon icon="ph:plus-light" className="size-3" />
            </span>
            <input
              value={rapida}
              onChange={(e) => setRapida(e.target.value)}
              placeholder="Agregar una tarea rápida y presiona Enter…"
              className="min-w-0 flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-muted-foreground/60"
            />
          </form>

          {grupos.map((g) => (
            <div key={g.key}>
              <div className="mb-2 flex items-center gap-2">
                {g.dotClass && <span className={cn('size-2 rounded-full', g.dotClass)} />}
                <span className="text-[13px] font-bold">{g.label}</span>
                <span className="font-mono text-[11px] font-bold text-muted-foreground/70">
                  {g.items.length}
                </span>
              </div>
              <div className="flex flex-col gap-2">
                {g.items.map((t) => (
                  <TareaRow
                    key={t.id}
                    tarea={t}
                    empresas={empresas}
                    onToggle={toggleHecha}
                    onEdit={setEditando}
                  />
                ))}
              </div>
            </div>
          ))}

          {hechas.length > 0 && (
            <div>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[13px] font-bold text-muted-foreground">
                  Completadas
                </span>
                <span className="font-mono text-[11px] font-bold text-muted-foreground/70">
                  {hechas.length}
                </span>
              </div>
              <div className="flex flex-col gap-2">
                {hechas.map((t) => (
                  <TareaRow
                    key={t.id}
                    tarea={t}
                    empresas={empresas}
                    onToggle={toggleHecha}
                    onEdit={setEditando}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        <TableroTareas tareas={filtradas} empresas={empresas} onEdit={setEditando} />
      )}

      <div className="flex items-center gap-2 text-[12.5px] text-muted-foreground/70">
        <Icon icon="ph:user-light" className="size-3.5" />
        {abiertas} {abiertas === 1 ? 'tarea abierta asignada' : 'tareas abiertas asignadas'} a ti.
      </div>

      <NuevaTareaDialog
        open={nuevaAbierta}
        onClose={() => setNuevaAbierta(false)}
        empresas={empresas}
        onCrear={crear}
      />
      <EditarTareaDrawer
        tarea={editando}
        empresas={empresas}
        onClose={() => setEditando(null)}
        onGuardar={actualizar}
        onEliminar={eliminar}
      />
    </div>
  );
}

function SegBtn({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12.5px] font-semibold transition-colors',
        on ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground',
      )}
    >
      {children}
    </button>
  );
}

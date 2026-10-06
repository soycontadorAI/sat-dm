'use client';

import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { esMac, formatearAtajo } from '@/lib/atajos';
import {
  ESPACIOS,
  destinoPorId,
  todosLosDestinos,
  type DestinoUbicado,
} from '@/lib/navegacion';
import {
  MESES,
  ejemplos,
  interpretar,
  mesAnterior,
  nombreCorto,
  normalizar,
  type CanalOrden,
  type EmpresaOrden,
  type Orden,
} from '@/lib/ordenes';
import { ponerPrefill } from '@/lib/prefill';
import { esWeb } from '@/lib/modo';
import { mensajeDeError } from '@/lib/errores';
import { abrirODescargar } from '@/lib/descargas';
import { agregarBreadcrumb } from '@/lib/telemetria';
import { registrarReciente } from '@/hooks/use-recientes';
import { useEmpresas } from '@/hooks/use-empresas';
import { useServer } from '@/providers/server-provider';
import type { Empresa } from '@/lib/types';
import { useEspaciosShell } from '@/components/layout/espacios-shell';
import { EtiquetaDestino } from '@/components/layout/panel-espacio';
import type { VistaPalette } from '@/components/layout/command-palette';
import { EmpresaBadge } from '@/components/empresas/empresa-badge';
import { Icon } from '@/components/ui/icon';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Command as CommandPrimitive } from 'cmdk';

interface Props {
  open: boolean;
  vista: VistaPalette;
  onOpenChange: (open: boolean) => void;
  onVistaChange: (vista: VistaPalette) => void;
}

const CANAL: Record<CanalOrden, { label: string; icon: string }> = {
  ws: { label: 'Web Service', icon: 'ph:cloud-arrow-down-light' },
  fiel: { label: 'e.firma', icon: 'ph:fingerprint-light' },
  ciec: { label: 'Contraseña', icon: 'ph:key-light' },
};

const ICONO_ORDEN: Record<Orden['tipo'], string> = {
  descargar: 'ph:download-simple-light',
  'descarga-rapida': 'ph:lightning-light',
  constancia: 'ph:identification-card-light',
  opinion: 'ph:seal-check-light',
  'listas-negras': 'ph:shield-check-light',
  diot: 'ph:file-text-light',
  calculadora: 'ph:calculator-light',
  'agregar-empresa': 'ph:plus-light',
  tema: 'ph:moon-light',
};

/** Atajos que se muestran junto a algunas pantallas. */
const ATAJO_DESTINO: Record<string, { tecla: string; shift?: boolean; mod?: boolean }> = {
  'descarga-rapida': { tecla: 'D', shift: true },
  ajustes: { tecla: ',' },
  ayuda: { tecla: 'F1', mod: false },
};

function Chip({ icon, children }: { icon?: ReactNode; children: ReactNode }) {
  return (
    <span className="inline-flex h-5.5 items-center gap-1.25 rounded-md border border-border bg-card px-1.75 text-[11.5px] font-semibold text-foreground">
      {icon}
      {children}
    </span>
  );
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-4.5 items-center rounded-[5px] border border-border bg-muted px-1.5 font-sans text-[10.5px] font-medium text-muted-foreground">
      {children}
    </kbd>
  );
}

/** Ruta de un destino para la columna derecha ("Revisar > Comprobantes"). */
function rutaDe(u: DestinoUbicado): string {
  return [u.espacio?.label, u.padre?.label].filter(Boolean).join(' > ');
}

/** Pantallas que coinciden con lo escrito (nombre, sinónimos, espacio). */
function buscarPaginas(q: string): DestinoUbicado[] {
  const nq = normalizar(q).replace(/^(ir a|ve a|abrir|abre|ir al|ve al)\s+/, '');
  if (!nq) return [];
  const palabras = nq.split(' ');
  const puntuadas: { u: DestinoUbicado; p: number }[] = [];
  for (const u of todosLosDestinos()) {
    const d = u.destino;
    const label = normalizar(d.label);
    const sin = (d.sinonimos ?? []).map(normalizar);
    const pajar = normalizar(
      [d.label, d.corto, ...(d.sinonimos ?? []), u.padre?.label, u.espacio?.label]
        .filter(Boolean)
        .join(' '),
    );
    if (!palabras.every((w) => pajar.includes(w))) continue;
    const p = label.startsWith(nq)
      ? 0
      : sin.includes(nq) || normalizar(d.corto ?? '') === nq
        ? 1
        : label.includes(nq)
          ? 2
          : sin.some((s) => s.startsWith(nq))
            ? 3
            : 4;
    puntuadas.push({ u, p });
  }
  return puntuadas.sort((a, b) => a.p - b.p).map((x) => x.u);
}

/**
 * ⌘K de la navegación por espacios: ir a cualquier pantalla (con sinónimos y
 * el espacio donde vive), cambiar de empresa por nombre o RFC, y órdenes en
 * lenguaje natural que muestran lo que entendieron (periodo, empresa, canal)
 * antes de ejecutarse. El intérprete es local (lib/ordenes.ts): lo que escribes
 * no sale del equipo. La vista 'empresas' (⌘E) se queda como la clásica.
 */
export function CommandPaletteEspacios({ open, vista, onOpenChange, onVistaChange }: Props) {
  const shell = useEspaciosShell();
  const { resolvedTheme, setTheme } = useTheme();
  const { empresas, seleccionar, refresh } = useEmpresas();
  const { apiClient } = useServer();

  const [q, setQ] = useState('');
  const [seleccion, setSeleccion] = useState('');
  const [cambiandoRfc, setCambiandoRfc] = useState<string | null>(null);
  const [mac, setMac] = useState(false);
  const [web, setWeb] = useState(false);

  useEffect(() => {
    setMac(esMac());
    setWeb(esWeb());
  }, []);

  useEffect(() => {
    setQ('');
  }, [open, vista]);

  const oscuro = resolvedTheme === 'dark';
  const activas = useMemo(() => empresas.filter((e) => !e.archived_at), [empresas]);
  const activa = activas.find((e) => e.default) ?? activas[0] ?? null;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const hoy = useMemo(() => new Date(), [open]);
  const mesPasado = MESES[mesAnterior(hoy).mes - 1];

  const texto = q.trim();
  const ordenes = useMemo(
    () => (vista === 'root' && texto ? interpretar(texto, activas, activa, hoy) : []),
    [vista, texto, activas, activa, hoy],
  );
  const paginas = useMemo(() => (vista === 'root' ? buscarPaginas(texto) : []), [vista, texto]);
  const nq = normalizar(texto);
  const espaciosQueCoinciden = useMemo(() => {
    const limpio = nq.replace(/^(ir a|ve a|abrir|abre)\s+/, '');
    if (!texto) return ESPACIOS;
    return ESPACIOS.filter((e) => normalizar(`${e.label} ${e.descripcion}`).includes(limpio));
  }, [nq, texto]);
  const empresasQueCoinciden = useMemo(() => {
    if (!nq) return activas;
    const palabras = nq.split(' ');
    return activas.filter((e) => {
      const pajar = normalizar(`${e.nombre} ${e.rfc}`);
      return palabras.every((w) => pajar.includes(w));
    });
  }, [activas, nq]);

  const ejemplosPedir = useMemo(() => ejemplos(activas, activa, hoy), [activas, activa, hoy]);

  // Agrupa las pantallas por espacio, en el orden del riel.
  const paginasPorGrupo = useMemo(() => {
    const grupos = new Map<string, DestinoUbicado[]>();
    for (const u of paginas.slice(0, 10)) {
      const g = u.espacio?.label ?? 'Cuenta y ayuda';
      grupos.set(g, [...(grupos.get(g) ?? []), u]);
    }
    return [...grupos.entries()];
  }, [paginas]);

  const accionesGenerales = useMemo(() => {
    const todas = [
      { id: 'acc-empresas', label: 'Cambiar de empresa…', icon: 'ph:buildings-light', atajo: { tecla: 'E' } },
      { id: 'acc-alta', label: 'Agregar empresa…', icon: 'ph:plus-light', atajo: { tecla: 'N' } },
      {
        id: 'acc-tema',
        label: oscuro ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro',
        icon: oscuro ? 'ph:sun-light' : 'ph:moon-light',
        atajo: { tecla: 'L', shift: true },
      },
      { id: 'acc-panel', label: 'Mostrar u ocultar el panel', icon: 'ph:sidebar-simple-light', atajo: { tecla: 'B' } },
    ];
    if (!texto) return todas;
    const tipos = new Set(ordenes.map((o) => o.tipo));
    return todas.filter((a) => {
      if (a.id === 'acc-alta' && tipos.has('agregar-empresa')) return false;
      if (a.id === 'acc-tema' && tipos.has('tema')) return false;
      const pajar = normalizar(a.label);
      return nq.split(' ').every((w) => pajar.includes(w));
    });
  }, [oscuro, texto, ordenes, nq]);

  // Orden de los items (para seleccionar el primero al escribir).
  const primerItem = useMemo(() => {
    if (vista === 'empresas') return empresasQueCoinciden[0] ? `emp-${empresasQueCoinciden[0].rfc}` : '';
    if (!texto) return 'ej-0';
    if (ordenes.length) return 'orden-0';
    if (espaciosQueCoinciden.length) return `esp-${espaciosQueCoinciden[0].id}`;
    if (paginasPorGrupo.length) return `pag-${paginasPorGrupo[0][1][0].destino.id}`;
    if (empresasQueCoinciden.length) return `emp-${empresasQueCoinciden[0].rfc}`;
    if (accionesGenerales.length) return accionesGenerales[0].id;
    return '';
  }, [vista, texto, ordenes, espaciosQueCoinciden, paginasPorGrupo, empresasQueCoinciden, accionesGenerales]);

  useEffect(() => {
    setSeleccion(primerItem);
  }, [primerItem, open]);

  const sinResultados =
    vista === 'root' &&
    !!texto &&
    ordenes.length === 0 &&
    paginas.length === 0 &&
    espaciosQueCoinciden.length === 0 &&
    empresasQueCoinciden.length === 0 &&
    accionesGenerales.length === 0;

  useEffect(() => {
    if (!sinResultados) return;
    const t = setTimeout(
      () => agregarBreadcrumb({ category: 'nav', message: 'palette_sin_resultado', data: { largo: texto.length } }),
      800,
    );
    return () => clearTimeout(t);
  }, [sinResultados, texto.length]);

  if (!shell) return null;

  function cerrar() {
    onOpenChange(false);
  }

  async function cambiarEmpresa(rfc: string) {
    if (cambiandoRfc) return;
    if (rfc === activa?.rfc) {
      cerrar();
      return;
    }
    const empresa = activas.find((e) => e.rfc === rfc);
    if (!empresa) return;
    setCambiandoRfc(rfc);
    try {
      await seleccionar(empresa.rfc, empresa.metodos);
      cerrar();
    } catch (err) {
      toast.error(mensajeDeError(err));
    } finally {
      setCambiandoRfc(null);
    }
  }

  /** Cambia la empresa activa a la de la orden si hace falta. */
  async function asegurarEmpresa(e: EmpresaOrden | null): Promise<Empresa | null> {
    if (!e) return null;
    const empresa = activas.find((x) => x.rfc === e.rfc) ?? null;
    if (!empresa) return null;
    if (empresa.rfc === activa?.rfc) return empresa;
    try {
      await seleccionar(empresa.rfc, empresa.metodos);
      return empresa;
    } catch (err) {
      toast.error(mensajeDeError(err));
      return null;
    }
  }

  async function documentoConEfirma(tipo: 'constancia' | 'opinion', empresa: Empresa) {
    const corto = nombreCorto(empresa.nombre);
    const id = toast.loading(
      tipo === 'constancia'
        ? `Descargando la Constancia de ${corto}…`
        : `Solicitando la Opinión 32-D de ${corto}…`,
      {
        description: 'Con su e.firma, sin captcha. Puede tardar un par de minutos.',
        icon: <Icon icon="ph:circle-notch-light" className="size-4 animate-spin text-auto" />,
      },
    );
    try {
      const r = tipo === 'constancia' ? await apiClient.constanciaFiel() : await apiClient.opinionFiel();
      refresh();
      toast.success(
        tipo === 'constancia' ? `Constancia de ${corto} descargada` : `Opinión 32-D de ${corto} descargada`,
        {
          id,
          description: tipo === 'opinion' ? 'El semáforo de la empresa ya está al día.' : undefined,
          icon: undefined,
          action: r.archivo
            ? {
                label: web ? 'Descargar' : 'Abrir',
                onClick: () => void abrirODescargar(apiClient, r.archivo, 'archivo'),
              }
            : undefined,
        },
      );
    } catch (err) {
      toast.error(mensajeDeError(err), { id, icon: undefined, description: undefined });
    }
  }

  async function ejecutar(o: Orden) {
    if (o.problema) {
      toast.error(o.problema);
      return;
    }
    agregarBreadcrumb({
      category: 'nav',
      message: `palette_orden: ${o.tipo}`,
      data: {
        periodo: !!o.periodo?.explicito,
        empresa: o.empresaMencionada,
        tipo: o.comprobante ?? null,
        canal: o.canal ?? null,
      },
    });
    cerrar();
    if (!shell) return;
    switch (o.tipo) {
      case 'descargar':
      case 'descarga-rapida': {
        const empresa = await asegurarEmpresa(o.empresa);
        if (!empresa || !o.periodo || !o.comprobante) return;
        const tipoTxt = o.comprobante === 'E' ? 'Emitidos' : o.comprobante === 'R' ? 'Recibidos' : 'Emitidos y recibidos';
        const etiqueta = `${tipoTxt} de ${o.periodo.etiqueta.toLowerCase()}, ${nombreCorto(empresa.nombre)}`;
        if (o.tipo === 'descargar') {
          ponerPrefill('descarga', {
            rfc: empresa.rfc,
            desde: o.periodo.desde,
            hasta: o.periodo.hasta,
            comprobante: o.comprobante,
            etiqueta,
          });
          shell.navegar('/descarga', 'buscador');
          registrarReciente('sat', {
            id: 'descarga',
            href: '/descarga',
            label: `${tipoTxt} ${MESES[o.periodo.mes - 1].slice(0, 3)} ${o.periodo.anio}, ${nombreCorto(empresa.nombre)}`,
            icon: 'ph:download-simple-light',
            rfc: empresa.rfc,
          });
        } else {
          ponerPrefill('portal', {
            rfc: empresa.rfc,
            desde: o.periodo.desde,
            hasta: o.periodo.hasta,
            tipo: o.comprobante === 'A' ? 'RE' : o.comprobante,
            etiqueta: `${etiqueta}, con ${o.canal === 'ciec' ? 'Contraseña' : 'e.firma'}`,
          });
          shell.navegar('/descarga/rapida', 'buscador');
        }
        return;
      }
      case 'constancia':
      case 'opinion': {
        if (!o.empresa) return;
        if (o.canal === 'ciec') {
          // Con Contraseña hay captcha: se resuelve en la fila de la empresa.
          shell.navegar(
            `/empresas?rfc=${encodeURIComponent(o.empresa.rfc)}&abrir=1&bajar=${o.tipo}`,
            'buscador',
          );
          return;
        }
        const empresa = await asegurarEmpresa(o.empresa);
        if (empresa) await documentoConEfirma(o.tipo, empresa);
        return;
      }
      case 'listas-negras': {
        if (await asegurarEmpresa(o.empresa)) shell.navegar('/listas-negras', 'buscador');
        return;
      }
      case 'diot': {
        const empresa = await asegurarEmpresa(o.empresa);
        if (!empresa) return;
        if (o.periodo) {
          ponerPrefill('diot', {
            rfc: empresa.rfc,
            periodo: `${o.periodo.anio}-${String(o.periodo.mes).padStart(2, '0')}`,
          });
        }
        shell.navegar('/diot', 'buscador');
        return;
      }
      case 'calculadora': {
        const href = o.destinoId ? destinoPorId(o.destinoId)?.destino.href : undefined;
        if (href) shell.navegar(href, 'buscador');
        return;
      }
      case 'agregar-empresa':
        shell.navegar('/empresas?alta=1', 'buscador');
        return;
      case 'tema':
        setTheme(o.tema === 'oscuro' ? 'dark' : 'light');
        return;
    }
  }

  function accionGeneral(id: string) {
    if (!shell) return;
    if (id === 'acc-empresas') {
      onVistaChange('empresas');
      return;
    }
    cerrar();
    if (id === 'acc-alta') shell.navegar('/empresas?alta=1', 'buscador');
    if (id === 'acc-tema') setTheme(oscuro ? 'light' : 'dark');
    if (id === 'acc-panel') shell.togglePanel();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (vista === 'empresas' && e.key === 'Backspace' && q === '') {
      e.preventDefault();
      onVistaChange('root');
    }
  }

  const placeholder =
    vista === 'empresas'
      ? 'Buscar empresa por nombre o RFC…'
      : `Busca o pide algo: "descargar recibidos de ${mesPasado} de…"`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        className="top-[13%] translate-y-0 gap-0 overflow-hidden rounded-[14px] p-0 sm:max-w-[680px]"
      >
        <DialogTitle className="sr-only">
          {vista === 'empresas' ? 'Cambiar de empresa' : 'Busca o pide algo'}
        </DialogTitle>
        <Command
          shouldFilter={false}
          value={seleccion}
          onValueChange={setSeleccion}
          onKeyDown={onKeyDown}
          loop
          className="rounded-[14px]"
        >
          <div className="flex items-center gap-2.5 border-b border-rule-soft px-4">
            <Icon
              icon={vista === 'empresas' ? 'ph:buildings-light' : 'ph:magnifying-glass-light'}
              className="size-4.5 shrink-0 text-muted-foreground"
            />
            <CommandPrimitive.Input
              value={q}
              onValueChange={setQ}
              placeholder={placeholder}
              className="flex h-13 w-full bg-transparent text-[15px] text-foreground outline-none placeholder:text-ghost"
            />
            <Kbd>Esc</Kbd>
          </div>
          <CommandList className="max-h-[min(440px,60vh)] p-1.5">
            {vista === 'empresas' ? (
              <>
                <CommandEmpty>Sin empresas que coincidan.</CommandEmpty>
                <CommandGroup heading="Cambiar de empresa">
                  {empresasQueCoinciden.map((e) => (
                    <ItemEmpresa
                      key={e.rfc}
                      empresa={e}
                      activa={e.rfc === activa?.rfc}
                      cambiando={cambiandoRfc === e.rfc}
                      onSelect={() => void cambiarEmpresa(e.rfc)}
                    />
                  ))}
                </CommandGroup>
              </>
            ) : !texto ? (
              <>
                <CommandGroup heading="Prueba a pedir">
                  {ejemplosPedir.map((x, i) => (
                    <CommandItem key={x} value={`ej-${i}`} onSelect={() => setQ(x)} className="min-h-10 rounded-[9px] px-2.5">
                      <Icon icon="ph:arrow-elbow-down-left-light" className="size-4.5 shrink-0 text-muted-foreground" />
                      <span className="flex-1 truncate font-medium">{x}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
                <CommandGroup heading="Espacios">
                  {ESPACIOS.map((e, i) => (
                    <CommandItem
                      key={e.id}
                      value={`esp-${e.id}`}
                      onSelect={() => {
                        cerrar();
                        shell.irAEspacio(e.id, 'buscador');
                      }}
                      className="min-h-10 rounded-[9px] px-2.5"
                    >
                      <Icon icon={e.icon} className="size-4.5 shrink-0 text-muted-foreground" />
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="truncate font-medium">Ir a {e.label}</span>
                        <span className="truncate text-xs text-muted-foreground">{e.descripcion}</span>
                      </span>
                      <Kbd>{formatearAtajo({ tecla: String(i + 1) }, mac)}</Kbd>
                    </CommandItem>
                  ))}
                </CommandGroup>
                <GrupoAcciones acciones={accionesGenerales} mac={mac} onSelect={accionGeneral} />
              </>
            ) : (
              <>
                {sinResultados && (
                  <div className="px-4 py-7 text-center text-[13px] leading-relaxed text-muted-foreground">
                    Sin resultados para &quot;{texto}&quot;.
                    <br />
                    Prueba con un verbo: descargar, constancia, opinión, finiquito.
                  </div>
                )}
                {ordenes.length > 0 && (
                  <CommandGroup heading="Acciones">
                    {ordenes.map((o, i) => (
                      <ItemOrden key={`${o.tipo}-${o.empresa?.rfc ?? i}`} orden={o} valor={`orden-${i}`} onSelect={() => void ejecutar(o)} />
                    ))}
                  </CommandGroup>
                )}
                {espaciosQueCoinciden.length > 0 && (
                  <CommandGroup heading="Espacios">
                    {espaciosQueCoinciden.map((e) => (
                      <CommandItem
                        key={e.id}
                        value={`esp-${e.id}`}
                        onSelect={() => {
                          cerrar();
                          shell.irAEspacio(e.id, 'buscador');
                        }}
                        className="min-h-10 rounded-[9px] px-2.5"
                      >
                        <Icon icon={e.icon} className="size-4.5 shrink-0 text-muted-foreground" />
                        <span className="flex-1 truncate font-medium">Ir a {e.label}</span>
                        <Kbd>{formatearAtajo({ tecla: String(ESPACIOS.indexOf(e) + 1) }, mac)}</Kbd>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
                {paginasPorGrupo.map(([grupo, items]) => (
                  <CommandGroup key={grupo} heading={grupo}>
                    {items.map((u) => {
                      const atajo = ATAJO_DESTINO[u.destino.id];
                      return (
                        <CommandItem
                          key={u.destino.id}
                          value={`pag-${u.destino.id}`}
                          onSelect={() => {
                            cerrar();
                            shell.abrirDestino(u.destino, 'buscador');
                          }}
                          className="min-h-10 rounded-[9px] px-2.5"
                        >
                          <Icon icon={u.destino.icon} className="size-4.5 shrink-0 text-muted-foreground" />
                          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <span className="flex items-center gap-1.5 truncate font-medium">
                              <span className="truncate">{u.destino.label}</span>
                              <EtiquetaDestino destino={u.destino} web={web} />
                            </span>
                            <span className="truncate text-xs text-muted-foreground">
                              {u.espacio ? `${rutaDe(u)}. ` : ''}
                              {u.destino.descripcion}
                            </span>
                          </span>
                          {atajo && <Kbd>{formatearAtajo(atajo, mac)}</Kbd>}
                        </CommandItem>
                      );
                    })}
                  </CommandGroup>
                ))}
                {empresasQueCoinciden.length > 0 && (
                  <CommandGroup heading="Cambiar de empresa">
                    {empresasQueCoinciden.slice(0, 5).map((e) => (
                      <ItemEmpresa
                        key={e.rfc}
                        empresa={e}
                        activa={e.rfc === activa?.rfc}
                        cambiando={cambiandoRfc === e.rfc}
                        onSelect={() => void cambiarEmpresa(e.rfc)}
                      />
                    ))}
                  </CommandGroup>
                )}
                {accionesGenerales.length > 0 && (
                  <GrupoAcciones acciones={accionesGenerales} mac={mac} onSelect={accionGeneral} />
                )}
              </>
            )}
          </CommandList>
          <div className="flex items-center gap-4 border-t border-rule-soft bg-background/60 px-3.5 py-2 text-[11.5px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.25">
              <Kbd>↑</Kbd>
              <Kbd>↓</Kbd> moverte
            </span>
            <span className="inline-flex items-center gap-1.25">
              <Kbd>
                <Icon icon="ph:arrow-elbow-down-left-light" className="size-2.75" />
              </Kbd>{' '}
              abrir o ejecutar
            </span>
            {vista === 'empresas' ? (
              <span className="inline-flex items-center gap-1.25">
                <Kbd>⌫</Kbd> regresar
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.25">
                <Kbd>{formatearAtajo({ tecla: 'E' }, mac)}</Kbd> empresas
              </span>
            )}
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

function GrupoAcciones({
  acciones,
  mac,
  onSelect,
}: {
  acciones: { id: string; label: string; icon: string; atajo: { tecla: string; shift?: boolean } }[];
  mac: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <CommandGroup heading="Acciones">
      {acciones.map((a) => (
        <CommandItem key={a.id} value={a.id} onSelect={() => onSelect(a.id)} className="min-h-10 rounded-[9px] px-2.5">
          <Icon icon={a.icon} className="size-4.5 shrink-0 text-muted-foreground" />
          <span className="flex-1 truncate font-medium">{a.label}</span>
          <Kbd>{formatearAtajo(a.atajo, mac)}</Kbd>
        </CommandItem>
      ))}
    </CommandGroup>
  );
}

function ItemEmpresa({
  empresa,
  activa,
  cambiando,
  onSelect,
}: {
  empresa: Empresa;
  activa: boolean;
  cambiando: boolean;
  onSelect: () => void;
}) {
  return (
    <CommandItem value={`emp-${empresa.rfc}`} onSelect={onSelect} className="min-h-10 rounded-[9px] px-2.5">
      <EmpresaBadge rfc={empresa.rfc} size="sm" />
      <span className="flex min-w-0 flex-1 flex-col gap-px">
        <span className="truncate text-[13px] font-semibold leading-tight">{empresa.nombre}</span>
        <span className="truncate font-mono text-[11px] text-muted-foreground">{empresa.rfc}</span>
      </span>
      {cambiando ? (
        <Icon icon="ph:circle-notch-light" className="size-4 shrink-0 animate-spin text-muted-foreground" />
      ) : (
        activa && <Icon icon="ph:check-circle-light" className="size-4 shrink-0 text-foreground" />
      )}
    </CommandItem>
  );
}

/** Una orden con lo que entendió, como etiquetas, antes de ejecutarla. */
function ItemOrden({ orden: o, valor, onSelect }: { orden: Orden; valor: string; onSelect: () => void }) {
  const canal = o.canal ? CANAL[o.canal] : null;
  const icono = o.tipo === 'tema' && o.tema === 'claro' ? 'ph:sun-light' : ICONO_ORDEN[o.tipo];
  const conEmpresa = !!o.empresa && o.tipo !== 'calculadora' && o.tipo !== 'agregar-empresa' && o.tipo !== 'tema';
  const conEtiquetas = !!(o.periodo || conEmpresa || canal);
  return (
    <CommandItem value={valor} onSelect={onSelect} className="items-start rounded-[9px] px-2.5 py-2.5">
      <Icon icon={icono} className="mt-0.5 size-4.5 shrink-0 text-foreground" />
      <span className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="truncate text-[13.5px] font-semibold">{o.titulo}</span>
        {conEtiquetas && (
          <span className="flex flex-wrap gap-1.25">
            {o.periodo && (
              <Chip icon={<Icon icon="ph:calendar-blank-light" className="size-3 text-muted-foreground" />}>
                {o.periodo.etiqueta}
              </Chip>
            )}
            {conEmpresa && o.empresa && (
              <Chip icon={<EmpresaBadge rfc={o.empresa.rfc} size="xs" />}>{nombreCorto(o.empresa.nombre)}</Chip>
            )}
            {canal && (
              <Chip icon={<Icon icon={canal.icon} className="size-3 text-muted-foreground" />}>{canal.label}</Chip>
            )}
          </span>
        )}
        {conEmpresa && !o.empresaMencionada && o.empresa && (
          <span className="text-xs text-muted-foreground">
            Empresa activa: {nombreCorto(o.empresa.nombre)} (menciona otra para cambiarla)
          </span>
        )}
        {o.problema ? (
          <span className="text-xs font-medium text-destructive">{o.problema}</span>
        ) : o.confirmar ? (
          <span className="text-xs text-muted-foreground">
            Enter llena la solicitud. La mandas con otro Enter.
          </span>
        ) : o.tipo === 'constancia' || o.tipo === 'opinion' ? (
          <span className="text-xs text-muted-foreground">
            {o.canal === 'ciec'
              ? 'Enter la pide con Contraseña: el captcha sale aquí mismo.'
              : 'Enter la descarga directo y te avisa cuando esté.'}
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          'mt-0.5 shrink-0 text-[11px] font-medium text-muted-foreground',
          'in-data-[selected=true]:text-foreground',
        )}
      >
        <Kbd>
          <Icon icon="ph:arrow-elbow-down-left-light" className="size-2.75" />
        </Kbd>
      </span>
    </CommandItem>
  );
}

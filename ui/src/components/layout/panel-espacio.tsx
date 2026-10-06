'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { espacioPorId, type Destino, type DestinoUbicado } from '@/lib/navegacion';
import { esMac, formatearAtajo } from '@/lib/atajos';
import { esWeb } from '@/lib/modo';
import { mensajeDeError } from '@/lib/errores';
import { useRecientes, type Reciente } from '@/hooks/use-recientes';
import { useEmpresas } from '@/hooks/use-empresas';
import { useEspaciosShell } from '@/components/layout/espacios-shell';
import { Icon } from '@/components/ui/icon';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/** Etiquetas del panel y de ⌘K: "Nuevo", "Pronto" y "Escritorio" (en la web). */
export function EtiquetaDestino({ destino, web }: { destino: Destino; web: boolean }) {
  return (
    <>
      {destino.estado === 'pronto' && (
        <span className="inline-flex h-4.5 shrink-0 items-center rounded-full bg-muted px-1.5 text-[10px] font-semibold text-ghost">
          Pronto
        </span>
      )}
      {destino.estado === 'nuevo' && (
        <span className="inline-flex h-4.5 shrink-0 items-center rounded-full bg-foreground px-1.5 text-[10px] font-semibold text-background">
          Nuevo
        </span>
      )}
      {destino.soloEscritorio && web && (
        <span className="inline-flex h-4.5 shrink-0 items-center gap-0.5 rounded-full border border-border bg-card px-1.5 text-[10px] font-semibold text-muted-foreground">
          <Icon icon="ph:desktop-light" className="size-2.75" />
          Escritorio
        </span>
      )}
    </>
  );
}

function estadoDe(d: Destino, activo: DestinoUbicado | null): 'activo' | 'abierto' | null {
  if (!activo) return null;
  if (activo.destino.id === d.id) return 'activo';
  if (activo.padre?.id === d.id) return 'abierto';
  return null;
}

/**
 * Panel del espacio activo: encabezado con su frase, destinos con su línea de
 * descripción (los hijos se despliegan dentro de su destino), Recientes y un
 * tip de ⌘K. Se esconde con ⌘B, con el botón de flecha doble o con un clic en
 * el espacio donde ya estás; el riel siempre se queda.
 */
export function PanelEspacio() {
  const shell = useEspaciosShell();
  const { empresas, seleccionar } = useEmpresas();
  const [mac, setMac] = useState(false);
  const [web, setWeb] = useState(false);

  useEffect(() => {
    setMac(esMac());
    setWeb(esWeb());
  }, []);

  const espacio = espacioPorId(shell?.espacioActivo ?? 'despacho');
  const recientes = useRecientes(espacio.id);

  if (!shell) return null;
  const activo = shell.destinoActivo;

  async function abrirReciente(r: Reciente) {
    if (!shell) return;
    const activa = empresas.find((e) => e.default);
    const empresa = r.rfc ? empresas.find((e) => e.rfc === r.rfc && !e.archived_at) : null;
    if (empresa && empresa.rfc !== activa?.rfc) {
      try {
        await seleccionar(empresa.rfc, empresa.metodos);
      } catch (err) {
        toast.error(mensajeDeError(err));
        return;
      }
    }
    shell.navegar(r.href, 'recientes');
  }

  return (
    <aside
      aria-label={`Panel de ${espacio.label}`}
      aria-hidden={!shell.panelAbierto}
      className={cn(
        'hidden shrink-0 overflow-hidden border-r bg-panel transition-[width] duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] md:block',
        shell.panelAbierto ? 'w-62' : 'w-0 border-r-0',
      )}
    >
      <div className="flex h-full w-62 flex-col">
        <div className="flex items-start justify-between gap-2 pb-2.5 pl-4.5 pr-3 pt-4.5">
          <div className="min-w-0">
            <h2 className="text-base font-bold tracking-[-0.018em] text-foreground">
              {espacio.label}
            </h2>
            <p className="mt-0.5 text-xs text-muted-foreground">{espacio.descripcion}</p>
          </div>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={shell.togglePanel}
                tabIndex={shell.panelAbierto ? 0 : -1}
                aria-label="Ocultar el panel"
                className="flex size-7.5 shrink-0 items-center justify-center rounded-md text-ghost transition-colors hover:bg-muted hover:text-foreground"
              >
                <Icon icon="ph:caret-double-left-light" className="size-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="right">
              Ocultar el panel ({formatearAtajo({ tecla: 'B' }, mac)})
            </TooltipContent>
          </Tooltip>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto px-2.5 pb-2.5 pt-0.5">
          {espacio.destinos.map((d) => {
            const estado = estadoDe(d, activo);
            const desplegar = !!d.hijos?.length && estado !== null;
            return (
              <div key={d.id}>
                <button
                  type="button"
                  onClick={() => shell.abrirDestino(d, 'panel')}
                  tabIndex={shell.panelAbierto ? 0 : -1}
                  aria-current={estado === 'activo' ? 'page' : undefined}
                  className={cn(
                    'flex w-full items-start gap-2.5 rounded-[9px] px-2.5 py-2.25 text-left transition-colors duration-[120ms]',
                    estado ? 'bg-muted' : 'hover:bg-muted/70',
                  )}
                >
                  <Icon
                    icon={d.icon}
                    className={cn(
                      'mt-px size-4.5 shrink-0',
                      estado ? 'text-foreground' : 'text-muted-foreground',
                    )}
                  />
                  <span className="min-w-0 flex-1">
                    <span
                      className={cn(
                        'flex items-center gap-1.5 text-[13.5px] font-semibold tracking-[-0.01em]',
                        d.estado === 'pronto' ? 'text-muted-foreground' : 'text-foreground',
                      )}
                    >
                      <span className="truncate">{d.label}</span>
                      <EtiquetaDestino destino={d} web={web} />
                    </span>
                    <span className="mt-0.5 block text-[11.5px] leading-[1.38] text-muted-foreground">
                      {d.descripcion}
                    </span>
                  </span>
                </button>
                {desplegar && (
                  <div className="mb-1.5 ml-7 mt-0.5 flex flex-col gap-px border-l border-border pl-3">
                    {d.hijos!.map((h) => {
                      const hEstado = estadoDe(h, activo);
                      return (
                        <button
                          key={h.id}
                          type="button"
                          onClick={() => shell.abrirDestino(h, 'panel')}
                          tabIndex={shell.panelAbierto ? 0 : -1}
                          aria-current={hEstado === 'activo' ? 'page' : undefined}
                          className={cn(
                            'flex w-full items-center gap-2 rounded-[7px] px-2.5 py-1.5 text-left text-[13px] transition-colors duration-[120ms]',
                            hEstado === 'activo'
                              ? 'bg-muted font-semibold text-foreground'
                              : 'font-medium text-muted-foreground hover:bg-muted/70 hover:text-foreground',
                          )}
                        >
                          <span className="min-w-0 flex-1 truncate">{h.corto ?? h.label}</span>
                          <EtiquetaDestino destino={h} web={web} />
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {recientes.length > 0 && (
          <div className="border-t border-rule-soft px-3 py-3">
            <h3 className="px-1.5 pb-1.5 text-[11.5px] font-semibold text-ghost">Recientes</h3>
            {recientes.map((r) => (
              <button
                key={`${r.href}-${r.rfc ?? ''}`}
                type="button"
                onClick={() => void abrirReciente(r)}
                tabIndex={shell.panelAbierto ? 0 : -1}
                className="flex w-full items-center gap-2.25 rounded-lg px-1.5 py-1.5 text-left text-[12.5px] text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground"
              >
                <Icon icon={r.icon} className="size-3.75 shrink-0" />
                <span className="min-w-0 flex-1 truncate">{r.label}</span>
              </button>
            ))}
          </div>
        )}

        <div className="mx-3 mb-3 flex items-start gap-1.5 rounded-[10px] border border-border bg-card px-3 py-2.5 text-xs leading-[1.45] text-muted-foreground">
          <Icon icon="ph:magnifying-glass-light" className="mt-0.5 size-3.25 shrink-0" />
          <span>
            Pide lo que necesites en{' '}
            <b className="font-semibold text-foreground">{formatearAtajo({ tecla: 'K' }, mac)}</b>:
            &quot;descargar recibidos de septiembre&quot;.
          </span>
        </div>
      </div>
    </aside>
  );
}

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useTheme } from 'next-themes';
import { toast } from 'sonner';

import {
  EVENTO_SIDEBAR_TOGGLE,
  esMac,
  formatearAtajo,
} from '@/lib/atajos';
import { NAV_ITEMS, NAV_SECUNDARIO, PAGINAS_EXTRA } from '@/lib/navegacion';
import { NAV_ESPACIOS } from '@/lib/features';
import { useNavegacion } from '@/providers/navegacion-provider';
import { mensajeDeError } from '@/lib/errores';
import { useEmpresas } from '@/hooks/use-empresas';
import { EmpresaBadge } from '@/components/empresas/empresa-badge';
import { Icon } from '@/components/ui/icon';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command';

export type VistaPalette = 'root' | 'empresas';

interface CommandPaletteProps {
  open: boolean;
  vista: VistaPalette;
  onOpenChange: (open: boolean) => void;
  onVistaChange: (vista: VistaPalette) => void;
}

/**
 * Command palette (⌘K / Ctrl+K): buscador de páginas y acciones para moverse
 * por la app sin mouse. La vista 'empresas' (⌘E) lista el catálogo y cambia
 * la empresa activa con Enter. El estado open/vista lo posee GlobalShortcuts;
 * este componente solo lo renderiza.
 */
export function CommandPalette({
  open,
  vista,
  onOpenChange,
  onVistaChange,
}: CommandPaletteProps) {
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const { empresas, seleccionar } = useEmpresas();
  const navegacion = useNavegacion();

  const [busqueda, setBusqueda] = useState('');
  // RFC de la empresa cuyo cambio está en curso (spinner + bloqueo).
  const [cambiandoRfc, setCambiandoRfc] = useState<string | null>(null);
  // Símbolo del modificador según plataforma; post-mount (depende de window).
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(esMac());
  }, []);

  // El input se limpia al abrir y al cambiar de vista (root ↔ empresas).
  useEffect(() => {
    setBusqueda('');
  }, [open, vista]);

  const oscuro = resolvedTheme === 'dark';
  // Labs de la navegación por espacios (F3): solo aparece si escribes "labs".
  // En el escritorio no hay barra de direcciones para `?labs=espacios`.
  const pideLabs = NAV_ESPACIOS && vista === 'root' && busqueda.trim().toLowerCase().startsWith('labs');
  const activas = empresas.filter((e) => !e.archived_at);
  const activa = activas.find((e) => e.default) ?? activas[0] ?? null;

  function navegar(href: string) {
    onOpenChange(false);
    router.push(href);
  }

  async function cambiarEmpresa(rfc: string) {
    if (cambiandoRfc) return;
    if (rfc === activa?.rfc) {
      onOpenChange(false);
      return;
    }
    const empresa = activas.find((e) => e.rfc === rfc);
    if (!empresa) return;
    setCambiandoRfc(rfc);
    try {
      await seleccionar(empresa.rfc, empresa.metodos);
      onOpenChange(false);
    } catch (err) {
      toast.error(mensajeDeError(err));
    } finally {
      setCambiandoRfc(null);
    }
  }

  // Backspace con el input vacío en empresas regresa a la vista principal.
  function onKeyDown(e: React.KeyboardEvent) {
    if (vista === 'empresas' && e.key === 'Backspace' && busqueda === '') {
      e.preventDefault();
      onVistaChange('root');
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        className="top-[22%] translate-y-0 gap-0 overflow-hidden p-0 sm:max-w-xl"
      >
        <DialogTitle className="sr-only">
          {vista === 'empresas' ? 'Cambiar de empresa' : 'Buscar página o acción'}
        </DialogTitle>
        <Command onKeyDown={onKeyDown}>
          <CommandInput
            value={busqueda}
            onValueChange={setBusqueda}
            placeholder={
              vista === 'empresas' ? 'Buscar empresa…' : 'Buscar página o acción…'
            }
          />
          <CommandList>
            {vista === 'root' ? (
              <>
                <CommandEmpty>Sin resultados.</CommandEmpty>
                <CommandGroup heading="Páginas">
                  {NAV_ITEMS.map((item, i) => (
                    <CommandItem
                      key={item.href}
                      value={item.label}
                      onSelect={() => navegar(item.href)}
                    >
                      <Icon icon={item.icon} className="size-4.5 shrink-0 text-muted-foreground" />
                      {item.label}
                      {i < 9 && (
                        <CommandShortcut>
                          {formatearAtajo({ tecla: String(i + 1) }, mac)}
                        </CommandShortcut>
                      )}
                    </CommandItem>
                  ))}
                  {PAGINAS_EXTRA.map((item) => (
                    <CommandItem
                      key={item.href}
                      value={item.label}
                      onSelect={() => navegar(item.href)}
                    >
                      <Icon icon={item.icon} className="size-4.5 shrink-0 text-muted-foreground" />
                      {item.label}
                      {item.href === '/descarga/rapida' && (
                        <CommandShortcut>
                          {formatearAtajo({ tecla: 'D', shift: true }, mac)}
                        </CommandShortcut>
                      )}
                    </CommandItem>
                  ))}
                  {NAV_SECUNDARIO.map((item) => (
                    <CommandItem
                      key={item.href}
                      value={item.label}
                      onSelect={() => navegar(item.href)}
                    >
                      <Icon icon={item.icon} className="size-4.5 shrink-0 text-muted-foreground" />
                      {item.label}
                      {item.href === '/ajustes' && (
                        <CommandShortcut>{formatearAtajo({ tecla: ',' }, mac)}</CommandShortcut>
                      )}
                      {item.href === '/ayuda' && (
                        <CommandShortcut>
                          {formatearAtajo({ tecla: 'F1', mod: false }, mac)}
                        </CommandShortcut>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
                {pideLabs && (
                  <CommandGroup heading="Labs">
                    <CommandItem
                      value="labs navegacion por espacios"
                      onSelect={() => {
                        navegacion.activarLabs();
                        onOpenChange(false);
                        toast.success('Navegación por espacios encendida en este equipo', {
                          description: 'Para volver a la clásica: Ajustes, Apariencia, Navegación.',
                        });
                      }}
                    >
                      <Icon icon="ph:flask-light" className="size-4.5 shrink-0 text-muted-foreground" />
                      Probar la navegación por espacios
                    </CommandItem>
                  </CommandGroup>
                )}
                <CommandGroup heading="Acciones">
                  <CommandItem
                    value="Cambiar de empresa"
                    onSelect={() => onVistaChange('empresas')}
                  >
                    <Icon icon="ph:buildings-light" className="size-4.5 shrink-0 text-muted-foreground" />
                    Cambiar de empresa…
                    <CommandShortcut>{formatearAtajo({ tecla: 'E' }, mac)}</CommandShortcut>
                  </CommandItem>
                  <CommandItem
                    value="Agregar empresa"
                    onSelect={() => navegar('/empresas?alta=1')}
                  >
                    <Icon icon="ph:plus-light" className="size-4.5 shrink-0 text-muted-foreground" />
                    Agregar empresa…
                    <CommandShortcut>{formatearAtajo({ tecla: 'N' }, mac)}</CommandShortcut>
                  </CommandItem>
                  <CommandItem
                    value="Cambiar tema claro oscuro"
                    onSelect={() => {
                      setTheme(oscuro ? 'light' : 'dark');
                      onOpenChange(false);
                    }}
                  >
                    <Icon
                      icon={oscuro ? 'ph:sun-light' : 'ph:moon-light'}
                      className="size-4.5 shrink-0 text-muted-foreground"
                    />
                    {oscuro ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
                    <CommandShortcut>
                      {formatearAtajo({ tecla: 'L', shift: true }, mac)}
                    </CommandShortcut>
                  </CommandItem>
                  <CommandItem
                    value="Colapsar expandir menú lateral"
                    onSelect={() => {
                      window.dispatchEvent(new Event(EVENTO_SIDEBAR_TOGGLE));
                      onOpenChange(false);
                    }}
                  >
                    <Icon icon="ph:sidebar-simple-light" className="size-4.5 shrink-0 text-muted-foreground" />
                    Colapsar o expandir el menú lateral
                    <CommandShortcut>{formatearAtajo({ tecla: 'B' }, mac)}</CommandShortcut>
                  </CommandItem>
                </CommandGroup>
              </>
            ) : (
              <>
                <CommandEmpty>Sin empresas.</CommandEmpty>
                <CommandGroup heading="Cambiar de empresa">
                  {activas.map((e) => (
                    <CommandItem
                      key={e.rfc}
                      value={`${e.nombre} ${e.rfc}`}
                      onSelect={() => void cambiarEmpresa(e.rfc)}
                    >
                      <EmpresaBadge rfc={e.rfc} size="sm" />
                      <span className="flex min-w-0 flex-1 flex-col gap-px">
                        <span className="truncate text-[12.5px] font-semibold leading-tight">
                          {e.nombre}
                        </span>
                        <span className="truncate font-mono text-[11px] text-muted-foreground">
                          {e.rfc}
                        </span>
                      </span>
                      {cambiandoRfc === e.rfc ? (
                        <Icon
                          icon="ph:circle-notch-light"
                          className="size-4 shrink-0 animate-spin text-muted-foreground"
                        />
                      ) : (
                        e.rfc === activa?.rfc && (
                          <Icon
                            icon="ph:check-circle-light"
                            className="size-4 shrink-0 text-success"
                          />
                        )
                      )}
                    </CommandItem>
                  ))}
                  <CommandItem
                    value="Administrar empresas"
                    onSelect={() => navegar('/empresas')}
                    className="font-semibold text-primary data-[selected=true]:text-primary"
                  >
                    <Icon icon="ph:buildings-light" className="size-4.5 shrink-0" />
                    Administrar empresas
                  </CommandItem>
                </CommandGroup>
              </>
            )}
          </CommandList>
          {/* Footer de hints de navegación con teclado. */}
          <div className="flex items-center justify-between border-t px-3 py-2 text-[11px] text-muted-foreground">
            <span>
              <kbd className="rounded border bg-muted px-1 py-px font-sans">↵</kbd> para
              seleccionar
            </span>
            <span>
              <kbd className="rounded border bg-muted px-1 py-px font-sans">↓</kbd>{' '}
              <kbd className="rounded border bg-muted px-1 py-px font-sans">↑</kbd> para
              navegar
            </span>
            <span>
              <kbd className="rounded border bg-muted px-1 py-px font-sans">esc</kbd> para
              cerrar
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

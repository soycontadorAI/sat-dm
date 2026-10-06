'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';
import {
  EVENTO_PALETTE_OPEN,
  EVENTO_SIDEBAR_TOGGLE,
  esMac,
  formatearAtajo,
} from '@/lib/atajos';
import { NAV_ITEMS } from '@/lib/navegacion';
import { AccountMenu } from '@/components/layout/account-menu';
import { BrandMark } from '@/components/layout/brand-mark';
import { EmpresaSwitcher } from '@/components/layout/empresa-switcher';
import { Icon } from '@/components/ui/icon';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';

const COLLAPSED_KEY = 'tc:sidebar-collapsed';

function NavItem({
  href,
  label,
  icon,
  active,
  collapsed,
}: {
  href: string;
  label: string;
  icon: string;
  active: boolean;
  collapsed: boolean;
}) {
  const link = (
    <Link
      href={href}
      className={cn(
        'relative flex items-center gap-3 rounded-lg text-[13.5px] font-medium transition-colors',
        collapsed ? 'size-11 justify-center' : 'px-3 py-2',
        active
          ? 'bg-accent font-semibold text-primary'
          : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
        // Barra azul del item activo, pegada al borde del sidebar.
        active &&
          'before:absolute before:-left-3 before:top-1/2 before:h-5.5 before:w-1 before:-translate-y-1/2 before:rounded-r before:bg-primary before:content-[""]',
        active && collapsed && 'before:-left-2.5',
      )}
    >
      <Icon
        icon={icon}
        className={cn('size-4.75 shrink-0', active ? 'text-primary' : '')}
      />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );

  if (!collapsed) return link;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{link}</TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  );
}

/** Abre el command palette (⌘K); muestra el atajo como kbd cuando hay espacio. */
function BuscarItem({ collapsed, mac }: { collapsed: boolean; mac: boolean }) {
  const boton = (
    <button
      onClick={() => window.dispatchEvent(new Event(EVENTO_PALETTE_OPEN))}
      className={cn(
        'flex items-center gap-3 rounded-lg text-[13.5px] font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground',
        collapsed ? 'size-11 justify-center' : 'w-full px-3 py-2',
      )}
    >
      <Icon icon="ph:magnifying-glass-light" className="size-4.75 shrink-0" />
      {!collapsed && (
        <>
          <span className="truncate">Buscar</span>
          <kbd className="ml-auto rounded border bg-muted px-1.5 py-px font-sans text-[10.5px] text-muted-foreground">
            {formatearAtajo({ tecla: 'K' }, mac)}
          </kbd>
        </>
      )}
    </button>
  );

  if (!collapsed) return boton;
  return (
    <Tooltip>
      <TooltipTrigger asChild>{boton}</TooltipTrigger>
      <TooltipContent side="right">
        Buscar ({formatearAtajo({ tecla: 'K' }, mac)})
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * Sidebar v2: marca + selector de empresa + nav plano + footer (Ayuda y
 * cuenta). Colapsable a modo solo-iconos; el estado persiste en localStorage.
 * La conexión y el semáforo de e.firma viven en la barra de estado inferior.
 */
export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  // Símbolo del atajo (⌘K vs Ctrl+K); post-mount, depende de window.
  const [mac, setMac] = useState(false);

  // localStorage solo post-mount (export estático: el primer render del
  // servidor y del cliente deben coincidir).
  useEffect(() => {
    setCollapsed(localStorage.getItem(COLLAPSED_KEY) === '1');
    setMac(esMac());
  }, []);

  function toggleCollapsed() {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSED_KEY, c ? '0' : '1');
      return !c;
    });
  }

  // ⌘B (GlobalShortcuts) colapsa/expande por evento window.
  useEffect(() => {
    const onToggle = () => toggleCollapsed();
    window.addEventListener(EVENTO_SIDEBAR_TOGGLE, onToggle);
    return () => window.removeEventListener(EVENTO_SIDEBAR_TOGGLE, onToggle);
  }, []);

  return (
    <aside
      className={cn(
        'hidden shrink-0 border-r bg-sidebar transition-[width] duration-200 md:flex md:flex-col',
        collapsed ? 'w-17' : 'w-62',
      )}
    >
      {/* Marca */}
      <div
        className={cn(
          'flex items-center gap-2.5 pb-3 pt-4',
          collapsed ? 'justify-center px-0' : 'px-3.5',
        )}
      >
        <BrandMark
          iconOnly={collapsed}
          className={cn(!collapsed && 'min-w-0 flex-1')}
        />
        {!collapsed && (
          <button
            onClick={toggleCollapsed}
            title="Colapsar menú"
            className="flex size-7.5 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <Icon icon="ph:sidebar-simple-light" className="size-4.5" />
          </button>
        )}
      </div>

      {/* Botón de expandir (solo colapsado, debajo de la marca) */}
      {collapsed && (
        <div className="flex justify-center pb-1">
          <button
            onClick={toggleCollapsed}
            title="Expandir menú"
            className="flex size-7.5 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <Icon icon="ph:sidebar-simple-light" className="size-4.5" />
          </button>
        </div>
      )}

      {/* Selector de empresa */}
      <div className={cn('pb-3', collapsed ? 'flex justify-center px-0' : 'px-3')}>
        <EmpresaSwitcher collapsed={collapsed} />
      </div>

      {/* Buscar (⌘K): descubribilidad del command palette. */}
      <div className={cn('pb-1', collapsed ? 'flex justify-center px-2.5' : 'px-3')}>
        <BuscarItem collapsed={collapsed} mac={mac} />
      </div>

      {/* Navegación */}
      <nav
        className={cn(
          'flex flex-1 flex-col gap-0.5 overflow-y-auto py-1',
          collapsed ? 'items-center px-2.5' : 'px-3',
        )}
      >
        {NAV_ITEMS.map(({ href, label, icon }) => (
          <NavItem
            key={href}
            href={href}
            label={label}
            icon={icon}
            collapsed={collapsed}
            active={href === '/' ? pathname === '/' : pathname.startsWith(href)}
          />
        ))}
      </nav>

      {/* Footer: Ayuda + cuenta */}
      <div
        className={cn(
          'flex flex-col gap-1 border-t py-2.5',
          collapsed ? 'items-center px-2.5' : 'px-3',
        )}
      >
        <NavItem
          href="/ayuda"
          label="Ayuda"
          icon="ph:question-light"
          collapsed={collapsed}
          active={pathname.startsWith('/ayuda')}
        />
        <AccountMenu collapsed={collapsed} />
      </div>
    </aside>
  );
}

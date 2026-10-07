'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { cn } from '@/lib/utils';
import { iniciales } from '@/lib/empresa-visual';
import { esWeb } from '@/lib/modo';
import { useAuth } from '@/providers/auth-provider';
import { Icon } from '@/components/ui/icon';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

/** Página pública que detecta el sistema y ofrece la descarga (con UTMs). */
const URL_DESCARGAR_APP =
  'https://todoconta.com/descargar?utm_source=app-web&utm_medium=menu-cuenta&utm_campaign=app-escritorio';

/**
 * Pill de cuenta: avatar con iniciales (corona si es Fundador) + email. Abre
 * el menú "Mi cuenta" con Ajustes, Suscripción y cuenta (página interna), y
 * Cerrar sesión. En la web agrega "Descargar app de escritorio".
 *
 * - Navegación clásica: footer del sidebar, abre hacia arriba.
 * - `variant="rail"` (espacios): solo el avatar abajo del riel, abre a la
 *   derecha.
 */
export function AccountMenu({
  collapsed,
  variant = 'sidebar',
}: {
  collapsed: boolean;
  variant?: 'sidebar' | 'rail';
}) {
  const [web, setWeb] = useState(false);
  useEffect(() => {
    setWeb(esWeb());
  }, []);
  const router = useRouter();
  const { license, logout } = useAuth();

  const email = license?.email ?? null;
  const esFundador = license?.plan === 'founder' || !!license?.is_founder;
  const plan = esFundador
    ? 'Fundador'
    : license?.plan === 'premium'
      ? 'Premium'
      : license?.plan === 'trial'
        ? 'Prueba'
        : 'Gratis';

  const avatar = (
    <span className="relative flex size-8.5 shrink-0 items-center justify-center rounded-full bg-foreground text-xs font-bold text-background">
      {email ? iniciales(email) : <Icon icon="ph:user-light" className="size-4" />}
      {esFundador && (
        <span className="absolute -left-1 -top-1.5 -rotate-[18deg] text-foreground">
          <Icon icon="ph:crown-simple-fill" className="size-3" />
        </span>
      )}
    </span>
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          title={collapsed && email ? email : undefined}
          className={cn(
            'flex items-center gap-2.5 rounded-xl border border-transparent text-left transition-colors',
            'hover:border-border hover:bg-card data-[state=open]:border-border data-[state=open]:bg-card',
            collapsed ? 'justify-center p-1' : 'w-full px-2 py-1.5',
          )}
        >
          {avatar}
          {!collapsed && (
            <>
              <span className="flex min-w-0 flex-1 flex-col gap-px">
                <span className="truncate text-[13px] font-semibold leading-tight text-foreground">
                  Mi cuenta
                </span>
                {email && (
                  <span className="truncate text-[11.5px] text-muted-foreground">
                    {email}
                  </span>
                )}
              </span>
              <Icon
                icon="ph:caret-up-light"
                className="size-4 shrink-0 text-muted-foreground"
              />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        side={collapsed || variant === 'rail' ? 'right' : 'top'}
        align={collapsed || variant === 'rail' ? 'end' : 'start'}
        className={cn(
          'rounded-xl',
          collapsed ? 'w-60' : 'w-[var(--radix-dropdown-menu-trigger-width)]',
        )}
      >
        <div className="px-3 pb-2 pt-2.5">
          <div className="mb-0.5 flex items-center justify-between gap-2">
            <span className="text-[15px] font-bold text-foreground">Mi cuenta</span>
            <span className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2.5 py-0.5 text-[11px] font-semibold text-foreground">
              {esFundador && <Icon icon="ph:crown-simple-fill" className="size-3" />}
              {plan}
            </span>
          </div>
          {email && (
            <span className="block truncate text-[11.5px] text-muted-foreground">
              {email}
            </span>
          )}
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => router.push('/ajustes')}
          className="gap-2.5 rounded-lg"
        >
          <Icon icon="ph:gear-light" className="size-4 text-muted-foreground" />
          Ajustes
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => router.push('/suscripcion')}
          className="gap-2.5 rounded-lg"
        >
          <Icon icon="ph:credit-card-light" className="size-4 text-muted-foreground" />
          Suscripción y cuenta
        </DropdownMenuItem>
        {/* Entrada fija de la app de escritorio (F3/F4): solo en la web y con la
            navegación nueva; la clásica se queda como estaba. */}
        {web && variant === 'rail' && (
          <DropdownMenuItem
            onSelect={() => window.open(URL_DESCARGAR_APP, '_blank', 'noopener')}
            className="gap-2.5 rounded-lg"
          >
            <Icon icon="ph:desktop-light" className="size-4 text-muted-foreground" />
            Descargar app de escritorio
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() => logout()}
          className="gap-2.5 rounded-lg text-destructive focus:bg-destructive/10 focus:text-destructive"
        >
          <Icon icon="ph:sign-out-light" className="size-4" />
          Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

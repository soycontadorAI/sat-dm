'use client';

import type { CSSProperties } from 'react';

import { Icon } from '@/components/ui/icon';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Button } from '@/components/ui/button';
import { useAnuncios } from '@/lib/anuncios';
import { useServer } from '@/providers/server-provider';
import { NotificationItem } from './notification-item';

const NO_DRAG: CSSProperties & { WebkitAppRegion?: string } = {
  WebkitAppRegion: 'no-drag',
};

/**
 * Campana de notificaciones para la Titlebar. Muestra anuncios traídos
 * desde el JSON remoto de TodoConta. El popover está cubierto por la
 * regla global de `no-drag` para el wrapper de Radix Popper; el botón
 * trigger queda dentro de la franja `WebkitAppRegion: drag` de la
 * Titlebar y necesita su propio `no-drag` inline.
 */
export function Bell() {
  const feed = useAnuncios();
  const { isRead, markRead, markAllRead, loading } = feed;
  // Modo de grabación (tutoriales): la campana sin anuncios ni punto de no
  // leídos; envejecen el video. No se anuncia en pantalla.
  const { modoGrabacion } = useServer();
  const anuncios = modoGrabacion ? [] : feed.anuncios;
  const unreadCount = modoGrabacion ? 0 : feed.unreadCount;

  const label =
    unreadCount > 0
      ? `Notificaciones (${unreadCount} sin leer)`
      : 'Notificaciones';

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={label}
          title={label}
          className="relative inline-flex size-7 items-center justify-center rounded-md text-foreground transition-colors hover:bg-secondary/60 focus-visible:outline-2 focus-visible:outline-ring"
          style={NO_DRAG}
        >
          <Icon icon="ph:bell-light" className="size-4" />
          {unreadCount > 0 && (
            <span
              className="absolute right-1 top-1 size-1.5 rounded-full bg-destructive"
              aria-hidden
            />
          )}
        </button>
      </PopoverTrigger>

      <PopoverContent align="end" sideOffset={6} className="w-80 p-0">
        <div className="flex items-center justify-between border-b px-3 py-2">
          <span className="text-sm font-semibold">Notificaciones</span>
          {anuncios.length > 0 && unreadCount > 0 && (
            <Button
              variant="ghost"
              size="xs"
              onClick={markAllRead}
              className="text-xs"
            >
              Marcar todo leído
            </Button>
          )}
        </div>

        <div className="max-h-96 overflow-y-auto overscroll-contain">
          {anuncios.length === 0 ? (
            <div className="flex flex-col items-center gap-2 px-4 py-10 text-center">
              <Icon icon="ph:bell-slash-light" className="size-6 text-muted-foreground" />
              <p className="text-xs text-muted-foreground">
                {loading ? 'Cargando…' : 'No tienes notificaciones nuevas.'}
              </p>
            </div>
          ) : (
            <ul className="divide-y">
              {anuncios.map((a) => (
                <NotificationItem
                  key={a.id}
                  anuncio={a}
                  read={isRead(a.id)}
                  onRead={() => markRead(a.id)}
                />
              ))}
            </ul>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

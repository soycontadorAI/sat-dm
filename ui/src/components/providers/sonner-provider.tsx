'use client';

import { useEffect, useState } from 'react';
import { Toaster } from 'sonner';
import { useTheme } from 'next-themes';

import { Icon } from '@/components/ui/icon';

/**
 * Monta el contenedor global de toasts (sonner). Coordina el tema visual
 * con next-themes para que claros/oscuros del toast hagan match con la app.
 * Patrón `mounted` evita mismatch de hidratación entre SSR y cliente.
 */
export function SonnerProvider() {
  const { resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  return (
    <Toaster
      theme={mounted ? ((resolvedTheme === 'dark' ? 'dark' : 'light') as 'light' | 'dark') : 'system'}
      position="top-right"
      richColors
      closeButton
      // Un toast "cargando" es trabajo automático en curso: gira en cian
      // (DESIGN.md, la regla del cian). Sonner no pinta el `icon` propio de
      // un toast.loading, así que va aquí.
      icons={{ loading: <Icon icon="ph:circle-notch-light" className="size-4 animate-spin text-auto" /> }}
    />
  );
}

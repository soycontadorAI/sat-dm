import type { Metadata } from 'next';
// Geist y Geist Mono (marca Señal) servidas desde la app: la CSP de la web no
// deja cargar Google Fonts y la app de escritorio corre sin red.
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './globals.css';
import { AuthProvider } from '@/providers/auth-provider';
import { NavegacionProvider } from '@/providers/navegacion-provider';
import { ServerProvider } from '@/providers/server-provider';
import { ThemeProvider } from '@/providers/theme-provider';
import { SonnerProvider } from '@/components/providers/sonner-provider';
import { Telemetria } from '@/components/providers/telemetria';
import { AppShell } from '@/components/layout/app-shell';
import { TooltipProvider } from '@/components/ui/tooltip';

export const metadata: Metadata = {
  title: 'TodoConta',
  description: 'TodoConta — descarga masiva de CFDIs y trámites del SAT',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <ServerProvider>
            <AuthProvider>
              {/* Clásica o espacios (F3): dentro de Auth porque la regla del
                  2 de noviembre mira el plan, y arriba del login para que
                  ?labs=espacios se capture aunque no haya sesión. */}
              <NavegacionProvider>
                <TooltipProvider>
                  <AppShell>{children}</AppShell>
                </TooltipProvider>
              </NavegacionProvider>
            </AuthProvider>
          </ServerProvider>
          <SonnerProvider />
          <Telemetria />
        </ThemeProvider>
      </body>
    </html>
  );
}

import type { Metadata } from 'next';
// Geist y Geist Mono (marca Señal) servidas desde la app: la CSP de la web no
// deja cargar Google Fonts y la app de escritorio corre sin red.
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import './globals.css';
import { AuthProvider } from '@/providers/auth-provider';
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
              <TooltipProvider>
                <AppShell>{children}</AppShell>
              </TooltipProvider>
            </AuthProvider>
          </ServerProvider>
          <SonnerProvider />
          <Telemetria />
        </ThemeProvider>
      </body>
    </html>
  );
}

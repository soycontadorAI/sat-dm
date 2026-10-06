'use client';

import type { ReactNode } from 'react';
import { usePathname } from 'next/navigation';

import { esWeb } from '@/lib/modo';
import { PromoBanner } from '@/components/auth/promo-banner';
import { AvisoDescargasMes } from '@/components/planes/aviso-descargas';
import { GlobalShortcuts } from '@/components/layout/global-shortcuts';
import { Sidebar } from '@/components/layout/sidebar';
import { StartupSplash } from '@/components/layout/startup-splash';
import { StatusBar } from '@/components/layout/status-bar';
import { Titlebar } from '@/components/layout/titlebar';
import { useEfirmaReminder } from '@/hooks/use-efirma-reminder';
import { useSolicitudesWatcher } from '@/hooks/use-solicitudes-watcher';
import { useAuth, usePlanesV3 } from '@/providers/auth-provider';
import LoginPage from '@/app/login/page';

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  // Side-effect: dispara la notificación diaria si alguna e.firma del
  // catálogo vence en ≤30 días (dedup global por día en localStorage).
  useEfirmaReminder();
  // Side-effect: observa las solicitudes WS de TODAS las empresas (el agente
  // las resuelve en background con el poller) y notifica éxitos/fallas por
  // empresa — en rojo cuando algo falló o venció.
  useSolicitudesWatcher();

  const { license, loading } = useAuth();
  const planesV3 = usePlanesV3();
  // (Versión web) /conectar debe ser alcanzable SIN sesión: es la puerta de
  // entrada manual al agente (piloto/soporte) cuando aún no hay conexión.
  const pathname = usePathname();
  const esConectar = esWeb() && !!pathname && pathname.startsWith('/conectar');
  // (Versión web) La vuelta de Google (/acceso/google) tampoco necesita sesión:
  // esa página canjea el código y conecta con el agente por su cuenta.
  const esAcceso = esWeb() && !!pathname && pathname.startsWith('/acceso');
  const sinSesion = esConectar || esAcceso;

  if (loading && !sinSesion) {
    return (
      <div className="flex h-screen flex-col overflow-hidden">
        <Titlebar />
        <StartupSplash />
      </div>
    );
  }

  if (!license?.authenticated || sinSesion) {
    // Renderea el LoginPage inline (no navegamos). La URL no cambia; al
    // autenticarse, `useAuth()` re-renderea con el shell normal.
    return (
      <div className="flex h-screen flex-col overflow-hidden">
        <Titlebar />
        <div className="flex-1 overflow-y-auto">
          {sinSesion ? children : <LoginPage />}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Titlebar />
      {/* La ventana de fundadores cerró y no vuelve: el FounderBanner se
          eliminó (2026-07). PromoBanner (50% en el anual) se retira con los
          planes v3: con el interruptor encendido ya no se muestra (el archivo
          se queda para el banner de F5). */}
      {!planesV3 && <PromoBanner />}
      {/* Planes v3: descargas al SAT del mes del plan gratis (aviso + diálogo). */}
      {planesV3 && <AvisoDescargasMes />}
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 overflow-y-auto p-6 md:p-8">{children}</main>
      </div>
      <StatusBar />
      {/* Atajos de teclado + command palette: solo con sesión iniciada. */}
      <GlobalShortcuts />
    </div>
  );
}

'use client';

import { useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';

import { useEmpresas } from '@/hooks/use-empresas';
import { useServer } from '@/providers/server-provider';
import { notifyEfirmaVencimiento, notifyRenovacionPendiente } from '@/lib/notify';
import { semaforoVencimiento } from '@/lib/vencimiento';
import { RENOVACION_EFIRMA_HABILITADA } from '@/lib/features';

const STORAGE_KEY_PREFIX = 'sat-dm:efirma-notified:'; // + YYYY-MM-DD
const STORAGE_KEY_RENOVACION = 'sat-dm:renovacion-notified:'; // + YYYY-MM-DD

/**
 * Una sola notificación agregada al día si **alguna** e.firma del catálogo
 * vence en ≤30 días. El mensaje incluye el total y la más urgente. Aparte, una
 * al día si quedó una renovación de e.firma a medias (la app se cerró a mitad
 * del trámite), con acceso directo a la empresa para terminarla.
 *
 * Se dispara en mount + cada vez que la ventana recupera foco. Dedup
 * global por día (clave `efirma-notified:YYYY-MM-DD`) para evitar ruido
 * si el usuario alterna entre apps varias veces.
 *
 * Render: nada (side-effect only). Se monta una vez en AppShell.
 */
export function useEfirmaReminder(): void {
  const { empresas } = useEmpresas();
  const empresasRef = useRef(empresas);
  empresasRef.current = empresas;
  const router = useRouter();
  const routerRef = useRef(router);
  routerRef.current = router;
  // Modo de grabación (tutoriales): las empresas de demo traen e.firmas por
  // vencer a propósito; el recordatorio saldría en cuadro.
  const { modoGrabacion, isConnected } = useServer();
  const grabandoRef = useRef(modoGrabacion);
  grabandoRef.current = modoGrabacion;

  useEffect(() => {
    // Hasta que el agente responda (su /health dice si está en modo de
    // grabación) no se avisa nada.
    if (!isConnected) return;

    function comprobar() {
      const lista = empresasRef.current;
      if (lista.length === 0 || grabandoRef.current) return;

      const hoy = new Date().toISOString().slice(0, 10);
      avisarRenovacionPendiente(hoy);
      const flagKey = `${STORAGE_KEY_PREFIX}${hoy}`;
      try {
        if (window.localStorage.getItem(flagKey) === '1') return;
      } catch {
        return; // localStorage no disponible
      }

      const enRiesgo: Array<{ rfc: string; dias: number }> = [];
      for (const e of lista) {
        if (!e.metodos.includes('fiel')) continue;
        const s = semaforoVencimiento(e.vencimiento);
        if (!s) continue;
        if (s.dias <= 30) enRiesgo.push({ rfc: e.rfc, dias: s.dias });
      }
      if (enRiesgo.length === 0) return;

      enRiesgo.sort((a, b) => a.dias - b.dias); // más urgente primero
      notifyEfirmaVencimiento({ rfcs: enRiesgo });

      try {
        window.localStorage.setItem(flagKey, '1');
      } catch { /* noop */ }
    }

    function avisarRenovacionPendiente(hoy: string) {
      if (!RENOVACION_EFIRMA_HABILITADA) return;
      const e = empresasRef.current.find((x) => !x.archived_at && x.renovacion_pendiente);
      if (!e) return;
      const flagKey = `${STORAGE_KEY_RENOVACION}${hoy}`;
      try {
        if (window.localStorage.getItem(flagKey) === '1') return;
        window.localStorage.setItem(flagKey, '1');
      } catch {
        return;
      }
      notifyRenovacionPendiente({
        rfc: e.rfc,
        enviada: !!e.renovacion_pendiente?.numero_operacion,
        onVer: () => routerRef.current.push(`/empresas/detalle?rfc=${encodeURIComponent(e.rfc)}&renovar=1`),
      });
    }

    // Espera 1.5s en mount para no competir con el splash/handshake.
    const t = setTimeout(comprobar, 1_500);
    window.addEventListener('focus', comprobar);
    return () => {
      clearTimeout(t);
      window.removeEventListener('focus', comprobar);
    };
    // No depende de `empresas` directamente — usa ref para no recrear
    // el listener cada vez que cambia el catálogo (que sucede mucho).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isConnected]);
}

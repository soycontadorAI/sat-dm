'use client';

import { useEffect, useRef } from 'react';

import { useEmpresas } from '@/hooks/use-empresas';
import { useServer } from '@/providers/server-provider';
import { notifyEfirmaVencimiento } from '@/lib/notify';
import { semaforoVencimiento } from '@/lib/vencimiento';

const STORAGE_KEY_PREFIX = 'sat-dm:efirma-notified:'; // + YYYY-MM-DD

/**
 * Una sola notificación agregada al día si **alguna** e.firma del catálogo
 * vence en ≤30 días. El mensaje incluye el total y la más urgente.
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

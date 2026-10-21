'use client';

import { useEffect } from 'react';

import { useAuth } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';
import { tienePiloto } from '@/lib/calendario';
import { notifyPilotoAviso } from '@/lib/notify';
import { esAvisoDeToast, toastsDeAvisos } from '@/lib/piloto';
import type { PilotoAviso } from '@/lib/types';

const CADA_MS = 5 * 60_000;
const CLAVE_VISTOS = 'sat-dm:piloto-avisos-vistos';
const MAX_VISTOS = 200;

function leerVistos(): number[] {
  try {
    const v = JSON.parse(window.localStorage.getItem(CLAVE_VISTOS) ?? '[]');
    return Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : [];
  } catch {
    return [];
  }
}

function guardarVistos(ids: number[]) {
  try {
    window.localStorage.setItem(CLAVE_VISTOS, JSON.stringify(ids.slice(-MAX_VISTOS)));
  } catch {
    // sin storage: puede repetirse un toast en la siguiente sesión
  }
}

/**
 * Watcher global de la descarga automática: cada 5 min consulta
 * `/piloto/estado` y avisa (toast) los avisos sin leer de resumen,
 * cancelación y e.firma que aún no se hayan mostrado; si llegan muchos a la
 * vez, uno solo que manda al cuadro de control. No los marca como leídos: eso
 * lo hace el usuario en el panel del cuadro de control.
 *
 * Montar UNA sola vez en el shell (junto a useSolicitudesWatcher).
 */
export function usePilotoAvisos(): void {
  const { apiClient, isConnected } = useServer();
  const { license } = useAuth();
  const conPiloto = tienePiloto(license);

  useEffect(() => {
    if (!isConnected || !conPiloto) return;
    let cancelado = false;

    const tick = async () => {
      let avisos: PilotoAviso[];
      try {
        ({ avisos } = await apiClient.pilotoEstado());
      } catch {
        return; // sin piloto en el agente o reiniciando: se reintenta
      }
      if (cancelado) return;
      const vistos = leerVistos();
      const nuevos = avisos.filter((a) => !a.leido && esAvisoDeToast(a) && !vistos.includes(a.id));
      if (nuevos.length === 0) return;
      for (const t of toastsDeAvisos(nuevos)) notifyPilotoAviso(t);
      guardarVistos([...vistos, ...nuevos.map((a) => a.id)]);
    };

    void tick();
    const t = setInterval(() => void tick(), CADA_MS);
    return () => {
      cancelado = true;
      clearInterval(t);
    };
  }, [apiClient, isConnected, conPiloto]);
}

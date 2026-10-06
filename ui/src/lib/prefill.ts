'use client';

import { useEffect, useState } from 'react';

// ---------------------------------------------------------------------------
// Prellenado de pantallas desde una orden de ⌘K ("descargar recibidos de
// septiembre de ..."). La orden deja aquí los datos y navega; la pantalla los
// toma UNA vez al montarse (o al llegar el evento, si ya estaba abierta). Vive
// en memoria: la app es una SPA y el prellenado no debe sobrevivir a un reload
// ni quedarse en la URL.
// ---------------------------------------------------------------------------

export interface PrefillDescarga {
  rfc: string;
  /** YYYY-MM-DD */
  desde: string;
  hasta: string;
  /** E, R o A (los dos). */
  comprobante: 'E' | 'R' | 'A';
  /** "Recibidos de septiembre 2026, Distribuidora El Roble". */
  etiqueta: string;
}

export interface PrefillPortal {
  rfc: string;
  desde: string;
  hasta: string;
  /** El select de Descarga rápida usa RE para "Ambas". */
  tipo: 'E' | 'R' | 'RE';
  /**
   * Acceso con el que se entra al portal. Sin él, el de siempre (e.firma si la
   * empresa la tiene). La orden lo fija ("con contraseña").
   */
  metodo?: 'fiel' | 'ciec';
  etiqueta: string;
}

export interface PrefillDiot {
  rfc: string;
  /** YYYY-MM */
  periodo: string;
}

interface Prefills {
  descarga: PrefillDescarga;
  portal: PrefillPortal;
  diot: PrefillDiot;
}

type Clave = keyof Prefills;

const EVENTO = 'tc:prefill';
const almacen: { [K in Clave]?: Prefills[K] } = {};

export function ponerPrefill<K extends Clave>(clave: K, valor: Prefills[K]) {
  almacen[clave] = valor;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(EVENTO, { detail: clave }));
  }
}

export function tomarPrefill<K extends Clave>(clave: K): Prefills[K] | null {
  const v = almacen[clave] ?? null;
  delete almacen[clave];
  return v as Prefills[K] | null;
}

/** Sin consumirlo: para estados iniciales (p. ej. el periodo de la DIOT). */
export function verPrefill<K extends Clave>(clave: K): Prefills[K] | null {
  return (almacen[clave] ?? null) as Prefills[K] | null;
}

/**
 * Prellenado de una orden de ⌘K para una pantalla.
 *
 * - `inicial`: el que ya estaba pendiente al montar. Se lee en el primer render
 *   (para usarlo como estado inicial: un Select de Radix que cambia de valor
 *   justo después de montarse se queda en blanco) y se consume al montar.
 * - `nuevo`: el que llega con la pantalla ya abierta (otra orden). Cada entrega
 *   es un objeto nuevo, así que sirve como dependencia de un efecto.
 */
export function usePrefill<K extends Clave>(
  clave: K,
): { inicial: Prefills[K] | null; nuevo: Prefills[K] | null } {
  // verPrefill no consume: el inicializador puede correr dos veces en dev.
  const [inicial] = useState<Prefills[K] | null>(() => verPrefill(clave));
  const [nuevo, setNuevo] = useState<Prefills[K] | null>(null);
  useEffect(() => {
    // El inicial se consume aquí (una sola vez por montaje real).
    if (inicial && verPrefill(clave) === inicial) tomarPrefill(clave);
    const tomar = () => {
      const v = tomarPrefill(clave);
      if (v) setNuevo({ ...v });
    };
    // Uno que llegó entre el primer render y este efecto.
    tomar();
    const onPrefill = (e: Event) => {
      if ((e as CustomEvent<Clave>).detail === clave) tomar();
    };
    window.addEventListener(EVENTO, onPrefill);
    return () => window.removeEventListener(EVENTO, onPrefill);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clave]);
  return { inicial, nuevo };
}

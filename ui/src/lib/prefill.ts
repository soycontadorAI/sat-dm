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
 * Entrega el prellenado pendiente de `clave` (al montar o cuando llegue uno
 * nuevo) y lo consume. Cada entrega es un objeto nuevo, así que sirve como
 * dependencia de un efecto.
 */
export function usePrefill<K extends Clave>(clave: K): Prefills[K] | null {
  const [valor, setValor] = useState<Prefills[K] | null>(null);
  useEffect(() => {
    const tomar = () => {
      const v = tomarPrefill(clave);
      if (v) setValor({ ...v });
    };
    tomar();
    const onPrefill = (e: Event) => {
      if ((e as CustomEvent<Clave>).detail === clave) tomar();
    };
    window.addEventListener(EVENTO, onPrefill);
    return () => window.removeEventListener(EVENTO, onPrefill);
  }, [clave]);
  return valor;
}

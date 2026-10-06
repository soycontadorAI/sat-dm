'use client';

import { useCallback, useEffect, useState } from 'react';

import type { EspacioId } from '@/lib/navegacion';

// ---------------------------------------------------------------------------
// Recientes del panel de espacios: las últimas 3 pantallas por espacio, con la
// empresa con la que se abrieron. Solo en este equipo (localStorage), nunca se
// sincroniza ni sale de la instalación.
// ---------------------------------------------------------------------------

const LLAVE = 'tc:recientes';
const POR_ESPACIO = 3;
/** Evento window: una pantalla registró (o enriqueció) un reciente. */
export const EVENTO_RECIENTE = 'tc:reciente';

export interface Reciente {
  /** Destino de navegacion.ts. */
  id: string;
  href: string;
  /** "Recibidos sep 2026, Distribuidora El Roble". */
  label: string;
  icon: string;
  /** Empresa activa al abrirlo; al volver se cambia a ella. */
  rfc?: string | null;
  ts: number;
}

type Almacen = Partial<Record<EspacioId, Reciente[]>>;

function leer(): Almacen {
  try {
    const raw = localStorage.getItem(LLAVE);
    return raw ? (JSON.parse(raw) as Almacen) : {};
  } catch {
    return {};
  }
}

function guardar(a: Almacen) {
  try {
    localStorage.setItem(LLAVE, JSON.stringify(a));
  } catch {
    /* sin storage: Recientes vacío */
  }
}

/** Ventana en la que un reciente con etiqueta propia no se pisa con la genérica. */
const VENTANA_ETIQUETA_MS = 5_000;

/**
 * Agrega (o sube al primer lugar) un reciente del espacio.
 *
 * `generico`: lo registra el shell al cambiar de ruta, con el nombre del
 * destino. Si esa misma pantalla acaba de entrar con una etiqueta propia (una
 * orden de ⌘K: "Recibidos sep 2026, El Roble"), se respeta la propia.
 */
export function registrarReciente(
  espacio: EspacioId,
  r: Omit<Reciente, 'ts'>,
  opciones: { generico?: boolean } = {},
) {
  const a = leer();
  const previa = a[espacio] ?? [];
  const mismo = (x: Reciente) => x.href === r.href && (x.rfc ?? null) === (r.rfc ?? null);
  const primero = previa[0];
  if (
    opciones.generico &&
    primero &&
    mismo(primero) &&
    primero.label !== r.label &&
    Date.now() - primero.ts < VENTANA_ETIQUETA_MS
  ) {
    return;
  }
  a[espacio] = [{ ...r, ts: Date.now() }, ...previa.filter((x) => !mismo(x))].slice(0, POR_ESPACIO);
  guardar(a);
  window.dispatchEvent(new Event(EVENTO_RECIENTE));
}

export function useRecientes(espacio: EspacioId | null): Reciente[] {
  const [recientes, setRecientes] = useState<Reciente[]>([]);

  const cargar = useCallback(() => {
    if (!espacio) {
      setRecientes([]);
      return;
    }
    setRecientes(leer()[espacio] ?? []);
  }, [espacio]);

  useEffect(() => {
    cargar();
    window.addEventListener(EVENTO_RECIENTE, cargar);
    window.addEventListener('storage', cargar);
    return () => {
      window.removeEventListener(EVENTO_RECIENTE, cargar);
      window.removeEventListener('storage', cargar);
    };
  }, [cargar]);

  return recientes;
}

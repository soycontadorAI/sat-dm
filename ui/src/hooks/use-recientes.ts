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

/** Agrega (o sube al primer lugar) un reciente del espacio. */
export function registrarReciente(espacio: EspacioId, r: Omit<Reciente, 'ts'>) {
  const a = leer();
  const lista = (a[espacio] ?? []).filter(
    (x) => !(x.href === r.href && (x.rfc ?? null) === (r.rfc ?? null)),
  );
  a[espacio] = [{ ...r, ts: Date.now() }, ...lista].slice(0, POR_ESPACIO);
  guardar(a);
  window.dispatchEvent(new Event(EVENTO_RECIENTE));
}

/**
 * Para que una pantalla ponga una etiqueta más rica que el nombre del destino
 * (p. ej. Descargar CFDIs después de una orden: "Recibidos sep 2026, El
 * Roble"). Reemplaza el reciente de esa ruta y empresa.
 */
export function enriquecerReciente(espacio: EspacioId, r: Omit<Reciente, 'ts'>) {
  registrarReciente(espacio, r);
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

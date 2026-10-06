'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';

import { fetchAnuncios } from './fetcher';
import { getReadMap, markAllRead as storageMarkAllRead, markRead as storageMarkRead } from './storage';
import type { Anuncio } from './types';

export type { Anuncio, AnuncioCategoria } from './types';

/**
 * Un anuncio con más de estos días de publicado cuenta como leído: sigue en la
 * lista, pero ya no suma a "sin leer" ni se marca como nuevo. Para quitarlo de
 * la lista, `expiresAt` en el JSON.
 */
export const DIAS_PARA_DAR_POR_LEIDO = 90;

/** Ids de los anuncios publicados hace más de DIAS_PARA_DAR_POR_LEIDO días. */
export function idsViejos(anuncios: Anuncio[], ahora = Date.now()): Set<string> {
  const limite = ahora - DIAS_PARA_DAR_POR_LEIDO * 86_400_000;
  const viejos = new Set<string>();
  for (const a of anuncios) {
    const t = Date.parse(a.publishedAt);
    if (Number.isFinite(t) && t < limite) viejos.add(a.id);
  }
  return viejos;
}

interface UseAnunciosState {
  anuncios: Anuncio[];
  unreadCount: number;
  isRead: (id: string) => boolean;
  markRead: (id: string) => void;
  markAllRead: () => void;
  refresh: () => Promise<void>;
  loading: boolean;
}

/**
 * Hook para la campana. Trae anuncios desde el JSON remoto con cache de
 * 1h, mantiene estado de leídos en localStorage y revalida cuando la
 * ventana recupera foco.
 *
 * Idempotente y seguro de montar varias veces; el cache vive en módulo.
 */
export function useAnuncios(): UseAnunciosState {
  const [anuncios, setAnuncios] = useState<Anuncio[]>([]);
  const [readMap, setReadMap] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);

  const cargar = useCallback(async (force = false) => {
    setLoading(true);
    try {
      const lista = await fetchAnuncios({ force });
      setAnuncios(lista);
    } finally {
      setLoading(false);
    }
  }, []);

  // Carga inicial + sincronizar mapa de leídos.
  useEffect(() => {
    setReadMap(getReadMap());
    cargar(false);
  }, [cargar]);

  // Revalida al recuperar foco (sin forzar cache; respeta TTL).
  useEffect(() => {
    function onFocus() {
      cargar(false);
    }
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [cargar]);

  const viejos = useMemo(() => idsViejos(anuncios), [anuncios]);

  const unreadCount = useMemo(
    () => anuncios.reduce((n, a) => (readMap[a.id] || viejos.has(a.id) ? n : n + 1), 0),
    [anuncios, readMap, viejos],
  );

  const isRead = useCallback(
    (id: string) => readMap[id] === true || viejos.has(id),
    [readMap, viejos],
  );

  const markRead = useCallback((id: string) => {
    setReadMap(storageMarkRead(id));
  }, []);

  const markAllRead = useCallback(() => {
    setReadMap(storageMarkAllRead(anuncios.map((a) => a.id)));
  }, [anuncios]);

  return {
    anuncios,
    unreadCount,
    isRead,
    markRead,
    markAllRead,
    refresh: () => cargar(true),
    loading,
  };
}

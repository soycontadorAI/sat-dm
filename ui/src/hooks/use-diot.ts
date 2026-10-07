'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { useEmpresas } from '@/hooks/use-empresas';
import { mensajeDeError } from '@/lib/errores';
import { usePrefill } from '@/lib/prefill';
import type {
  CatalogosDiot,
  EstadoDiot,
  FilaDiot,
  HallazgoDiot,
  ResumenPrellenadoDiot,
} from '@/lib/types';

const DEBOUNCE_MS = 500;

/** Periodo por default: el mes anterior al actual (el que se declara). */
export function periodoAnterior(hoy = new Date()): string {
  const d = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** Renglón nuevo para captura manual (proveedor nacional, manifiesto Sí). */
export function nuevaFilaDiot(catalogos: CatalogosDiot | null): FilaDiot {
  const fila: FilaDiot = {
    tipo_tercero: '04',
    tipo_operacion: '85',
    rfc: '',
    id_fiscal: '',
    nombre_extranjero: '',
    pais: '',
    lugar_jurisdiccion: '',
    manifiesto: '01',
    origen: 'manual',
  };
  for (const campo of catalogos?.campos ?? []) {
    if (campo.tipo === 'entero') fila[campo.clave] = 0;
  }
  return fila;
}

interface UseDiotState {
  rfcActivo: string | null;
  periodo: string;
  setPeriodo: (p: string) => void;
  filas: FilaDiot[];
  errores: HallazgoDiot[];
  advertencias: HallazgoDiot[];
  /** Origen del último guardado: 'prellenado' | 'manual' | null (sin estado). */
  origen: EstadoDiot['origen'];
  resumen: ResumenPrellenadoDiot | null;
  catalogos: CatalogosDiot | null;
  cargando: boolean;
  guardando: boolean;
  prellenando: boolean;
  setCampo: (index: number, campo: string, valor: string | number) => void;
  agregarFila: () => void;
  eliminarFila: (index: number) => void;
  prellenar: () => Promise<void>;
}

/**
 * Estado de la DIOT ligado a la empresa activa Y al periodo seleccionado.
 *
 * - Al cambiar RFC o periodo restaura la tabla desde `GET /diot/estado`.
 * - Cada edición dispara un PUT (full-replace) con debounce de 500 ms; el
 *   agente re-valida y devuelve errores/advertencias frescos.
 * - Guard de época contra respuestas fuera de orden (mismo patrón que
 *   `use-calculadora`).
 */
export function useDiot(): UseDiotState {
  const { apiClient, isConnected } = useServer();
  const { empresas, loading: empresasLoading } = useEmpresas();

  const rfcActivo = empresas.find((e) => e.default)?.rfc ?? null;

  // Orden de ⌘K ("DIOT de agosto de ..."): la pantalla abre en ese periodo.
  const { inicial: prefillInicial, nuevo: prefillNuevo } = usePrefill('diot');
  const [periodo, setPeriodoState] = useState<string>(
    () => prefillInicial?.periodo ?? periodoAnterior(),
  );
  const [filas, setFilas] = useState<FilaDiot[]>([]);
  const [errores, setErrores] = useState<HallazgoDiot[]>([]);
  const [advertencias, setAdvertencias] = useState<HallazgoDiot[]>([]);
  const [origen, setOrigen] = useState<EstadoDiot['origen']>(null);
  const [resumen, setResumen] = useState<ResumenPrellenadoDiot | null>(null);
  const [catalogos, setCatalogos] = useState<CatalogosDiot | null>(null);
  const [cargando, setCargando] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [prellenando, setPrellenando] = useState(false);

  const epochRef = useRef(0);
  const filasRef = useRef(filas);
  filasRef.current = filas;
  // true mientras las filas en memoria son las del servidor (nada que guardar).
  const sinCambiosRef = useRef(true);

  const aplicarEstado = useCallback((estado: EstadoDiot) => {
    sinCambiosRef.current = true;
    setFilas(estado.filas ?? []);
    setErrores(estado.errores ?? []);
    setAdvertencias(estado.advertencias ?? []);
    setOrigen(estado.origen ?? null);
    if (estado.resumen) setResumen(estado.resumen);
  }, []);

  // Catálogos (una sola vez por sesión).
  useEffect(() => {
    if (!isConnected || catalogos) return;
    let activo = true;
    apiClient
      .diotCatalogos()
      .then((c) => {
        if (activo) setCatalogos(c);
      })
      .catch(() => {
        // Los selects usan fallbacks mínimos; no molestamos con toast.
      });
    return () => {
      activo = false;
    };
  }, [apiClient, isConnected, catalogos]);

  // Restaurar la tabla al cambiar empresa o periodo.
  useEffect(() => {
    if (!isConnected || empresasLoading) return;
    if (!rfcActivo) {
      setCargando(false);
      return;
    }
    let activo = true;
    epochRef.current += 1;
    const epoch = epochRef.current;
    setCargando(true);
    setResumen(null);

    apiClient
      .diotEstado(rfcActivo, periodo)
      .then((estado) => {
        if (!activo || epochRef.current !== epoch) return;
        aplicarEstado(estado);
      })
      .catch((e) => {
        if (!activo || epochRef.current !== epoch) return;
        toast.error(mensajeDeError(e), { id: 'diot-estado' });
      })
      .finally(() => {
        if (activo && epochRef.current === epoch) setCargando(false);
      });

    return () => {
      activo = false;
    };
  }, [apiClient, isConnected, empresasLoading, rfcActivo, periodo, aplicarEstado]);

  // Guardado reactivo con debounce tras cada edición.
  useEffect(() => {
    if (cargando || !rfcActivo || sinCambiosRef.current) return;
    const epoch = epochRef.current;
    const timer = setTimeout(async () => {
      if (epochRef.current !== epoch) return;
      setGuardando(true);
      try {
        const estado = await apiClient.diotGuardar(rfcActivo, periodo, filasRef.current);
        if (epochRef.current !== epoch) return;
        // Solo se refrescan las validaciones: las filas locales pueden llevar
        // ediciones más nuevas que la respuesta.
        setErrores(estado.errores ?? []);
        setAdvertencias(estado.advertencias ?? []);
        setOrigen(estado.origen ?? null);
      } catch (e) {
        if (epochRef.current !== epoch) return;
        toast.error(mensajeDeError(e), { id: 'diot-guardar' });
      } finally {
        setGuardando(false);
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [apiClient, filas, cargando, rfcActivo, periodo]);

  const setPeriodo = useCallback((p: string) => {
    epochRef.current += 1;
    setPeriodoState(p);
  }, []);

  // Otra orden de ⌘K con la pantalla ya abierta.
  useEffect(() => {
    if (prefillNuevo?.periodo) setPeriodo(prefillNuevo.periodo);
  }, [prefillNuevo, setPeriodo]);

  const marcarEdicion = useCallback(() => {
    epochRef.current += 1;
    sinCambiosRef.current = false;
  }, []);

  const setCampo = useCallback(
    (index: number, campo: string, valor: string | number) => {
      marcarEdicion();
      setFilas((prev) =>
        prev.map((fila, i) => (i === index ? { ...fila, [campo]: valor } : fila)),
      );
    },
    [marcarEdicion],
  );

  const agregarFila = useCallback(() => {
    marcarEdicion();
    setFilas((prev) => [...prev, nuevaFilaDiot(catalogos)]);
  }, [marcarEdicion, catalogos]);

  const eliminarFila = useCallback(
    (index: number) => {
      marcarEdicion();
      setFilas((prev) => prev.filter((_, i) => i !== index));
    },
    [marcarEdicion],
  );

  const prellenar = useCallback(async () => {
    if (!rfcActivo) return;
    epochRef.current += 1;
    const epoch = epochRef.current;
    setPrellenando(true);
    try {
      const estado = await apiClient.diotPrellenar(rfcActivo, periodo);
      if (epochRef.current !== epoch) return;
      aplicarEstado(estado);
      const n = estado.resumen?.proveedores ?? estado.filas.length;
      const excluidos = estado.resumen?.cfdis_excluidos ?? 0;
      const sufijoExcluidos =
        excluidos > 0 ? ` · ${excluidos} excluido${excluidos === 1 ? '' : 's'} manualmente en Comprobantes` : '';
      toast.success(
        n > 0
          ? `${n} proveedor${n === 1 ? '' : 'es'} prellenado${n === 1 ? '' : 's'} desde ${estado.resumen?.cfdis_considerados ?? 0} CFDIs${sufijoExcluidos}`
          : `No hay CFDIs recibidos en el buffer para este periodo${sufijoExcluidos}`,
        { id: 'diot-prellenar' },
      );
    } catch (e) {
      if (epochRef.current === epoch) toast.error(mensajeDeError(e), { id: 'diot-prellenar' });
    } finally {
      if (epochRef.current === epoch) setPrellenando(false);
    }
  }, [apiClient, rfcActivo, periodo, aplicarEstado]);

  return {
    rfcActivo,
    periodo,
    setPeriodo,
    filas,
    errores,
    advertencias,
    origen,
    resumen,
    catalogos,
    cargando,
    guardando,
    prellenando,
    setCampo,
    agregarFila,
    eliminarFila,
    prellenar,
  };
}

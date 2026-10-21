'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { ApiError } from '@/lib/api-client';
import { VERIFICAR_POLL_INTERVAL_MS } from '@/lib/constants';
import type { ResumenServido, Solicitud, SolicitudRequest } from '@/lib/types';
import { resumenDeRespuesta } from '@/lib/servir-base';
import { mensajeDeError } from '@/lib/errores';

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

export type DescargaState =
  | 'idle'
  | 'requesting'
  | 'polling'
  | 'ready'
  | 'downloading'
  | 'done'
  | 'error';

// ---------------------------------------------------------------------------
// LocalStorage: flujo activo POR EMPRESA
//
// La llave lleva el RFC (`sat-dm-request-id:XAXX010101000`). Antes era una
// llave global única: al cambiar de empresa, la página retomaba el polling de
// una solicitud de OTRA empresa y el "Estado de la solicitud" aparecía en
// todas (y /verificar iba firmado con la FIEL equivocada). Ver PR.
// ---------------------------------------------------------------------------

// Llave global legacy (pre-fix). Se elimina al montar para que una solicitud
// vieja no "resucite" en todas las empresas tras actualizar.
const LS_LEGACY_KEY = 'sat-dm-request-id';
// Una solicitud pendiente >72h ya venció para el SAT: no vale la pena retomarla.
const RESUME_MAX_AGE_MS = 72 * 60 * 60 * 1000;

function lsKey(rfc: string): string {
  return `sat-dm-request-id:${rfc}`;
}

function loadRequestId(rfc: string | null): string | null {
  if (typeof window === 'undefined' || !rfc) return null;
  const raw = localStorage.getItem(lsKey(rfc));
  if (!raw) return null;
  try {
    const { id, ts } = JSON.parse(raw) as { id?: string; ts?: number };
    if (!id) return null;
    if (typeof ts === 'number' && Date.now() - ts > RESUME_MAX_AGE_MS) {
      localStorage.removeItem(lsKey(rfc));
      return null;
    }
    return id;
  } catch {
    localStorage.removeItem(lsKey(rfc));
    return null;
  }
}

function saveRequestId(rfc: string | null, id: string | null) {
  if (typeof window === 'undefined' || !rfc) return;
  if (id) {
    localStorage.setItem(lsKey(rfc), JSON.stringify({ id, ts: Date.now() }));
  } else {
    localStorage.removeItem(lsKey(rfc));
  }
}

/**
 * ¿El estado del catálogo local es terminal para el flujo activo?
 * - "descargada": el poller del agente (o una sesión anterior) ya bajó los
 *   paquetes — no hay nada que verificar ni descargar.
 * - "vencida"/"4"/"5": la solicitud murió en el SAT; el catálogo ya guarda el
 *   mensaje. ("3" NO es terminal: está lista y el flujo debe descargarla.)
 */
function estadoCatalogoFinal(
  estado: string | undefined,
): 'descargada' | 'fallida' | null {
  if (estado === 'descargada') return 'descargada';
  if (estado === 'vencida' || estado === '4' || estado === '5') return 'fallida';
  return null;
}

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface UseDescargaReturn {
  state: DescargaState;
  requestId: string | null;
  codEstado: number | null;
  mensaje: string | null;
  numeroCfdis: number | null;
  packageIds: string[];
  archivosDescargados: string[];
  error: string | null;
  /** Lo que se sirvió de la base en la última solicitud CFDI (null si nada). */
  resumen: ResumenServido | null;
  solicitar: (request: SolicitudRequest) => Promise<void>;
  descargar: () => Promise<void>;
  reset: () => void;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

/**
 * Flujo activo de descarga WS de UNA empresa (`rfc`): solicitar → polling →
 * descarga automática. El estado persistido en localStorage va aislado por
 * RFC, así que cambiar de empresa nunca arrastra la solicitud de otra.
 */
export function useDescarga(
  rfc: string | null,
  pollIntervalMs: number = VERIFICAR_POLL_INTERVAL_MS,
): UseDescargaReturn {
  const { apiClient } = useServer();

  const [state, setState] = useState<DescargaState>('idle');
  const [requestId, setRequestId] = useState<string | null>(null);
  const [codEstado, setCodEstado] = useState<number | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const [numeroCfdis, setNumeroCfdis] = useState<number | null>(null);
  const [packageIds, setPackageIds] = useState<string[]>([]);
  const [archivosDescargados, setArchivosDescargados] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [resumen, setResumen] = useState<ResumenServido | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);
  // El RFC vigente, para que los callbacks asíncronos no escriban en la llave
  // de otra empresa si el usuario cambió mientras el request estaba en vuelo.
  const rfcRef = useRef(rfc);
  // ID de la solicitud cuyo flujo sigue VIVO. Un /verificar contra el SAT
  // puede tardar minutos (reintentos del agente); si mientras tanto el flujo
  // se cerró (catálogo resuelto, reset, cambio de empresa), su respuesta
  // tardía se descarta comparando contra este ref.
  const pollIdRef = useRef<string | null>(null);
  // RequestID para la cual ya disparamos la descarga automática al pasar a 'ready'.
  // Permite re-descargar manualmente (descargar() puede llamarse de nuevo) sin
  // que el efecto auto-dispare otra vez por el mismo state→ready transition.
  const autoDescargaDispatchedRef = useRef<string | null>(null);
  // Generación de `solicitar`: sube al enviar, en reset() y al cambiar de
  // empresa. La respuesta de /solicitar/desde-base (que puede tardar mientras
  // se piden varios rangos) solo se aplica si su generación sigue vigente.
  const solicitarGenRef = useRef(0);

  // -----------------------------------------------------------------------
  // Cleanup interval
  // -----------------------------------------------------------------------

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    // El loop murió: cualquier respuesta en vuelo de este flujo se descarta.
    pollIdRef.current = null;
  }, []);

  // Evita encimar verificaciones si el SAT responde más lento que el intervalo.
  const pollBusyRef = useRef(false);

  // -----------------------------------------------------------------------
  // Convergencia con el catálogo local
  // -----------------------------------------------------------------------

  /**
   * Cierra el flujo activo si el catálogo local ya tiene la solicitud en un
   * estado terminal. El poller del agente verifica y descarga solicitudes en
   * background (por TODAS las empresas), así que puede resolverla mientras la
   * página no la vigila; sin esta convergencia, la llave de localStorage
   * revivía un "Verificando estado…" eterno sobre una solicitud ya Descargada
   * (y en el peor caso volvía a bajar los paquetes).
   *
   * Devuelve true si el flujo quedó cerrado (o ya estaba cerrado).
   */
  const cerrarSiCatalogoResuelto = useCallback(
    async (id: string): Promise<boolean> => {
      const rfcActual = rfcRef.current;
      if (!rfcActual) return false;
      let sol: Solicitud | undefined;
      try {
        const res = await apiClient.listSolicitudes(rfcActual);
        sol = res.solicitudes.find((s) => s.id_solicitud === id);
      } catch {
        // El agente local no respondió: sigue el flujo normal contra el SAT.
        return false;
      }
      if (!mountedRef.current || pollIdRef.current !== id) return true;
      const final = estadoCatalogoFinal(sol?.estado);
      if (!final) return false;

      stopPolling();
      pollIdRef.current = null;
      saveRequestId(rfcRef.current, null);
      if (final === 'descargada') {
        // Ya la bajó el poller: flujo limpio. La fila "Descargada" queda en
        // Solicitudes recientes y el watcher global ya notificó el éxito.
        setState('idle');
        setRequestId(null);
        setCodEstado(null);
        setMensaje(null);
        setNumeroCfdis(null);
        setPackageIds([]);
        // El resumen se queda: lo servido de la base sigue siendo cierto y solo
        // se limpia con "Nueva solicitud", al cambiar de empresa o al enviar otra.
      } else {
        setError(sol?.mensaje || 'La solicitud fue rechazada o venció en el SAT.');
        setState('error');
      }
      return true;
    },
    [apiClient, stopPolling],
  );

  // -----------------------------------------------------------------------
  // Poll once
  // -----------------------------------------------------------------------

  const pollOnce = useCallback(
    async (id: string) => {
      // Catálogo primero (consulta local, barata): si el poller del agente ya
      // resolvió la solicitud, cierra el flujo sin tocar al SAT. Va ANTES del
      // candado pollBusy para poder cerrar aunque un /verificar lento (los
      // reintentos del agente pueden tardar minutos) siga en vuelo.
      if (await cerrarSiCatalogoResuelto(id)) return;

      if (pollBusyRef.current) return;
      pollBusyRef.current = true;
      try {
        const res = await apiClient.verificar({ id_solicitud: id, poll: false });
        // Flujo cerrado mientras verificábamos (catálogo/reset/cambio de
        // empresa): la respuesta tardía ya no manda.
        if (!mountedRef.current || pollIdRef.current !== id) return;

        // Sin cod_estado = el SAT no reconoce la solicitud para esta e.firma
        // (típicamente pertenece a otra empresa, o ya caducó en el SAT).
        // Cerramos el flujo y limpiamos para no pollearla eternamente.
        if (!res.cod_estado) {
          setError(
            res.mensaje ||
              'El SAT no reconoce esta solicitud para la empresa activa. Crea una nueva solicitud.',
          );
          setState('error');
          stopPolling();
          saveRequestId(rfcRef.current, null);
          return;
        }

        // SAT returns cod_estado as string, coerce to number
        const codEstadoNum = Number(res.cod_estado);
        setCodEstado(codEstadoNum);
        setMensaje(res.mensaje);
        setNumeroCfdis(res.numero_cfdis);

        if (codEstadoNum === 3 || res.terminada) {
          // Ready to download
          setPackageIds(res.package_ids);
          setState('ready');
          stopPolling();
        } else if (codEstadoNum === 4 || codEstadoNum === 5 || codEstadoNum === 6) {
          // Error, rechazada o vencida: estado final — el agente ya lo persistió
          // en el catálogo; aquí cerramos el flujo activo.
          setError(res.mensaje || 'La solicitud fue rechazada o tuvo un error.');
          setState('error');
          stopPolling();
          saveRequestId(rfcRef.current, null);
        }
        // cod_estado 1 or 2: keep polling
      } catch (err) {
        if (!mountedRef.current || pollIdRef.current !== id) return;
        // 503 = el SAT no responde (transitorio, lo traduce el agente): NO es
        // el fin del flujo. Seguimos verificando en el mismo intervalo — y el
        // tick del catálogo cierra solo si el poller del agente la resuelve.
        if (err instanceof ApiError && err.status === 503) {
          setMensaje('El SAT está tardando en responder; seguimos verificando.');
          return;
        }
        const msg = mensajeDeError(err);
        setError(`Error al verificar solicitud: ${msg}`);
        setState('error');
        stopPolling();
        // Un 400 del agente es un rechazo definitivo (no reintentable);
        // errores de red / 401 / 5xx son transitorios y el flujo se retoma
        // en el siguiente mount (el poller del agente sigue trabajando).
        if (err instanceof ApiError && err.status === 400) {
          saveRequestId(rfcRef.current, null);
        }
      } finally {
        pollBusyRef.current = false;
      }
    },
    [apiClient, stopPolling, cerrarSiCatalogoResuelto],
  );

  // -----------------------------------------------------------------------
  // Start polling loop
  // -----------------------------------------------------------------------

  const startPolling = useCallback(
    (id: string) => {
      stopPolling();
      pollIdRef.current = id;
      setState('polling');

      // Poll immediately once
      pollOnce(id);

      // Then on interval
      intervalRef.current = setInterval(() => {
        pollOnce(id);
      }, pollIntervalMs);
    },
    [pollOnce, pollIntervalMs, stopPolling],
  );

  // -----------------------------------------------------------------------
  // solicitar
  // -----------------------------------------------------------------------

  const solicitar = useCallback(
    async (request: SolicitudRequest) => {
      const gen = ++solicitarGenRef.current;
      const vigente = () => mountedRef.current && solicitarGenRef.current === gen;
      try {
        setState('requesting');
        setError(null);
        setCodEstado(null);
        setMensaje(null);
        setNumeroCfdis(null);
        setPackageIds([]);
        setArchivosDescargados([]);
        setResumen(null);

        // CFDI: primero lo consolidado sale de la base y solo los huecos van al
        // SAT. Metadata no se consolida: sigue por /solicitar.
        if (request.tipo_solicitud === 'CFDI') {
          const res = await apiClient.solicitarDesdeBase(request);
          // Reset, cambio de empresa o una solicitud más nueva: respuesta vieja.
          if (!vigente()) return;

          setResumen(resumenDeRespuesta(res, request.tipo_comprobante === 'E' ? 'E' : 'R'));
          if (!res.id_solicitud) {
            // Todo estaba consolidado: no hay nada que verificar ni descargar.
            setRequestId(null);
            saveRequestId(rfcRef.current, null);
            setState('done');
            return;
          }
          // La primera solicitud lleva el flujo; el resto queda en la lista y
          // el poller del agente las baja solas.
          setRequestId(res.id_solicitud);
          saveRequestId(rfcRef.current, res.id_solicitud);
          startPolling(res.id_solicitud);
          return;
        }

        const res = await apiClient.solicitar(request);
        if (!vigente()) return;

        setRequestId(res.id_solicitud);
        saveRequestId(rfcRef.current, res.id_solicitud);
        startPolling(res.id_solicitud);
      } catch (err) {
        if (!vigente()) return;
        const msg = mensajeDeError(err);
        setError(`Error al solicitar descarga: ${msg}`);
        setState('error');
      }
    },
    [apiClient, startPolling],
  );

  // -----------------------------------------------------------------------
  // descargar
  // -----------------------------------------------------------------------

  const descargar = useCallback(async () => {
    if (!requestId) return;

    try {
      setState('downloading');
      setError(null);

      const res = await apiClient.descargar(requestId);
      if (!mountedRef.current) return;

      setArchivosDescargados(res.archivos);
      saveRequestId(rfcRef.current, null);
      setState('done');
    } catch (err) {
      if (!mountedRef.current) return;
      // 409 = el poller en background ya está bajando esta solicitud: no es un
      // error para el usuario; el catálogo quedará en "Descargada" solo.
      if (err instanceof ApiError && err.status === 409) {
        saveRequestId(rfcRef.current, null);
        setState('done');
        return;
      }
      const msg = mensajeDeError(err);
      setError(`Error al descargar: ${msg}`);
      setState('error');
    }
  }, [apiClient, requestId]);

  // -----------------------------------------------------------------------
  // reset
  // -----------------------------------------------------------------------

  const reset = useCallback(() => {
    solicitarGenRef.current++;
    stopPolling();
    setState('idle');
    setRequestId(null);
    setCodEstado(null);
    setMensaje(null);
    setNumeroCfdis(null);
    setPackageIds([]);
    setArchivosDescargados([]);
    setError(null);
    setResumen(null);
    saveRequestId(rfcRef.current, null);
    autoDescargaDispatchedRef.current = null;
  }, [stopPolling]);

  // Auto-descarga: tan pronto la solicitud quede lista, dispara `descargar()`
  // una sola vez por solicitud (sin bloquear la re-descarga manual posterior).
  useEffect(() => {
    if (
      state === 'ready' &&
      requestId &&
      autoDescargaDispatchedRef.current !== requestId
    ) {
      autoDescargaDispatchedRef.current = requestId;
      void descargar();
    }
  }, [state, requestId, descargar]);

  // -----------------------------------------------------------------------
  // Por empresa: al montar Y al cambiar de RFC se limpia el estado en memoria
  // y se retoma el polling SOLO si esta empresa dejó una solicitud pendiente.
  // -----------------------------------------------------------------------

  useEffect(() => {
    mountedRef.current = true;
    rfcRef.current = rfc;

    // Migración: la llave global legacy hacía que una solicitud apareciera en
    // TODAS las empresas. Se elimina sin retomarla; si sigue viva, el poller
    // del agente y la lista de solicitudes la resuelven por su cuenta.
    if (typeof window !== 'undefined') {
      localStorage.removeItem(LS_LEGACY_KEY);
    }

    // Cambio de empresa: estado en memoria a cero (sin tocar localStorage de
    // la empresa anterior — su flujo sigue guardado y el poller lo atiende).
    solicitarGenRef.current++;
    stopPolling();
    setState('idle');
    setRequestId(null);
    setCodEstado(null);
    setMensaje(null);
    setNumeroCfdis(null);
    setPackageIds([]);
    setArchivosDescargados([]);
    setError(null);
    setResumen(null);
    autoDescargaDispatchedRef.current = null;

    const savedId = loadRequestId(rfc);
    if (savedId) {
      setRequestId(savedId);
      // Antes de revivir el polling, pregunta al catálogo: el poller del
      // agente pudo haberla resuelto mientras la página no existía (app
      // cerrada, otra pantalla, otra empresa). Sin esto, una solicitud ya
      // "Descargada" reaparecía como "Verificando estado…" para siempre.
      pollIdRef.current = savedId;
      setState('polling');
      void cerrarSiCatalogoResuelto(savedId).then((cerrado) => {
        if (!cerrado && mountedRef.current && pollIdRef.current === savedId) {
          startPolling(savedId);
        }
      });
    }

    return () => {
      mountedRef.current = false;
      stopPolling();
    };
    // Reinicia solo cuando cambia la empresa activa.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rfc]);

  return {
    state,
    requestId,
    codEstado,
    mensaje,
    numeroCfdis,
    packageIds,
    archivosDescargados,
    error,
    resumen,
    solicitar,
    descargar,
    reset,
  };
}

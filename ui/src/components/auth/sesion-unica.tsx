'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { Titlebar } from '@/components/layout/titlebar';
import type { EstadoSesionUnica, PeticionSesionUnica } from '@/lib/api-client';
import { esWeb } from '@/lib/modo';
import {
  ESTADO_ESCRITORIO_MS,
  LATIDO_WEB_MS,
  etiquetaNavegador,
  haceCuanto,
  instalacionNavegador,
  interaccionHaceS,
  marcarInteraccion,
} from '@/lib/sesion-unica';
import { useAuth } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';

/** Un latido por foco como mucho cada tanto (cambiar de ventana seguido). */
const FOCO_MIN_MS = 10_000;

/**
 * Una sesión activa a la vez (F1.1): gana la sesión más reciente.
 *
 * - Al abrir la app con sesión (o al iniciar sesión) reclama la cuenta para
 *   esta instalación: las demás se cierran en su siguiente latido.
 * - Late para enterarse de que otra instalación reclamó: en la web cada 60 s
 *   (vía su agente); en escritorio lo hace el agente y aquí se lee su estado
 *   local cada 15 s. En los dos, además, al volver a la ventana.
 * - Si otra la reclamó (modo exigir), muestra "Se cerró esta sesión…" encima de
 *   todo, sin desmontar nada (no se pierde lo que estaba en pantalla), con
 *   "Continuar aquí" (reclama de nuevo, sin volver a iniciar sesión) y
 *   "Cerrar sesión".
 *
 * Nunca cierra sin una respuesta del servicio que lo pida: sin internet, con
 * el servicio viejo o con cualquier error, la app sigue abierta. En modo
 * observar nunca se cierra.
 */
export function SesionUnica() {
  const { apiClient, isConnected } = useServer();
  const { license, logout } = useAuth();
  const web = esWeb();

  const autenticado = license?.authenticated === true;
  const usuario = autenticado ? (license?.user_id ?? 'sin-id') : null;

  const [cerrada, setCerrada] = useState(false);
  const [otra, setOtra] = useState<EstadoSesionUnica['otra']>(null);
  const [intervaloWeb, setIntervaloWeb] = useState(LATIDO_WEB_MS);
  const [ocupado, setOcupado] = useState<'continuar' | 'salir' | null>(null);
  const [, setTick] = useState(0);

  const cerradaRef = useRef(false);
  const reclamadaPara = useRef<string | null>(null);
  const ultimoFoco = useRef(0);
  const botonRef = useRef<HTMLButtonElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);

  const cuerpo = useCallback((): PeticionSesionUnica => {
    const interaccion_hace_s = interaccionHaceS();
    if (!web) return { interaccion_hace_s };
    return {
      instalacion_id: instalacionNavegador(),
      etiqueta: etiquetaNavegador(),
      interaccion_hace_s,
    };
  }, [web]);

  // El cierre es "pegajoso": solo lo abre "Continuar aquí" (o cambiar de
  // cuenta). Así un reinicio del agente no reabre la app a medias.
  const aplicar = useCallback((e: EstadoSesionUnica) => {
    if (e.cerrada) {
      setOtra(e.otra);
      setCerrada(true);
    }
    if (e.heartbeat_segundos > 0) {
      setIntervaloWeb(Math.min(Math.max(e.heartbeat_segundos, 15), 600) * 1000);
    }
  }, []);

  useEffect(() => {
    cerradaRef.current = cerrada;
  }, [cerrada]);

  // Interacción del usuario (para medir uso simultáneo en modo observar).
  useEffect(() => {
    const eventos = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const;
    eventos.forEach((ev) => window.addEventListener(ev, marcarInteraccion, { passive: true }));
    return () => eventos.forEach((ev) => window.removeEventListener(ev, marcarInteraccion));
  }, []);

  // Cambio de cuenta o cierre de sesión: se olvida todo.
  useEffect(() => {
    if (usuario === null) {
      reclamadaPara.current = null;
      setCerrada(false);
      setOtra(null);
    }
  }, [usuario]);

  // Reclamar al abrir la app con sesión o al iniciar sesión (una vez por
  // cuenta; una reconexión con el agente NO vuelve a reclamar).
  useEffect(() => {
    if (!usuario || !isConnected || reclamadaPara.current === usuario) return;
    reclamadaPara.current = usuario;
    setCerrada(false);
    setOtra(null);
    marcarInteraccion(); // abrir la app es una acción del usuario
    apiClient
      .sesionReclamar(cuerpo())
      .then(aplicar)
      .catch(() => {
        /* sin respuesta nunca se cierra */
      });
  }, [usuario, isConnected, apiClient, cuerpo, aplicar]);

  const latir = useCallback(() => {
    if (!usuario || !isConnected || cerradaRef.current) return;
    apiClient
      .sesionLatido(cuerpo())
      .then(aplicar)
      .catch(() => {});
  }, [usuario, isConnected, apiClient, cuerpo, aplicar]);

  // Periódico: la web late (vía su agente); el escritorio lee el estado local
  // del agente, que late por su cuenta cada 60 s aunque la ventana esté cerrada.
  useEffect(() => {
    if (!usuario || !isConnected || cerrada) return;
    const id = web
      ? setInterval(latir, intervaloWeb)
      : setInterval(() => {
          apiClient
            .sesionEstado(interaccionHaceS())
            .then(aplicar)
            .catch(() => {});
        }, ESTADO_ESCRITORIO_MS);
    return () => clearInterval(id);
  }, [usuario, isConnected, cerrada, web, intervaloWeb, latir, apiClient, aplicar]);

  // Al volver a la ventana: latido inmediato (con tope de frecuencia).
  useEffect(() => {
    const alVolver = () => {
      if (document.visibilityState !== 'visible') return;
      const ahora = Date.now();
      if (ahora - ultimoFoco.current < FOCO_MIN_MS) return;
      ultimoFoco.current = ahora;
      latir();
    };
    window.addEventListener('focus', alVolver);
    document.addEventListener('visibilitychange', alVolver);
    return () => {
      window.removeEventListener('focus', alVolver);
      document.removeEventListener('visibilitychange', alVolver);
    };
  }, [latir]);

  // Con la pantalla de cierre: "hace N min" al día, foco en el botón y los
  // atajos de la app de abajo apagados.
  useEffect(() => {
    if (!cerrada) return;
    botonRef.current?.focus();
    const id = setInterval(() => setTick((t) => t + 1), 30_000);
    const bloquearTeclas = (e: KeyboardEvent) => {
      if (!overlayRef.current?.contains(e.target as Node)) {
        e.stopPropagation();
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', bloquearTeclas, true);
    return () => {
      clearInterval(id);
      window.removeEventListener('keydown', bloquearTeclas, true);
    };
  }, [cerrada]);

  const continuarAqui = async () => {
    setOcupado('continuar');
    marcarInteraccion();
    try {
      const e = await apiClient.sesionReclamar(cuerpo());
      if (!e.cerrada) {
        setCerrada(false);
        setOtra(null);
      }
    } catch {
      // Sin respuesta nunca se queda cerrada.
      setCerrada(false);
      setOtra(null);
    } finally {
      setOcupado(null);
    }
  };

  const cerrarSesion = async () => {
    setOcupado('salir');
    try {
      await logout();
    } finally {
      setOcupado(null);
    }
  };

  if (!cerrada || !autenticado) return null;

  const detalle = [otra?.etiqueta, haceCuanto(otra?.desde)].filter(Boolean).join(', ');

  return (
    <div
      ref={overlayRef}
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="sesion-cerrada-titulo"
      aria-describedby="sesion-cerrada-detalle"
      className="fixed inset-0 z-[100] flex flex-col bg-background"
    >
      <Titlebar />
      <div className="flex flex-1 items-center justify-center px-6">
        <div className="flex max-w-md flex-col items-center gap-5 text-center">
          <div className="flex size-12 items-center justify-center rounded-full border bg-muted">
            <Icon icon="ph:desktop-light" className="size-6 text-muted-foreground" />
          </div>
          <div className="space-y-2">
            <h1 id="sesion-cerrada-titulo" className="text-lg font-semibold">
              TodoConta se abrió en otra computadora
            </h1>
            <p id="sesion-cerrada-detalle" className="text-sm leading-relaxed text-muted-foreground">
              Se cerró esta sesión porque abriste TodoConta en otra computadora
              {detalle ? ` (${detalle})` : ''}. Solo puede estar abierta en una a la vez.
            </p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              No se perdió nada. Lo que tenías en pantalla y las descargas en segundo plano
              siguen aquí al continuar.
            </p>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button ref={botonRef} onClick={continuarAqui} disabled={ocupado !== null}>
              {ocupado === 'continuar' ? (
                <Icon icon="ph:circle-notch-light" className="animate-spin" />
              ) : (
                <Icon icon="ph:arrow-counter-clockwise-light" />
              )}
              Continuar aquí
            </Button>
            <Button variant="outline" onClick={cerrarSesion} disabled={ocupado !== null}>
              <Icon icon="ph:sign-out-light" />
              Cerrar sesión
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

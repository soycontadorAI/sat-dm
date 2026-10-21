/**
 * API pública de notificaciones.
 *
 * Patrón:
 *   1. Lee prefs; si el toggle está OFF, no-op.
 *   2. Elige UN mensaje del pool y lo pasa a los transportes (consistencia
 *      entre sonner y nativa).
 *   3. Gating por foco:
 *       - App enfocada (`visibilityState=visible` Y `hasFocus`) → solo sonner.
 *       - App en background / otra app al frente → solo nativa.
 *       - Excepción: errores críticos disparan AMBAS (sonner persistente
 *         + ping del SO).
 *   4. Dedup por `id` derivado (canal:rfc:jobId).
 */

import { toast } from 'sonner';

import {
  type DescargaCanal,
  mensajeDescargaError,
  mensajeDescargaSuccess,
  mensajeEfirmaAviso,
  mensajeRenovacionPendiente,
} from './messages';
import { dispatchNative } from './native';
import { getNotifPrefs } from './prefs';

const DURATION = {
  success: 5_000,
  error: 7_000,
  info: 5_000,
};

const NATIVE_TITLES = {
  descargaOk: 'Descarga lista 🎉',
  descargaErr: 'Descarga con error 😨',
  efirma: 'e.firma por vencer ⌛️',
  renovacion: 'Renovación de e.firma pendiente',
} as const;

function tieneFoco(): boolean {
  if (typeof document === 'undefined') return false;
  return document.visibilityState === 'visible' && document.hasFocus();
}

export interface NotifyDescargaCompletaArgs {
  canal: DescargaCanal;
  rfc: string;
  count?: number;
  jobId?: string;
}

export function notifyDescargaCompleta(args: NotifyDescargaCompletaArgs): void {
  if (!getNotifPrefs().descargas) return;
  const id = `descarga:${args.canal}:${args.rfc}:${args.jobId ?? 'ok'}`;
  const mensaje = mensajeDescargaSuccess(args.canal, { count: args.count, rfc: args.rfc });

  if (tieneFoco()) {
    toast.success(mensaje, { id, duration: DURATION.success });
  } else {
    void dispatchNative({ title: NATIVE_TITLES.descargaOk, body: mensaje });
  }
}

export interface NotifyDescargaErrorArgs {
  canal: DescargaCanal;
  rfc: string;
  motivo?: string;
  jobId?: string;
}

export function notifyDescargaError(args: NotifyDescargaErrorArgs): void {
  if (!getNotifPrefs().descargas) return;
  const id = `descarga:${args.canal}:${args.rfc}:${args.jobId ?? 'err'}`;
  const mensaje = mensajeDescargaError(args.canal, {
    rfc: args.rfc,
    motivo: args.motivo ?? 'Revisa el detalle.',
  });

  // Errores SIEMPRE disparan ambos canales: el sonner persistente para
  // cuando el usuario está mirando, y la nativa para cuando se fue a otra
  // app a esperar (criticidad alta).
  toast.error(mensaje, { id, duration: DURATION.error });
  void dispatchNative({ title: NATIVE_TITLES.descargaErr, body: mensaje, urgent: true });
}

export interface NotifyEfirmaArgs {
  /** Lista de e.firmas en riesgo (≤30 días), ordenadas por urgencia ascendente. */
  rfcs: Array<{ rfc: string; dias: number }>;
}

export function notifyEfirmaVencimiento(args: NotifyEfirmaArgs): void {
  if (!getNotifPrefs().efirma) return;
  if (args.rfcs.length === 0) return;
  const proxima = args.rfcs[0];
  const id = `efirma:${new Date().toISOString().slice(0, 10)}`;
  const mensaje = mensajeEfirmaAviso({
    n: args.rfcs.length,
    rfc: proxima.rfc,
    dias: proxima.dias,
  });

  if (tieneFoco()) {
    toast.warning(mensaje, { id, duration: DURATION.info });
  } else {
    void dispatchNative({ title: NATIVE_TITLES.efirma, body: mensaje });
  }
}

export interface NotifyRenovacionPendienteArgs {
  rfc: string;
  /** true = el SAT ya tiene el trámite (falta el cert); false = falta enviarlo. */
  enviada: boolean;
  /** Abre la empresa para terminar el trámite. */
  onVer?: () => void;
}

/** Aviso de una renovación de e.firma a medias (la app se cerró a mitad del trámite). */
export function notifyRenovacionPendiente(args: NotifyRenovacionPendienteArgs): void {
  if (!getNotifPrefs().efirma) return;
  const id = `renovacion:${args.rfc}:${new Date().toISOString().slice(0, 10)}`;
  const mensaje = mensajeRenovacionPendiente(args.enviada, args.rfc);

  if (tieneFoco()) {
    toast.warning(mensaje, {
      id,
      duration: 10_000,
      action: args.onVer ? { label: 'Terminar', onClick: args.onVer } : undefined,
    });
  } else {
    void dispatchNative({ title: NATIVE_TITLES.renovacion, body: mensaje });
  }
}

export interface NotifyPilotoAvisoArgs {
  id: number;
  tipo: 'resumen' | 'cancelacion' | 'efirma';
  mensaje: string;
}

/** Aviso de la descarga automática: resumen del cierre, cancelaciones y e.firma. */
export function notifyPilotoAviso(args: NotifyPilotoAvisoArgs): void {
  const prefs = getNotifPrefs();
  if (args.tipo === 'efirma' ? !prefs.efirma : !prefs.descargas) return;
  const id = `piloto:${args.id}`;
  if (tieneFoco()) {
    const opciones = { id, duration: DURATION.info };
    if (args.tipo === 'resumen') toast.success(args.mensaje, opciones);
    else toast.warning(args.mensaje, opciones);
  } else {
    void dispatchNative({ title: 'Descarga automática', body: args.mensaje });
  }
}

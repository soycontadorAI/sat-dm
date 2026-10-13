// Lógica pura del resumen de "solicitud desde la base": qué se sirvió sin ir
// al SAT y qué huecos sí se pidieron. Sin React ni DOM (pruebas: pnpm test).

import { MESES } from './calendario.ts';
import type {
  ErrorRangoBase,
  ResumenServido,
  SolicitudDesdeBaseResponse,
  SolicitudHueco,
} from './types.ts';

function partes(iso: string): { y: number; m: number; d: number } | null {
  const r = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  if (!r) return null;
  const m = Number(r[2]);
  if (m < 1 || m > 12) return null;
  return { y: Number(r[1]), m, d: Number(r[3]) };
}

const nombreMes = (m: number) => MESES[m - 1].toLowerCase();

/**
 * Rango corto en español: "10 de marzo", "10 al 12 de marzo",
 * "28 de marzo al 2 de abril". Agrega el año solo si cruza de año.
 */
export function rangoCorto(inicio: string, fin: string): string {
  const a = partes(inicio);
  const b = partes(fin);
  if (!a || !b) return inicio === fin ? inicio : `${inicio} al ${fin}`;
  if (a.y === b.y && a.m === b.m && a.d === b.d) return `${a.d} de ${nombreMes(a.m)}`;
  if (a.y !== b.y) {
    return `${a.d} de ${nombreMes(a.m)} de ${a.y} al ${b.d} de ${nombreMes(b.m)} de ${b.y}`;
  }
  if (a.m === b.m) return `${a.d} al ${b.d} de ${nombreMes(a.m)}`;
  return `${a.d} de ${nombreMes(a.m)} al ${b.d} de ${nombreMes(b.m)}`;
}

/** Lista en prosa: "a", "a y b", "a, b y c". */
export function unirLista(items: string[]): string {
  if (items.length <= 1) return items.join('');
  return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`;
}

export function listaRangos(huecos: { fecha_inicio: string; fecha_fin: string }[]): string {
  return unirLista(huecos.map((h) => rangoCorto(h.fecha_inicio, h.fecha_fin)));
}

/** Normaliza la respuesta del agente (errores puede faltar). */
export function resumenDeRespuesta(
  res: SolicitudDesdeBaseResponse,
  direccion: 'E' | 'R',
): ResumenServido {
  return {
    direccion,
    servidos: res.servidos,
    solicitudes: res.solicitudes ?? [],
    errores: res.errores ?? [],
  };
}

/** "Emitidos" / "Recibidos". */
export function etiquetaDireccion(direccion: 'E' | 'R'): string {
  return direccion === 'E' ? 'Emitidos' : 'Recibidos';
}

/** Título del bloque de lo servido: lleva la dirección solo si hay más de un resumen. */
export function tituloServido(direccion: 'E' | 'R', totalResumenes: number): string {
  return totalResumenes > 1
    ? `Servido desde la base · ${etiquetaDireccion(direccion)}`
    : 'Servido desde la base';
}

const plural = (n: number, uno: string, varios: string) => (n === 1 ? uno : varios);

/** "12 días ya estaban consolidados en la base (340 CFDI): se guardaron …" */
export function textoServidos(dias: number, cfdis: number): string {
  const sujeto =
    dias === 1 ? '1 día ya estaba consolidado' : `${dias} días ya estaban consolidados`;
  if (cfdis === 0) return `${sujeto} en la base, sin CFDI: no hizo falta ir al SAT por ${dias === 1 ? 'él' : 'ellos'}.`;
  return `${sujeto} en la base (${cfdis} CFDI): se guardaron en la carpeta de la descarga sin ir al SAT.`;
}

/** "Al SAT se pidieron solo los huecos: 10 al 12 de marzo y …" ('' si no hubo). */
export function textoHuecos(huecos: SolicitudHueco[]): string {
  if (huecos.length === 0) return '';
  const etiqueta = huecos.length === 1 ? 'el hueco' : 'los huecos';
  return `Al SAT se pidieron solo ${etiqueta}: ${listaRangos(huecos)}.`;
}

/** Nota de CFDI de días servidos que no tienen XML guardado ('' si 0). */
export function textoSinXml(n: number): string {
  if (n <= 0) return '';
  return `${n} ${plural(n, 'CFDI de esos días no tiene', 'CFDI de esos días no tienen')} XML guardado.`;
}

export function textoErrorRango(e: ErrorRangoBase): string {
  // El mensaje del tope ya dice todo (plan, descargas usadas y cuándo se renuevan).
  if (e.tipo === 'cupo') return e.mensaje;
  return `${rangoCorto(e.rango[0], e.rango[1])}: ${e.mensaje}`;
}

/** Orden en que se muestran los avisos de errores. */
export const TIPOS_ERROR = ['sat', 'base', 'cupo'] as const;

/** Título del aviso de errores según su tipo (y plural si son varios). */
export function tituloErrores(tipo: ErrorRangoBase['tipo'], n: number): string {
  if (tipo === 'base') {
    return n === 1
      ? 'No se pudo guardar lo que ya estaba en la base'
      : 'En varias solicitudes no se pudo guardar lo que ya estaba en la base';
  }
  if (tipo === 'cupo') return 'No se pidió al SAT lo que faltaba: llegaste al tope de descargas';
  return n === 1 ? 'Un rango no se pudo solicitar' : 'Algunos rangos no se pudieron solicitar';
}

/** ¿Hay algo que mostrar en el aviso de lo servido? */
export function hayServidos(r: ResumenServido | null): r is ResumenServido {
  return !!r && r.servidos.dias > 0;
}

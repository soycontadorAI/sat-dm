// ---------------------------------------------------------------------------
// Intérprete de órdenes de ⌘K (F3, navegacion-espacios.md sección 4).
//
// Puro y determinista: `interpretar(texto, empresas, activa, hoy)` regresa las
// órdenes que entendió, con sus parámetros (periodo, empresa, tipo, canal) y si
// piden confirmación. No toca red, UI ni React, y no manda lo que escribes a
// ningún servidor (no hay IA aquí). Sin imports a propósito: las pruebas corren
// con `node --test src/lib/ordenes.test.ts`.
// ---------------------------------------------------------------------------

export type MetodoOrden = 'fiel' | 'ciec';

export interface EmpresaOrden {
  rfc: string;
  nombre: string;
  metodos: MetodoOrden[];
  archived_at?: string | null;
}

export type TipoOrden =
  | 'descargar'
  | 'descarga-rapida'
  | 'constancia'
  | 'opinion'
  | 'listas-negras'
  | 'diot'
  | 'calculadora'
  | 'agregar-empresa'
  | 'tema';

/** E = emitidos, R = recibidos, A = los dos. */
export type ComprobanteOrden = 'E' | 'R' | 'A';

/** ws = Web Service (e.firma), fiel = portal con e.firma, ciec = portal con Contraseña. */
export type CanalOrden = 'ws' | 'fiel' | 'ciec';

export interface PeriodoOrden {
  anio: number;
  /** 1 a 12. */
  mes: number;
  /** YYYY-MM-DD */
  desde: string;
  /** YYYY-MM-DD */
  hasta: string;
  /** "Septiembre 2026" */
  etiqueta: string;
  /** El usuario lo dijo (mes, "este mes", "mes pasado"); false = default. */
  explicito: boolean;
}

export interface Orden {
  tipo: TipoOrden;
  /** "Descargar CFDIs recibidos". */
  titulo: string;
  /** Empresa sobre la que actúa (la mencionada o la activa). */
  empresa: EmpresaOrden | null;
  /** true si la mencionó; false si se tomó la activa. */
  empresaMencionada: boolean;
  periodo?: PeriodoOrden;
  comprobante?: ComprobanteOrden;
  canal?: CanalOrden;
  /** El canal lo forzó el usuario ("con contraseña", "con e.firma"). */
  canalForzado?: boolean;
  /** Para calculadora: id del destino en navegacion.ts (calc-finiquito). */
  destinoId?: string;
  tema?: 'claro' | 'oscuro';
  /**
   * Pide un segundo Enter antes de mandar algo al SAT (descarga de CFDIs: el SAT
   * limita las solicitudes repetidas con el mismo criterio).
   */
  confirmar: boolean;
  /** Algo impide ejecutarla tal cual (sin accesos, sin empresa). */
  problema?: string;
}

export const MESES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
] as const;

/** Abreviaturas que también se aceptan ("sep", "sept"). */
const MESES_CORTOS: Record<string, number> = {
  ene: 1, feb: 2, mar: 3, abr: 4, may: 5, jun: 6, jul: 7, ago: 8,
  sep: 9, sept: 9, set: 9, oct: 10, nov: 11, dic: 12,
};

/** Minúsculas, sin acentos ni diéresis, espacios colapsados. */
export function normalizar(s: string): string {
  return s
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim();
}

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

function capital(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function periodoDeMes(anio: number, mes: number, explicito: boolean): PeriodoOrden {
  const ultimo = new Date(anio, mes, 0).getDate();
  return {
    anio,
    mes,
    desde: `${anio}-${pad(mes)}-01`,
    hasta: `${anio}-${pad(mes)}-${pad(ultimo)}`,
    etiqueta: `${capital(MESES[mes - 1])} ${anio}`,
    explicito,
  };
}

/** Mes anterior al de `hoy` (para "mes pasado" y los ejemplos de ⌘K). */
export function mesAnterior(hoy: Date): { anio: number; mes: number } {
  const d = new Date(hoy.getFullYear(), hoy.getMonth() - 1, 1);
  return { anio: d.getFullYear(), mes: d.getMonth() + 1 };
}

/**
 * Periodo mencionado: nombre del mes (o su abreviatura), "este mes" o "mes
 * pasado", con año opcional ("septiembre 2025", "septiembre de 2025"). Si el
 * mes todavía no llega este año, toma el del año pasado. null si no hay.
 */
export function periodoDe(n: string, hoy: Date): PeriodoOrden | null {
  const anioHoy = hoy.getFullYear();
  const mesHoy = hoy.getMonth() + 1;
  if (/\bmes pasado\b|\bmes anterior\b|\bpasado mes\b/.test(n)) {
    const m = mesAnterior(hoy);
    return periodoDeMes(m.anio, m.mes, true);
  }
  if (/\beste mes\b|\bmes actual\b|\bmes en curso\b/.test(n)) {
    return periodoDeMes(anioHoy, mesHoy, true);
  }
  let mes = 0;
  let fin = -1;
  const palabras = n.split(/[\s,.]+/);
  palabras.forEach((p, i) => {
    const idx = (MESES as readonly string[]).indexOf(p);
    if (idx >= 0) {
      mes = idx + 1;
      fin = i;
    } else if (MESES_CORTOS[p] && !mes) {
      mes = MESES_CORTOS[p];
      fin = i;
    }
  });
  if (!mes) return null;
  // Año explícito justo después del mes ("septiembre 2025" / "septiembre de 2025").
  const sig = palabras.slice(fin + 1, fin + 3).find((p) => /^20\d{2}$/.test(p));
  const anio = sig ? Number(sig) : mes > mesHoy ? anioHoy - 1 : anioHoy;
  return periodoDeMes(anio, mes, true);
}

/** Palabras que no identifican a una empresa aunque tengan 4 letras o más. */
const NO_IDENTIFICAN = new Set(['sapi', 'sofom', 'civil', 'empresa', 'empresas']);
const CONECTORES = new Set(['de', 'del', 'la', 'el', 'los', 'las', 'y', 'e']);

/** Palabras del nombre corto (antes de la primera coma) que sirven para identificarla. */
export function palabrasClave(nombre: string): string[] {
  const corto = nombre.split(',')[0];
  return normalizar(corto)
    .replace(/[^a-z0-9ñ\s-]/g, ' ')
    .split(/\s+/)
    .filter((w) => w.length >= 4 && !CONECTORES.has(w) && !NO_IDENTIFICAN.has(w));
}

/**
 * Empresas mencionadas, con su puntaje: por palabras del nombre de 4 letras o
 * más ("panaderia", "roble") o por el RFC completo. Regresa las que empatan
 * en el puntaje más alto (para mostrar una acción por cada una).
 */
export function empresasMencionadas(n: string, empresas: EmpresaOrden[]): EmpresaOrden[] {
  const palabras = new Set(n.replace(/[^a-z0-9ñ\s-]/g, ' ').split(/\s+/));
  let mejor = 0;
  let empatadas: EmpresaOrden[] = [];
  for (const e of empresas) {
    if (e.archived_at) continue;
    let puntos = 0;
    const rfc = normalizar(e.rfc);
    if (palabras.has(rfc)) puntos += 100;
    for (const w of palabrasClave(e.nombre)) {
      // Palabra completa, o prefijo de 5+ letras ("distribuidora" con "distri").
      if (palabras.has(w)) puntos += w.length;
      else if ([...palabras].some((p) => p.length >= 5 && w.startsWith(p))) puntos += p5(w);
    }
    if (puntos === 0) continue;
    if (puntos > mejor) {
      mejor = puntos;
      empatadas = [e];
    } else if (puntos === mejor) {
      empatadas.push(e);
    }
  }
  return mejor >= 4 ? empatadas : [];
}

function p5(w: string): number {
  // Un prefijo vale menos que la palabra completa, para que "panaderia la
  // central" gane sobre una coincidencia parcial de otra empresa.
  return Math.max(4, Math.floor(w.length / 2));
}

function comprobanteDe(n: string): ComprobanteOrden {
  const e = /\bemitid\w*/.test(n);
  const r = /\brecibid\w*/.test(n);
  if (e && !r) return 'E';
  if (r && !e) return 'R';
  return 'A';
}

function canalForzadoDe(n: string): CanalOrden | null {
  if (/\b(contrasena|ciec)\b/.test(n)) return 'ciec';
  if (/\b(e\.?\s?firma|efirma|fiel)\b/.test(n)) return 'fiel';
  return null;
}

const TITULO_COMPROBANTE: Record<ComprobanteOrden, string> = {
  E: 'emitidos',
  R: 'recibidos',
  A: 'emitidos y recibidos',
};

const CALCULADORAS: [RegExp, string, string][] = [
  [/\bfiniquito\b/, 'calc-finiquito', 'Calcular finiquito'],
  [/\baguinaldo\b/, 'calc-aguinaldo', 'Calcular aguinaldo'],
  [/\bliquidacion\b|\bindemnizacion\b/, 'calc-liquidacion', 'Calcular liquidación'],
  [/\bptu\b|\breparto de utilidades\b/, 'calc-ptu', 'Calcular PTU'],
  [/\bsbc\b|\bsalario base\b/, 'calc-sbc', 'Calcular Salario Base de Cotización'],
  [/\bisr\b/, 'calc-isr', 'Calcular ISR de sueldos'],
  [/\bcarga patronal\b|\bcuotas (del )?imss\b|\bimss\b/, 'calc-carga', 'Calcular carga patronal'],
];

function quitarCortesia(n: string): string {
  return n
    .replace(/^(por favor|porfa|oye|quiero|necesito|puedes|me puedes)\s+/g, '')
    .replace(/\s+(por favor|porfa)$/g, '');
}

/**
 * Interpreta lo que escribiste en ⌘K. Una orden empieza con lo que quieres
 * hacer ("descargar", "constancia", "opinión", "finiquito"...). Si no mencionas
 * empresa usa la activa; si dos empresas empatan regresa una orden por cada
 * una. Regresa [] si no hay un verbo que entienda (el buscador sigue mostrando
 * pantallas y empresas).
 */
export function interpretar(
  texto: string,
  empresas: EmpresaOrden[],
  activa: EmpresaOrden | null,
  hoy: Date,
): Orden[] {
  const n = quitarCortesia(normalizar(texto));
  if (n.length < 2) return [];

  const mencionadas = empresasMencionadas(n, empresas);
  const objetivos: { empresa: EmpresaOrden | null; mencionada: boolean }[] = mencionadas.length
    ? mencionadas.map((e) => ({ empresa: e, mencionada: true }))
    : [{ empresa: activa, mencionada: false }];

  const out: Orden[] = [];
  const periodo = periodoDe(n, hoy);
  const forzado = canalForzadoDe(n);

  const esConstancia = /\b(constancia|csf)\b|situacion fiscal/.test(n);
  const esOpinion = /\bopinion\b|\b32-?d\b/.test(n);
  const esRapida = /\bdescarga rapida\b|\brapida\b/.test(n);
  const esDescarga =
    !esConstancia &&
    !esOpinion &&
    /\b(descarg\w*|bajar|baja|bajame|solicit\w*|trae|traer|traeme)\b/.test(n);
  const esListas = /\blistas? negras?\b|\b69-?b\b|\b69\b|\befos\b|\bedos\b/.test(n);
  const esDiot = /\bdiot\b/.test(n) && !/\bpresentar\b|\bpresentadas?\b|\bacuses?\b/.test(n);

  for (const { empresa, mencionada } of objetivos) {
    const base = { empresa, empresaMencionada: mencionada };
    const sinEmpresa = empresa ? undefined : 'Sin empresa activa: agrega una en Empresas.';
    const tieneFiel = !!empresa?.metodos.includes('fiel');
    const tieneCiec = !!empresa?.metodos.includes('ciec');
    const sinAccesos =
      empresa && !tieneFiel && !tieneCiec
        ? 'Esta empresa no tiene e.firma ni Contraseña en este equipo.'
        : undefined;

    if (esDescarga || (esRapida && !esConstancia && !esOpinion)) {
      const comprobante = comprobanteDe(n);
      const per = periodo ?? periodoDeMes(hoy.getFullYear(), hoy.getMonth() + 1, false);
      // Canal: Web Service si tiene e.firma; si solo tiene Contraseña, Descarga
      // rápida. "con contraseña" / "con e.firma" lo fuerzan; "descarga rápida"
      // va por el portal con el método preferido.
      let canal: CanalOrden | undefined;
      let problema = sinEmpresa ?? sinAccesos;
      if (forzado === 'ciec') {
        canal = 'ciec';
        if (!problema && !tieneCiec) problema = 'Esta empresa no tiene Contraseña del SAT en este equipo.';
      } else if (forzado === 'fiel') {
        canal = esRapida ? 'fiel' : 'ws';
        if (!problema && !tieneFiel) problema = 'Esta empresa no tiene e.firma en este equipo.';
      } else if (esRapida) {
        canal = tieneFiel ? 'fiel' : tieneCiec ? 'ciec' : undefined;
      } else {
        canal = tieneFiel ? 'ws' : tieneCiec ? 'ciec' : undefined;
      }
      const porPortal = canal === 'ciec' || canal === 'fiel';
      out.push({
        ...base,
        tipo: porPortal ? 'descarga-rapida' : 'descargar',
        titulo: porPortal
          ? `Descarga rápida de ${TITULO_COMPROBANTE[comprobante]}`
          : `Descargar CFDIs ${TITULO_COMPROBANTE[comprobante]}`,
        periodo: per,
        comprobante,
        canal,
        canalForzado: !!forzado,
        confirmar: true,
        problema,
      });
    }

    // Constancia y opinión: la app las baja con e.firma si la empresa la tiene
    // (sin captcha) y si no con Contraseña (captcha dentro de la app). La
    // etiqueta de canal dice cuál va a usar; "con contraseña" no lo cambia.
    const canalDocumento: CanalOrden | undefined = tieneFiel ? 'fiel' : tieneCiec ? 'ciec' : undefined;

    if (esConstancia) {
      out.push({
        ...base,
        tipo: 'constancia',
        titulo: 'Descargar Constancia de Situación Fiscal',
        canal: canalDocumento,
        confirmar: false,
        problema: sinEmpresa ?? sinAccesos,
      });
    }

    if (esOpinion) {
      out.push({
        ...base,
        tipo: 'opinion',
        titulo: 'Descargar Opinión de Cumplimiento 32-D',
        canal: canalDocumento,
        confirmar: false,
        problema: sinEmpresa ?? sinAccesos,
      });
    }

    if (esListas && !esDescarga) {
      out.push({
        ...base,
        tipo: 'listas-negras',
        titulo: 'Revisar listas negras (69 y 69-B)',
        confirmar: false,
        problema: sinEmpresa,
      });
    }

    if (esDiot) {
      out.push({
        ...base,
        tipo: 'diot',
        titulo: 'Abrir la DIOT',
        // Sin periodo, la pantalla abre en el mes anterior (su default).
        periodo: periodo ?? undefined,
        confirmar: false,
        problema: sinEmpresa,
      });
    }
  }

  // Órdenes que no dependen de la empresa.
  for (const [re, id, titulo] of CALCULADORAS) {
    if (re.test(n) && !out.some((o) => o.destinoId === id)) {
      out.push({
        tipo: 'calculadora',
        titulo,
        destinoId: id,
        empresa: null,
        empresaMencionada: false,
        confirmar: false,
      });
      break;
    }
  }

  if (/\b(agregar|agrega|alta|nueva|registrar|registra|anadir)\b.*\bempresa\b/.test(n)) {
    out.push({
      tipo: 'agregar-empresa',
      titulo: 'Agregar empresa',
      empresa: null,
      empresaMencionada: false,
      confirmar: false,
    });
  }

  const tema = /\b(tema|modo) (oscuro|noche)\b/.test(n)
    ? 'oscuro'
    : /\b(tema|modo) (claro|dia)\b/.test(n)
      ? 'claro'
      : null;
  if (tema) {
    out.push({
      tipo: 'tema',
      titulo: tema === 'oscuro' ? 'Cambiar a tema oscuro' : 'Cambiar a tema claro',
      tema,
      empresa: null,
      empresaMencionada: false,
      confirmar: false,
    });
  }

  return out;
}

/** Nombre corto para chips y avisos: antes de la primera coma. */
export function nombreCorto(nombre: string): string {
  return nombre.split(',')[0].trim();
}

/** Ejemplos de "Prueba a pedir" con las empresas de la cuenta (nunca órdenes que no existen). */
export function ejemplos(
  empresas: EmpresaOrden[],
  activa: EmpresaOrden | null,
  hoy: Date,
): string[] {
  const { mes } = mesAnterior(hoy);
  const vivas = empresas.filter((e) => !e.archived_at);
  const otra = vivas.find((e) => e.rfc !== activa?.rfc) ?? activa;
  const tercera = vivas.find((e) => e.rfc !== activa?.rfc && e.rfc !== otra?.rfc) ?? otra;
  const out: string[] = [];
  out.push(
    activa
      ? `Descargar recibidos de ${MESES[mes - 1]} de ${nombreCorto(activa.nombre)}`
      : `Descargar recibidos de ${MESES[mes - 1]}`,
  );
  if (otra) out.push(`Constancia de ${nombreCorto(otra.nombre)}`);
  if (tercera) out.push(`Opinión 32-D de ${nombreCorto(tercera.nombre)}`);
  out.push('Finiquito');
  return out;
}

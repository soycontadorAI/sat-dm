// ---------------------------------------------------------------------------
// Planes v3 (F1 de docs/operacion/plan-app-v3.md en todoconta-apps): catálogo
// que muestra la app y reglas del tope de empresas.
//
// Precios con IVA, idénticos al seed de la migración 038 (`CATALOGO_PLANES` en
// apps/web/src/lib/desktop/planes.ts). Si cambian allá, cámbialos aquí. El
// cobro lo decide siempre el servidor: esto solo es lo que se enseña.
// ---------------------------------------------------------------------------

import type { IntervaloPlan, PlanCodigo, PlanV3Venta, TopeEmpresas } from '@/lib/api-client';
import type { PlanLicencia } from '@/providers/auth-provider';

export interface PlanV3Catalogo {
  codigo: PlanV3Venta;
  nombre: string;
  /** Anual = 10 mensualidades. */
  precioAnual: number;
  precioMensual: number;
  empresas: number;
  usuarios: number;
  lema: string;
  incluye: { texto: string; si: boolean }[];
}

function incluye(mcp: boolean, completo: boolean) {
  return [
    { texto: 'Escritorio y web con la misma cuenta', si: true },
    { texto: 'Descarga masiva, procesadores, DIOT y listas negras', si: true },
    { texto: 'Exportaciones a Excel y TXT de la DIOT', si: true },
    { texto: 'Conexión con tu IA (MCP): Claude o ChatGPT', si: mcp },
    { texto: 'Abacus, tu asistente por WhatsApp', si: completo },
    { texto: 'API para tus sistemas', si: completo },
  ];
}

export const CATALOGO_V3: readonly PlanV3Catalogo[] = [
  {
    codigo: 'esencial',
    nombre: 'Esencial',
    precioAnual: 3490,
    precioMensual: 349,
    empresas: 10,
    usuarios: 1,
    lema: 'La app completa para llevar tus empresas.',
    incluye: incluye(false, false),
  },
  {
    codigo: 'pro',
    nombre: 'Pro',
    precioAnual: 6990,
    precioMensual: 699,
    empresas: 50,
    usuarios: 3,
    lema: 'Más empresas y tu IA trabajando con tus datos.',
    incluye: incluye(true, false),
  },
  {
    codigo: 'completo',
    nombre: 'Completo',
    precioAnual: 14990,
    precioMensual: 1499,
    empresas: 100,
    usuarios: 5,
    lema: 'Para el despacho grande: Abacus y la API.',
    incluye: incluye(true, true),
  },
];

export function planDelCatalogo(codigo: string | null | undefined): PlanV3Catalogo | null {
  return CATALOGO_V3.find((p) => p.codigo === codigo) ?? null;
}

export function precioDe(plan: PlanV3Catalogo, intervalo: IntervaloPlan): number {
  return intervalo === 'anual' ? plan.precioAnual : plan.precioMensual;
}

export function sufijoIntervalo(intervalo: IntervaloPlan): string {
  return intervalo === 'anual' ? 'al año' : 'al mes';
}

export function empresasTexto(n: number): string {
  return n === 1 ? '1 empresa' : `${n} empresas`;
}

/** Planes que se venden con tope de empresas (aplica aunque falte el interruptor). */
export const PLANES_V3_CON_TOPE: readonly string[] = ['esencial', 'pro', 'completo', 'medida'];

/** Sin tope pase lo que pase: legado y fundadores (sección 3 del plan). */
const PLANES_SIN_TOPE: readonly string[] = [
  'desktop',
  'desktop_ia',
  'fundador',
  'profesional',
  'despachos',
  'empresarial',
  'legado',
];

type Siguiente = TopeEmpresas['siguiente_plan'];

/** A qué plan se sugiere subir (mismo mapa que el agente, `tope_empresas.py`). */
export const SIGUIENTE_PLAN: Partial<Record<PlanCodigo, Siguiente>> = {
  gratis: { codigo: 'esencial', nombre: 'Esencial', empresas: 10 },
  esencial: { codigo: 'pro', nombre: 'Pro', empresas: 50 },
  trial: { codigo: 'completo', nombre: 'Completo', empresas: 100 },
  pro: { codigo: 'completo', nombre: 'Completo', empresas: 100 },
  completo: { codigo: 'medida', nombre: 'A la medida', empresas: null },
  medida: null,
};

/**
 * Tope de empresas que la app enseña y hace cumplir. `null` = no aplica (sin
 * datos, legado, fundador o interruptor de planes v3 apagado): sin contador ni
 * candado. Mismo criterio que el agente.
 */
export function estadoTope(
  plan: PlanLicencia | null,
  activas: number,
  planesV3: boolean,
): TopeEmpresas | null {
  if (!planesV3 || !plan || plan.legado || PLANES_SIN_TOPE.includes(plan.codigo)) return null;
  const tope = plan.limites.empresas;
  if (typeof tope !== 'number' || tope <= 0) return null;
  return {
    plan_codigo: plan.codigo,
    plan_nombre: plan.nombre,
    tope,
    activas,
    sobran: Math.max(0, activas - tope),
    siguiente_plan: SIGUIENTE_PLAN[plan.codigo] ?? null,
  };
}

export function topeLleno(t: TopeEmpresas | null): boolean {
  return !!t && t.activas >= t.tope;
}

/** Al 80% se avisa en Empresas. */
export function topeCerca(t: TopeEmpresas | null): boolean {
  return !!t && t.activas < t.tope && t.activas >= Math.ceil(t.tope * 0.8);
}

function salida(s: Siguiente): string {
  if (s && s.empresas) return `cambia a ${s.nombre} (${empresasTexto(s.empresas)})`;
  if (s) return 'escríbenos para un plan a la medida';
  return 'escríbenos para ampliarlo';
}

/** Mismo texto que el 402 del agente (para el diálogo que se abre antes de intentar). */
export function mensajeTope(t: TopeEmpresas): string {
  const sujeto =
    t.plan_codigo === 'trial' ? 'tu prueba' : t.plan_nombre ? `tu plan ${t.plan_nombre}` : 'tu plan';
  if (t.sobran > 0) {
    const sobran = t.sobran === 1 ? 'te sobra 1' : `te sobran ${t.sobran}`;
    return (
      `Tienes ${t.activas} empresas activas y ${sujeto} incluye ${t.tope}: ${sobran}. ` +
      `Archiva las que ya no trabajes o ${salida(t.siguiente_plan)}.`
    );
  }
  const Sujeto = sujeto.charAt(0).toUpperCase() + sujeto.slice(1);
  return `${Sujeto} incluye ${empresasTexto(t.tope)}. Archiva una que ya no trabajes o ${salida(t.siguiente_plan)}.`;
}

// ---------------------------------------------------------------------------
// Descargas al SAT del mes (plan gratis)
// ---------------------------------------------------------------------------

const MESES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
  'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
];

/** "2026-12-01" → "1 de diciembre" (sin pasar por Date: nada de zonas horarias). */
export function fechaLarga(iso: string): string {
  const [, mes, dia] = iso.split('-').map((x) => parseInt(x, 10));
  if (!mes || !dia || mes < 1 || mes > 12) return iso;
  return `${dia} de ${MESES[mes - 1]}`;
}

/** Mismo texto que el 402 `tope_descargas` del agente. */
export function mensajeTopeDescargas(t: {
  tope: number;
  usadas: number;
  reinicia: string;
  plan_nombre: string | null;
  siguiente_plan: { nombre: string } | null;
}): string {
  const siguiente = t.siguiente_plan?.nombre ?? 'Esencial';
  return (
    `Tu plan ${t.plan_nombre ?? 'Gratis'} incluye ${t.tope} descargas al mes y ya usaste las ${t.usadas}. ` +
    `Se renuevan el ${fechaLarga(t.reinicia)}; para seguir hoy, cambia a ${siguiente} (descargas sin límite).`
  );
}

// Pruebas de la lógica pura del cuadro de control. pnpm test.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  celda,
  claseEstado,
  claseTexto,
  diasDelMes,
  esFutura,
  ESTADOS,
  fechaValida,
  rangoMes,
  resumenAnio,
  textoSolicitud,
  tienePiloto,
} from './calendario.ts';
import type { CalendarioAnio } from './types.ts';

const cal: Pick<CalendarioAnio, 'dias' | 'hoy' | 'resumen'> = {
  hoy: '2026-10-13',
  dias: {
    '2026-03-04': {
      E: { estado: 'provisional', total_bd: 12 },
      R: { estado: 'error', total_bd: 0, error_codigo: '5002' },
    },
    '2026-03-05': { E: { estado: 'provisional', total_bd: 0 } },
    '2026-03-06': { R: { estado: 'en_proceso', total_bd: 0 } },
  },
  resumen: {
    E: { pendiente: 250, provisional: 40, error: 1 },
    R: { pendiente: 240, en_proceso: 2, error: 3 },
  },
};

test('diasDelMes: febrero común y bisiesto, meses de 30 y 31', () => {
  assert.equal(diasDelMes(2026, 2), 28);
  assert.equal(diasDelMes(2024, 2), 29);
  assert.equal(diasDelMes(2026, 4), 30);
  assert.equal(diasDelMes(2026, 12), 31);
});

test('fechaValida: el 30 de febrero no existe', () => {
  assert.equal(fechaValida(2026, 2, 30), false);
  assert.equal(fechaValida(2024, 2, 29), true);
  assert.equal(fechaValida(2026, 4, 31), false);
  assert.equal(fechaValida(2026, 1, 31), true);
});

test('esFutura compara contra hoy; hoy no es futuro', () => {
  assert.equal(esFutura('2026-10-14', '2026-10-13'), true);
  assert.equal(esFutura('2026-10-13', '2026-10-13'), false);
  assert.equal(esFutura('2025-12-31', '2026-01-01'), false);
});

test('rangoMes da el primer y el último día', () => {
  assert.deepEqual(rangoMes(2026, 2), { desde: '2026-02-01', hasta: '2026-02-28' });
  assert.deepEqual(rangoMes(2024, 2), { desde: '2024-02-01', hasta: '2024-02-29' });
  assert.deepEqual(rangoMes(2026, 12), { desde: '2026-12-01', hasta: '2026-12-31' });
});

test('celda en Ambos: tooltip con las dos direcciones y total E+R', () => {
  const c = celda(cal, '2026-03-04', 'A');
  assert.equal(c.tooltip, '4 mar 2026 · Emitidos: Provisional (12) · Recibidos: Error');
  assert.deepEqual(c.contenido, { tipo: 'total', valor: 12 });
  assert.deepEqual(c.estados.map((e) => e.estado), ['provisional', 'error']);
});

test('celda con filtro: solo la dirección pedida', () => {
  const r = celda(cal, '2026-03-04', 'R');
  assert.equal(r.tooltip, '4 mar 2026 · Recibidos: Error');
  assert.deepEqual(r.contenido, { tipo: 'error' });
  const e = celda(cal, '2026-03-04', 'E');
  assert.deepEqual(e.contenido, { tipo: 'total', valor: 12 });
});

test('celda: un día sin CFDI provisional muestra 0, no vacío', () => {
  assert.deepEqual(celda(cal, '2026-03-05', 'E').contenido, { tipo: 'total', valor: 0 });
});

test('celda: en_proceso es un punto; ausente es pendiente vacío', () => {
  assert.deepEqual(celda(cal, '2026-03-06', 'R').contenido, { tipo: 'punto' });
  const vacio = celda(cal, '2026-03-07', 'A');
  assert.deepEqual(vacio.contenido, { tipo: 'vacio' });
  assert.equal(vacio.tooltip, '7 mar 2026 · Emitidos: Por descargar · Recibidos: Por descargar');
});

test('celda: sin piloto, un día pasado pendiente invita a Pro; hoy y con datos no', () => {
  assert.ok(celda(cal, '2026-03-07', 'A', { sinPiloto: true }).tooltip.endsWith('Con Pro se descarga solo.'));
  assert.ok(!celda(cal, '2026-03-04', 'A', { sinPiloto: true }).tooltip.includes('Con Pro'));
  assert.ok(!celda(cal, '2026-10-13', 'A', { sinPiloto: true }).tooltip.includes('Con Pro'));
  assert.ok(!celda(cal, '2026-03-07', 'A').tooltip.includes('Con Pro'));
});

test('claseEstado: una clase distinta por estado', () => {
  const clases = ESTADOS.map(claseEstado);
  assert.equal(new Set(clases).size, ESTADOS.length);
  assert.ok(claseEstado('error').includes('dark:'));
});

test('claseTexto: blanco sobre oscuros, chip si chocan', () => {
  assert.equal(claseTexto(['consolidado']), 'text-white');
  assert.equal(claseTexto(['provisional', 'pendiente']), 'text-foreground');
  assert.ok(claseTexto(['provisional', 'error']).includes('bg-background'));
});

test('resumenAnio: Ambos suma E y R', () => {
  assert.equal(resumenAnio(cal, 'A').pendiente, 490);
  assert.equal(resumenAnio(cal, 'A').error, 4);
  assert.equal(resumenAnio(cal, 'E').provisional, 40);
  assert.equal(resumenAnio(cal, 'R').en_proceso, 2);
  assert.equal(resumenAnio(cal, 'R').consolidado, 0);
});

test('textoSolicitud traduce los códigos del SAT', () => {
  assert.equal(textoSolicitud('solicitada'), 'En cola');
  assert.equal(textoSolicitud('1'), 'En cola');
  assert.equal(textoSolicitud('2'), 'Procesando');
  assert.equal(textoSolicitud('3'), 'Lista');
  assert.equal(textoSolicitud('descargada'), 'Descargada');
  assert.equal(textoSolicitud('4'), 'Error del SAT');
  assert.equal(textoSolicitud('5'), 'Rechazada');
  assert.equal(textoSolicitud('vencida'), 'Vencida');
});

test('tienePiloto: capacidades manda; sin ellas, el flag premium', () => {
  assert.equal(tienePiloto(null), false);
  assert.equal(tienePiloto({ premium_features_unlocked: true }), true);
  assert.equal(tienePiloto({ premium_features_unlocked: true, capacidades: { piloto: false } }), false);
  assert.equal(tienePiloto({ premium_features_unlocked: false, capacidades: { piloto: true } }), true);
  assert.equal(tienePiloto({}), false);
});

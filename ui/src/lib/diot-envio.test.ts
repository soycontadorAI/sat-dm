// Pruebas de la lógica pura de Enviar DIOT. pnpm test.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  avisoLayout,
  compararTotales,
  etiquetaPeriodoDiot,
  layoutEsperado,
  leerPeriodoParam,
  periodoClave,
  rangoMeses,
  tonoEstatusDiot,
  veredictoPresentacion,
} from './diot-envio.ts';
import type { DiotPresentacionResultado, DiotTotales } from './types.ts';

const totales = (o: Partial<DiotTotales> = {}): DiotTotales => ({
  operaciones: 10, iva_acreditable: 1000, iva_retenido: 50, layout: '2025', ...o,
});
const resultado = (o: Partial<DiotPresentacionResultado> = {}): DiotPresentacionResultado => ({
  estado: 'validado', totales_txt: totales(), totales_portal: totales(),
  discrepancias: null, acuse: null, ...o,
});

test('periodoClave y etiquetaPeriodoDiot', () => {
  assert.equal(periodoClave(2026, 8), '2026-08');
  assert.equal(periodoClave(2026, 12), '2026-12');
  assert.equal(etiquetaPeriodoDiot(2026, 8), 'Agosto 2026');
});

test('leerPeriodoParam: solo YYYY-MM con mes válido', () => {
  assert.deepEqual(leerPeriodoParam('2026-08'), { ejercicio: 2026, mes: 8 });
  assert.equal(leerPeriodoParam('2026-13'), null);
  assert.equal(leerPeriodoParam('2026-00'), null);
  assert.equal(leerPeriodoParam('2026-8'), null);
  assert.equal(leerPeriodoParam('x'), null);
  assert.equal(leerPeriodoParam(null), null);
});

test('layoutEsperado y avisoLayout: 2025+ usa 54 campos, antes 23', () => {
  assert.equal(layoutEsperado(2025), '2025');
  assert.equal(layoutEsperado(2024), 'v24');
  assert.equal(avisoLayout(2026, '2025'), null);
  assert.equal(avisoLayout(2024, 'v24'), null);
  assert.equal(avisoLayout(2026, undefined), null);
  assert.match(avisoLayout(2026, 'v24') ?? '', /23 campos.*54 campos/);
});

test('veredicto: las discrepancias ganan aunque el estado sea validado', () => {
  assert.equal(veredictoPresentacion(null), null);
  assert.equal(veredictoPresentacion(resultado()), 'validado');
  assert.equal(veredictoPresentacion(resultado({ discrepancias: ['Operaciones: TXT=1 vs portal=2'] })), 'discrepancias');
  assert.equal(veredictoPresentacion(resultado({ discrepancias: [] })), 'validado');
  assert.equal(veredictoPresentacion(resultado({ estado: 'presentado', acuse: '/x.pdf' })), 'presentado');
  assert.equal(veredictoPresentacion(resultado({ estado: 'no_presentada' })), 'no_presentada');
  assert.equal(veredictoPresentacion(resultado({ estado: 'desconocido' })), 'desconocido');
});

test('compararTotales: operaciones exactas, montos con tolerancia de 3 pesos', () => {
  assert.deepEqual(compararTotales(null, totales()), []);
  const ok = compararTotales(totales(), totales({ iva_acreditable: 1003 }));
  assert.ok(ok.every((f) => f.coincide));
  assert.equal(ok[1].diferencia, 3);
  const mal = compararTotales(totales(), totales({ iva_acreditable: 1004, operaciones: 11 }));
  assert.equal(mal[0].coincide, false);   // operaciones: ni una de diferencia
  assert.equal(mal[1].coincide, false);   // 4 pesos > tolerancia
  assert.equal(mal[2].coincide, true);
});

test('tonoEstatusDiot: rechazo en rojo, presentada en verde, lo demás neutro', () => {
  assert.equal(tonoEstatusDiot('Presentada'), 'success');
  assert.equal(tonoEstatusDiot('Aceptada'), 'success');
  assert.equal(tonoEstatusDiot('Rechazada'), 'error');
  assert.equal(tonoEstatusDiot('En proceso'), 'warning');
  assert.equal(tonoEstatusDiot('Algo raro'), 'neutral');
  assert.equal(tonoEstatusDiot(undefined), 'neutral');
});

test('rangoMeses: un mes o todo el ejercicio', () => {
  assert.deepEqual(rangoMeses('todos'), { mesIni: 1, mesFin: 12 });
  assert.deepEqual(rangoMeses(5), { mesIni: 5, mesFin: 5 });
});

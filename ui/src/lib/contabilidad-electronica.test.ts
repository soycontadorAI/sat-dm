// Pruebas de la lógica pura de Contabilidad electrónica. pnpm test.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ejerciciosDisponibles,
  etiquetaPeriodo,
  etiquetaTipo,
  resumenAcuses,
  revisarLote,
  tonoEstatus,
} from './contabilidad-electronica.ts';
import type { CeFicha } from './types.ts';

const ficha = (o: Partial<CeFicha> = {}): CeFicha => ({
  path: '/x/SSA980330HU1202601BN.zip',
  archivo: 'SSA980330HU1202601BN.zip',
  rfc: 'SSA980330HU1',
  tipo: 'BN',
  anio: '2026',
  mes: '01',
  problemas: [],
  ...o,
});

test('etiquetaPeriodo: mes, ajuste al cierre y año suelto', () => {
  assert.equal(etiquetaPeriodo('2026', '01'), 'Enero 2026');
  assert.equal(etiquetaPeriodo('2026', '12'), 'Diciembre 2026');
  assert.equal(etiquetaPeriodo('2026', '13'), 'Ajuste al cierre 2026');
  assert.equal(etiquetaPeriodo('2026', ''), '2026');
  assert.equal(etiquetaPeriodo(undefined, '01'), '');
});

test('etiquetaTipo: catálogo y balanza con nombre de contador', () => {
  assert.equal(etiquetaTipo('CT'), 'Catálogo de cuentas');
  assert.equal(etiquetaTipo('BN'), 'Balanza de comprobación');
  assert.equal(etiquetaTipo('ZZ'), 'ZZ');
});

test('revisarLote: vacío, con problemas, RFC distinto y varios RFC', () => {
  assert.equal(revisarLote([], 'SSA980330HU1').ok, false);
  assert.equal(revisarLote([ficha()], 'SSA980330HU1').ok, true);
  // el RFC de la empresa se compara sin importar mayúsculas
  assert.equal(revisarLote([ficha()], 'ssa980330hu1').ok, true);

  const mal = revisarLote([ficha({ problemas: ['XML no cuadra'] })], 'SSA980330HU1');
  assert.equal(mal.ok, false);
  assert.match(mal.errores[0], /1 de 1 no pasan/);

  const otro = revisarLote([ficha()], 'XAXX010101000');
  assert.equal(otro.ok, false);
  assert.match(otro.errores[0], /empresa activa es XAXX010101000/);

  const varios = revisarLote([ficha(), ficha({ rfc: 'SAJ0205248A9' })], null);
  assert.equal(varios.ok, false);
  assert.match(varios.errores[0], /varios RFC/);
});

test('revisarLote: sin empresa activa solo exige coherencia interna', () => {
  assert.equal(revisarLote([ficha()], null).ok, true);
});

test('tonoEstatus: solo Aceptado es verde; Recibido es aviso', () => {
  assert.equal(tonoEstatus('Aceptado'), 'success');
  assert.equal(tonoEstatus('Rechazado'), 'error');
  assert.equal(tonoEstatus('Recibido'), 'warning');
  assert.equal(tonoEstatus(undefined), 'neutral');
});

test('resumenAcuses cuenta por estatus', () => {
  const r = resumenAcuses([
    { folio: '1', estatus: 'Aceptado' },
    { folio: '2', estatus: 'Rechazado' },
    { folio: '3', estatus: 'Recibido' },
    { folio: '4', estatus: 'Aceptado' },
  ]);
  assert.deepEqual(r, { total: 4, aceptados: 2, rechazados: 1, recibidos: 1 });
});

test('ejerciciosDisponibles: el actual y 4 anteriores', () => {
  assert.deepEqual(ejerciciosDisponibles(new Date(2026, 9, 31)), [2026, 2025, 2024, 2023, 2022]);
});

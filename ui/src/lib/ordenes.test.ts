// Pruebas del intérprete de órdenes de ⌘K. Sin dependencias: Node las corre
// con su runner y su soporte nativo de TypeScript:
//   pnpm test:ordenes   (= node --test src/lib/ordenes.test.ts)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ejemplos,
  empresasMencionadas,
  interpretar,
  normalizar,
  periodoDe,
  type EmpresaOrden,
} from './ordenes.ts';

const EMPRESAS: EmpresaOrden[] = [
  { rfc: 'DER180922QX4', nombre: 'Distribuidora El Roble, S.A.', metodos: ['fiel', 'ciec'] },
  { rfc: 'PCE150308MT7', nombre: 'Panadería La Central, S. de R.L.', metodos: ['fiel'] },
  { rfc: 'SIB200117HU9', nombre: 'Servicios Integrales del Bajío', metodos: ['fiel'] },
  { rfc: 'TML160923KP8', nombre: 'Transportes Molina, S.A.', metodos: ['ciec'] },
  { rfc: 'REAN741122K85', nombre: 'Norma Reyes Aguilar', metodos: ['fiel', 'ciec'] },
  { rfc: 'GACL850312H40', nombre: 'Laura García Cervantes', metodos: ['fiel'] },
  { rfc: 'COV110714AB2', nombre: 'Constructora del Valle, S.A. de C.V.', metodos: ['fiel', 'ciec'] },
  { rfc: 'SCI130506AT8', nombre: 'Servicios Contables Integrales, S.C.', metodos: ['fiel'] },
  { rfc: 'ARC010101AA1', nombre: 'Archivada Ejemplo', metodos: ['fiel'], archived_at: '2026-01-01' },
];
const ACTIVA = EMPRESAS[0];
// 6 de octubre de 2026 (mediodía, para no depender de la zona horaria).
const HOY = new Date(2026, 9, 6, 12);

function una(texto: string) {
  const r = interpretar(texto, EMPRESAS, ACTIVA, HOY);
  assert.equal(r.length, 1, `"${texto}" debía dar 1 orden y dio ${r.length}: ${r.map((o) => o.tipo)}`);
  return r[0];
}

test('normaliza acentos y mayúsculas', () => {
  assert.equal(normalizar('  Opinión  32-D de PANADERÍA '), 'opinion 32-d de panaderia');
});

test('descargar recibidos de septiembre de una empresa mencionada', () => {
  const o = una('descargar recibidos de septiembre de Distribuidora El Roble');
  assert.equal(o.tipo, 'descargar');
  assert.equal(o.comprobante, 'R');
  assert.equal(o.canal, 'ws');
  assert.equal(o.empresa?.rfc, 'DER180922QX4');
  assert.equal(o.empresaMencionada, true);
  assert.equal(o.confirmar, true);
  assert.deepEqual(
    [o.periodo?.desde, o.periodo?.hasta, o.periodo?.etiqueta],
    ['2026-09-01', '2026-09-30', 'Septiembre 2026'],
  );
});

test('basta con una palabra del nombre ("distribuidora", sin acentos)', () => {
  const o = una('descargar recibidos de septiembre de distribuidora');
  assert.equal(o.empresa?.rfc, 'DER180922QX4');
});

test('sin empresa usa la activa y lo dice', () => {
  const o = una('bajar emitidos del mes pasado');
  assert.equal(o.empresa?.rfc, ACTIVA.rfc);
  assert.equal(o.empresaMencionada, false);
  assert.equal(o.comprobante, 'E');
  assert.equal(o.periodo?.etiqueta, 'Septiembre 2026');
});

test('sin tipo pide los dos y sin periodo usa el mes en curso', () => {
  const o = una('descargar');
  assert.equal(o.comprobante, 'A');
  assert.equal(o.periodo?.etiqueta, 'Octubre 2026');
  assert.equal(o.periodo?.explicito, false);
});

test('"descargar agosto" toma agosto de este año', () => {
  assert.equal(una('descargar agosto').periodo?.desde, '2026-08-01');
});

test('un mes que todavía no llega toma el del año pasado', () => {
  const o = una('descargar recibidos de diciembre');
  assert.equal(o.periodo?.anio, 2025);
  assert.equal(o.periodo?.hasta, '2025-12-31');
});

test('año explícito', () => {
  assert.equal(una('descargar emitidos de marzo de 2025').periodo?.desde, '2025-03-01');
  assert.equal(una('descargar emitidos de febrero 2024').periodo?.hasta, '2024-02-29');
});

test('una empresa solo con Contraseña va a Descarga rápida', () => {
  const o = una('descargar recibidos de septiembre de transportes molina');
  assert.equal(o.tipo, 'descarga-rapida');
  assert.equal(o.canal, 'ciec');
  assert.equal(o.confirmar, true);
});

test('"con contraseña" fuerza el portal', () => {
  const o = una('descargar recibidos de septiembre de roble con contraseña');
  assert.equal(o.tipo, 'descarga-rapida');
  assert.equal(o.canal, 'ciec');
  assert.equal(o.canalForzado, true);
});

test('"con contraseña" en una empresa sin Contraseña avisa el problema', () => {
  const o = una('descargar recibidos de panaderia con contraseña');
  assert.ok(o.problema);
});

test('descarga rápida usa el portal con e.firma si la hay', () => {
  const o = una('descarga rápida de Panadería La Central');
  assert.equal(o.tipo, 'descarga-rapida');
  assert.equal(o.canal, 'fiel');
  assert.equal(o.empresa?.rfc, 'PCE150308MT7');
});

test('constancia y opinión se ejecutan sin segundo Enter', () => {
  const c = una('constancia de Panadería La Central');
  assert.equal(c.tipo, 'constancia');
  assert.equal(c.canal, 'fiel');
  assert.equal(c.confirmar, false);
  const csf = una('csf de laura garcia');
  assert.equal(csf.tipo, 'constancia');
  assert.equal(csf.empresa?.rfc, 'GACL850312H40');
  const op = una('opinion de transportes molina');
  assert.equal(op.tipo, 'opinion');
  assert.equal(op.canal, 'ciec');
  assert.equal(una('32-D de Norma Reyes').empresa?.rfc, 'REAN741122K85');
});

test('constancia no se confunde con descarga de CFDIs', () => {
  const r = interpretar('descargar constancia de panaderia', EMPRESAS, ACTIVA, HOY);
  assert.deepEqual(r.map((o) => o.tipo), ['constancia']);
});

test('empate entre dos empresas: una orden por cada una', () => {
  const r = interpretar('opinión de servicios integrales', EMPRESAS, ACTIVA, HOY);
  assert.deepEqual(
    r.map((o) => o.empresa?.rfc).sort(),
    ['SCI130506AT8', 'SIB200117HU9'],
  );
  // "bajío" desempata.
  assert.equal(una('opinión de servicios integrales del bajío').empresa?.rfc, 'SIB200117HU9');
});

test('por RFC completo', () => {
  const o = una('constancia de PCE150308MT7');
  assert.equal(o.empresa?.rfc, 'PCE150308MT7');
  assert.deepEqual(empresasMencionadas(normalizar('pce150308mt7'), EMPRESAS).map((e) => e.rfc), [
    'PCE150308MT7',
  ]);
});

test('las archivadas no cuentan', () => {
  assert.deepEqual(empresasMencionadas('archivada', EMPRESAS), []);
});

test('listas negras y sinónimos (69-B)', () => {
  assert.equal(una('listas negras de Constructora del Valle').tipo, 'listas-negras');
  const o = una('69-B de Panadería');
  assert.equal(o.tipo, 'listas-negras');
  assert.equal(o.empresa?.rfc, 'PCE150308MT7');
});

test('DIOT con periodo y DIOT sin periodo', () => {
  const o = una('DIOT de agosto de Distribuidora El Roble');
  assert.equal(o.tipo, 'diot');
  assert.equal(o.periodo?.mes, 8);
  assert.equal(una('DIOT').periodo, undefined);
  assert.equal(una('DIOT del mes pasado').periodo?.mes, 9);
});

test('presentar DIOT es Pronto: no es orden', () => {
  assert.deepEqual(interpretar('presentar DIOT', EMPRESAS, ACTIVA, HOY), []);
});

test('calculadoras', () => {
  assert.equal(una('finiquito').destinoId, 'calc-finiquito');
  assert.equal(una('aguinaldo').destinoId, 'calc-aguinaldo');
  assert.equal(una('PTU').destinoId, 'calc-ptu');
  assert.equal(una('isr de sueldos').destinoId, 'calc-isr');
  assert.equal(una('salario base').destinoId, 'calc-sbc');
  assert.equal(una('liquidación').destinoId, 'calc-liquidacion');
  assert.equal(una('carga patronal').destinoId, 'calc-carga');
});

test('agregar empresa y tema', () => {
  assert.equal(una('agregar empresa').tipo, 'agregar-empresa');
  assert.equal(una('tema oscuro').tema, 'oscuro');
  assert.equal(una('tema claro').tema, 'claro');
});

test('sin verbo no hay orden (el buscador muestra pantallas y empresas)', () => {
  assert.deepEqual(interpretar('panaderia', EMPRESAS, ACTIVA, HOY), []);
  assert.deepEqual(interpretar('nomina', EMPRESAS, ACTIVA, HOY), []);
  assert.deepEqual(interpretar('x', EMPRESAS, ACTIVA, HOY), []);
});

test('sin empresa activa ni mencionada avisa', () => {
  const r = interpretar('descargar recibidos', [], null, HOY);
  assert.equal(r.length, 1);
  assert.ok(r[0].problema);
});

test('periodo: este mes y abreviaturas', () => {
  assert.equal(periodoDe('descargar este mes', HOY)?.mes, 10);
  assert.equal(periodoDe('descargar sep', HOY)?.mes, 9);
  assert.equal(periodoDe('descargar', HOY), null);
});

test('ejemplos con las empresas de la cuenta, sin la orden para todas', () => {
  const ej = ejemplos(EMPRESAS, ACTIVA, HOY);
  assert.equal(ej[0], 'Descargar recibidos de septiembre de Distribuidora El Roble');
  assert.ok(ej.some((e) => e.startsWith('Constancia de ')));
  assert.ok(!ej.some((e) => /todas/i.test(e)));
  // Cada ejemplo se entiende como orden.
  for (const e of ej) assert.ok(interpretar(e, EMPRESAS, ACTIVA, HOY).length >= 1, e);
});

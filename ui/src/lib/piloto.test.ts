// Pruebas de la lógica pura de la descarga automática. pnpm test.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  avisosSinLeer,
  conteoIncluidas,
  esAvisoDeToast,
  toastsDeAvisos,
  etiquetaEstado,
  infoAviso,
  textoCierre,
  textoIncluidas,
  textoPausa,
  textoProximaPasada,
} from './piloto.ts';
import type { PilotoAviso, PilotoEmpresa } from './types.ts';

// Fechas locales (sin zona) para que la prueba no dependa del huso del equipo.
const iso = (y: number, m: number, d: number, h: number, mi: number) =>
  new Date(y, m - 1, d, h, mi).toISOString();

test('próxima pasada: hoy, mañana, en curso y lejana', () => {
  const ahora = new Date(2026, 9, 13, 22, 0);
  assert.equal(textoProximaPasada(iso(2026, 10, 13, 23, 5), ahora), 'hoy 23:05');
  assert.equal(textoProximaPasada(iso(2026, 10, 14, 1, 13), ahora), 'mañana 1:13');
  assert.equal(textoProximaPasada(iso(2026, 10, 13, 21, 0), ahora), 'en curso');
  assert.equal(textoProximaPasada(iso(2026, 10, 20, 1, 13), ahora), '20 oct. 1:13');
  assert.equal(textoProximaPasada(null, ahora), 'sin programar');
  assert.equal(textoProximaPasada('basura', ahora), 'sin programar');
});

test('cierre del mes', () => {
  assert.equal(textoCierre({ periodo: '2026-09', fecha: '2026-10-05' }), 'Cierre de septiembre: 5 oct.');
  assert.equal(textoCierre({ periodo: '2026-12', fecha: '2027-01-05' }), 'Cierre de diciembre: 5 ene.');
  assert.equal(textoCierre(null), null);
  assert.equal(textoCierre({ periodo: 'x', fecha: 'y' }), null);
});

test('avisos: icono y etiqueta por tipo', () => {
  assert.equal(infoAviso('resumen').icon, 'ph:check-circle-light');
  assert.equal(infoAviso('error').etiqueta, 'Error');
  assert.equal(infoAviso('cancelacion').icon, 'ph:receipt-x-light');
  assert.equal(infoAviso('efirma').etiqueta, 'e.firma');
});

test('pausa y etiqueta de estado', () => {
  assert.match(textoPausa('sesion') ?? '', /otra instalación/);
  assert.match(textoPausa('licencia') ?? '', /plan ya no incluye/);
  assert.equal(textoPausa(null), null);
  assert.equal(textoPausa('inactivo'), null);
  assert.equal(etiquetaEstado({ activo: false, pausado_por: 'inactivo' }), 'Apagada');
  assert.equal(etiquetaEstado({ activo: true, pausado_por: null }), 'Activa');
  assert.equal(etiquetaEstado({ activo: true, pausado_por: 'sesion' }), 'Pausada');
  assert.equal(etiquetaEstado({ activo: true, pausado_por: 'licencia' }), 'Pausada');
});

const emp = (rfc: string, incluida: boolean, motivo: string | null = null): PilotoEmpresa => ({
  rfc,
  nombre: rfc,
  incluida,
  elegible: motivo === null,
  motivo,
});

test('conteo de incluidas ignora archivadas', () => {
  const lista = [emp('A', true), emp('B', false, 'No incluida'), emp('C', true, 'Sin e.firma'), emp('D', false, 'Archivada')];
  assert.deepEqual(conteoIncluidas(lista), { incluidas: 2, total: 3 });
  assert.equal(textoIncluidas(lista), '2 de 3 empresas incluidas');
  assert.equal(textoIncluidas([emp('A', true)]), '1 de 1 empresa incluida');
});

test('avisos sin leer ordenados y tipos de toast', () => {
  const a = (id: number, tipo: PilotoAviso['tipo'], leido: boolean, creado_en: string): PilotoAviso => ({
    id, tipo, rfc: null, periodo: null, mensaje: 'x', creado_en, leido,
  });
  const lista = [a(1, 'resumen', false, '2026-10-01'), a(2, 'error', false, '2026-10-03'), a(3, 'efirma', true, '2026-10-02')];
  assert.deepEqual(avisosSinLeer(lista).map((x) => x.id), [2, 1]);
  assert.equal(esAvisoDeToast(lista[0]), true);
  assert.equal(esAvisoDeToast(lista[1]), false);
});

test('muchos avisos nuevos a la vez se juntan en uno', () => {
  const aviso = (id: number, tipo: PilotoAviso['tipo']): PilotoAviso => ({
    id, tipo, rfc: 'AAA010101AAA', periodo: '2026-09', mensaje: `aviso ${id}`, creado_en: '', leido: false,
  });
  const pocos = [aviso(1, 'resumen'), aviso(2, 'cancelacion'), aviso(3, 'error')];
  assert.deepEqual(
    toastsDeAvisos(pocos).map((t) => t.id),
    [1, 2], // "error" se queda en el panel
  );
  const muchos = [1, 2, 3, 4, 5].map((i) => aviso(i, i === 5 ? 'resumen' : 'cancelacion'));
  const uno = toastsDeAvisos(muchos);
  assert.equal(uno.length, 1);
  assert.equal(uno[0].id, 5);
  assert.equal(uno[0].tipo, 'cancelacion');
  assert.match(uno[0].mensaje, /^5 avisos nuevos/);
  const resumenes = toastsDeAvisos([1, 2, 3, 4].map((i) => aviso(i, 'resumen')));
  assert.equal(resumenes[0].tipo, 'resumen');
});

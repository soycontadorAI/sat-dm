// Pruebas de qué navegación ve una instalación (clásica o espacios). Sin
// dependencias: pnpm test (= node --test src/lib/*.test.ts).

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { modoDeLabs, resolverModoNavegacion, type EntradaModo } from './navegacion-modo.ts';

const DESDE = new Date('2026-11-02T00:00:00-06:00');
const ANTES = new Date('2026-10-23T12:00:00-06:00');
const DESPUES = new Date('2026-11-02T09:00:00-06:00');

function entrada(cambios: Partial<EntradaModo> = {}): EntradaModo {
  return {
    disponible: true,
    preferencia: null,
    licencia: null,
    paraTodos: false,
    enPrueba: false,
    recordado: false,
    ahora: ANTES,
    desde: DESDE,
    ...cambios,
  };
}

test('sin nada, la clásica', () => {
  assert.deepEqual(resolverModoNavegacion(entrada()), { modo: 'clasica', origen: 'default' });
});

test('el interruptor apagado gana sobre todo (ni labs)', () => {
  const r = resolverModoNavegacion(
    entrada({ disponible: false, preferencia: 'espacios', paraTodos: true, enPrueba: true, ahora: DESPUES }),
  );
  assert.deepEqual(r, { modo: 'clasica', origen: 'apagado' });
});

test('labs o Ajustes: la preferencia de la instalación manda', () => {
  assert.equal(resolverModoNavegacion(entrada({ preferencia: 'espacios' })).modo, 'espacios');
  // Quien volvió a la clásica no recibe espacios el 2 de noviembre aunque esté en prueba.
  const r = resolverModoNavegacion(entrada({ preferencia: 'clasica', enPrueba: true, ahora: DESPUES }));
  assert.deepEqual(r, { modo: 'clasica', origen: 'preferencia' });
});

test('una prueba antes del 2 de noviembre sigue en la clásica', () => {
  assert.equal(resolverModoNavegacion(entrada({ enPrueba: true, ahora: ANTES })).modo, 'clasica');
});

test('desde el 2 de noviembre, las cuentas en prueba (y las nuevas) abren con espacios', () => {
  const r = resolverModoNavegacion(entrada({ enPrueba: true, ahora: DESPUES }));
  assert.deepEqual(r, { modo: 'espacios', origen: 'prueba' });
  // Justo a la medianoche de la Ciudad de México.
  assert.equal(resolverModoNavegacion(entrada({ enPrueba: true, ahora: DESDE })).modo, 'espacios');
});

test('las que pagan siguen con la clásica el 2 de noviembre', () => {
  assert.equal(resolverModoNavegacion(entrada({ enPrueba: false, ahora: DESPUES })).modo, 'clasica');
});

test('lo recordado se queda al pagar o al terminar la prueba', () => {
  const r = resolverModoNavegacion(entrada({ enPrueba: false, recordado: true, ahora: DESPUES }));
  assert.deepEqual(r, { modo: 'espacios', origen: 'recordado' });
});

test('la licencia puede encenderla o apagarla por segmento, sin sacar versión', () => {
  assert.equal(resolverModoNavegacion(entrada({ licencia: 'espacios' })).modo, 'espacios');
  assert.equal(
    resolverModoNavegacion(entrada({ licencia: 'clasica', enPrueba: true, recordado: true, ahora: DESPUES })).modo,
    'clasica',
  );
});

test('fase 2: para todos', () => {
  assert.deepEqual(resolverModoNavegacion(entrada({ paraTodos: true })), {
    modo: 'espacios',
    origen: 'para-todos',
  });
});

test('?labs=espacios y ?labs=clasica, también en lista', () => {
  assert.equal(modoDeLabs('?labs=espacios'), 'espacios');
  assert.equal(modoDeLabs('?labs=csd,espacios'), 'espacios');
  assert.equal(modoDeLabs('?labs=clasica'), 'clasica');
  assert.equal(modoDeLabs('?labs=off'), 'clasica');
  assert.equal(modoDeLabs('?labs=csd'), null);
  assert.equal(modoDeLabs(''), null);
});

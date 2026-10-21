// Pruebas de la lógica pura de la solicitud desde la base. pnpm test.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  etiquetaDireccion,
  hayServidos,
  listaRangos,
  rangoCorto,
  resumenDeRespuesta,
  textoErrorRango,
  textoHuecos,
  TIPOS_ERROR,
  textoServidos,
  textoSinXml,
  tituloErrores,
  tituloServido,
  unirLista,
} from './servir-base.ts';
import type { ResumenServido } from './types.ts';

test('rangoCorto: un día, mismo mes, cruce de mes y de año', () => {
  assert.equal(rangoCorto('2026-03-10', '2026-03-10'), '10 de marzo');
  assert.equal(rangoCorto('2026-03-10', '2026-03-12'), '10 al 12 de marzo');
  assert.equal(rangoCorto('2026-03-28', '2026-04-02'), '28 de marzo al 2 de abril');
  assert.equal(
    rangoCorto('2025-12-30', '2026-01-02'),
    '30 de diciembre de 2025 al 2 de enero de 2026',
  );
});

test('rangoCorto: fecha inválida no truena', () => {
  assert.equal(rangoCorto('x', 'x'), 'x');
  assert.equal(rangoCorto('x', 'y'), 'x al y');
});

test('unirLista y listaRangos', () => {
  assert.equal(unirLista([]), '');
  assert.equal(unirLista(['a']), 'a');
  assert.equal(unirLista(['a', 'b']), 'a y b');
  assert.equal(unirLista(['a', 'b', 'c']), 'a, b y c');
  assert.equal(
    listaRangos([
      { fecha_inicio: '2026-03-10', fecha_fin: '2026-03-12' },
      { fecha_inicio: '2026-03-20', fecha_fin: '2026-03-20' },
    ]),
    '10 al 12 de marzo y 20 de marzo',
  );
});

test('textoServidos: singular y plural', () => {
  assert.equal(
    textoServidos(12, 340),
    '12 días ya estaban consolidados en la base (340 CFDI): se guardaron en la carpeta de la descarga sin ir al SAT.',
  );
  assert.match(textoServidos(1, 3), /^1 día ya estaba consolidado/);
  assert.equal(
    textoServidos(3, 0),
    '3 días ya estaban consolidados en la base, sin CFDI: no hizo falta ir al SAT por ellos.',
  );
});

test('textoHuecos: vacío, uno y varios', () => {
  assert.equal(textoHuecos([]), '');
  assert.equal(
    textoHuecos([{ id_solicitud: 'a', fecha_inicio: '2026-03-10', fecha_fin: '2026-03-12' }]),
    'Al SAT se pidieron solo el hueco: 10 al 12 de marzo.',
  );
  assert.equal(
    textoHuecos([
      { id_solicitud: 'a', fecha_inicio: '2026-03-10', fecha_fin: '2026-03-12' },
      { id_solicitud: 'b', fecha_inicio: '2026-03-20', fecha_fin: '2026-03-22' },
    ]),
    'Al SAT se pidieron solo los huecos: 10 al 12 de marzo y 20 al 22 de marzo.',
  );
});

test('textoSinXml', () => {
  assert.equal(textoSinXml(0), '');
  assert.equal(textoSinXml(1), '1 CFDI de esos días no tiene XML guardado.');
  assert.equal(textoSinXml(4), '4 CFDI de esos días no tienen XML guardado.');
});

test('textoErrorRango', () => {
  assert.equal(
    textoErrorRango({
      tipo: 'sat',
      rango: ['2026-03-20', '2026-03-22'],
      mensaje: 'El SAT rechazó',
    }),
    '20 al 22 de marzo: El SAT rechazó',
  );
});

const base = (dias: number, cfdis: number, sin_xml = 0): ResumenServido => ({
  direccion: 'R',
  servidos: { dias, cfdis, ruta: `/r/${dias}`, sin_xml },
  solicitudes: [],
  errores: [],
});

test('resumenDeRespuesta: errores ausente -> [] y conserva la dirección', () => {
  const res = {
    ok: true,
    id_solicitud: null,
    solicitudes: [],
    servidos: { dias: 2, cfdis: 5, ruta: '/x', sin_xml: 0 },
  };
  const r = resumenDeRespuesta(res, 'E');
  assert.deepEqual(r.errores, []);
  assert.equal(r.servidos.dias, 2);
  assert.equal(r.direccion, 'E');
  assert.equal(resumenDeRespuesta(res, 'R').direccion, 'R');
});

test('resumenDeRespuesta: no mezcla los días ni la ruta de E y R', () => {
  const e = resumenDeRespuesta(
    { ok: true, id_solicitud: null, solicitudes: [], servidos: { dias: 2, cfdis: 1, ruta: '/e', sin_xml: 0 } },
    'E',
  );
  const r = resumenDeRespuesta(
    { ok: true, id_solicitud: null, solicitudes: [], servidos: { dias: 3, cfdis: 4, ruta: '/r', sin_xml: 0 } },
    'R',
  );
  assert.equal(e.servidos.ruta, '/e');
  assert.equal(r.servidos.ruta, '/r');
  assert.equal(e.servidos.dias + r.servidos.dias, 5);
});

test('etiquetaDireccion y tituloServido', () => {
  assert.equal(etiquetaDireccion('E'), 'Emitidos');
  assert.equal(etiquetaDireccion('R'), 'Recibidos');
  assert.equal(tituloServido('R', 1), 'Servido desde la base');
  assert.equal(tituloServido('E', 2), 'Servido desde la base · Emitidos');
  assert.equal(tituloServido('R', 2), 'Servido desde la base · Recibidos');
});

test('hayServidos', () => {
  assert.equal(hayServidos(null), false);
  assert.equal(hayServidos(base(0, 0)), false);
  assert.equal(hayServidos(base(2, 10, 1)), true);
});

test('tituloErrores: según el tipo y en plural si son varios', () => {
  assert.equal(tituloErrores('sat', 1), 'Un rango no se pudo solicitar');
  assert.equal(tituloErrores('sat', 2), 'Algunos rangos no se pudieron solicitar');
  assert.equal(tituloErrores('base', 1), 'No se pudo guardar lo que ya estaba en la base');
  assert.equal(
    tituloErrores('base', 2),
    'En varias solicitudes no se pudo guardar lo que ya estaba en la base',
  );
});

test('resumenDeRespuesta conserva el tipo de cada error', () => {
  const r = resumenDeRespuesta(
    {
      ok: true,
      id_solicitud: null,
      solicitudes: [],
      servidos: { dias: 0, cfdis: 0, ruta: null, sin_xml: 0 },
      errores: [
        { tipo: 'sat', rango: ['2026-03-01', '2026-03-02'], mensaje: 'a' },
        { tipo: 'base', rango: ['2026-03-01', '2026-03-10'], mensaje: 'b' },
      ],
    },
    'R',
  );
  assert.deepEqual(r.errores.map((e) => e.tipo), ['sat', 'base']);
});

test('errores de tipo cupo: texto con solo el mensaje y título propio', () => {
  const e = {
    tipo: 'cupo' as const,
    rango: ['2026-03-04', '2026-03-08'] as [string, string],
    mensaje: 'Tu plan Gratis incluye 10 descargas al mes y ya usaste las 10.',
    datos: { tope: 10, usadas: 10 },
  };
  assert.equal(textoErrorRango(e), e.mensaje);
  assert.equal(
    tituloErrores('cupo', 1),
    'No se pidió al SAT lo que faltaba: llegaste al tope de descargas',
  );
  assert.equal(tituloErrores('cupo', 3), tituloErrores('cupo', 1));
  assert.deepEqual([...TIPOS_ERROR], ['sat', 'base', 'cupo']);
  assert.equal(
    textoErrorRango({ tipo: 'sat', rango: ['2026-03-04', '2026-03-05'], mensaje: 'x' }),
    '4 al 5 de marzo: x',
  );
});

test('resumenDeRespuesta conserva el error de cupo con sus datos', () => {
  const r = resumenDeRespuesta(
    {
      ok: true,
      id_solicitud: null,
      solicitudes: [],
      servidos: { dias: 3, cfdis: 1, ruta: '/x', sin_xml: 0 },
      errores: [
        { tipo: 'cupo', rango: ['2026-03-04', '2026-03-08'], mensaje: 'tope', datos: { tope: 10 } },
      ],
    },
    'R',
  );
  assert.equal(r.errores[0].tipo, 'cupo');
  assert.deepEqual(r.errores[0].datos, { tope: 10 });
  assert.equal(hayServidos(r), true);
});

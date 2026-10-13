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

// --- Historial ---

import {
  etiquetaMes,
  historialTerminado,
  desdeInicial,
  mesesDisponibles,
  nombreMes,
  porcentajeHistorial,
  textoEmpezados,
  textoHistorial,
  textoHistorialEmpresa,
} from './piloto.ts';
import type { PilotoHistorial } from './types.ts';

const hist = (o: Partial<PilotoHistorial> = {}): PilotoHistorial => ({
  desde: '2025-01-01',
  minimo: '2021-11-01',
  maximo: '2026-08-01',
  meses_total: 20,
  meses_completos: 3,
  meses_con_diferencia: 1,
  siguiente: '2026-07',
  ...o,
});

test('nombres de mes', () => {
  assert.equal(etiquetaMes('2025-01-01'), 'ene 2025');
  assert.equal(etiquetaMes('2026-07'), 'jul 2026');
  assert.equal(etiquetaMes('basura'), '');
  assert.equal(nombreMes('2026-07'), 'julio de 2026');
  assert.equal(nombreMes(null), '');
});

test('meses disponibles: del más reciente al más antiguo, inclusive', () => {
  const m = mesesDisponibles('2025-11-01', '2026-02-01');
  assert.deepEqual(
    m.map((x) => x.valor),
    ['2026-02-01', '2026-01-01', '2025-12-01', '2025-11-01'],
  );
  assert.equal(m[0].etiqueta, 'feb 2026');
  assert.equal(mesesDisponibles('2026-08-01', '2026-08-01').length, 1);
  assert.deepEqual(mesesDisponibles('2026-09-01', '2026-08-01'), []);
  assert.equal(mesesDisponibles('2021-11-01', '2026-08-01').length, 58);
});

test('texto del progreso del historial', () => {
  assert.equal(textoHistorial(hist()), '3 de 20 meses en la base, 1 con diferencia; va en julio de 2026');
  assert.equal(
    textoHistorial(hist({ meses_con_diferencia: 0, meses_completos: 0 })),
    '0 de 20 meses en la base; va en julio de 2026',
  );
  assert.equal(textoHistorial(hist({ desde: null })), '');
  const fin = hist({ meses_completos: 20, siguiente: null });
  assert.equal(historialTerminado(fin), true);
  assert.equal(textoHistorial(fin), 'Terminado: 20 de 20 meses en la base (1 con diferencia).');
  // Un mes que falló sin reintento ya no deja el avance "yendo" en él.
  const conError = hist({ meses_completos: 18, meses_con_error: 2, siguiente: null });
  assert.equal(historialTerminado(conError), true);
  assert.equal(
    textoHistorial(conError),
    'Terminado: 18 de 20 meses en la base (1 con diferencia; 2 no se pudieron cerrar).',
  );
  assert.equal(
    textoHistorial(hist({ meses_con_error: 1 })),
    '3 de 20 meses en la base, 1 con diferencia, 1 no se pudo cerrar; va en julio de 2026',
  );
  assert.equal(historialTerminado(hist({ desde: null, siguiente: null, meses_completos: 20 })), false);
  assert.equal(historialTerminado(hist({ siguiente: null, meses_total: 0 })), false);
});

test('texto del historial con varias empresas y singulares', () => {
  assert.equal(
    textoHistorial(hist({ meses: 10, empresas: 3, meses_total: 30, meses_completos: 12 })),
    '3 empresas, 10 meses: 12 de 30 cierres en la base, 1 con diferencia; va en julio de 2026',
  );
  assert.equal(
    textoHistorial(hist({ meses: 10, empresas: 1, meses_total: 10, meses_completos: 3 })),
    '3 de 10 meses en la base, 1 con diferencia; va en julio de 2026',
  );
  assert.equal(
    textoHistorial(hist({ meses_total: 1, meses_completos: 1, meses_con_diferencia: 0, siguiente: null })),
    'Terminado: 1 de 1 mes en la base.',
  );
  assert.equal(
    textoHistorial(hist({ empresas: 2, meses: 1, meses_total: 2, meses_completos: 2, meses_con_diferencia: 0, siguiente: null })),
    'Terminado: 2 de 2 cierres en la base.',
  );
});

test('meses ya empezados tras detener el historial', () => {
  assert.equal(textoEmpezados(hist({ desde: null, empezados: 1 })), 'Se termina 1 mes que ya había empezado.');
  assert.equal(textoEmpezados(hist({ desde: null, empezados: 3 })), 'Se terminan 3 meses que ya habían empezado.');
  assert.equal(textoEmpezados(hist({ desde: null, empezados: 0 })), '');
  assert.equal(textoEmpezados(hist({ empezados: 2 })), '');
  assert.equal(textoEmpezados(hist({ desde: null })), '');
});

test('porcentaje del historial', () => {
  assert.equal(porcentajeHistorial(hist()), 15);
  assert.equal(porcentajeHistorial(hist({ meses_total: 0 })), 0);
  assert.equal(porcentajeHistorial(hist({ meses_completos: 99 })), 100);
  // Los que fallaron sin reintento cuentan como hechos: al terminar llega a 100.
  assert.equal(porcentajeHistorial(hist({ meses_completos: 18, meses_con_error: 2 })), 100);
  assert.equal(porcentajeHistorial(hist({ meses_completos: 3, meses_con_error: 2 })), 25);
});

test('el selector de activar arranca en el mínimo si el guardado ya no está en la lista', () => {
  assert.equal(desdeInicial(hist({ desde: '2025-01-01' })), '2025-01-01');
  assert.equal(desdeInicial(hist({ desde: '2021-06-01', minimo: '2021-11-01' })), '2021-11-01');
  assert.equal(desdeInicial(hist({ desde: null })), '');
  assert.equal(desdeInicial(undefined), '');
});

test('historial por empresa', () => {
  const e = { rfc: 'AAA010101AAA', nombre: 'X', incluida: true, elegible: true, motivo: null };
  assert.equal(textoHistorialEmpresa({ ...e, historial_completos: 3, historial_total: 20 }), 'Historial: 3/20');
  assert.equal(textoHistorialEmpresa({ ...e, historial_total: 0 }), null);
  assert.equal(textoHistorialEmpresa(e), null);
});

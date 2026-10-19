// ---------------------------------------------------------------------------
// Abrir vs. descargar: la misma acción del historial en los dos modos.
//
// En desktop "abrir" delega al SO (POST /abrir: Finder/Explorer o el visor de
// PDF). En la versión web no hay SO que abrir: el navegador BAJA el archivo
// (/descargas/archivo) o la carpeta como ZIP (/descargas/zip). Los helpers de
// copy/icono mantienen los botones coherentes en ambos modos.
// ---------------------------------------------------------------------------

import type { SatApiClient } from './api-client';
import { esWeb } from './modo';

export type ModoAbrir = 'carpeta' | 'archivo';

/** Abre (desktop) o descarga (web) una ruta registrada en el historial. */
export async function abrirODescargar(
  apiClient: SatApiClient,
  ruta: string,
  modo: ModoAbrir,
): Promise<void> {
  if (!esWeb()) {
    await apiClient.abrir(ruta, modo);
    return;
  }
  const url = apiClient.urlDescargaHistorial(ruta, modo === 'archivo' ? 'archivo' : 'zip');
  // <a download> en vez de window.open: no deja una pestaña en blanco y
  // respeta el Content-Disposition attachment del agente.
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

/**
 * Guarda un Blob como archivo, en desktop y en web: es el mismo mecanismo de
 * los exports del procesador y las calculadoras.
 */
export function guardarBlob(blob: Blob, nombre: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = nombre;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Tooltip del botón según el modo de ejecución. */
export function tituloAbrir(modo: ModoAbrir): string {
  if (esWeb()) {
    return modo === 'archivo' ? 'Descargar el PDF' : 'Descargar como ZIP';
  }
  return modo === 'archivo' ? 'Abrir el PDF' : 'Abrir la carpeta donde se guardó';
}

/** Icono del botón: en la web la "carpeta" se baja, no se abre. */
export function iconoAbrir(modo: ModoAbrir): string {
  if (esWeb() && modo === 'carpeta') return 'ph:download-simple-light';
  return modo === 'archivo' ? 'ph:file-pdf-light' : 'ph:folder-open-light';
}

// ---------------------------------------------------------------------------
// Entregar la sesión al agente recién aprovisionado (versión web).
//
// La primera vez que un usuario entra, el provisioner crea su contenedor y
// contesta en cuanto el agente responde dentro del servidor. El proxy público
// (Traefik) puede tardar unos segundos más en publicar la ruta /u/<slug>:
// mientras tanto el navegador ve un fallo de red ("Failed to fetch") o un 404
// sin CORS. Se reintenta hasta ~15 s antes de mostrar el error.
// ---------------------------------------------------------------------------

import { ApiError, SatApiClient } from '@/lib/api-client';
import type { ProvisionResult } from '@/lib/provisioner-client';

const ESPERA_MAXIMA_MS = 15_000;
const PAUSA_MS = 1_000;

function esTransitorio(err: unknown): boolean {
  // Sin respuesta HTTP legible (red o proxy sin CORS) o el proxy aún sin ruta.
  if (!(err instanceof ApiError)) return true;
  return [404, 502, 503, 504].includes(err.status);
}

export async function adoptarSesion(r: ProvisionResult): Promise<void> {
  const cliente = new SatApiClient(r.base_url);
  const limite = Date.now() + ESPERA_MAXIMA_MS;
  for (;;) {
    try {
      await cliente.authAdoptSession(r.session);
      return;
    } catch (err) {
      if (!esTransitorio(err) || Date.now() + PAUSA_MS > limite) throw err;
      await new Promise((resolve) => setTimeout(resolve, PAUSA_MS));
    }
  }
}

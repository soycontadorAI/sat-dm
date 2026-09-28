// ---------------------------------------------------------------------------
// Cliente del provisioner (versión web): el servicio en el VPS que hace el
// PRIMER login (contra Supabase), valida la licencia y enciende/devuelve el
// agente personal del usuario. Ver docs/producto/especificaciones.md (Parte I).
//
// Solo aplica al build web (NEXT_PUBLIC_PROVISIONER_URL); en desktop el login
// va directo al agente local.
// ---------------------------------------------------------------------------

const PROVISIONER_URL = (process.env.NEXT_PUBLIC_PROVISIONER_URL ?? '').replace(/\/+$/, '');

/** Sesión de Supabase que el provisioner autenticó y el agente debe adoptar. */
export interface SesionProvisionada {
  access_token: string;
  refresh_token?: string | null;
  user_id: string;
  email?: string | null;
}

export interface ProvisionResult {
  /** Base URL del agente personal del usuario (p. ej. …/u/abc123). */
  base_url: string;
  /** Token de auth del agente. */
  token: string;
  session: SesionProvisionada;
}

export class ProvisionerError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = 'ProvisionerError';
  }
}

/** True si este build tiene provisioner configurado (login web automático). */
export function provisionerDisponible(): boolean {
  return PROVISIONER_URL.length > 0;
}

async function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${PROVISIONER_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ProvisionerError(0, 'No se pudo contactar el servicio. Revisa tu conexión.');
  }
  if (!res.ok) {
    let detail = 'Ocurrió un error. Intenta de nuevo.';
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
    } catch {
      // sin cuerpo JSON: se queda el mensaje genérico
    }
    throw new ProvisionerError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export function provisionLoginPassword(
  email: string,
  password: string,
): Promise<ProvisionResult> {
  return post<ProvisionResult>('/provision/login-password', { email, password });
}

export async function provisionOtpSend(email: string): Promise<void> {
  await post<{ ok: boolean }>('/provision/otp-send', { email });
}

export function provisionOtpVerify(
  email: string,
  token: string,
): Promise<ProvisionResult> {
  return post<ProvisionResult>('/provision/otp-verify', { email, token });
}

/** Canjea tokens ya emitidos por Supabase (OAuth / magic link) por el agente. */
export function provisionConToken(
  accessToken: string,
  refreshToken?: string | null,
): Promise<ProvisionResult> {
  return post<ProvisionResult>('/provision/con-token', {
    access_token: accessToken,
    refresh_token: refreshToken ?? null,
  });
}

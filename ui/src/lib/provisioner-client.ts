// ---------------------------------------------------------------------------
// Cliente del provisioner (versión web): el servicio en el VPS que hace el
// PRIMER login (contra Supabase), valida la licencia y enciende/devuelve el
// agente personal del usuario. Ver docs/producto/especificaciones.md (Parte I).
// También registra cuentas nuevas desde la web (por código o con contraseña).
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

/** Registro con contraseña: o hay que confirmar el correo, o ya quedó el espacio. */
export type ProvisionSignupResult =
  | { ok: boolean; requiere_confirmacion: true }
  | (ProvisionResult & { requiere_confirmacion: false });

export class ProvisionerError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    /** Motivo legible por la UI; "capacidad" = no caben espacios nuevos por ahora. */
    public readonly motivo?: string,
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
    let motivo: string | undefined;
    try {
      const data = await res.json();
      if (typeof data.detail === 'string') detail = data.detail;
      if (typeof data.motivo === 'string') motivo = data.motivo;
    } catch {
      // sin cuerpo JSON: se queda el mensaje genérico
    }
    throw new ProvisionerError(res.status, detail, motivo);
  }
  return res.json() as Promise<T>;
}

export function provisionLoginPassword(
  email: string,
  password: string,
): Promise<ProvisionResult> {
  return post<ProvisionResult>('/provision/login-password', { email, password });
}

/**
 * Envía un código de 6 dígitos. `crearCuenta` = registro por código (el mismo
 * código crea la cuenta); `tipo: 'signup'` = reenviar la confirmación de un
 * registro con contraseña. Sin opciones es el login por código de siempre.
 */
export async function provisionOtpSend(
  email: string,
  opts: { crearCuenta?: boolean; nombre?: string; tipo?: 'email' | 'signup' } = {},
): Promise<void> {
  await post<{ ok: boolean }>('/provision/otp-send', {
    email,
    crear_cuenta: opts.crearCuenta ?? false,
    nombre: opts.nombre ?? '',
    tipo: opts.tipo ?? 'email',
  });
}

/** Verifica el código. `tipo: 'signup'` confirma un registro con contraseña. */
export function provisionOtpVerify(
  email: string,
  token: string,
  tipo: 'email' | 'signup' = 'email',
): Promise<ProvisionResult> {
  return post<ProvisionResult>('/provision/otp-verify', { email, token, tipo });
}

/** Registro con correo y contraseña desde la web. */
export function provisionSignup(
  email: string,
  password: string,
  nombre: string,
): Promise<ProvisionSignupResult> {
  return post<ProvisionSignupResult>('/provision/signup', { email, password, nombre });
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

// ---------------------------------------------------------------------------
// Acceso con Google en la web (OAuth con PKCE)
//
// El provisioner arma la URL de Supabase (con el redirect fijo
// https://app.todoconta.com/acceso/google) y entrega el code_verifier; el
// navegador lo guarda en sessionStorage, navega a Google en la misma pestaña y,
// al volver, /acceso/google lo canjea con el `code`. El navegador no puede
// hablar con Supabase directo (CSP), por eso el canje también va por aquí.
// ---------------------------------------------------------------------------

const VERIFIER_GOOGLE_KEY = 'todoconta.google.verifier';

export function provisionOauthStart(
  provider: 'google' = 'google',
): Promise<{ url: string; verifier: string }> {
  return post<{ url: string; verifier: string }>('/provision/oauth/start', { provider });
}

export function provisionOauthCallback(code: string, verifier: string): Promise<ProvisionResult> {
  return post<ProvisionResult>('/provision/oauth/callback', { code, verifier });
}

/** Guarda el verifier hasta que Google regrese a esta misma pestaña. */
export function guardarVerifierGoogle(verifier: string): void {
  try {
    window.sessionStorage.setItem(VERIFIER_GOOGLE_KEY, verifier);
  } catch {
    // sessionStorage bloqueado: el canje fallará con "expiró" y se reintenta.
  }
}

/** Lee y borra el verifier (es de un solo uso). */
export function tomarVerifierGoogle(): string | null {
  try {
    const v = window.sessionStorage.getItem(VERIFIER_GOOGLE_KEY);
    window.sessionStorage.removeItem(VERIFIER_GOOGLE_KEY);
    return v;
  } catch {
    return null;
  }
}

/** Arranca el acceso con Google: guarda el verifier y se va a Google. */
export async function iniciarGoogleWeb(): Promise<void> {
  const { url, verifier } = await provisionOauthStart('google');
  guardarVerifierGoogle(verifier);
  window.location.assign(url);
}


'use client';

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react';

import Link from 'next/link';

import { useServer } from '@/providers/server-provider';
import { useAuth } from '@/providers/auth-provider';
import { BrandMark } from '@/components/layout/brand-mark';
import { Icon } from '@/components/ui/icon';
import { ApiError, SatApiClient } from '@/lib/api-client';
import { esWeb } from '@/lib/modo';
import {
  ProvisionerError,
  provisionerDisponible,
  provisionLoginPassword,
  provisionOtpSend,
  provisionOtpVerify,
  type ProvisionResult,
} from '@/lib/provisioner-client';
import { mensajeDeError } from '@/lib/errores';
import { cn } from '@/lib/utils';

// ---------------------------------------------------------------------------
// Login en-app estilo Notion (sin navegador): contraseña u OTP de 6 dígitos.
// La sesión Supabase se guarda en el agente (keyring); el renderer solo ve el
// estado derivado vía useAuth(). Reemplaza al device-code flow (que sigue
// disponible en el agente como fallback, pero sin UI).
// ---------------------------------------------------------------------------

type Vista = 'login' | 'signup';
type Metodo = 'password' | 'codigo';
type Paso = 'form' | 'otp' | 'done';

/** Contexto del paso OTP: cómo verificar y cómo reenviar. */
interface OtpContexto {
  /** Tipo de verificación GoTrue: 'email' (login/registro por código) | 'signup' (confirmar registro con contraseña). */
  tipo: 'email' | 'signup';
  crearCuenta: boolean;
  nombre: string;
}

const EMAIL_RE = /^\S+@\S+\.\S+$/;

/** Pricing público: el único lugar donde se puede activar un plan sin entrar. */
const URL_PLANES = 'https://todoconta.com/planes';

/** Error del login: mensaje y, cuando aplica, la salida para desatorarse. */
interface ErrorAuth {
  mensaje: string;
  /** El provisioner rechazó por plan (403): sin CTA el usuario queda encerrado. */
  sinPlan?: boolean;
}

function errorAuth(e: unknown): ErrorAuth {
  // ApiError.message viene como "[401] detalle"; mostramos solo el detalle.
  if (e instanceof ApiError) return { mensaje: e.detail };
  if (e instanceof ProvisionerError) {
    // El checkout vive detrás del agente y el agente no enciende sin plan, así
    // que el 403 tiene que ofrecer a dónde ir o no hay forma de salir del loop.
    return { mensaje: e.detail, sinPlan: e.status === 403 };
  }
  return { mensaje: mensajeDeError(e) };
}

/** Payload del deep link `todoconta://<action>?code=…` que reenvía el preload. */
interface ProtocolPayload {
  action?: string;
  code?: string | null;
  error?: string | null;
}

/** Bridge de Electron (preload). En navegador todo es undefined. */
interface DesktopBridge {
  satAgent?: { isDesktop?: boolean };
  satDesktop?: {
    onProtocolActivated?: (cb: (p: ProtocolPayload) => void) => () => void;
  };
}

function desktopBridge(): DesktopBridge {
  if (typeof window === 'undefined') return {};
  return window as unknown as DesktopBridge;
}

export default function LoginPage() {
  const { apiClient, conectar, webSinConexion } = useServer();
  const { refresh } = useAuth();

  // Versión web SIN agente conocido: el login pasa por el provisioner (que
  // valida contra Supabase, enciende el contenedor del usuario y devuelve
  // {base_url, token, session}). Ya conectados, el flujo normal via agente
  // funciona igual que en desktop.
  const webNecesitaProvision = esWeb() && webSinConexion;

  // Guarda la conexión y entrega la sesión al agente recién aprovisionado.
  const adoptarYConectar = useCallback(
    async (r: ProvisionResult) => {
      // El token debe estar en localStorage ANTES del request (el cliente lo
      // lee de ahí para el header X-Agent-Token).
      conectar({ baseUrl: r.base_url, token: r.token });
      const cliente = new SatApiClient(r.base_url);
      await cliente.authAdoptSession(r.session);
    },
    [conectar],
  );

  const [vista, setVista] = useState<Vista>('login');
  // Código de acceso por default: los usuarios existentes de la web no tienen
  // contraseña (la app en línea usa magic link); la contraseña es opcional.
  const [metodo, setMetodo] = useState<Metodo>('codigo');
  const [paso, setPaso] = useState<Paso>('form');
  const [otpCtx, setOtpCtx] = useState<OtpContexto>({
    tipo: 'email',
    crearCuenta: false,
    nombre: '',
  });

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [nombre, setNombre] = useState('');
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ErrorAuth | null>(null);

  // OAuth Google (solo desktop): el flujo va por el navegador del SO y vuelve
  // por el deep link `todoconta://auth-callback`. `googleEsperando` cubre el
  // hueco entre abrir el navegador y recibir el code.
  const [esDesktop, setEsDesktop] = useState(false);
  const [googleEsperando, setGoogleEsperando] = useState(false);

  const esLogin = vista === 'login';
  const esPwd = metodo === 'password';

  const cambiarVista = useCallback((v: Vista) => {
    setVista(v);
    setMetodo('codigo');
    setPaso('form');
    setPassword('');
    setError(null);
  }, []);

  const cambiarMetodo = useCallback((m: Metodo) => {
    setMetodo(m);
    setError(null);
  }, []);

  // Al completar el login, una pequeña pausa para que se vea el estado de
  // éxito antes de que refresh() re-renderee el shell con el dashboard.
  useEffect(() => {
    if (paso !== 'done') return;
    const t = setTimeout(() => {
      refresh();
    }, 900);
    return () => clearTimeout(t);
  }, [paso, refresh]);

  // Canjea el auth_code de Google por la sesión (la guarda el agente) y entra.
  const manejarCodigoGoogle = useCallback(
    async (code: string) => {
      setError(null);
      setGoogleEsperando(true);
      try {
        await apiClient.authOauthCallback(code);
        setGoogleEsperando(false);
        setPaso('done');
      } catch (err) {
        setGoogleEsperando(false);
        setError(errorAuth(err));
      }
    },
    [apiClient],
  );

  // Detecta desktop y se suscribe al deep link de Google. Ramifica por
  // `action` para no tocar el device-code legado (`activated`).
  useEffect(() => {
    const b = desktopBridge();
    setEsDesktop(!!b.satAgent?.isDesktop);
    const suscribir = b.satDesktop?.onProtocolActivated;
    if (!suscribir) return;
    return suscribir((p) => {
      if (p?.action !== 'auth-callback') return;
      if (p.code) {
        void manejarCodigoGoogle(p.code);
      } else {
        // El usuario canceló o Google devolvió error.
        setGoogleEsperando(false);
        setError({ mensaje: 'No se pudo continuar con Google. Intenta de nuevo.' });
      }
    });
  }, [manejarCodigoGoogle]);

  // Arranca el OAuth: pide la URL al agente y la abre en el navegador del SO
  // (window.open pasa por setWindowOpenHandler → shell.openExternal).
  const iniciarGoogle = useCallback(async () => {
    setError(null);
    setGoogleEsperando(true);
    try {
      const { url } = await apiClient.authOauthStart('google');
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      setGoogleEsperando(false);
      setError(errorAuth(err));
    }
  }, [apiClient]);

  // Login/OTP unificados: en la web sin conexión pasan por el provisioner
  // (que además conecta con el agente); en desktop o ya conectados, directo
  // al agente como siempre.
  const loginConPassword = useCallback(
    async (correo: string, pwd: string) => {
      if (webNecesitaProvision) {
        await adoptarYConectar(await provisionLoginPassword(correo, pwd));
      } else {
        await apiClient.authLoginPassword(correo, pwd);
      }
    },
    [webNecesitaProvision, adoptarYConectar, apiClient],
  );

  const enviarOtp = useCallback(
    async (correo: string, opts: { crearCuenta?: boolean; nombre?: string } = {}) => {
      if (webNecesitaProvision) {
        await provisionOtpSend(correo);
      } else {
        await apiClient.authOtpSend(correo, opts);
      }
    },
    [webNecesitaProvision, apiClient],
  );

  const verificarOtp = useCallback(
    async (correo: string, codigo: string, tipo: 'email' | 'signup') => {
      if (webNecesitaProvision) {
        await adoptarYConectar(await provisionOtpVerify(correo, codigo));
      } else {
        await apiClient.authOtpVerify(correo, codigo, tipo);
      }
    },
    [webNecesitaProvision, adoptarYConectar, apiClient],
  );

  const submit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const correo = email.trim();
      if (!EMAIL_RE.test(correo)) {
        setError({ mensaje: 'Escribe un correo válido.' });
        return;
      }
      setError(null);
      setLoading(true);
      try {
        if (esLogin && esPwd) {
          if (!password) {
            setError({ mensaje: 'Escribe tu contraseña.' });
            return;
          }
          await loginConPassword(correo, password);
          setPaso('done');
        } else if (esLogin) {
          await enviarOtp(correo);
          setOtpCtx({ tipo: 'email', crearCuenta: false, nombre: '' });
          setPaso('otp');
        } else if (esPwd) {
          if (password.length < 8) {
            setError({ mensaje: 'La contraseña debe tener mínimo 8 caracteres.' });
            return;
          }
          const r = await apiClient.authSignup(correo, password, nombre.trim());
          if (r.requiere_confirmacion) {
            setOtpCtx({ tipo: 'signup', crearCuenta: false, nombre: nombre.trim() });
            setPaso('otp');
          } else {
            setPaso('done');
          }
        } else {
          await apiClient.authOtpSend(correo, {
            crearCuenta: true,
            nombre: nombre.trim(),
          });
          setOtpCtx({ tipo: 'email', crearCuenta: true, nombre: nombre.trim() });
          setPaso('otp');
        }
      } catch (err) {
        setError(errorAuth(err));
      } finally {
        setLoading(false);
      }
    },
    [apiClient, email, password, nombre, esLogin, esPwd, loginConPassword, enviarOtp],
  );

  return (
    <div className="flex min-h-full justify-center bg-background px-6 pb-10 pt-14">
      <div className="w-full max-w-96">
        {webNecesitaProvision && !provisionerDisponible() ? (
          // Build web sin provisioner configurado (piloto F1): la conexión con
          // el agente se captura a mano en /conectar.
          <div className="animate-in fade-in slide-in-from-bottom-1 duration-200">
            <Marca />
            <h1 className="mb-4 text-center text-[26px] font-bold leading-[1.22] tracking-[-0.02em] text-foreground">
              Versión web en piloto
            </h1>
            <p className="text-center text-sm leading-relaxed text-muted-foreground">
              Esta instancia todavía no tiene el servicio de acceso automático.
              Si tienes los datos de tu espacio (URL y token), conéctate en{' '}
              <Link href="/conectar" className="font-semibold text-primary hover:underline">
                Conectar con mi espacio
              </Link>
              .
            </p>
          </div>
        ) : paso === 'done' ? (
          <DoneStep esLogin={esLogin} />
        ) : paso === 'otp' ? (
          <OtpStep
            email={email.trim()}
            esLogin={esLogin}
            verificar={(codigo) => verificarOtp(email.trim(), codigo, otpCtx.tipo)}
            reenviar={async () => {
              if (otpCtx.tipo === 'signup') {
                await apiClient.authOtpSend(email.trim(), { tipo: 'signup' });
              } else {
                await enviarOtp(email.trim(), {
                  crearCuenta: otpCtx.crearCuenta,
                  nombre: otpCtx.nombre,
                });
              }
            }}
            onVolver={() => {
              setPaso('form');
              setError(null);
            }}
            onExito={() => setPaso('done')}
          />
        ) : (
          <div className="animate-in fade-in slide-in-from-bottom-1 duration-200">
            <Marca />
            <h1 className="mb-8 text-center">
              <span className="block text-[26px] font-bold leading-[1.22] tracking-[-0.02em] text-foreground">
                {esLogin ? 'Bienvenido de vuelta.' : 'Crea tu cuenta.'}
              </span>
              <span className="block text-[26px] font-bold leading-[1.22] tracking-[-0.02em] text-muted-foreground/70">
                {esLogin ? 'Inicia sesión en TodoConta' : 'Empieza gratis con TodoConta'}
              </span>
            </h1>

            <form onSubmit={submit} noValidate>
              {!esLogin && (
                <Campo label="Nombre completo" htmlFor="login-nombre">
                  <TxtInput
                    id="login-nombre"
                    type="text"
                    autoComplete="name"
                    placeholder="Tu nombre"
                    value={nombre}
                    onChange={(v) => setNombre(v)}
                  />
                </Campo>
              )}

              <Campo
                label="Correo electrónico"
                htmlFor="login-email"
                help={
                  !esPwd
                    ? esLogin
                      ? 'Te enviaremos un código de acceso de un solo uso a tu correo.'
                      : 'Te enviaremos un código para confirmar tu correo.'
                    : undefined
                }
              >
                <TxtInput
                  id="login-email"
                  type="email"
                  autoComplete="email"
                  placeholder="tucorreo@despacho.mx"
                  value={email}
                  onChange={(v) => setEmail(v)}
                />
              </Campo>

              {esPwd && (
                <div className="animate-in fade-in slide-in-from-bottom-1 mb-4.5 duration-200">
                  <label
                    htmlFor="login-pwd"
                    className="mb-2 flex items-baseline justify-between gap-3 text-[13px] font-semibold text-foreground"
                  >
                    <span>{esLogin ? 'Contraseña' : 'Crea una contraseña'}</span>
                    {esLogin && (
                      <button
                        type="button"
                        className="shrink-0 whitespace-nowrap text-xs font-medium text-primary hover:underline"
                        onClick={() => cambiarMetodo('codigo')}
                        title="Entra con un código a tu correo"
                      >
                        ¿La olvidaste?
                      </button>
                    )}
                  </label>
                  <div className="relative flex items-center">
                    <TxtInput
                      id="login-pwd"
                      type={showPwd ? 'text' : 'password'}
                      autoComplete={esLogin ? 'current-password' : 'new-password'}
                      placeholder={esLogin ? 'Tu contraseña' : 'Mínimo 8 caracteres'}
                      value={password}
                      onChange={(v) => setPassword(v)}
                      className="pr-12"
                    />
                    <button
                      type="button"
                      className="absolute right-1.5 flex size-9 items-center justify-center rounded-md text-muted-foreground/70 hover:bg-secondary hover:text-muted-foreground"
                      title={showPwd ? 'Ocultar' : 'Mostrar'}
                      aria-label={showPwd ? 'Ocultar contraseña' : 'Mostrar contraseña'}
                      onClick={() => setShowPwd((s) => !s)}
                    >
                      <Icon
                        icon={showPwd ? 'ph:eye-slash-light' : 'ph:eye-light'}
                        className="size-4.5"
                      />
                    </button>
                  </div>
                </div>
              )}

              {error && <ErrorInline error={error} />}

              <BotonPrimario loading={loading}>
                {esLogin ? (esPwd ? 'Iniciar sesión' : 'Continuar') : 'Crear cuenta'}
              </BotonPrimario>

              <button
                type="button"
                className="mt-4 block w-full text-center text-[13.5px] font-medium text-primary hover:underline"
                onClick={() => cambiarMetodo(esPwd ? 'codigo' : 'password')}
              >
                {esLogin
                  ? esPwd
                    ? 'Ingresar con código de acceso'
                    : 'Prefiero usar mi contraseña'
                  : esPwd
                    ? 'Crear cuenta con código de acceso'
                    : 'Prefiero crear una contraseña'}
              </button>
            </form>

            <Divider>{esLogin ? 'o continúa con' : 'o regístrate con'}</Divider>

            {/* OAuth Google. En desktop el flujo va por el navegador del SO y
                vuelve por el deep link `todoconta://auth-callback`; en
                navegador (sin Electron) no aplica el deep link → queda
                "Próximamente". Una cuenta @gmail creada por OTP se vincula sola
                en Supabase (mismo email verificado). */}
            {esDesktop ? (
              <>
                <button
                  type="button"
                  onClick={iniciarGoogle}
                  disabled={googleEsperando}
                  className="flex h-11.5 w-full items-center justify-center gap-2.5 rounded-lg border border-input bg-card text-[15px] font-semibold text-foreground transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-60 dark:bg-secondary dark:hover:bg-secondary/80"
                >
                  {googleEsperando ? (
                    <>
                      <Icon icon="ph:circle-notch-light" className="size-4.5 animate-spin" />
                      Conectando con Google…
                    </>
                  ) : (
                    <>
                      <GoogleG />
                      Google
                    </>
                  )}
                </button>
                {googleEsperando && (
                  <p className="mt-2 text-center text-[13px] text-muted-foreground">
                    Continúa en la ventana de tu navegador.{' '}
                    <button
                      type="button"
                      className="font-medium text-primary hover:underline"
                      onClick={() => setGoogleEsperando(false)}
                    >
                      Cancelar
                    </button>
                  </p>
                )}
              </>
            ) : (
              <span title="Próximamente" className="block">
                <button
                  type="button"
                  disabled
                  className="flex h-11.5 w-full cursor-not-allowed items-center justify-center gap-2.5 rounded-lg border border-input bg-card text-[15px] font-semibold text-foreground opacity-50 dark:bg-secondary"
                >
                  <GoogleG />
                  Google
                </button>
              </span>
            )}

            <div className="mt-7 text-center">
              {/* En la web el acceso requiere una cuenta con plan (la valida el
                  provisioner); el registro vive en la app de escritorio. */}
              {webNecesitaProvision ? (
                <p className="text-sm text-muted-foreground">
                  Usa la cuenta con la que activaste TodoConta.
                </p>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {esLogin ? '¿Primera vez?' : '¿Ya tienes cuenta?'}{' '}
                  <button
                    type="button"
                    className="font-semibold text-primary hover:underline"
                    onClick={() => cambiarVista(esLogin ? 'signup' : 'login')}
                  >
                    {esLogin ? 'Crea tu cuenta' : 'Inicia sesión'}
                  </button>
                </p>
              )}
              <p className="mt-7 border-t border-border/60 pt-5 text-xs leading-relaxed text-muted-foreground/80">
                {esLogin ? 'Al continuar' : 'Al crear tu cuenta'}, aceptas los{' '}
                <LinkExterno href="https://todoconta.com/terminos">
                  Términos y condiciones
                </LinkExterno>{' '}
                y la{' '}
                <LinkExterno href="https://todoconta.com/privacidad">
                  Política de privacidad
                </LinkExterno>{' '}
                de TodoConta.
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Paso OTP: 6 cajas de dígito, auto-advance, reenviar con timer, volver.
// ---------------------------------------------------------------------------

const OTP_LEN = 6;
const RESEND_SECS = 30;

function OtpStep({
  email,
  esLogin,
  verificar: verificarCodigo,
  reenviar: reenviarCodigo,
  onVolver,
  onExito,
}: {
  email: string;
  esLogin: boolean;
  /** Verifica el código (agente o provisioner, lo decide el padre). */
  verificar: (codigo: string) => Promise<void>;
  /** Reenvía el código con el mismo contexto del envío original. */
  reenviar: () => Promise<void>;
  onVolver: () => void;
  onExito: () => void;
}) {
  const [vals, setVals] = useState<string[]>(Array(OTP_LEN).fill(''));
  const [secs, setSecs] = useState(RESEND_SECS);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ErrorAuth | null>(null);
  const refs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    refs.current[0]?.focus();
  }, []);

  useEffect(() => {
    const t = setInterval(() => setSecs((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(t);
  }, []);

  const setAt = (i: number, v: string) => {
    const d = v.replace(/\D/g, '').slice(-1);
    setVals((prev) => {
      const n = [...prev];
      n[i] = d;
      return n;
    });
    if (d && i < OTP_LEN - 1) refs.current[i + 1]?.focus();
  };

  const onKey = (i: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !vals[i] && i > 0) refs.current[i - 1]?.focus();
  };

  // Pegar el código completo desde el correo llena las 6 cajas de una vez.
  const onPaste = (e: React.ClipboardEvent) => {
    const digits = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, OTP_LEN);
    if (!digits) return;
    e.preventDefault();
    setVals(digits.split('').concat(Array(OTP_LEN - digits.length).fill('')));
    refs.current[Math.min(digits.length, OTP_LEN - 1)]?.focus();
  };

  const completo = vals.every(Boolean);

  const verificar = async () => {
    setError(null);
    setLoading(true);
    try {
      await verificarCodigo(vals.join(''));
      onExito();
    } catch (e) {
      setError(errorAuth(e));
    } finally {
      setLoading(false);
    }
  };

  const reenviar = async () => {
    setError(null);
    try {
      await reenviarCodigo();
      setSecs(RESEND_SECS);
      setVals(Array(OTP_LEN).fill(''));
      refs.current[0]?.focus();
    } catch (e) {
      setError(errorAuth(e));
    }
  };

  return (
    <div className="animate-in fade-in slide-in-from-bottom-1 duration-200">
      <button
        type="button"
        className="mb-6 inline-flex items-center gap-1.5 text-[13px] font-medium text-muted-foreground hover:text-foreground"
        onClick={onVolver}
      >
        <Icon icon="ph:arrow-left-light" className="size-4" />
        Volver
      </button>
      <Marca />
      <h1 className="mb-7 text-center">
        <span className="block text-[26px] font-bold leading-[1.22] tracking-[-0.02em] text-foreground">
          Revisa tu correo
        </span>
        <span className="mt-2 block text-[15px] font-medium leading-relaxed text-muted-foreground">
          Enviamos un código de 6 dígitos a
          <br />
          <span className="font-semibold text-foreground">{email}</span>
        </span>
      </h1>

      <div className="flex justify-between gap-2.5">
        {vals.map((v, i) => (
          <input
            key={i}
            ref={(el) => {
              refs.current[i] = el;
            }}
            className="h-14 w-full rounded-[9px] border border-input bg-card text-center font-mono text-[22px] font-semibold text-foreground outline-none transition-[border-color,box-shadow] focus:border-primary focus:ring-[3px] focus:ring-primary/15 dark:bg-secondary"
            inputMode="numeric"
            maxLength={1}
            value={v}
            aria-label={`Dígito ${i + 1} de ${OTP_LEN}`}
            onChange={(e) => setAt(i, e.target.value)}
            onKeyDown={(e) => onKey(i, e)}
            onPaste={onPaste}
          />
        ))}
      </div>

      {error && (
        <div className="mt-4">
          <ErrorInline error={error} />
        </div>
      )}

      <div className="mt-5">
        <BotonPrimario loading={loading} disabled={!completo} onClick={verificar} type="button">
          {esLogin ? 'Verificar e iniciar sesión' : 'Verificar y crear cuenta'}
        </BotonPrimario>
      </div>

      <p className="mt-5 text-center text-[13px] text-muted-foreground">
        ¿No te llegó?{' '}
        {secs > 0 ? (
          <span>Reenviar en 0:{String(secs).padStart(2, '0')}</span>
        ) : (
          <button
            type="button"
            className="font-semibold text-primary hover:underline"
            onClick={reenviar}
          >
            Reenviar código
          </button>
        )}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Estado de éxito
// ---------------------------------------------------------------------------

function DoneStep({ esLogin }: { esLogin: boolean }) {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-1 py-16 text-center duration-200">
      <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-success/10 text-success">
        <Icon icon="ph:check-light" className="size-8" />
      </span>
      <h3 className="text-xl font-semibold text-foreground">
        {esLogin ? 'Sesión iniciada' : 'Cuenta creada'}
      </h3>
      <p className="mt-2 text-sm text-muted-foreground">
        {esLogin ? 'Abriendo tu espacio de trabajo…' : 'Preparando tu espacio de trabajo…'}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Piezas compartidas
// ---------------------------------------------------------------------------

function Marca() {
  return (
    <div className="mb-6 flex justify-center">
      <BrandMark size={46} wordmarkSize={24} priority iconClassName="rounded-xl shadow-sm" />
    </div>
  );
}

function Campo({
  label,
  htmlFor,
  help,
  children,
}: {
  label: string;
  htmlFor: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-4.5">
      <label
        htmlFor={htmlFor}
        className="mb-2 block text-[13px] font-semibold text-foreground"
      >
        {label}
      </label>
      {children}
      {help && (
        <p className="mt-2 px-0.5 text-xs leading-normal text-muted-foreground/80">{help}</p>
      )}
    </div>
  );
}

function TxtInput({
  onChange,
  className,
  ...rest
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'className'> & {
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <input
      {...rest}
      className={cn(
        'h-11.5 w-full rounded-lg border border-input bg-card px-3.5 text-[15px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-muted-foreground/60 focus:border-primary focus:ring-[3px] focus:ring-primary/15 dark:bg-secondary',
        className,
      )}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

function BotonPrimario({
  children,
  loading = false,
  disabled = false,
  type = 'submit',
  onClick,
}: {
  children: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  type?: 'submit' | 'button';
  onClick?: () => void;
}) {
  return (
    <button
      type={type}
      disabled={disabled || loading}
      onClick={onClick}
      className="mt-1.5 flex h-11.5 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[15px] font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-55"
    >
      {loading ? (
        <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
      ) : (
        children
      )}
    </button>
  );
}

function Divider({ children }: { children: ReactNode }) {
  return (
    <div className="my-6 flex items-center gap-3.5 text-[13px] text-muted-foreground/80">
      <span className="h-px flex-1 bg-border" />
      {children}
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

function ErrorInline({ error }: { error: ErrorAuth }) {
  return (
    <div
      role="alert"
      className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] leading-snug text-destructive"
    >
      <p>{error.mensaje}</p>
      {error.sinPlan && (
        <a
          href={URL_PLANES}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1.5 inline-flex items-center gap-1 font-semibold underline underline-offset-2"
        >
          Ver planes y activar
          <Icon icon="ph:arrow-up-right-light" className="size-3.5" />
        </a>
      )}
    </div>
  );
}

function LinkExterno({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-muted-foreground underline hover:text-foreground"
    >
      {children}
    </a>
  );
}

/** Logo oficial de Google (marca de OAuth, multicolor — no Phosphor). */
function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" className="size-4.75">
      <path
        fill="#EA4335"
        d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
      />
      <path
        fill="#FBBC05"
        d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
      />
    </svg>
  );
}

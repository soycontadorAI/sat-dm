'use client';

import { useEffect, useRef, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { BrandMark } from '@/components/layout/brand-mark';
import { Icon } from '@/components/ui/icon';
import { adoptarSesion } from '@/lib/adoptar-sesion';
import { mensajeDeError } from '@/lib/errores';
import { esWeb } from '@/lib/modo';
import {
  ProvisionerError,
  iniciarGoogleWeb,
  provisionOauthCallback,
  tomarVerifierGoogle,
} from '@/lib/provisioner-client';

// ---------------------------------------------------------------------------
// Vuelta del acceso con Google en la versión web.
//
// Supabase regresa aquí con `?code=…` (o con `error`/`error_description`). La
// página canjea el código en el provisioner con el verifier que guardó el
// login en sessionStorage, guarda la conexión con el agente igual que los
// otros caminos de login web y entra a la app. Vive fuera de /auth/* porque
// Vercel reescribe esa ruta al producto viejo (ui/vercel.json). Lee la URL en
// un efecto: con `output: 'export'` no hay servidor que la procese.
// ---------------------------------------------------------------------------

const URL_PLANES = 'https://todoconta.com/planes';
const URL_DESCARGAR = 'https://todoconta.com/descargar';

interface ErrorAcceso {
  mensaje: string;
  sinPlan?: boolean;
  sinEspacio?: boolean;
}

/** Lee `code` y los errores de la query y, por si acaso, del fragmento. */
function leerRespuesta(): { code: string | null; error: string | null; descripcion: string | null } {
  const query = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  const tomar = (clave: string) => query.get(clave) ?? hash.get(clave);
  return {
    code: query.get('code'),
    error: tomar('error_code') ?? tomar('error'),
    descripcion: tomar('error_description'),
  };
}

function errorDeGoogle(error: string, descripcion: string | null): ErrorAcceso {
  if (error === 'access_denied') {
    return { mensaje: 'Cancelaste el acceso con Google. Puedes intentarlo de nuevo.' };
  }
  if (error === 'provider_disabled' || /provider is not enabled/i.test(descripcion ?? '')) {
    return { mensaje: 'El acceso con Google no está disponible por el momento.' };
  }
  return { mensaje: 'No se pudo continuar con Google. Intenta de nuevo.' };
}

function errorDeCanje(e: unknown): ErrorAcceso {
  if (e instanceof ProvisionerError) {
    return {
      mensaje: e.detail,
      sinPlan: e.status === 403,
      sinEspacio: e.motivo === 'capacidad',
    };
  }
  return { mensaje: mensajeDeError(e) };
}

export default function AccesoGooglePage() {
  const { conectar } = useServer();
  const [estado, setEstado] = useState<'canjeando' | 'listo' | 'error'>('canjeando');
  const [error, setError] = useState<ErrorAcceso | null>(null);
  const [reintentando, setReintentando] = useState(false);
  // En desarrollo React monta dos veces: el código es de un solo uso.
  const iniciado = useRef(false);

  useEffect(() => {
    if (iniciado.current) return;
    iniciado.current = true;

    const { code, error: errorGoogle, descripcion } = leerRespuesta();
    const verifier = tomarVerifierGoogle();
    // El código y el verifier son de un solo uso: fuera de la URL de una vez.
    window.history.replaceState(null, '', window.location.pathname);

    if (!esWeb()) {
      setError({ mensaje: 'Esta página solo aplica a la versión web.' });
      setEstado('error');
      return;
    }
    if (errorGoogle) {
      setError(errorDeGoogle(errorGoogle, descripcion));
      setEstado('error');
      return;
    }
    if (!code || !verifier) {
      setError({ mensaje: 'El acceso con Google expiró. Vuelve a intentarlo.' });
      setEstado('error');
      return;
    }

    void (async () => {
      try {
        const r = await provisionOauthCallback(code, verifier);
        // Igual que los otros caminos de login web: el token va a localStorage
        // ANTES de hablar con el agente, y el agente adopta la sesión.
        conectar({ baseUrl: r.base_url, token: r.token });
        await adoptarSesion(r);
        setEstado('listo');
        // Recarga completa en la raíz: los providers leen la conexión nueva y
        // la licencia ya viene con sesión.
        window.location.replace('/');
      } catch (e) {
        setError(errorDeCanje(e));
        setEstado('error');
      }
    })();
  }, [conectar]);

  const reintentar = async () => {
    setReintentando(true);
    try {
      await iniciarGoogleWeb();
    } catch (e) {
      setReintentando(false);
      setError(errorDeCanje(e));
    }
  };

  return (
    <div className="flex min-h-full justify-center bg-background px-6 pb-10 pt-14">
      <div className="w-full max-w-96 text-center">
        <div className="mb-6 flex justify-center">
          <BrandMark size={46} wordmarkSize={24} priority iconClassName="rounded-xl shadow-sm" />
        </div>

        {estado !== 'error' ? (
          <div className="animate-in fade-in slide-in-from-bottom-1 py-10 duration-200">
            <span className="mx-auto mb-5 flex size-16 items-center justify-center rounded-full bg-primary/10 text-primary">
              {estado === 'listo' ? (
                <Icon icon="ph:check-light" className="size-8" />
              ) : (
                <Icon icon="ph:circle-notch-light" className="size-8 animate-spin" />
              )}
            </span>
            <h1 className="text-xl font-semibold text-foreground">
              {estado === 'listo' ? 'Listo' : 'Entrando con Google'}
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {estado === 'listo'
                ? 'Abriendo tu espacio de trabajo…'
                : 'Estamos preparando tu espacio. Puede tardar unos segundos la primera vez.'}
            </p>
          </div>
        ) : (
          <div className="animate-in fade-in slide-in-from-bottom-1 duration-200">
            <h1 className="mb-3 text-[22px] font-bold leading-tight tracking-[-0.02em] text-foreground">
              No pudimos entrar con Google
            </h1>
            <div
              role="alert"
              className="mb-5 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-left text-[13px] leading-snug text-destructive"
            >
              <p>{error?.mensaje}</p>
              {error?.sinPlan && (
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
              {error?.sinEspacio && (
                <a
                  href={URL_DESCARGAR}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-1.5 inline-flex items-center gap-1 font-semibold underline underline-offset-2"
                >
                  Mientras, usa la app de escritorio
                  <Icon icon="ph:arrow-up-right-light" className="size-3.5" />
                </a>
              )}
            </div>
            {esWeb() && (
              <button
                type="button"
                onClick={reintentar}
                disabled={reintentando}
                className="flex h-11.5 w-full items-center justify-center gap-2 rounded-lg bg-primary text-[15px] font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-55"
              >
                {reintentando ? (
                  <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                ) : (
                  'Intentar de nuevo con Google'
                )}
              </button>
            )}
            <button
              type="button"
              onClick={() => window.location.replace('/')}
              className="mt-4 block w-full text-center text-[13.5px] font-medium text-primary hover:underline"
            >
              Volver al inicio de sesión
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

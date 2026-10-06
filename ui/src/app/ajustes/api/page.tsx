'use client';

// Ruta ESTÁTICA `/ajustes/api` — gestión de API keys + conexión MCP.
//
// No usa `[param]` ni `useSearchParams`, así que bajo `output: 'export'` emite
// su propio `ajustes/api/index.html` y navega bien en SPA y en reload (ver la
// convención de routing en ui/CLAUDE.md). Funciona igual en Desktop y en Web:
// el agente proxya a la API de servicios con el Bearer de la sesión, que existe
// en ambos modos — el renderer nunca ve el token.

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { usePlanesV3, usePlanLicencia } from '@/providers/auth-provider';
import { PageHeading } from '@/components/layout/page-heading';
import { CandadoPlan } from '@/components/planes/candado-plan';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Icon } from '@/components/ui/icon';
import {
  ResourceList,
  type ResourceListColumn,
} from '@/components/shared/resource-list';
import { ApiError, type ApiKey } from '@/lib/api-client';
import { formatDate } from '@/lib/formatting';

// Dirección pública del MCP de TodoConta. La misma en Desktop y Web: identifica
// al usuario por su API key, no por el equipo. La guía paso a paso vive en la
// landing (todoconta.com/mcp).
const MCP_URL = 'https://agente.todoconta.com/mcp';

async function copiar(texto: string, ok: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(texto);
    toast.success(ok);
  } catch {
    toast.error('No se pudo copiar. Cópialo a mano.');
  }
}

export default function AjustesApiPage() {
  const { apiClient } = useServer();
  // Candados por plan (planes v3). Sin interruptor o sin datos del plan, todo
  // se ve como hoy: la falta de datos nunca pone candado.
  const planesV3 = usePlanesV3();
  const planLicencia = usePlanLicencia();
  const caps = planesV3 ? planLicencia?.capacidades ?? null : null;
  const conMcp = !caps || caps.mcp;
  const conApi = !caps || caps.api;
  const puedeEmitir = conMcp || conApi;
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [cargando, setCargando] = useState(true);
  const [nombre, setNombre] = useState('');
  const [creando, setCreando] = useState(false);
  // Secreto recién emitido: se muestra UNA sola vez (no se puede volver a ver).
  const [nueva, setNueva] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    try {
      const r = await apiClient.listApiKeys();
      setKeys(r.keys);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'No se pudieron leer tus keys.');
    } finally {
      setCargando(false);
    }
  }, [apiClient]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  async function crear() {
    const n = nombre.trim();
    if (!n || creando) return;
    setError(null);
    setCreando(true);
    try {
      const r = await apiClient.createApiKey(n);
      setNueva(r.key);
      setNombre('');
      await cargar();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : 'No se pudo crear la key.');
    } finally {
      setCreando(false);
    }
  }

  async function revocar(k: ApiKey) {
    if (
      !window.confirm(
        `¿Revocar "${k.nombre}"? Los sistemas o asistentes que la usen dejarán de funcionar.`,
      )
    ) {
      return;
    }
    try {
      await apiClient.revokeApiKey(k.id);
      toast.success('Key revocada.');
      await cargar();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'No se pudo revocar la key.');
    }
  }

  const activas = keys.filter((k) => !k.revocada_en);

  const columns: ResourceListColumn<ApiKey>[] = [
    {
      key: 'nombre',
      header: 'Nombre',
      render: (k) => (
        <div className="min-w-0">
          <div className="truncate font-medium">
            {k.nombre}
            {k.revocada_en && (
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                (revocada)
              </span>
            )}
          </div>
          <div className="truncate font-mono text-xs text-muted-foreground">
            {k.prefijo}…
          </div>
        </div>
      ),
    },
    {
      key: 'creada',
      header: 'Creada',
      width: 'w-24',
      hideOnMobile: true,
      align: 'right',
      render: (k) => (
        <span className="text-xs text-muted-foreground">{formatDate(k.creada_en)}</span>
      ),
    },
    {
      key: 'uso',
      header: 'Último uso',
      width: 'w-24',
      hideOnMobile: true,
      align: 'right',
      render: (k) => (
        <span className="text-xs text-muted-foreground">
          {k.ultima_vez_usada ? formatDate(k.ultima_vez_usada) : 'Nunca'}
        </span>
      ),
    },
  ];

  return (
    <div className="max-w-3xl space-y-6">
      <div className="space-y-3">
        <Link
          href="/ajustes"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <Icon icon="ph:arrow-left-light" className="size-4" /> Preferencias
        </Link>
        <PageHeading
          title="API y conexiones (MCP)"
          description="Emite y revoca las keys con las que tus sistemas (o tu asistente de IA vía MCP) se conectan a TodoConta."
        />
      </div>

      {/* Secreto recién emitido: cópialo ahora, no se puede volver a ver. */}
      {nueva && (
        <Alert>
          <Icon icon="ph:key-light" />
          <AlertDescription>
            <p className="font-semibold text-foreground">
              Tu nueva key. Cópiala ahora, no se puede volver a ver:
            </p>
            <div className="flex w-full items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-md bg-muted px-3 py-2 font-mono text-xs">
                {nueva}
              </code>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void copiar(nueva, 'Key copiada')}
              >
                <Icon icon="ph:copy-light" className="size-4" /> Copiar
              </Button>
            </div>
            <button
              type="button"
              className="text-xs text-muted-foreground underline hover:text-foreground"
              onClick={() => setNueva(null)}
            >
              Ya la guardé
            </button>
          </AlertDescription>
        </Alert>
      )}

      {/* Crear (sin MCP ni API en el plan, las keys no sirven para nada) */}
      {puedeEmitir && (
      <Card className="gap-4 p-5">
        <div>
          <div className="flex items-center gap-2 text-[15px] font-bold tracking-tight">
            <Icon icon="ph:key-light" className="size-4.5 text-foreground/70" />
            Nueva API key
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Una key por integración (por ejemplo, "Claude" o "Mi sistema de facturación"),
            así puedes revocarlas por separado.
          </p>
        </div>
        <div className="flex gap-2">
          <Input
            placeholder="Nombre de la key"
            value={nombre}
            maxLength={100}
            onChange={(e) => setNombre(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void crear();
            }}
          />
          <Button onClick={() => void crear()} disabled={creando || !nombre.trim()}>
            {creando ? (
              <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
            ) : (
              'Crear key'
            )}
          </Button>
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </Card>
      )}

      {/* Listado (sin poder emitir, solo si quedan keys de antes para revocar) */}
      {(puedeEmitir || keys.length > 0) && (
      <Card className="gap-4 p-5">
        <div>
          <div className="text-[15px] font-bold tracking-tight">Tus keys</div>
          <p className="mt-1 text-sm text-muted-foreground">
            {activas.length === 0
              ? 'Aún no tienes keys activas.'
              : `${activas.length} activa${activas.length === 1 ? '' : 's'}.`}{' '}
            Qué puedes hacer con ellas:{' '}
            <a
              href="https://todoconta.com/mcp"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-foreground"
            >
              todoconta.com/mcp
            </a>
            .
          </p>
        </div>
        {cargando ? (
          <div className="flex justify-center py-6">
            <Icon icon="ph:circle-notch-light" className="size-5 animate-spin text-muted-foreground" />
          </div>
        ) : keys.length === 0 ? (
          <p className="py-2 text-sm text-muted-foreground">
            Crea tu primera key arriba para conectar tus sistemas o tu asistente de IA.
          </p>
        ) : (
          <ResourceList
            items={keys}
            getKey={(k) => k.id}
            columns={columns}
            dimmed={false}
            actions={(k) =>
              k.revocada_en ? null : (
                <Button variant="outline" size="sm" onClick={() => void revocar(k)}>
                  Revocar
                </Button>
              )
            }
          />
        )}
      </Card>
      )}

      {/* Conexión MCP */}
      {!conMcp ? (
        <CandadoPlan titulo="Conexión con IA (MCP)" plan="Pro">
          Conecta Claude o ChatGPT a tus empresas para pedir constancias, CFDIs y
          reportes desde el chat. Viene en los planes Pro y Completo.
        </CandadoPlan>
      ) : (
      <Card className="gap-4 p-5">
        <div>
          <div className="flex items-center gap-2 text-[15px] font-bold tracking-tight">
            <Icon icon="ph:plugs-connected-light" className="size-4.5 text-foreground/70" />
            Conexión con IA (MCP)
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            Conecta Claude, ChatGPT u otro asistente compatible con MCP a tus
            servicios de TodoConta (empresas, Constancia, Opinión 32-D, CFDIs,
            listas negras). Agrégalo como "conector personalizado" con esta
            dirección y autentícate con una de tus API keys.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-md bg-muted px-3 py-2 font-mono text-xs">
            {MCP_URL}
          </code>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void copiar(MCP_URL, 'Dirección copiada')}
          >
            <Icon icon="ph:copy-light" className="size-4" /> Copiar
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          ¿Cómo conectarlo paso a paso? Mira la guía en{' '}
          <a
            href="https://todoconta.com/mcp"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-foreground"
          >
            todoconta.com/mcp
          </a>
          .
        </p>
      </Card>
      )}

      {/* API REST y Abacus: solo con planes v3 y datos del plan */}
      {caps && !caps.api && (
        <CandadoPlan titulo="API para tus sistemas" plan="Completo">
          Conecta tu sistema de facturación o tus propios scripts a TodoConta.
          Viene en el plan Completo.
        </CandadoPlan>
      )}
      {caps &&
        (caps.abacus ? (
          <Card className="gap-2 p-5">
            <div className="flex items-center gap-2 text-[15px] font-bold tracking-tight">
              <Icon icon="ph:chat-circle-light" className="size-4.5 text-foreground/70" />
              Abacus por WhatsApp
            </div>
            <p className="text-sm text-muted-foreground">
              Viene en tu plan. Para vincular tu número de WhatsApp, escríbenos a{' '}
              <a
                href="mailto:soporte@todoconta.com?subject=Vincular Abacus"
                className="font-semibold text-foreground underline"
              >
                soporte@todoconta.com
              </a>
              .
            </p>
          </Card>
        ) : (
          <CandadoPlan titulo="Abacus por WhatsApp" plan="Completo">
            Tu asistente fiscal por WhatsApp: pide constancias, opiniones y CFDIs
            desde el chat. Viene en el plan Completo.
          </CandadoPlan>
        ))}
    </div>
  );
}

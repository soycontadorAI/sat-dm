'use client';

import { useEffect, useState, type ReactNode } from 'react';
import { useTheme } from 'next-themes';
import Link from 'next/link';

import { cn } from '@/lib/utils';
import { useServer } from '@/providers/server-provider';
import { useAuth, usePlanesV3, usePlanLicencia } from '@/providers/auth-provider';
import { PlanRequerido } from '@/components/planes/candado-plan';
import { PageHeading } from '@/components/layout/page-heading';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { Icon } from '@/components/ui/icon';
import { getNotifPrefs, setNotifPrefs, type NotifPrefs } from '@/lib/notify/prefs';
import { esWeb } from '@/lib/modo';
import { useUpdates } from '@/hooks/use-updates';

const TEMAS = [
  { value: 'light', label: 'Claro' },
  { value: 'dark', label: 'Oscuro' },
  { value: 'system', label: 'Sistema' },
] as const;

/** Selector de carpeta nativo del SO (solo en Electron); null en navegador. */
function elegirCarpetaNativo(): Promise<string | null> | null {
  if (typeof window === 'undefined') return null;
  const d = (window as unknown as {
    satDesktop?: { elegirCarpeta?: () => Promise<string | null> };
  }).satDesktop;
  return d?.elegirCarpeta ? d.elegirCarpeta() : null;
}

/** Tarjeta de sección: encabezado con icono + filas divididas. */
function AjCard({
  icon,
  title,
  children,
}: {
  icon: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card className="gap-0 px-5 py-1.5">
      <div className="flex items-center gap-2 pb-1.5 pt-3.5 text-[15px] font-bold tracking-tight">
        <Icon icon={icon} className="size-4.5 text-foreground/70" />
        {title}
      </div>
      <div>{children}</div>
    </Card>
  );
}

/**
 * Fila "Versión": número actual + botón "Buscar actualizaciones" (solo en la
 * app instalada). El main de Electron consulta el GitHub Release más reciente
 * (latest.yml), descarga en background y aquí se sigue el progreso; al quedar
 * lista, el botón cambia a "Reiniciar ahora".
 */
function VersionRow({ version }: { version: string | undefined }) {
  const { updates, conUpdater, ocupado, check, install } = useUpdates();

  const sub = !conUpdater
    ? undefined
    : updates?.estado === 'buscando'
      ? 'Buscando actualizaciones…'
      : updates?.estado === 'al-dia'
        ? 'Estás en la última versión.'
        : updates?.estado === 'descargando'
          ? `Descargando la versión ${updates.version ?? ''}… ${updates.progreso ?? 0}%`
          : updates?.estado === 'lista'
            ? `La versión ${updates.version ?? ''} está lista para instalarse.`
            : updates?.estado === 'error'
              ? 'No se pudo buscar actualizaciones. Revisa tu conexión e intenta de nuevo.'
              : undefined;

  return (
    <AjRow
      label="Versión"
      sub={sub}
      control={
        <div className="flex items-center gap-3">
          <span className="font-mono text-[13px] text-foreground/80">
            {version || '—'}
          </span>
          {conUpdater &&
            (updates?.estado === 'lista' ? (
              <Button size="sm" onClick={() => install()}>
                Reiniciar ahora
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                disabled={ocupado}
                onClick={() => check()}
              >
                {ocupado ? (
                  <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                ) : (
                  'Buscar actualizaciones'
                )}
              </Button>
            ))}
        </div>
      }
    />
  );
}

/** Fila de ajuste: label + descripción a la izquierda, control a la derecha. */
function AjRow({
  label,
  sub,
  control,
  col,
}: {
  label: string;
  sub?: ReactNode;
  control: ReactNode;
  /** Control debajo del texto (para grupos de botones anchos). */
  col?: boolean;
}) {
  return (
    <div
      className={cn(
        'flex gap-4 border-t py-3.75',
        col ? 'flex-col' : 'items-center justify-between',
      )}
    >
      <div className="min-w-0">
        <div className="text-[13.5px] font-semibold">{label}</div>
        {sub && (
          <div className="mt-0.5 max-w-prose text-xs leading-snug text-muted-foreground">
            {sub}
          </div>
        )}
      </div>
      <div className="shrink-0">{control}</div>
    </div>
  );
}

export default function AjustesPage() {
  const { apiClient } = useServer();
  const { license, logout } = useAuth();
  // Planes v3: el plan no incluye la MCP (ni la API) → etiqueta "Pro" en la fila.
  const planesV3 = usePlanesV3();
  const planLicencia = usePlanLicencia();
  const sinMcp = planesV3 && planLicencia !== null && !planLicencia.capacidades.mcp;
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  const [esWindows, setEsWindows] = useState(false);
  const [dir, setDir] = useState('');
  const [editable, setEditable] = useState(false);
  const [saving, setSaving] = useState(false);
  const [syncCreds, setSyncCreds] = useState<boolean | null>(null);
  const [notifPrefs, setNotifPrefsState] = useState<NotifPrefs>({
    descargas: true,
    efirma: true,
  });

  useEffect(() => {
    setMounted(true);
    setNotifPrefsState(getNotifPrefs());
    const ua = navigator.platform || navigator.userAgent || '';
    setEsWindows(/Win/i.test(ua));
  }, []);

  function actualizarNotif(patch: Partial<NotifPrefs>) {
    setNotifPrefsState(setNotifPrefs(patch));
  }

  useEffect(() => {
    apiClient
      .getDescargasDir()
      .then((r) => setDir(r.dir))
      .catch(() => {});
    if (!esWeb()) {
      apiClient
        .getSyncCredenciales()
        .then((r) => setSyncCreds(r.activado))
        .catch(() => {});
    }
  }, [apiClient]);

  async function cambiarSyncCreds(v: boolean) {
    setSyncCreds(v); // optimista; el agente persiste en settings.json
    try {
      await apiClient.setSyncCredenciales(v);
    } catch {
      setSyncCreds(!v);
    }
  }

  async function guardar(nueva: string) {
    setSaving(true);
    try {
      const r = await apiClient.setDescargasDir(nueva);
      setDir(r.dir);
      setEditable(false);
    } finally {
      setSaving(false);
    }
  }

  async function cambiar() {
    const picker = elegirCarpetaNativo();
    if (picker) {
      const elegida = await picker; // diálogo nativo del SO
      if (elegida) await guardar(elegida);
    } else {
      setEditable(true); // navegador (dev): editar la ruta a mano
    }
  }

  const web = esWeb();
  const version = process.env.NEXT_PUBLIC_APP_VERSION;
  const sistema = mounted ? (web ? 'Web' : esWindows ? 'Windows' : 'macOS') : '—';

  return (
    <div className="max-w-260 space-y-6">
      <PageHeading
        title="Preferencias de la aplicación"
        description="Estos ajustes se guardan solo en este equipo."
      />

      <div className="grid items-start gap-4.5 md:grid-cols-2">
        {/* Almacenamiento */}
        <AjCard icon="ph:folder-light" title="Almacenamiento">
          <AjRow
            label={web ? 'Tus descargas' : 'Carpeta de descarga'}
            sub={
              web ? (
                // En la web las descargas viven en el espacio del usuario en la
                // nube; se bajan a su equipo con el botón Descargar.
                'Viven en tu espacio seguro en la nube. Bájalas a tu equipo con el botón Descargar del Historial.'
              ) : (
                <span className="block truncate font-mono">{dir || '—'}</span>
              )
            }
            control={
              web ? null : (
                <Button variant="outline" size="sm" onClick={cambiar} disabled={saving}>
                  {saving ? (
                    <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                  ) : (
                    'Cambiar'
                  )}
                </Button>
              )
            }
          />
          {!web && editable && (
            <div className="flex gap-2 border-t py-3.75">
              <Input
                value={dir}
                onChange={(e) => setDir(e.target.value)}
                className="font-mono text-xs"
              />
              <Button size="sm" onClick={() => guardar(dir)} disabled={saving}>
                Guardar
              </Button>
            </div>
          )}
          <AjRow
            label="Estructura"
            sub="Las facturas se ordenan en subcarpetas por tipo y por RFC."
            control={<span className="text-xs text-muted-foreground">Automática</span>}
          />
          {/* Continuidad de credenciales (solo desktop): viajan cifradas
              directo al espacio privado del usuario, nunca a BD compartidas. */}
          {!web && (
            <AjRow
              label="Sincronizar credenciales con mi espacio en línea"
              sub="Tu e.firma y Contraseña del SAT viajan cifradas directo a tu espacio privado — nunca a bases de datos compartidas — para que puedas seguir trabajando desde el navegador, y lo que captures en la web aparezca aquí."
              control={
                <Switch
                  checked={syncCreds ?? true}
                  disabled={syncCreds === null}
                  onCheckedChange={cambiarSyncCreds}
                />
              }
            />
          )}
        </AjCard>

        {/* Apariencia */}
        <AjCard icon="ph:sun-light" title="Apariencia">
          <AjRow
            label="Tema"
            sub="«Sistema» sigue lo que use tu computadora."
            col
            control={
              <div className="flex gap-2">
                {TEMAS.map((t) => {
                  const activo = mounted && theme === t.value;
                  return (
                    <Button
                      key={t.value}
                      size="sm"
                      variant={activo ? 'default' : 'outline'}
                      onClick={() => setTheme(t.value)}
                      aria-pressed={activo}
                    >
                      {t.label}
                    </Button>
                  );
                })}
              </div>
            }
          />
        </AjCard>

        {/* Notificaciones */}
        <AjCard icon="ph:bell-light" title="Notificaciones">
          <AjRow
            label="Avisarme cuando termine una descarga"
            sub="Vale para e.firma o Contraseña del SAT. También te avisamos si alguna falla."
            control={
              <Switch
                checked={notifPrefs.descargas}
                onCheckedChange={(v) => actualizarNotif({ descargas: v })}
              />
            }
          />
          <AjRow
            label="Recordarme si mi e.firma está por vencer"
            sub="Una vez al día, cuando le queden 30 días o menos."
            control={
              <Switch
                checked={notifPrefs.efirma}
                onCheckedChange={(v) => actualizarNotif({ efirma: v })}
              />
            }
          />
        </AjCard>

        {/* Equipo (despachos/empresarial): miembros + permisos por empresa.
            La página se auto-gatea (muestra "Sin equipo" si no aplica). */}
        <AjCard icon="ph:users-light" title="Equipo">
          <AjRow
            label="Miembros y permisos"
            sub="Invita colaboradores, gestiona sus roles y a qué empresas del equipo tienen acceso."
            control={
              <Button asChild variant="outline" size="sm">
                <Link href="/ajustes/equipo">Administrar</Link>
              </Button>
            }
          />
        </AjCard>

        {/* API y conexiones (MCP): gestión de keys + conector de IA. Aplica en
            Desktop y Web por igual (el agente tiene la sesión en ambos). */}
        <AjCard icon="ph:plugs-connected-light" title="API y conexiones (MCP)">
          <AjRow
            label="API keys y conexión con IA"
            sub="Emite y revoca las keys para conectar tus sistemas (o tu asistente de IA vía MCP) a TodoConta."
            control={
              <div className="flex items-center gap-2">
                {sinMcp && <PlanRequerido plan="Pro" />}
                <Button asChild variant="outline" size="sm">
                  <Link href="/ajustes/api">{sinMcp ? 'Ver' : 'Administrar'}</Link>
                </Button>
              </div>
            }
          />
        </AjCard>

        {/* Acerca de */}
        <AjCard icon="ph:info-light" title="Acerca de">
          <VersionRow version={version} />
          <AjRow
            label="Equipo"
            control={
              <span className="font-mono text-[13px] text-foreground/80">
                {sistema}
              </span>
            }
          />
          <AjRow
            label="Cuenta"
            sub={license?.email ? <span className="truncate">{license.email}</span> : undefined}
            control={
              <Button
                variant="ghost"
                size="sm"
                className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                onClick={() => logout()}
              >
                Cerrar sesión
              </Button>
            }
          />
        </AjCard>
      </div>
    </div>
  );
}

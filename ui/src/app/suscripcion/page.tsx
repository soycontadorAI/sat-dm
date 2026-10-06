'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useAuth, usePlanesV3 } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';
import { mensajeDeError } from '@/lib/errores';
import { diasRestantes, formatDate, formatPesosEnteros } from '@/lib/formatting';
import type { TransferIntentResponse } from '@/lib/api-client';
import { cn } from '@/lib/utils';
import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import {
  CopyRow,
  EstadoBadge,
  IaUpsellCard,
  InfoRow,
  MetodoTile,
  Note,
  PlanCard,
} from '@/components/suscripcion/piezas';
import { SuscripcionV3 } from '@/components/suscripcion/suscripcion-v3';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

/**
 * Página interna de suscripción y cuenta (/suscripcion).
 *
 * Layout de dos columnas (boceto de Claude Design):
 *  - Principal: tarjeta del plan según estado (oferta trial/free · activo premium ·
 *    Miembro Fundador). En la oferta, el pago se elige con tiles tipo radio
 *    (tarjeta Stripe / transferencia) y la transferencia carga los datos al elegirla.
 *  - Rail: cuenta regresiva de prueba (con barra), tarjeta de cuenta y ayuda.
 *
 * Ruta estática (cumple `output: 'export'`).
 *
 * Con el interruptor de planes v3 encendido (flag `PLANES_V3` o
 * `license.planes_v3_activo`) se muestra `SuscripcionV3`: los tres planes con
 * selector anual o mensual. Apagado, la vista de siempre (`SuscripcionActual`).
 */

const INCLUYE = [
  'Descarga masiva ilimitada de CFDIs del SAT',
  'Todas las empresas y RFC que necesites',
  'Herramientas premium en línea, de regalo',
];

export default function SuscripcionPage() {
  const planesV3 = usePlanesV3();
  return planesV3 ? <SuscripcionV3 /> : <SuscripcionActual />;
}

function SuscripcionActual() {
  const { license, refresh, logout } = useAuth();
  const { apiClient } = useServer();

  const [busyTarjeta, setBusyTarjeta] = useState(false);
  const [busyIa, setBusyIa] = useState(false);
  const [busyTransfer, setBusyTransfer] = useState(false);
  const [busyCancel, setBusyCancel] = useState(false);
  const [transfer, setTransfer] = useState<TransferIntentResponse | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [metodo, setMetodo] = useState<'tarjeta' | 'transferencia'>('tarjeta');
  const [equipo, setEquipo] = useState('Esta computadora');

  // Al entrar, fuerza un refresh del license (bypassa el cache de 24h del agente)
  // para que el precio y la promo coincidan con lo que aplicará el checkout.
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const ua = navigator.userAgent;
    setEquipo(/Mac/i.test(ua) ? 'Esta Mac' : /Win/i.test(ua) ? 'Esta PC' : 'Esta computadora');
  }, []);

  if (!license?.authenticated) return null;

  const plan = license.plan ?? 'free';
  const esFundador = plan === 'founder' || license.is_founder === true;
  const esPremium = plan === 'premium';
  const esPrueba = plan === 'trial';
  const promoActive = license.promo_active === true;
  const precio = promoActive ? license.promo_price_mxn ?? 1495 : license.regular_price_mxn ?? 2990;
  const regular = license.regular_price_mxn ?? 2990;
  const ahorro = Math.max(0, regular - precio);
  const dias = license.days_remaining ?? null;
  const cancela = license.subscription_cancel_at_period_end === true;
  const promoDias = license.promo_ends_at ? diasRestantes(license.promo_ends_at) : null;
  const pct = dias !== null ? Math.max(6, Math.min(100, Math.round((dias / 15) * 100))) : 0;
  const tieneIa = license.ai_features_unlocked === true;
  const precioIa = esFundador
    ? license.ia_founder_price_mxn ?? 2490
    : license.ia_price_mxn ?? 4990;
  const precioIaLista = license.ia_price_mxn ?? 4990;
  const planLabel = esFundador
    ? 'Fundador'
    : esPremium
      ? tieneIa
        ? 'Plan anual con IA'
        : 'Plan anual'
      : esPrueba
        ? 'Prueba'
        : 'Gratis';

  async function pagarTarjeta() {
    if (busyTarjeta) return;
    setBusyTarjeta(true);
    try {
      const { url } = await apiClient.authSubscribe('anual');
      window.open(url, '_blank', 'noopener,noreferrer');
      toast.info(
        'Te abrimos el navegador para pagar. Cuando termines, vuelve y toca "Ya pagué — actualizar estado".',
      );
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyTarjeta(false);
    }
  }

  async function pagarIa() {
    if (busyIa) return;
    setBusyIa(true);
    try {
      const { url } = await apiClient.authSubscribe('anual_ia');
      window.open(url, '_blank', 'noopener,noreferrer');
      toast.info(
        'Te abrimos el navegador para pagar. Cuando termines, vuelve y toca "Ya pagué — actualizar estado".',
      );
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyIa(false);
    }
  }

  async function pedirTransferencia() {
    if (busyTransfer) return;
    setBusyTransfer(true);
    try {
      const res = await apiClient.authTransferIntent();
      setTransfer(res);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyTransfer(false);
    }
  }

  function elegirMetodo(m: 'tarjeta' | 'transferencia') {
    setMetodo(m);
    if (m === 'transferencia' && !transfer && !busyTransfer) void pedirTransferencia();
  }

  async function confirmarCancelar() {
    if (busyCancel) return;
    setBusyCancel(true);
    try {
      const res = await apiClient.authCancelSubscription();
      toast.success(
        res.message ??
          'Tu suscripción se cancelará al fin del periodo. Conservas el acceso hasta entonces.',
      );
      setCancelOpen(false);
      await refresh();
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyCancel(false);
    }
  }

  async function copiar(texto: string, etiqueta: string) {
    try {
      await navigator.clipboard.writeText(texto);
      toast.success(`${etiqueta} copiada`);
    } catch {
      toast.error('No se pudo copiar');
    }
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeading
        title="Suscripción y cuenta"
        description="Administra tu plan, tus pagos y los datos de tu cuenta. La app funciona siempre; la suscripción mantiene el proyecto vivo."
      />

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        {/* ── Columna principal ── */}
        <div className="flex min-w-0 flex-col gap-5">
          {esFundador ? (
            <>
              <PlanCard
                markClass="bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400"
                icon="ph:crown-simple-fill"
                titulo="Miembro Fundador"
                badge={<EstadoBadge tone="amber">De por vida</EstadoBadge>}
              >
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Tienes acceso de por vida a la app de escritorio y a las herramientas
                  premium en línea. Gracias por construir esto desde el inicio.
                </p>
              </PlanCard>
              {tieneIa ? (
                <Note icon="ph:sparkle-light">
                  Tu plan con IA está activo: Abacus por WhatsApp y la conexión de tu IA
                  (API + MCP) trabajan con tus empresas.
                </Note>
              ) : (
                <IaUpsellCard
                  precio={precioIa}
                  precioLista={precioIaLista}
                  esFundador
                  busy={busyIa}
                  onPagar={pagarIa}
                />
              )}
            </>
          ) : esPremium ? (
            <>
              <PlanCard
                markClass="bg-success/10 text-success"
                icon="ph:crown-simple-light"
                titulo={tieneIa ? 'Plan anual con IA' : 'Plan anual'}
                badge={
                  <EstadoBadge tone="success">
                    <Icon
                      icon={cancela ? 'ph:info-light' : 'ph:check-circle-light'}
                      className="size-3.5"
                    />
                    {cancela ? 'Cancela al renovar' : 'Activo'}
                  </EstadoBadge>
                }
              >
                <div className="flex flex-col">
                  <InfoRow
                    label={cancela ? 'Termina el' : 'Próxima renovación'}
                    value={license.expires_at ? formatDate(license.expires_at) : '—'}
                  />
                  <InfoRow label="Acceso premium en línea" value="Incluido" />
                  {tieneIa && <InfoRow label="Asistente con IA (Abacus + MCP)" value="Incluido" />}
                </div>
                {cancela ? (
                  <Note icon="ph:info-light">
                    Tu suscripción terminará el {formatDate(license.expires_at ?? '')} y no se
                    renovará. Conservas el acceso hasta esa fecha.
                  </Note>
                ) : (
                  <div>
                    <Button variant="outline" onClick={() => setCancelOpen(true)}>
                      <Icon icon="ph:x-circle-light" className="size-4" />
                      Cancelar plan
                    </Button>
                  </div>
                )}
              </PlanCard>
              {!tieneIa && (
                <Note icon="ph:sparkle-light">
                  ¿Quieres agregar la IA (Abacus por WhatsApp + conexión de Claude/ChatGPT)?
                  Escríbenos a{' '}
                  <a
                    href="mailto:soporte@todoconta.com?subject=Subir a plan con IA"
                    className="font-semibold text-primary hover:underline"
                  >
                    soporte@todoconta.com
                  </a>{' '}
                  y hacemos el cambio sin que pierdas lo que ya pagaste.
                </Note>
              )}
            </>
          ) : (
            /* trial / free → oferta */
            <>
            <PlanCard
              className="border-primary/40"
              markClass="bg-accent text-primary"
              icon="ph:crown-simple-light"
              titulo="Plan anual"
              badge={
                promoActive ? (
                  <EstadoBadge tone="primary">
                    <Icon icon="ph:percent-light" className="size-3.5" />
                    50% de por vida
                  </EstadoBadge>
                ) : (
                  <EstadoBadge tone="muted">Facturación anual</EstadoBadge>
                )
              }
            >
              {/* precio */}
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-4xl font-extrabold tracking-tight tabular-nums">
                  {formatPesosEnteros(precio)}
                </span>
                <span className="text-sm font-medium text-muted-foreground">/ año</span>
                {promoActive && ahorro > 0 && (
                  <>
                    <span className="text-base text-muted-foreground/70 line-through tabular-nums">
                      {formatPesosEnteros(regular)}
                    </span>
                    <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-bold text-success">
                      Ahorras {formatPesosEnteros(ahorro)}
                    </span>
                  </>
                )}
              </div>

              {/* incluye */}
              <ul className="flex flex-col gap-2.5">
                {INCLUYE.map((t) => (
                  <li key={t} className="flex items-center gap-2.5 text-sm text-foreground/90">
                    <Icon icon="ph:check-circle-light" className="size-4 shrink-0 text-success" />
                    {t}
                  </li>
                ))}
              </ul>

              {/* promo congelada */}
              {promoActive && (
                <div className="flex gap-2.5 rounded-lg border border-primary/20 bg-accent/60 p-3 text-[13px] leading-relaxed text-foreground/80">
                  <Icon icon="ph:lock-light" className="mt-0.5 size-4 shrink-0 text-primary" />
                  <p>
                    <strong className="font-semibold text-accent-foreground">
                      Tu precio queda congelado.
                    </strong>{' '}
                    Suscríbete {promoDias !== null ? `en los próximos ${promoDias} días` : 'ahora'} y
                    conservas {formatPesosEnteros(precio)}/año en cada renovación, aunque el precio de
                    lista suba. Solo lo pierdes si cancelas.
                  </p>
                </div>
              )}

              {/* separador */}
              <div className="flex items-center gap-3 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                <span className="h-px flex-1 bg-border" />
                Elige cómo pagar
                <span className="h-px flex-1 bg-border" />
              </div>

              {/* método */}
              <div className="grid grid-cols-2 gap-3">
                <MetodoTile
                  on={metodo === 'tarjeta'}
                  onClick={() => elegirMetodo('tarjeta')}
                  icon="ph:credit-card-light"
                  titulo="Tarjeta"
                  sub="Activación inmediata · vía Stripe"
                />
                <MetodoTile
                  on={metodo === 'transferencia'}
                  onClick={() => elegirMetodo('transferencia')}
                  icon="ph:bank-light"
                  titulo="Transferencia"
                  sub="Se activa en unas horas"
                />
              </div>

              {/* acción según método */}
              {metodo === 'tarjeta' ? (
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="lg" onClick={pagarTarjeta} disabled={busyTarjeta}>
                    <Icon
                      icon={busyTarjeta ? 'ph:circle-notch-light' : 'ph:lightning-light'}
                      className={cn('size-4', busyTarjeta && 'animate-spin')}
                    />
                    Pagar {formatPesosEnteros(precio)} con tarjeta
                  </Button>
                  <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Icon icon="ph:lock-light" className="size-3.5" />
                    Pago seguro con Stripe.
                  </span>
                </div>
              ) : (
                <div className="rounded-xl border bg-secondary/50 p-4">
                  <div className="mb-3 flex items-center gap-2 text-sm font-bold">
                    <Icon icon="ph:bank-light" className="size-4 text-primary" />
                    Transfiere {formatPesosEnteros(transfer?.amount_mxn ?? precio)} a esta cuenta
                  </div>
                  {busyTransfer && !transfer ? (
                    <div className="flex items-center gap-2 py-1.5 text-sm text-muted-foreground">
                      <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                      Obteniendo datos de la cuenta…
                    </div>
                  ) : transfer && transfer.banco.clabe ? (
                    <>
                      <div className="flex flex-col">
                        {transfer.banco.beneficiario && (
                          <CopyRow etiqueta="Beneficiario" valor={transfer.banco.beneficiario} onCopy={copiar} />
                        )}
                        {transfer.banco.banco && (
                          <CopyRow etiqueta="Banco" valor={transfer.banco.banco} onCopy={copiar} />
                        )}
                        {transfer.banco.clabe && (
                          <CopyRow etiqueta="CLABE" valor={transfer.banco.clabe} mono onCopy={copiar} />
                        )}
                        {transfer.banco.referencia && (
                          <CopyRow etiqueta="Referencia" valor={transfer.banco.referencia} mono onCopy={copiar} />
                        )}
                      </div>
                      <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
                        <Icon icon="ph:info-light" className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                          {transfer.message ??
                            'La activación por transferencia puede tardar unas horas.'}{' '}
                          Envíanos tu comprobante para activar tu cuenta.
                        </span>
                      </p>
                    </>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      Los datos bancarios aún no están configurados. Contacta a soporte.
                    </p>
                  )}
                </div>
              )}

              {/* refrescar estado */}
              <button
                type="button"
                onClick={() => refresh()}
                className="inline-flex items-center gap-1.5 self-start text-xs font-semibold text-muted-foreground transition-colors hover:text-primary"
              >
                <Icon icon="ph:arrows-clockwise-light" className="size-3.5" />
                Ya pagué — actualizar estado
              </button>
            </PlanCard>
            <IaUpsellCard
              precio={precioIa}
              precioLista={precioIaLista}
              busy={busyIa}
              onPagar={pagarIa}
            />
            </>
          )}
        </div>

        {/* ── Rail ── */}
        <aside className="flex flex-col gap-4">
          {esPrueba && dias !== null && (
            <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm">
              <div className="mb-3 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                <Icon icon="ph:hourglass-medium-light" className="size-4 text-muted-foreground/70" />
                Periodo de prueba
              </div>
              <div className="mb-3 text-2xl font-extrabold tracking-tight">
                {dias}{' '}
                <span className="text-sm font-medium text-muted-foreground">
                  {dias === 1 ? 'día restante' : 'días restantes'}
                </span>
              </div>
              <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-secondary">
                <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
              </div>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Cuando termine, la app sigue funcionando. Las funciones premium pedirán plan.
              </p>
            </div>
          )}

          <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm">
            <div className="mb-3 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
              <Icon icon="ph:gear-light" className="size-4 text-muted-foreground/70" />
              Tu cuenta
            </div>
            <div className="flex flex-col">
              {license.email && <InfoRow label="Correo" value={license.email} />}
              <InfoRow label="Plan" value={planLabel} />
              <InfoRow label="Equipo" value={equipo} />
            </div>
            <button
              type="button"
              onClick={() => logout()}
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground transition-colors hover:text-destructive"
            >
              <Icon icon="ph:sign-out-light" className="size-3.5" />
              Cerrar sesión
            </button>
          </div>

          <div className="flex gap-2 px-1 text-xs leading-relaxed text-muted-foreground">
            <Icon icon="ph:question-light" className="mt-0.5 size-4 shrink-0 text-muted-foreground/70" />
            <span>
              ¿Dudas con tu plan o tu pago?{' '}
              <a
                href="mailto:soporte@todoconta.com"
                className="font-semibold text-primary hover:underline"
              >
                Escríbenos
              </a>{' '}
              y te ayudamos.
            </span>
          </div>
        </aside>
      </div>

      {/* Diálogo de cancelación */}
      <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>¿Cancelar tu suscripción?</DialogTitle>
            <DialogDescription>
              No se renovará al final del periodo. Conservas el acceso hasta
              {license.expires_at ? ` el ${formatDate(license.expires_at)}` : ' el fin del periodo'}.
              Pierdes el precio bloqueado de la promo si vuelves a suscribirte después.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCancelOpen(false)} disabled={busyCancel}>
              Conservar
            </Button>
            <Button variant="destructive" onClick={confirmarCancelar} disabled={busyCancel}>
              {busyCancel && <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />}
              Sí, cancelar
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

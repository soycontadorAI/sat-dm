'use client';

import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { useAuth, usePlanLicencia } from '@/providers/auth-provider';
import { useServer } from '@/providers/server-provider';
import { useEmpresas } from '@/hooks/use-empresas';
import { mensajeDeError } from '@/lib/errores';
import { formatDate, formatPesosEnteros } from '@/lib/formatting';
import type { IntervaloPlan, PlanV3Venta, TransferIntentResponse } from '@/lib/api-client';
import {
  CATALOGO_V3,
  empresasTexto,
  planDelCatalogo,
  precioDe,
  sufijoIntervalo,
  type PlanV3Catalogo,
} from '@/lib/planes-v3';
import { cn } from '@/lib/utils';
import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  CopyRow,
  EstadoBadge,
  IaUpsellCard,
  InfoRow,
  MetodoTile,
  Note,
  PlanCard,
} from '@/components/suscripcion/piezas';

/**
 * /suscripcion con los planes v3 (F1 de docs/operacion/plan-app-v3.md en
 * todoconta-apps). Se muestra solo con el interruptor encendido.
 *
 * Según la cuenta:
 *  - Plan v3 (Esencial, Pro, Completo): su plan, uso del tope y cambio de plan
 *    con prorrateo (bajar se bloquea si las empresas activas no caben).
 *  - Legado (Anual, Anual con IA, planes web viejos): tarjeta "Tu precio
 *    asegurado" y los planes nuevos con el aviso de que cambiar libera ese precio.
 *  - Fundador: su licencia de por vida y, si no la tiene, la IA a su precio.
 *  - Prueba y Gratis: los tres planes, anual o mensual, con tarjeta o SPEI
 *    (la transferencia solo es anual).
 * El servidor decide siempre el precio; aquí solo se elige plan e intervalo.
 */

type Situacion = 'v3' | 'medida' | 'fundador' | 'legado' | 'prueba' | 'gratis';
type Metodo = 'tarjeta' | 'transferencia';

interface Confirmacion {
  plan: PlanV3Catalogo;
  motivo: 'legado' | 'cambio';
}

const PLANES_V3_PAGO: readonly string[] = ['esencial', 'pro', 'completo'];

export function SuscripcionV3() {
  const { license, refresh, logout } = useAuth();
  const plan = usePlanLicencia();
  const { apiClient } = useServer();
  const { empresas } = useEmpresas();

  const [intervalo, setIntervalo] = useState<IntervaloPlan>('anual');
  const [elegido, setElegido] = useState<PlanV3Venta | null>(null);
  const [metodo, setMetodo] = useState<Metodo>('tarjeta');
  const [transfer, setTransfer] = useState<TransferIntentResponse | null>(null);
  const [busyPago, setBusyPago] = useState(false);
  const [busyTransfer, setBusyTransfer] = useState(false);
  const [busyIa, setBusyIa] = useState(false);
  const [busyCancel, setBusyCancel] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [confirmar, setConfirmar] = useState<Confirmacion | null>(null);
  const [equipo, setEquipo] = useState('Esta computadora');

  // Al entrar, licencia fresca (bypassa el cache de 24 h del agente).
  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const ua = navigator.userAgent;
    setEquipo(/Mac/i.test(ua) ? 'Esta Mac' : /Win/i.test(ua) ? 'Esta PC' : 'Esta computadora');
  }, []);

  // El intervalo de la suscripción vigente manda la primera vez.
  const intervaloActual = license?.intervalo ?? null;
  useEffect(() => {
    if (intervaloActual) setIntervalo(intervaloActual);
  }, [intervaloActual]);

  if (!license?.authenticated) return null;

  const codigo = plan?.codigo;
  const suscrito = license.plan === 'premium';
  const esFundador = license.is_founder === true || license.plan === 'founder';
  const situacion: Situacion =
    suscrito && codigo && PLANES_V3_PAGO.includes(codigo)
      ? 'v3'
      : suscrito && codigo === 'medida'
        ? 'medida'
        : esFundador
          ? 'fundador'
          : suscrito
            ? 'legado'
            : license.plan === 'trial'
              ? 'prueba'
              : 'gratis';

  const activas = empresas.length
    ? empresas.filter((e) => !e.archived_at).length
    : plan?.empresasActivas ?? 0;
  const cancela = license.subscription_cancel_at_period_end === true;
  const vence = license.expires_at ? formatDate(license.expires_at) : null;
  const dias = license.days_remaining ?? null;
  const tieneIa = license.ai_features_unlocked === true;
  const planActual = situacion === 'v3' ? planDelCatalogo(codigo) : null;
  const catalogoElegido = planDelCatalogo(elegido);
  const muestraPlanes = situacion === 'v3' || situacion === 'legado' || situacion === 'prueba' || situacion === 'gratis';

  // ── Acciones ──────────────────────────────────────────────────────────────

  function cambiarIntervalo(i: IntervaloPlan) {
    setIntervalo(i);
    // La transferencia solo es anual (su monto no cambia con el selector).
    if (i === 'mensual') setMetodo('tarjeta');
  }

  function elegir(p: PlanV3Catalogo) {
    if (situacion === 'v3') {
      setConfirmar({ plan: p, motivo: 'cambio' });
      return;
    }
    setElegido(p.codigo);
    setTransfer(null);
    if (metodo === 'transferencia') void pedirTransferencia(p.codigo);
  }

  async function contratar(p: PlanV3Catalogo) {
    if (busyPago) return;
    setBusyPago(true);
    try {
      const res = await apiClient.authSubscribePlan(p.codigo, intervalo);
      if (res.url) {
        window.open(res.url, '_blank', 'noopener,noreferrer');
        toast.info(
          'Te abrimos el navegador para pagar. Cuando termines, vuelve y toca "Ya pagué, actualizar estado".',
        );
      } else {
        toast.success(res.message ?? `Listo: tu plan ahora es ${p.nombre}.`);
        setElegido(null);
        await refresh();
      }
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyPago(false);
    }
  }

  function pagarConTarjeta() {
    if (!catalogoElegido) return;
    if (situacion === 'legado') setConfirmar({ plan: catalogoElegido, motivo: 'legado' });
    else void contratar(catalogoElegido);
  }

  async function pedirTransferencia(p: PlanV3Venta) {
    if (busyTransfer) return;
    setBusyTransfer(true);
    try {
      setTransfer(await apiClient.authTransferIntent(p));
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyTransfer(false);
    }
  }

  function elegirMetodo(m: Metodo) {
    if (m === 'transferencia' && intervalo === 'mensual') return;
    setMetodo(m);
    if (m === 'transferencia' && elegido && !transfer && !busyTransfer) void pedirTransferencia(elegido);
  }

  async function pagarIa() {
    if (busyIa) return;
    setBusyIa(true);
    try {
      const { url } = await apiClient.authSubscribe('anual_ia');
      window.open(url, '_blank', 'noopener,noreferrer');
      toast.info(
        'Te abrimos el navegador para pagar. Cuando termines, vuelve y toca "Ya pagué, actualizar estado".',
      );
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusyIa(false);
    }
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

  // ── Render ────────────────────────────────────────────────────────────────

  const botonCancelar = cancela ? (
    <Note icon="ph:info-light">
      Tu suscripción termina{vence ? ` el ${vence}` : ''} y no se renovará. Conservas el acceso
      hasta esa fecha.
    </Note>
  ) : (
    <div>
      <Button variant="outline" onClick={() => setCancelOpen(true)}>
        <Icon icon="ph:x-circle-light" className="size-4" />
        Cancelar plan
      </Button>
    </div>
  );

  const badgeEstado = (
    <EstadoBadge tone="success">
      <Icon icon={cancela ? 'ph:info-light' : 'ph:check-circle-light'} className="size-3.5" />
      {cancela ? 'Cancela al renovar' : 'Activo'}
    </EstadoBadge>
  );

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeading
        title="Suscripción y cuenta"
        description="Tu plan, tus pagos y los datos de tu cuenta."
      />

      <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-5">
          {/* ── Estado de la cuenta ── */}
          {situacion === 'v3' && planActual && (
            <PlanCard
              markClass="bg-success/10 text-success"
              icon="ph:crown-simple-light"
              titulo={`Plan ${planActual.nombre}`}
              badge={badgeEstado}
            >
              <div className="flex flex-col">
                {intervaloActual && (
                  <InfoRow label="Cobro" value={intervaloActual === 'anual' ? 'Anual' : 'Mensual'} />
                )}
                <InfoRow label={cancela ? 'Termina el' : 'Próxima renovación'} value={vence ?? 'Sin fecha'} />
                <InfoRow
                  label="Empresas activas"
                  value={`${activas} de ${plan?.limites.empresas ?? planActual.empresas}`}
                />
                <InfoRow
                  label="Usuarios"
                  value={`Hasta ${plan?.limites.usuarios ?? planActual.usuarios}`}
                />
              </div>
              {botonCancelar}
            </PlanCard>
          )}

          {situacion === 'medida' && (
            <PlanCard
              markClass="bg-success/10 text-success"
              icon="ph:crown-simple-light"
              titulo="Plan A la medida"
              badge={badgeEstado}
            >
              <div className="flex flex-col">
                <InfoRow label={cancela ? 'Termina el' : 'Próxima renovación'} value={vence ?? 'Sin fecha'} />
                {typeof plan?.limites.empresas === 'number' && (
                  <InfoRow label="Empresas activas" value={`${activas} de ${plan.limites.empresas}`} />
                )}
              </div>
              <Note icon="ph:chat-circle-light">
                Tu plan se armó a tu medida. Para cambiarlo, escríbenos a{' '}
                <a href="mailto:soporte@todoconta.com" className="font-semibold text-foreground hover:underline">
                  soporte@todoconta.com
                </a>
                .
              </Note>
            </PlanCard>
          )}

          {situacion === 'fundador' && (
            <>
              <PlanCard
                markClass="bg-amber-100 text-amber-600 dark:bg-amber-500/15 dark:text-amber-400"
                icon="ph:crown-simple-fill"
                titulo="Miembro Fundador"
                badge={<EstadoBadge tone="amber">De por vida</EstadoBadge>}
              >
                <p className="text-sm leading-relaxed text-muted-foreground">
                  Tu licencia es de por vida, con empresas ilimitadas y la conexión con tu IA
                  (MCP). Gracias por construir esto desde el inicio.
                </p>
              </PlanCard>
              {tieneIa ? (
                <Note icon="ph:sparkle-light">
                  Tu plan con IA está activo: Abacus por WhatsApp y la API trabajan con tus
                  empresas.
                </Note>
              ) : (
                <IaUpsellCard
                  precio={license.ia_founder_price_mxn ?? 2490}
                  precioLista={license.ia_price_mxn ?? 4990}
                  esFundador
                  busy={busyIa}
                  onPagar={pagarIa}
                />
              )}
            </>
          )}

          {situacion === 'legado' && (
            <PlanCard
              className="border-primary/40"
              markClass="bg-accent text-primary"
              icon="ph:lock-simple-light"
              titulo="Tu precio asegurado"
              badge={badgeEstado}
            >
              <p className="text-sm leading-relaxed text-foreground/90">
                {typeof plan?.precioAseguradoMxn === 'number' ? (
                  <>
                    Pagas{' '}
                    <strong className="font-semibold tabular-nums">
                      {formatPesosEnteros(plan.precioAseguradoMxn)} al año
                    </strong>{' '}
                    en tu plan {plan.nombre}, con empresas ilimitadas, mientras sigas suscrito.
                  </>
                ) : (
                  <>
                    Conservas las condiciones de tu plan {plan?.nombre ?? 'actual'}, con empresas
                    ilimitadas, mientras sigas suscrito.
                  </>
                )}
              </p>
              <div className="flex flex-col">
                <InfoRow label={cancela ? 'Termina el' : 'Próxima renovación'} value={vence ?? 'Sin fecha'} />
              </div>
              <Note icon="ph:warning-light">
                Si cambias a uno de los planes nuevos, dejas este precio y ya no lo puedes
                recuperar. Los planes nuevos tienen tope de empresas.
              </Note>
              {botonCancelar}
            </PlanCard>
          )}

          {situacion === 'prueba' && (
            <PlanCard
              markClass="bg-accent text-primary"
              icon="ph:hourglass-medium-light"
              titulo="Tu prueba"
              badge={
                dias !== null ? (
                  <EstadoBadge tone="primary">
                    {dias === 1 ? 'Queda 1 día' : `Quedan ${dias} días`}
                  </EstadoBadge>
                ) : undefined
              }
            >
              <p className="text-sm leading-relaxed text-muted-foreground">
                Mientras dura, tienes lo del plan Pro: hasta 50 empresas, exportaciones y la
                conexión con tu IA (MCP). Elige tu plan para seguir sin cortes.
              </p>
            </PlanCard>
          )}

          {situacion === 'gratis' && (
            <PlanCard markClass="bg-secondary text-muted-foreground" icon="ph:user-light" titulo="Plan Gratis">
              <p className="text-sm leading-relaxed text-muted-foreground">
                La app de escritorio sigue funcionando con lo básico. Para la web, más empresas,
                las exportaciones y la conexión con tu IA, elige un plan.
              </p>
            </PlanCard>
          )}

          {/* ── Planes ── */}
          {muestraPlanes && (
            <section className="flex flex-col gap-4">
              <div className="flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h2 className="text-lg font-extrabold tracking-tight">
                    {situacion === 'legado' ? 'Planes nuevos' : situacion === 'v3' ? 'Cambiar de plan' : 'Elige tu plan'}
                  </h2>
                  <p className="mt-0.5 text-[13px] text-muted-foreground">
                    Precios con IVA. El anual cuesta 10 mensualidades: 2 meses gratis.
                  </p>
                </div>
                <SelectorIntervalo valor={intervalo} onCambio={cambiarIntervalo} />
              </div>

              <div className="grid gap-4 md:grid-cols-3">
                {CATALOGO_V3.map((p) => {
                  const esActual = situacion === 'v3' && p.codigo === codigo;
                  const mismoIntervalo = !intervaloActual || intervaloActual === intervalo;
                  const noCabe = activas > p.empresas;
                  // Bajar de plan con suscripción v3: bloqueado si no caben.
                  const bloqueado = situacion === 'v3' && !esActual && noCabe;
                  let cta: string;
                  if (esActual && mismoIntervalo) cta = 'Tu plan actual';
                  else if (esActual) cta = intervalo === 'anual' ? 'Pasar a anual' : 'Pasar a mensual';
                  else if (situacion === 'v3' || situacion === 'legado') cta = `Cambiar a ${p.nombre}`;
                  else cta = `Elegir ${p.nombre}`;
                  return (
                    <TarjetaPlan
                      key={p.codigo}
                      plan={p}
                      intervalo={intervalo}
                      seleccionado={elegido === p.codigo}
                      etiqueta={
                        esActual
                          ? 'Tu plan'
                          : situacion === 'prueba' && p.codigo === 'pro'
                            ? 'Lo de tu prueba'
                            : undefined
                      }
                      cta={cta}
                      deshabilitado={(esActual && mismoIntervalo) || bloqueado || busyPago}
                      onElegir={() => elegir(p)}
                      nota={
                        bloqueado
                          ? `Tienes ${activas} empresas activas y ${p.nombre} incluye ${p.empresas}. Archiva ${activas - p.empresas} para cambiar.`
                          : undefined
                      }
                    />
                  );
                })}
              </div>
            </section>
          )}

          {/* ── Pago (alta nueva o legado que cambia) ── */}
          {catalogoElegido && situacion !== 'v3' && (
            <PlanCard
              className="border-primary/40"
              markClass="bg-accent text-primary"
              icon="ph:credit-card-light"
              titulo={`${catalogoElegido.nombre} ${intervalo}`}
            >
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-4xl font-extrabold tracking-tight tabular-nums">
                  {formatPesosEnteros(precioDe(catalogoElegido, intervalo))}
                </span>
                <span className="text-sm font-medium text-muted-foreground">
                  {sufijoIntervalo(intervalo)}, IVA incluido
                </span>
              </div>

              {activas > catalogoElegido.empresas && (
                <Note icon="ph:warning-light">
                  Tienes {activas} empresas activas y {catalogoElegido.nombre} incluye{' '}
                  {empresasTexto(catalogoElegido.empresas)}. Después de pagar no podrás agregar
                  más hasta archivar {activas - catalogoElegido.empresas}.
                </Note>
              )}
              {situacion === 'legado' && (
                <Note icon="ph:warning-light">
                  Al cambiar dejas tu precio asegurado y ya no lo puedes recuperar.
                </Note>
              )}

              <div className="grid grid-cols-2 gap-3">
                <MetodoTile
                  on={metodo === 'tarjeta'}
                  onClick={() => elegirMetodo('tarjeta')}
                  icon="ph:credit-card-light"
                  titulo="Tarjeta"
                  sub="Activación inmediata con Stripe"
                />
                <MetodoTile
                  on={metodo === 'transferencia'}
                  onClick={() => elegirMetodo('transferencia')}
                  icon="ph:bank-light"
                  titulo="Transferencia"
                  sub={intervalo === 'mensual' ? 'Solo para el pago anual' : 'Se activa en unas horas'}
                />
              </div>

              {metodo === 'tarjeta' ? (
                <div className="flex flex-wrap items-center gap-3">
                  <Button size="lg" onClick={pagarConTarjeta} disabled={busyPago}>
                    <Icon
                      icon={busyPago ? 'ph:circle-notch-light' : 'ph:lightning-light'}
                      className={cn('size-4', busyPago && 'animate-spin')}
                    />
                    Pagar {formatPesosEnteros(precioDe(catalogoElegido, intervalo))} con tarjeta
                  </Button>
                  <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Icon icon="ph:lock-light" className="size-3.5" />
                    Pago seguro con Stripe.
                  </span>
                </div>
              ) : (
                <DatosTransferencia
                  monto={transfer?.amount_mxn ?? catalogoElegido.precioAnual}
                  transfer={transfer}
                  cargando={busyTransfer}
                  onCopiar={copiar}
                />
              )}

              <button
                type="button"
                onClick={() => refresh()}
                className="inline-flex items-center gap-1.5 self-start text-xs font-semibold text-muted-foreground transition-colors hover:text-primary"
              >
                <Icon icon="ph:arrows-clockwise-light" className="size-3.5" />
                Ya pagué, actualizar estado
              </button>
            </PlanCard>
          )}
        </div>

        {/* ── Rail ── */}
        <aside className="flex flex-col gap-4">
          <div className="rounded-xl border bg-card p-5 text-card-foreground shadow-sm">
            <div className="mb-3 flex items-center gap-1.5 text-[13px] font-bold">
              <Icon icon="ph:gear-light" className="size-4 text-muted-foreground/70" />
              Tu cuenta
            </div>
            <div className="flex flex-col">
              {license.email && <InfoRow label="Correo" value={license.email} />}
              <InfoRow label="Plan" value={plan?.nombre ?? 'Sin datos'} />
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
              ¿Más de 100 empresas o más usuarios? Armamos un plan a tu medida.{' '}
              <a href="mailto:soporte@todoconta.com" className="font-semibold text-primary hover:underline">
                Escríbenos
              </a>
              .
            </span>
          </div>
        </aside>
      </div>

      {/* Confirmar cambio de plan (legado o v3 con prorrateo) */}
      <Dialog open={confirmar !== null} onOpenChange={(o) => !o && setConfirmar(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {confirmar?.motivo === 'legado'
                ? '¿Dejar tu precio asegurado?'
                : `¿Cambiar a ${confirmar?.plan.nombre ?? ''} ${intervalo}?`}
            </DialogTitle>
            <DialogDescription>
              {confirmar?.motivo === 'legado'
                ? `Al cambiar a ${confirmar.plan.nombre} dejas tu precio actual y tus empresas ilimitadas. Si después quieres regresar, ya no se puede.`
                : 'Stripe ajusta el cobro con prorrateo: pagas o se te abona la diferencia del periodo.'}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setConfirmar(null)} disabled={busyPago}>
              {confirmar?.motivo === 'legado' ? 'Conservar mi plan' : 'Cancelar'}
            </Button>
            <Button
              onClick={async () => {
                if (!confirmar) return;
                await contratar(confirmar.plan);
                setConfirmar(null);
              }}
              disabled={busyPago}
            >
              {busyPago && <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />}
              Sí, cambiar a {confirmar?.plan.nombre ?? ''}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancelación */}
      <Dialog open={cancelOpen} onOpenChange={setCancelOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>¿Cancelar tu suscripción?</DialogTitle>
            <DialogDescription>
              No se renovará al final del periodo. Conservas el acceso hasta
              {vence ? ` el ${vence}` : ' el fin del periodo'}.
              {situacion === 'legado' && ' Si regresas después, entras con los precios nuevos.'}
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

/* ─────────────────────────── Piezas ─────────────────────────── */

function SelectorIntervalo({
  valor,
  onCambio,
}: {
  valor: IntervaloPlan;
  onCambio: (i: IntervaloPlan) => void;
}) {
  const opciones: { valor: IntervaloPlan; etiqueta: string }[] = [
    { valor: 'anual', etiqueta: 'Anual' },
    { valor: 'mensual', etiqueta: 'Mensual' },
  ];
  return (
    <div role="radiogroup" aria-label="Forma de cobro" className="inline-flex rounded-lg border bg-secondary/60 p-0.5">
      {opciones.map((o) => (
        <button
          key={o.valor}
          type="button"
          role="radio"
          aria-checked={valor === o.valor}
          onClick={() => onCambio(o.valor)}
          className={cn(
            'rounded-md px-3.5 py-1.5 text-[13px] font-semibold transition-colors',
            valor === o.valor
              ? 'bg-card text-foreground shadow-sm'
              : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {o.etiqueta}
        </button>
      ))}
    </div>
  );
}

function TarjetaPlan({
  plan,
  intervalo,
  seleccionado,
  etiqueta,
  cta,
  deshabilitado,
  onElegir,
  nota,
}: {
  plan: PlanV3Catalogo;
  intervalo: IntervaloPlan;
  seleccionado: boolean;
  etiqueta?: string;
  cta: string;
  deshabilitado: boolean;
  onElegir: () => void;
  nota?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col gap-4 rounded-xl border bg-card p-5 text-card-foreground shadow-sm',
        seleccionado && 'border-primary ring-1 ring-primary',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-base font-extrabold tracking-tight">{plan.nombre}</h3>
        {etiqueta && <EstadoBadge tone="muted">{etiqueta}</EstadoBadge>}
      </div>
      <p className="text-[13px] leading-snug text-muted-foreground">{plan.lema}</p>
      <div className="flex items-baseline gap-1.5 whitespace-nowrap">
        <span className="text-[28px] leading-none font-extrabold tracking-tight tabular-nums">
          {formatPesosEnteros(precioDe(plan, intervalo))}
        </span>
        <span className="text-[13px] text-muted-foreground">{sufijoIntervalo(intervalo)}</span>
      </div>
      <ul className="flex flex-col gap-2 text-[13px]">
        <li className="flex items-center gap-2 font-semibold">
          <Icon icon="ph:buildings-light" className="size-4 shrink-0 text-foreground/70" />
          Hasta {empresasTexto(plan.empresas)} activas
        </li>
        <li className="flex items-center gap-2 font-semibold">
          <Icon icon="ph:users-light" className="size-4 shrink-0 text-foreground/70" />
          {plan.usuarios === 1 ? '1 usuario' : `${plan.usuarios} usuarios`}
        </li>
        {plan.incluye.map((f) => (
          <li
            key={f.texto}
            className={cn('flex items-start gap-2', f.si ? 'text-foreground/90' : 'text-muted-foreground/70')}
          >
            <Icon
              icon={f.si ? 'ph:check-light' : 'ph:minus-light'}
              className={cn('mt-0.5 size-4 shrink-0', f.si ? 'text-success' : 'text-muted-foreground/60')}
            />
            <span>{f.texto}</span>
          </li>
        ))}
      </ul>
      <div className="mt-auto flex flex-col gap-2">
        <Button
          variant={seleccionado ? 'default' : 'outline'}
          onClick={onElegir}
          disabled={deshabilitado}
        >
          {cta}
        </Button>
        {nota && <p className="text-xs leading-relaxed text-muted-foreground">{nota}</p>}
      </div>
    </div>
  );
}

function DatosTransferencia({
  monto,
  transfer,
  cargando,
  onCopiar,
}: {
  monto: number;
  transfer: TransferIntentResponse | null;
  cargando: boolean;
  onCopiar: (texto: string, etiqueta: string) => void;
}) {
  return (
    <div className="rounded-xl border bg-secondary/50 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-bold">
        <Icon icon="ph:bank-light" className="size-4 text-primary" />
        Transfiere {formatPesosEnteros(monto)} a esta cuenta
      </div>
      {cargando && !transfer ? (
        <div className="flex items-center gap-2 py-1.5 text-sm text-muted-foreground">
          <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
          Obteniendo datos de la cuenta…
        </div>
      ) : transfer && transfer.banco.clabe ? (
        <>
          <div className="flex flex-col">
            {transfer.banco.beneficiario && (
              <CopyRow etiqueta="Beneficiario" valor={transfer.banco.beneficiario} onCopy={onCopiar} />
            )}
            {transfer.banco.banco && <CopyRow etiqueta="Banco" valor={transfer.banco.banco} onCopy={onCopiar} />}
            <CopyRow etiqueta="CLABE" valor={transfer.banco.clabe} mono onCopy={onCopiar} />
            {transfer.banco.referencia && (
              <CopyRow etiqueta="Referencia" valor={transfer.banco.referencia} mono onCopy={onCopiar} />
            )}
          </div>
          <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
            <Icon icon="ph:info-light" className="mt-0.5 size-3.5 shrink-0" />
            <span>
              {transfer.message ?? 'La activación por transferencia puede tardar unas horas.'} Envíanos
              tu comprobante para activar tu cuenta.
            </span>
          </p>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">
          Los datos bancarios aún no están configurados. Escríbenos a soporte.
        </p>
      )}
    </div>
  );
}

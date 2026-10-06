'use client';

import { useRouter } from 'next/navigation';

import { useAuth, usePlanesV3, usePlanLicencia, type PlanLicencia } from '@/providers/auth-provider';
import type { LicenseStatus } from '@/lib/api-client';
import { Badge } from '@/components/ui/badge';
import { Icon } from '@/components/ui/icon';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { FounderBadge } from '@/components/auth/founder-badge';
import { formatDate } from '@/lib/formatting';

/**
 * Badge de plan del titlebar. Selecciona la variante según `license.plan`:
 *
 * - `founder`  → `<FounderBadge />` (corona ámbar, acceso de por vida).
 * - `premium`  → badge púrpura con días restantes; tooltip tranquilizador (o
 *                aviso de cancelación si `cancel_at_period_end`).
 * - `trial`    → badge azul con días restantes; tooltip sobre el periodo de prueba.
 * - `free`     → badge "Gratis" con CTA a suscribirse.
 *
 * Premium/trial/free son clickeables y llevan a `/suscripcion`. Viven dentro del
 * contenedor `no-drag` del titlebar.
 *
 * Con el interruptor de planes v3 encendido y datos del plan, el badge usa los
 * nombres nuevos (`PlanBadgeV3`): Esencial, Pro, Completo, Prueba, Gratis y los
 * del legado (Anual, Anual con IA, Fundador...).
 */
export function PlanBadge() {
  const { license } = useAuth();
  const router = useRouter();
  const planesV3 = usePlanesV3();
  const planLicencia = usePlanLicencia();

  if (!license?.authenticated) return null;

  if (planesV3 && planLicencia) {
    return (
      <PlanBadgeV3
        plan={planLicencia}
        license={license}
        onClick={() => router.push('/suscripcion')}
      />
    );
  }

  // Founder tiene prioridad y su propio badge celebratorio.
  if (license.plan === 'founder' || license.is_founder) {
    return <FounderBadge />;
  }

  const dias = license.days_remaining ?? null;
  const diasLabel = dias === null ? '' : dias === 1 ? '1 día' : `${dias} días`;
  const ir = () => router.push('/suscripcion');

  if (license.plan === 'premium') {
    const cancela = license.subscription_cancel_at_period_end;
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button" onClick={ir} className="appearance-none bg-transparent p-0">
            <Badge
              variant="chip"
              className="gap-1"
              tabIndex={0}
            >
              <Icon
                icon="ph:crown-simple-fill"
                className="size-3"
              />
              {diasLabel ? `Premium, ${diasLabel}` : 'Premium'}
            </Badge>
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="end" className="w-64 rounded-xl p-3.5 text-left">
          <span className="flex items-center gap-1.5 text-[13.5px] font-extrabold tracking-tight">
            <Icon icon="ph:crown-simple-fill" className="size-3.5" />
            Suscripción activa
          </span>
          <span className="mt-1.5 block text-xs leading-relaxed text-background/80">
            {cancela
              ? `Tu suscripción termina el ${formatDate(license.expires_at ?? '')} y no se renovará. Puedes reactivarla cuando quieras.`
              : 'Sigue trabajando tranquilo: tu suscripción sigue vigente.'}
          </span>
        </TooltipContent>
      </Tooltip>
    );
  }

  if (license.plan === 'trial') {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <button type="button" onClick={ir} className="appearance-none bg-transparent p-0">
            <Badge
              variant="chip"
              className="gap-1"
              tabIndex={0}
            >
              <Icon
                icon="ph:hourglass-medium-light"
                className="size-3"
              />
              {diasLabel ? `Prueba, ${diasLabel}` : 'Prueba'}
            </Badge>
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom" align="end" className="w-64 rounded-xl p-3.5 text-left">
          <span className="block text-[13.5px] font-extrabold tracking-tight">
            Periodo de prueba
          </span>
          <span className="mt-1.5 block text-xs leading-relaxed text-background/80">
            Puedes usar la app con todas sus funciones. Más adelante algunas
            podrían requerir suscripción. Toca para ver tu plan.
          </span>
        </TooltipContent>
      </Tooltip>
    );
  }

  // free
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" onClick={ir} className="appearance-none bg-transparent p-0">
          <Badge variant="chip" className="gap-1" tabIndex={0}>
            Gratis
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end" className="w-64 rounded-xl p-3.5 text-left">
        <span className="block text-[13.5px] font-extrabold tracking-tight">
          Plan gratuito
        </span>
        <span className="mt-1.5 block text-xs leading-relaxed text-background/80">
          La app sigue funcional. Suscríbete para apoyar el proyecto y asegurar
          el mejor precio. Toca para ver opciones.
        </span>
      </TooltipContent>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------
// Planes v3
// ---------------------------------------------------------------------------

const PLANES_V3_PAGO: readonly string[] = ['esencial', 'pro', 'completo', 'medida'];

function PlanBadgeV3({
  plan,
  license,
  onClick,
}: {
  plan: PlanLicencia;
  license: LicenseStatus;
  onClick: () => void;
}) {
  if (plan.codigo === 'fundador') return <FounderBadge />;

  const dias = license.days_remaining ?? null;
  const cancela = license.subscription_cancel_at_period_end === true;
  const vence = license.expires_at ? formatDate(license.expires_at) : null;

  let etiqueta = plan.nombre;
  let icono: string | null = 'ph:crown-simple-fill';
  let titulo = `Plan ${plan.nombre}`;
  let texto: string;

  if (plan.codigo === 'trial') {
    etiqueta = dias === null ? 'Prueba' : `Prueba: ${dias === 1 ? '1 día' : `${dias} días`}`;
    icono = 'ph:hourglass-medium-light';
    titulo = 'Periodo de prueba';
    texto =
      'Tienes lo del plan Pro mientras dura la prueba: hasta 50 empresas, exportaciones y la conexión con tu IA (MCP). Toca para ver los planes.';
  } else if (plan.codigo === 'gratis') {
    icono = null;
    titulo = 'Plan Gratis';
    texto =
      'La app sigue funcionando con lo básico: hasta 5 empresas y 10 descargas al SAT al mes. Toca para ver los planes.';
  } else if (PLANES_V3_PAGO.includes(plan.codigo)) {
    texto = cancela
      ? `Tu suscripción termina${vence ? ` el ${vence}` : ''} y no se renovará. Puedes reactivarla cuando quieras.`
      : `Tu plan está activo${vence ? ` hasta el ${vence}` : ''}. Toca para ver tu suscripción.`;
  } else {
    // Legado: Anual, Anual con IA, planes web viejos y suscripciones manuales.
    titulo = `${plan.nombre}: tu precio asegurado`;
    texto = cancela
      ? `Tu suscripción termina${vence ? ` el ${vence}` : ''} y no se renovará. Si regresas después, entras con los precios nuevos.`
      : 'Conservas tu precio y tus condiciones mientras sigas suscrito.';
  }

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" onClick={onClick} className="appearance-none bg-transparent p-0">
          {/* Señal: el plan es un chip neutro (píldora blanca con regla). */}
          <Badge variant="chip" className="gap-1" tabIndex={0}>
            {icono && <Icon icon={icono} className="size-3" />}
            {etiqueta}
          </Badge>
        </button>
      </TooltipTrigger>
      <TooltipContent side="bottom" align="end" className="w-64 rounded-xl p-3.5 text-left">
        <span className="block text-[13.5px] font-extrabold tracking-tight">{titulo}</span>
        <span className="mt-1.5 block text-xs leading-relaxed text-background/80">{texto}</span>
      </TooltipContent>
    </Tooltip>
  );
}

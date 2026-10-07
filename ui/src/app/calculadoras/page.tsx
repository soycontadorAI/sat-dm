'use client';

import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { Icon } from '@/components/ui/icon';

interface CalculadoraCard {
  href: string;
  titulo: string;
  descripcion: string;
  icono: string;
}

const CALCULADORAS: CalculadoraCard[] = [
  {
    href: '/calculadoras/isr',
    titulo: 'ISR de sueldos',
    descripcion: 'Calcula la retención de ISR del período con subsidio para el empleo.',
    icono: 'ph:percent-light',
  },
  {
    href: '/calculadoras/aguinaldo',
    titulo: 'Aguinaldo',
    descripcion: 'Aguinaldo proporcional a los días trabajados, con el ISR de la parte gravada.',
    icono: 'ph:gift-light',
  },
  {
    href: '/calculadoras/sbc',
    titulo: 'Salario Base de Cotización',
    descripcion: 'Factor de integración y SBC diario y mensual para dar de alta ante el IMSS.',
    icono: 'ph:heartbeat-light',
  },
  {
    href: '/calculadoras/finiquito',
    titulo: 'Finiquito',
    descripcion: 'Partes proporcionales y neto a pagar al terminar la relación laboral.',
    icono: 'ph:receipt-light',
  },
  {
    href: '/calculadoras/liquidacion',
    titulo: 'Liquidación',
    descripcion: 'Finiquito más indemnizaciones según el tipo de terminación.',
    icono: 'ph:scales-light',
  },
  {
    href: '/calculadoras/carga-patronal',
    titulo: 'Carga patronal',
    descripcion: 'Costo real de un empleado: cuotas IMSS, Infonavit e impuesto estatal sobre nómina.',
    icono: 'ph:factory-light',
  },
  {
    href: '/calculadoras/ptu',
    titulo: 'PTU',
    descripcion: 'Reparto de utilidades por trabajador, comparando el ISR del Art. 96 y el Art. 174.',
    icono: 'ph:users-three-light',
  },
];

export default function CalculadorasPage() {
  return (
    <div className="space-y-6">
      <PageHeading
        title="Calculadoras"
        description="Herramientas de nómina y previsión social. Cada cálculo se guarda automáticamente para la empresa activa."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {CALCULADORAS.map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="group flex h-full flex-col gap-3 rounded-xl border bg-card p-5 shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary hover:shadow-md"
          >
            <div className="flex items-center gap-3">
              <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-accent text-primary">
                <Icon icon={card.icono} className="size-5" />
              </span>
              <span className="text-[15px] font-bold tracking-tight">{card.titulo}</span>
            </div>
            <p className="flex-1 text-[13px] leading-normal text-muted-foreground">
              {card.descripcion}
            </p>
            <span className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-primary">
              Abrir
            </span>
          </Link>
        ))}
      </div>
    </div>
  );
}

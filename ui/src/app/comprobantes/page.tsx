'use client';

import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';

interface Procesador {
  href: string;
  title: string;
  description: string;
  icon: string;
  disponible: boolean;
}

// Tres procesadores espejo de todoconta-apps. Por ahora solo CFDI está activo;
// Pagos y Nómina se activan en PRs siguientes según el roadmap.
const PROCESADORES: Procesador[] = [
  {
    href: '/comprobantes/cfdi',
    title: 'Procesador de CFDI',
    description:
      'Procesa CFDIs de ingreso, egreso, traslado y pagos. Filtra, agrupa y exporta a Excel o CSV.',
    icon: 'ph:files-light',
    disponible: true,
  },
  {
    href: '/comprobantes/pagos',
    title: 'Procesador de Pagos',
    description:
      'Relaciona facturas PPD con sus complementos de pago. Detecta pagos huérfanos y complementos extemporáneos.',
    icon: 'ph:link-light',
    disponible: true,
  },
  {
    href: '/comprobantes/nomina',
    title: 'Procesador de Nómina',
    description:
      'CFDIs de Nómina 1.2 con desglose por empleado, conciliación IMSS y reportes de ISR retenido.',
    icon: 'ph:users-three-light',
    disponible: true,
  },
];

export default function ComprobantesPage() {
  return (
    <div className="space-y-6">
      <PageHeading
        title="Comprobantes"
        description="Procesa los XMLs descargados para obtener tablas, validaciones, reportes y exportaciones."
      />

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {PROCESADORES.map((p) => (
          <Card key={p.href} className={cn(!p.disponible && 'opacity-60')}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Icon icon={p.icon} className="size-5" />
                {p.title}
                {!p.disponible && (
                  <Badge variant="secondary" className="ml-auto text-[10px]">
                    Próximamente
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>{p.description}</CardDescription>
            </CardHeader>
            <CardContent>
              {p.disponible ? (
                <Button variant="outline" size="sm" asChild>
                  <Link href={p.href}>
                    Abrir
                  </Link>
                </Button>
              ) : (
                <Button variant="outline" size="sm" disabled>
                  No disponible
                </Button>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

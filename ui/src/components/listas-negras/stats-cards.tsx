'use client';

import { Card } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';
import type { ProcesadorListasNegrasStats } from '@/lib/types';

interface Props {
  stats: ProcesadorListasNegrasStats | null;
  loading?: boolean;
}

interface CardData {
  label: string;
  value: number;
  icon: string;
  tone: 'rojo' | 'amber' | 'gris' | 'verde';
  hint?: string;
}

const TONOS = {
  rojo: 'text-red-700 dark:text-red-300',
  amber: 'text-amber-700 dark:text-amber-300',
  gris: 'text-muted-foreground',
  verde: 'text-green-700 dark:text-green-300',
} as const;

export function StatsCards({ stats, loading }: Props) {
  const cards: CardData[] = [
    {
      label: 'EFOS (emisores únicos)',
      value: stats?.efos_emisores_unicos ?? 0,
      icon: 'ph:warning-light',
      tone: 'rojo',
      hint: 'RFCs en lista 69-B con situación Definitivo o Presunto',
    },
    {
      label: 'EDOS (mis CFDIs)',
      value: stats?.cfdis_edos ?? 0,
      icon: 'ph:files-light',
      tone: 'rojo',
      hint: 'CFDIs cuyo emisor es EFOS: riesgo fiscal directo',
    },
    {
      label: 'Emisor aclarado',
      value: stats?.cfdis_emisor_aclarado ?? 0,
      icon: 'ph:warning-circle-light',
      tone: 'amber',
      hint: 'En 69-B con desvirtuación o sentencia favorable (antecedente)',
    },
    {
      label: 'Emisor en lista 69',
      value: stats?.cfdis_emisor_69 ?? 0,
      icon: 'ph:warning-circle-light',
      tone: 'amber',
      hint: 'Créditos firmes, no localizado, exigibles, etc.',
    },
    {
      label: 'Limpios',
      value: stats?.cfdis_limpios ?? 0,
      icon: 'ph:shield-check-light',
      tone: 'verde',
    },
    {
      label: 'Sin validar',
      value: stats?.cfdis_sin_validar ?? 0,
      icon: 'ph:circle-light',
      tone: 'gris',
      hint: 'No han pasado por consulta. Usa "Validar" arriba',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
      {cards.map((c) => (
        <Card key={c.label} className="p-4" title={c.hint}>
          <div className="flex items-start justify-between gap-2">
            <span className="text-xs text-muted-foreground">{c.label}</span>
            <Icon icon={c.icon} className={cn('size-4 shrink-0', TONOS[c.tone])} />
          </div>
          <div className={cn('mt-2 text-2xl font-semibold tabular-nums', TONOS[c.tone])}>
            {loading ? '–' : c.value.toLocaleString('es-MX')}
          </div>
        </Card>
      ))}
    </div>
  );
}

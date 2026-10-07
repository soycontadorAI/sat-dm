'use client';

import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { Icon } from '@/components/ui/icon';
import { cn } from '@/lib/utils';

export type StatusTone = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'ai';

const statusBadgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded-full border font-medium transition-colors whitespace-nowrap',
  {
    variants: {
      tone: {
        // Estados fiscales de Señal: fondo *-bg y la palabra en su color.
        success: 'border-transparent bg-success-bg text-success',
        warning: 'border-transparent bg-warning-bg text-warning',
        error: 'border-transparent bg-destructive-bg text-destructive',
        info: 'border-border bg-card text-foreground',
        neutral: 'border-transparent bg-muted text-muted-foreground',
        // Lo automático: texto cian (auto-text), sin fondo de color.
        ai: 'border-transparent bg-transparent px-0 text-auto-text',
      },
      size: {
        sm: 'px-2 py-0.5 text-[10px]',
        default: 'px-2.5 py-0.5 text-xs',
      },
    },
    defaultVariants: {
      tone: 'neutral',
      size: 'default',
    },
  },
);

const iconSizeMap = {
  sm: 'size-2.5',
  default: 'size-3',
} as const;

export interface StatusBadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof statusBadgeVariants> {
  icon?: string;
  pulse?: boolean;
}

export function StatusBadge({
  className,
  tone,
  size,
  icon,
  pulse = false,
  children,
  ...props
}: StatusBadgeProps) {
  const iconClass = iconSizeMap[size ?? 'default'];

  return (
    <span className={cn(statusBadgeVariants({ tone, size }), className)} {...props}>
      {icon && <Icon icon={icon} className={cn(iconClass, pulse && 'animate-spin')} />}
      {children}
    </span>
  );
}

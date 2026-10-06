'use client';

import { useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { Badge } from '@/components/ui/badge';
import { Icon } from '@/components/ui/icon';
import { FielUploadDialog } from '@/components/fiel/fiel-upload-dialog';
import { cn } from '@/lib/utils';
import { semaforoVencimiento, type EstadoVencimiento } from '@/lib/vencimiento';

// Color del badge del RFC según el semáforo de vencimiento.
const ESTILO_RFC: Record<EstadoVencimiento, string> = {
  verde: 'bg-green-600 hover:bg-green-700',
  amarillo: 'bg-amber-500 hover:bg-amber-600',
  rojo: 'bg-red-600 hover:bg-red-700',
};

const ESTILO_TEXTO: Record<EstadoVencimiento, string> = {
  verde: 'text-green-700 dark:text-green-400',
  amarillo: 'text-amber-700 dark:text-amber-400',
  rojo: 'text-red-700 dark:text-red-400',
};

export function FielStatus() {
  const { fielStatus } = useServer();
  const [dialogOpen, setDialogOpen] = useState(false);

  const sem = fielStatus.loaded ? semaforoVencimiento(fielStatus.vencimiento) : null;

  return (
    <>
      <button
        type="button"
        onClick={() => setDialogOpen(true)}
        className="w-full space-y-1 text-left"
      >
        {fielStatus.loaded ? (
          <Badge
            variant="default"
            className={cn(
              'w-full cursor-pointer justify-start gap-2 px-3 py-1.5',
              sem ? ESTILO_RFC[sem.estado] : 'bg-green-600 hover:bg-green-700',
            )}
          >
            <Icon icon="ph:key-light" className="size-3.5" />
            <span className="truncate">{fielStatus.rfc}</span>
          </Badge>
        ) : (
          <Badge
            variant="secondary"
            className="w-full cursor-pointer justify-start gap-2 px-3 py-1.5"
          >
            <Icon icon="ph:key-light" className="size-3.5" />
            <span>Sin e.firma</span>
          </Badge>
        )}
        {sem && (
          <span className={cn('block px-1 text-[11px] font-medium', ESTILO_TEXTO[sem.estado])}>
            e.firma: {sem.label.charAt(0).toLowerCase() + sem.label.slice(1)}
          </span>
        )}
      </button>

      <FielUploadDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </>
  );
}

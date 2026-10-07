'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
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
import { ApiError } from '@/lib/api-client';
import { mensajeDeError } from '@/lib/errores';
import type { Empresa } from '@/lib/types';

// ---------------------------------------------------------------------------
// "Usar en la versión web": sube las credenciales de la empresa al espacio en
// línea del usuario (opt-in, empresa por empresa, acción explícita).
//
// El copy es la pieza clave: las credenciales viajan cifradas DIRECTO al
// espacio privado del usuario (su agente personal en la nube) — nunca a bases
// de datos compartidas ni terceros. Es la misma alta que haría capturándolas
// a mano en la web, solo que sin recapturar.
// ---------------------------------------------------------------------------

function etiquetaCredenciales(metodos: string[]): string {
  const partes = [];
  if (metodos.includes('fiel')) partes.push('tu e.firma (.cer, .key) y su contraseña');
  if (metodos.includes('ciec')) partes.push('tu Contraseña del SAT');
  return partes.join(' y ');
}

export function SubirEspacioDialog({
  empresa,
  open,
  onOpenChange,
  onDone,
}: {
  empresa: Empresa;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Llamado tras subir con éxito (p. ej. para refrescar la lista). */
  onDone?: () => void;
}) {
  const { apiClient } = useServer();
  const [subiendo, setSubiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const credenciales = etiquetaCredenciales(empresa.metodos);

  async function subir() {
    setError(null);
    setSubiendo(true);
    try {
      const r = await apiClient.subirAlEspacio(empresa.rfc, empresa.metodos);
      toast.success(
        r.subidos.length > 1
          ? 'Listo: tu e.firma y tu Contraseña del SAT ya están en tu espacio en línea.'
          : r.subidos[0] === 'fiel'
            ? 'Listo: tu e.firma ya está en tu espacio en línea.'
            : 'Listo: tu Contraseña del SAT ya está en tu espacio en línea.',
      );
      onOpenChange(false);
      onDone?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : mensajeDeError(e));
    } finally {
      setSubiendo(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !subiendo && onOpenChange(v)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Icon icon="ph:cloud-arrow-up-light" className="size-5" />
            Usar esta empresa en la versión web
          </DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-3 pt-1 text-[13px] leading-relaxed">
              <p>
                Para operar con <span className="font-semibold text-foreground">{empresa.nombre}</span>{' '}
                desde cualquier navegador, {credenciales} se {empresa.metodos.length > 1 ? 'subirán' : 'subirá'}{' '}
                a tu espacio en línea.
              </p>
              <p className="rounded-md border border-border bg-secondary/50 px-3 py-2">
                <Icon icon="ph:shield-check-light" className="mr-1 inline size-3.5 align-[-2px]" />
                Viajan <span className="font-semibold text-foreground">cifradas y directo a tu espacio
                privado</span>, el mismo lugar seguro donde quedan cuando las capturas en la
                versión web. Nadie más puede usarlas: no pasan por bases de datos compartidas
                ni por terceros, y puedes quitarlas de la web cuando quieras.
              </p>
            </div>
          </DialogDescription>
        </DialogHeader>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-[13px] leading-snug text-destructive"
          >
            {error}
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={subiendo}>
            Ahora no
          </Button>
          <Button onClick={subir} disabled={subiendo}>
            {subiendo ? (
              <>
                <Icon icon="ph:circle-notch-light" className="mr-1.5 size-4 animate-spin" />
                Subiendo de forma segura…
              </>
            ) : (
              <>
                <Icon icon="ph:cloud-arrow-up-light" className="mr-1.5 size-4" />
                Subir de forma segura
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

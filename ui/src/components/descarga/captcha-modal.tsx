'use client';

import { useEffect, useState } from 'react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { CaptchaState } from '@/hooks/use-ciec-job';

interface CaptchaModalProps {
  captcha: CaptchaState | null;
  onResolver: (texto: string | null) => void;
  /** Captchas que distinguen mayúsculas y minúsculas (la recuperación pública
   * de certificados del SAT): se mandan tal cual, sin pasar a mayúsculas. */
  respetarMayusculas?: boolean;
}

/**
 * Modal del captcha del SAT: muestra la imagen que el agente capturó (headless) y
 * captura el texto. Enviar reanuda el scraping; cerrar/Cancelar lo aborta (null).
 */
export function CaptchaModal({ captcha, onResolver, respetarMayusculas = false }: CaptchaModalProps) {
  const [texto, setTexto] = useState('');

  // Limpiar el input cuando llega un captcha nuevo (p. ej. reintento).
  useEffect(() => {
    setTexto('');
  }, [captcha?.imagen]);

  return (
    <Dialog open={captcha !== null} onOpenChange={(o) => { if (!o) onResolver(null); }}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Captcha del SAT</DialogTitle>
          <DialogDescription>
            Intento {captcha?.intento} de {captcha?.max}. Teclea las letras de la imagen
            {respetarMayusculas ? ' tal como aparecen (distingue mayúsculas y minúsculas).' : '.'}
          </DialogDescription>
        </DialogHeader>

        {captcha && (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              const v = respetarMayusculas ? texto.trim() : texto.trim().toUpperCase();
              if (v) onResolver(v);
            }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={captcha.imagen}
              alt="Captcha"
              className="mx-auto h-20 rounded border bg-white object-contain"
            />
            <Input
              autoFocus
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder={respetarMayusculas ? 'Captcha' : 'CAPTCHA'}
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              className={cn(
                'text-center font-mono text-lg tracking-widest',
                !respetarMayusculas && 'uppercase',
              )}
            />
            <div className="flex gap-2">
              <Button
                type="button"
                variant="outline"
                className="flex-1"
                onClick={() => onResolver(null)}
              >
                Cancelar
              </Button>
              <Button type="submit" className="flex-1" disabled={!texto.trim()}>
                Enviar
              </Button>
            </div>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}

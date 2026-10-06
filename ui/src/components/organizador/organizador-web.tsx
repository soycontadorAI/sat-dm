'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';

/** Página pública que detecta el sistema y ofrece la descarga (con UTMs). */
const URL_DESCARGAR =
  'https://todoconta.com/descargar?utm_source=app-web&utm_medium=organizador&utm_campaign=app-escritorio';

type Sistema = 'macOS' | 'Windows' | null;

function sistemaDelNavegador(): Sistema {
  const ua = navigator.userAgent || '';
  if (/Windows/i.test(ua)) return 'Windows';
  if (/Macintosh|Mac OS X/i.test(ua) && !/iPhone|iPad/i.test(ua)) return 'macOS';
  return null;
}

/**
 * El Organizador en la versión web (navegación por espacios): trabaja sobre
 * las carpetas de tu computadora, así que en la web se explica y se ofrece la
 * app de escritorio o la descarga en ZIP desde el Historial (principio
 * desktop-first: lo que no funciona igual en la web se explica). Nunca dice
 * ni insinúa que la web sea insegura.
 */
export function OrganizadorWeb() {
  const router = useRouter();
  const [sistema, setSistema] = useState<Sistema>(null);

  useEffect(() => {
    setSistema(sistemaDelNavegador());
  }, []);

  return (
    <Card className="max-w-2xl">
      <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-start">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-[10px] border border-border bg-background text-foreground">
          <Icon icon="ph:desktop-light" className="size-5.5" />
        </span>
        <div className="min-w-0 space-y-3">
          <h2 className="text-lg font-bold tracking-[-0.015em]">
            El Organizador vive en la app de escritorio
          </h2>
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            El Organizador trabaja sobre las carpetas de tu computadora. Por eso vive en la app de
            escritorio: ordena, renombra y quita duplicados directo en tu disco. En la web, tus XML
            los bajas en ZIP.
          </p>
          <div className="flex flex-wrap gap-2 pt-1">
            <Button onClick={() => window.open(URL_DESCARGAR, '_blank', 'noopener')}>
              <Icon icon="ph:download-simple-light" className="size-4" />
              {sistema ? `Descargar para ${sistema}` : 'Descargar la app de escritorio'}
            </Button>
            <Button variant="outline" onClick={() => router.push('/historial')}>
              <Icon icon="ph:file-zip-light" className="size-4" />
              Bajar mis XML en ZIP
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

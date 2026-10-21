'use client';

import Link from 'next/link';
import { useState } from 'react';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { useServer } from '@/providers/server-provider';
import { abrirODescargar, iconoAbrir, tituloAbrir } from '@/lib/descargas';
import { mensajeDeError } from '@/lib/errores';
import {
  etiquetaDireccion,
  hayServidos,
  textoErrorRango,
  textoHuecos,
  textoServidos,
  textoSinXml,
  TIPOS_ERROR,
  tituloErrores,
  tituloServido,
} from '@/lib/servir-base';
import type { ResumenServido } from '@/lib/types';

/**
 * Avisos de la solicitud "desde la base": lo consolidado que se sirvió sin ir
 * al SAT (un bloque por dirección), los huecos que sí se pidieron y los rangos
 * que fallaron (un aviso por tipo: los que no se pudieron solicitar al SAT y los
 * que no se pudieron guardar de la base).
 */
export function ServidoBaseAviso({ resumenes }: { resumenes: ResumenServido[] }) {
  const errores = resumenes.flatMap((r) =>
    r.errores.map((e) => ({ direccion: r.direccion, tipo: e.tipo, texto: textoErrorRango(e) })),
  );

  return (
    <>
      {resumenes.filter(hayServidos).map((r) => (
        <BloqueServido key={r.direccion} resumen={r} total={resumenes.length} />
      ))}
      {TIPOS_ERROR.map((tipo) => {
        const delTipo = errores.filter((e) => (e.tipo ?? 'sat') === tipo);
        if (delTipo.length === 0) return null;
        return (
          <Alert key={tipo} variant="warning">
            <Icon icon="ph:warning-light" className="size-4" />
            <AlertTitle>{tituloErrores(tipo, delTipo.length)}</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {delTipo.map((e, i) => (
                  <li key={`${e.direccion}-${i}`}>
                    {resumenes.length > 1 ? `${etiquetaDireccion(e.direccion)}, ${e.texto}` : e.texto}
                  </li>
                ))}
              </ul>
              {tipo === 'cupo' && (
                <Link href="/suscripcion" className="mt-2 inline-block font-medium underline">
                  Ver planes
                </Link>
              )}
            </AlertDescription>
          </Alert>
        );
      })}
    </>
  );
}

function BloqueServido({ resumen, total }: { resumen: ResumenServido; total: number }) {
  const { apiClient } = useServer();
  const [errorAbrir, setErrorAbrir] = useState<string | null>(null);
  const { servidos, solicitudes } = resumen;
  const huecos = textoHuecos(solicitudes);
  const sinXml = textoSinXml(servidos.sin_xml);

  const abrir = async () => {
    if (!servidos.ruta) return;
    setErrorAbrir(null);
    try {
      await abrirODescargar(apiClient, servidos.ruta, 'carpeta');
    } catch (e) {
      setErrorAbrir(mensajeDeError(e));
    }
  };

  return (
    <Alert>
      <Icon icon="ph:database-light" className="size-4" />
      <AlertTitle>{tituloServido(resumen.direccion, total)}</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>{textoServidos(servidos.dias, servidos.cfdis)}</p>
        {huecos && <p>{huecos}</p>}
        {sinXml && <p>{sinXml}</p>}
        {servidos.ruta && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={abrir} title={tituloAbrir('carpeta')}>
              <Icon icon={iconoAbrir('carpeta')} className="size-4" />
              Abrir carpeta
            </Button>
            {errorAbrir && <span className="text-xs text-destructive">{errorAbrir}</span>}
          </div>
        )}
      </AlertDescription>
    </Alert>
  );
}

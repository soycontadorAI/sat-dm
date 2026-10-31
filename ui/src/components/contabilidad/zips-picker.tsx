'use client';

import { useRef, useState, type DragEvent } from 'react';

import { useServer } from '@/providers/server-provider';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { mensajeDeError } from '@/lib/errores';
import { cn } from '@/lib/utils';
import type { CeFicha } from '@/lib/types';

interface ZipsPickerProps {
  /** Recibe la revisión previa de los ZIP (con las rutas DEL AGENTE). */
  onFichas: (fichas: CeFicha[]) => void;
  disabled?: boolean;
  /** Ya hay archivos elegidos: el botón pasa a "Cambiar archivos". */
  hayArchivos?: boolean;
}

/** Selector nativo de la app de escritorio (preload `elegirZips`); ausente en la web y en builds viejos. */
function selectorNativo(): (() => Promise<string[]>) | null {
  if (typeof window === 'undefined') return null;
  const d = (window as unknown as {
    satDesktop?: { elegirZips?: () => Promise<string[]> };
  }).satDesktop;
  return d?.elegirZips ?? null;
}

/**
 * Elegir los ZIP que generó el software contable (Contalink, CONTPAQi…).
 *
 * - Desktop: diálogo nativo del SO → rutas → `/ce/inventario`.
 * - Web (y arrastrar y soltar en ambos modos): el navegador no conoce rutas
 *   locales, así que los ZIP se suben al agente (`/ce/subir`), que los revisa
 *   igual. Los ZIP de contabilidad pesan KB: la subida no es un costo.
 */
export function ZipsPicker({ onFichas, disabled, hayArchivos }: ZipsPickerProps) {
  const { apiClient } = useServer();
  const inputRef = useRef<HTMLInputElement>(null);
  const [cargando, setCargando] = useState(false);
  const [arrastrando, setArrastrando] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bloqueado = disabled || cargando;

  async function revisar(tarea: () => Promise<{ archivos: CeFicha[] }>) {
    setCargando(true);
    setError(null);
    try {
      const r = await tarea();
      onFichas(r.archivos);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setCargando(false);
    }
  }

  async function elegir() {
    const nativo = selectorNativo();
    if (!nativo) {
      inputRef.current?.click();
      return;
    }
    const rutas = await nativo();
    if (rutas.length > 0) await revisar(() => apiClient.ceInventario(rutas));
  }

  function subir(files: File[]) {
    const zips = files.filter((f) => f.name.toLowerCase().endsWith('.zip'));
    if (zips.length === 0) {
      setError('Solo se aceptan archivos .zip (los que genera tu software contable).');
      return;
    }
    void revisar(() => apiClient.ceSubir(zips));
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setArrastrando(false);
    if (bloqueado) return;
    subir(Array.from(e.dataTransfer.files));
  }

  return (
    <div className="space-y-2">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!bloqueado) setArrastrando(true);
        }}
        onDragLeave={() => setArrastrando(false)}
        onDrop={onDrop}
        className={cn(
          'flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-8 text-center transition-colors',
          arrastrando ? 'border-primary bg-accent' : 'border-input bg-card',
          bloqueado && 'opacity-60',
        )}
      >
        <span className="flex size-10 items-center justify-center rounded-[10px] bg-accent text-primary">
          <Icon
            icon={cargando ? 'ph:circle-notch-light' : 'ph:file-zip-light'}
            className={cn('size-5', cargando && 'animate-spin')}
          />
        </span>
        <div className="space-y-1">
          <p className="text-sm font-semibold">
            {cargando ? 'Revisando los archivos…' : 'Arrastra aquí tus ZIP o elígelos'}
          </p>
          <p className="max-w-prose text-xs text-muted-foreground">
            Los que generas en tu software contable (Contalink, CONTPAQi…), con el nombre del
            Anexo 24: RFC + año + mes + tipo, por ejemplo{' '}
            <span className="font-mono">SSA980330HU1202601BN.zip</span>.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void elegir()} disabled={bloqueado}>
          <Icon icon="ph:upload-simple-light" className="size-4" />
          {hayArchivos ? 'Cambiar archivos' : 'Elegir ZIP'}
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept=".zip,application/zip"
          multiple
          className="hidden"
          onChange={(e) => {
            subir(Array.from(e.target.files ?? []));
            e.target.value = ''; // permite elegir el mismo archivo otra vez
          }}
        />
      </div>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

'use client';

import { useRef, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { useEmpresas } from '@/hooks/use-empresas';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Icon } from '@/components/ui/icon';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type { ProcesadorCargarResponse } from '@/lib/types';
import { cn } from '@/lib/utils';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /**
   * Si `true`, omite el `<Card>` envolvente (Header + Content) y renderiza
   * solo el cuerpo (tabs + alerts). Usado cuando el uploader vive dentro de
   * un `Dialog` para no duplicar el shell.
   */
  bareback?: boolean;
  /** Llamado tras una carga exitosa para refrescar el listado/stats del padre. */
  onCargado: () => void;
}

const MAX_BATCH = 500;

export function CfdiUploader({ bareback = false, onCargado }: Props) {
  const { apiClient } = useServer();
  const { empresas, loading: empresasLoading } = useEmpresas();
  const empresaActiva = empresas.find((e) => e.default);
  const sinEmpresa = !empresasLoading && !empresaActiva;
  const [desde, setDesde] = useState('');
  const [hasta, setHasta] = useState('');
  const [tipoEmpresa, setTipoEmpresa] = useState<'E' | 'R'>('R');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resumen, setResumen] = useState<ProcesadorCargarResponse | null>(null);
  const [progreso, setProgreso] = useState<{ lote: number; total: number } | null>(null);
  const [dragActivo, setDragActivo] = useState(false);
  const folderInput = useRef<HTMLInputElement | null>(null);

  async function subirArchivos(files: File[]) {
    // El drop no respeta `disabled`: gate explícito también aquí.
    if (!empresaActiva) return;
    const xmls = files.filter((f) => f.name.toLowerCase().endsWith('.xml'));
    if (xmls.length === 0) {
      setError('No se encontraron archivos `.xml` en la selección.');
      return;
    }
    setError(null);
    setResumen(null);
    setBusy(true);

    // Particiona la carga en lotes de MAX_BATCH y los procesa secuencialmente
    // (no en paralelo: el agente es single-process y un thread a la vez evita
    // contención en SQLite). Acumulamos el summary final.
    const lotes: File[][] = [];
    for (let i = 0; i < xmls.length; i += MAX_BATCH) {
      lotes.push(xmls.slice(i, i + MAX_BATCH));
    }

    const acum: ProcesadorCargarResponse = {
      agregados: 0,
      duplicados: 0,
      omitidos_rfc: 0,
      errores: [],
    };

    try {
      for (let i = 0; i < lotes.length; i++) {
        setProgreso({ lote: i + 1, total: lotes.length });
        const r = await apiClient.procesadorCargar(empresaActiva.rfc, lotes[i]);
        acum.agregados += r.agregados;
        acum.duplicados += r.duplicados;
        acum.omitidos_rfc += r.omitidos_rfc;
        acum.errores.push(...r.errores);
        // Refrescar a medida que llegan lotes para que la tabla / stats
        // se vayan poblando sin esperar al último.
        onCargado();
      }
      setResumen(acum);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setBusy(false);
      setProgreso(null);
    }
  }

  async function importarDesdeEmpresa() {
    if (!empresaActiva) {
      setError('No hay empresa activa. Selecciona una en Empresas.');
      return;
    }
    setError(null);
    setResumen(null);
    setBusy(true);
    try {
      const r = await apiClient.procesadorCargarDesdeEmpresa({
        rfc: empresaActiva.rfc,
        desde: desde || undefined,
        hasta: hasta || undefined,
        tipo: tipoEmpresa,
      });
      setResumen(r);
      onCargado();
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setBusy(false);
    }
  }

  function handleDrop(ev: React.DragEvent<HTMLDivElement>) {
    ev.preventDefault();
    setDragActivo(false);
    if (busy) return;
    const files = Array.from(ev.dataTransfer.files ?? []);
    subirArchivos(files);
  }

  function handleFiles(ev: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(ev.target.files ?? []);
    subirArchivos(files);
    ev.target.value = '';
  }

  // Sin empresa activa el procesador no tiene dónde guardar: el buffer y los
  // filtros viven POR empresa en el agente. Se bloquean ambas vías de carga.
  const cuerpo = sinEmpresa ? (
    <Alert variant="warning">
      <Icon icon="ph:warning-light" className="size-4" />
      <AlertDescription>
        No hay empresa activa. Activa una empresa en la sección Empresas para
        cargar comprobantes: el procesador guarda los XMLs por empresa.
      </AlertDescription>
    </Alert>
  ) : (
    <div className="space-y-4">
      <Tabs defaultValue="archivos">
          <TabsList>
            <TabsTrigger value="archivos">
              <Icon icon="ph:file-arrow-up-light" className="size-4" />
              Archivos
            </TabsTrigger>
            <TabsTrigger value="empresa">
              <Icon icon="ph:buildings-light" className="size-4" />
              Desde empresa
            </TabsTrigger>
          </TabsList>

          {/* Drag & drop + examinar carpeta */}
          <TabsContent value="archivos" className="space-y-3">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                if (!busy) setDragActivo(true);
              }}
              onDragLeave={() => setDragActivo(false)}
              onDrop={handleDrop}
              className={cn(
                'flex flex-col items-center justify-center gap-2 rounded-md border-2 border-dashed p-8 text-center transition-colors',
                dragActivo
                  ? 'border-primary bg-primary/5'
                  : 'border-muted-foreground/30 bg-muted/10',
                busy && 'opacity-60',
              )}
            >
              <Icon icon="ph:file-arrow-up-light" className="size-8 text-muted-foreground" />
              <div className="text-sm">
                Arrastra tus archivos <span className="font-mono">.xml</span> aquí
              </div>
              <Button
                variant="outline"
                size="sm"
                type="button"
                disabled={busy || !empresaActiva}
                onClick={() => folderInput.current?.click()}
              >
                <Icon icon="ph:folder-open-light" className="size-4" />
                Examinar carpeta
              </Button>
              {/* webkitdirectory permite seleccionar una carpeta completa */}
              <input
                ref={folderInput}
                type="file"
                multiple
                /* @ts-expect-error — webkitdirectory no está en el HTMLInputElement de TS */
                webkitdirectory=""
                directory=""
                className="hidden"
                onChange={handleFiles}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Solo se cargan comprobantes de la empresa activa
              {empresaActiva && (
                <>
                  {' '}(<span className="font-mono">{empresaActiva.rfc}</span> como
                  emisor o receptor)
                </>
              )}
              ; el resto se omite. Las selecciones grandes se procesan en lotes
              de {MAX_BATCH}. Los duplicados (mismo UUID) se ignoran.
            </p>
          </TabsContent>

          {/* Importar desde la empresa activa */}
          <TabsContent value="empresa" className="space-y-3">
            {!empresaActiva ? (
              <Alert>
                <Icon icon="ph:info-light" className="size-4" />
                <AlertDescription>
                  No hay empresa activa. Actívala desde la sección Empresas.
                </AlertDescription>
              </Alert>
            ) : (
              <>
                <div className="text-xs text-muted-foreground">
                  Empresa activa:{' '}
                  <span className="font-medium text-foreground">{empresaActiva.nombre}</span>{' '}
                  <span className="font-mono">{empresaActiva.rfc}</span>
                </div>

                <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                  <div className="space-y-2">
                    <Label>Comprobantes</Label>
                    <Select
                      value={tipoEmpresa}
                      onValueChange={(v) => setTipoEmpresa(v as 'E' | 'R')}
                    >
                      <SelectTrigger className="w-full">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="R">Recibidos</SelectItem>
                        <SelectItem value="E">Emitidos</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="cdesde">Desde (opcional)</Label>
                    <Input
                      id="cdesde"
                      type="date"
                      value={desde}
                      onChange={(e) => setDesde(e.target.value)}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="chasta">Hasta (opcional)</Label>
                    <Input
                      id="chasta"
                      type="date"
                      value={hasta}
                      onChange={(e) => setHasta(e.target.value)}
                    />
                  </div>
                  <div className="flex items-end">
                    <Button
                      type="button"
                      className="w-full"
                      disabled={busy}
                      onClick={importarDesdeEmpresa}
                    >
                      {busy ? (
                        <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                      ) : (
                        <Icon icon="ph:download-simple-light" className="size-4" />
                      )}
                      Importar
                    </Button>
                  </div>
                </div>
              </>
            )}
            <p className="text-xs text-muted-foreground">
              Escanea la carpeta de descargas de la empresa activa y agrega las
              facturas encontradas (las repetidas se cargan una sola vez).
            </p>
          </TabsContent>
        </Tabs>

        {progreso && progreso.total > 1 && (
          <Alert>
            <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
            <AlertDescription>
              Procesando lote {progreso.lote} de {progreso.total}…
            </AlertDescription>
          </Alert>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {resumen && (
          <Alert
            variant={
              resumen.omitidos_rfc > 0 && resumen.agregados === 0
                ? 'warning'
                : 'default'
            }
          >
            <Icon
              icon={
                resumen.omitidos_rfc > 0 && resumen.agregados === 0
                  ? 'ph:warning-light'
                  : 'ph:check-circle-light'
              }
              className="size-4"
            />
            <AlertDescription>
              {[
                `${resumen.agregados} agregados`,
                resumen.duplicados > 0 && `${resumen.duplicados} duplicados`,
                resumen.omitidos_rfc > 0 &&
                  `${resumen.omitidos_rfc} omitidos por no corresponder al RFC ${empresaActiva?.rfc ?? 'de la empresa activa'}`,
                resumen.archivos_encontrados !== undefined &&
                  `${resumen.archivos_encontrados} archivos escaneados`,
                resumen.errores.length > 0 && `${resumen.errores.length} con error`,
              ]
                .filter(Boolean)
                .join(', ')}
            </AlertDescription>
          </Alert>
        )}
    </div>
  );

  if (bareback) {
    return cuerpo;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon icon="ph:upload-light" className="size-4" />
          Cargar XMLs
        </CardTitle>
        <CardDescription>
          Arrastra archivos, examina una carpeta o importa los que ya descargó el agente para
          la empresa activa. Los XMLs se acumulan hasta que pulses Borrar.
        </CardDescription>
      </CardHeader>
      <CardContent>{cuerpo}</CardContent>
    </Card>
  );
}

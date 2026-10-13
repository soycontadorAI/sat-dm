'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import type { CfdiFiltros, PlantillaExport } from '@/lib/types';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa activa: el export sale de SU índice. */
  rfc: string;
  filtros: Partial<CfdiFiltros>;
}

function descargarBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/**
 * Exportar con plantilla (procesador/plantillas.py): qué columnas, y dos
 * opciones que no viven en la plantilla y arrancan apagadas: una fila por
 * concepto y convertir a MXN. Sale con los filtros de la tabla.
 */
export function CfdiExportButtons({ rfc, filtros }: Props) {
  const { apiClient } = useServer();
  const [abierto, setAbierto] = useState(false);
  const [plantillas, setPlantillas] = useState<PlantillaExport[]>([]);
  const [plantillaId, setPlantillaId] = useState('');
  const [porConcepto, setPorConcepto] = useState(false);
  const [convertirMxn, setConvertirMxn] = useState(false);
  const [formato, setFormato] = useState<'xlsx' | 'csv'>('xlsx');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!abierto) return;
    let vivo = true;
    apiClient
      .plantillasListar()
      .then((r) => {
        if (!vivo) return;
        setPlantillas(r.plantillas);
        setPlantillaId((actual) =>
          actual && r.plantillas.some((p) => p.id === actual) ? actual : r.predeterminada,
        );
      })
      .catch((e) => toast.error(mensajeDeError(e)));
    return () => {
      vivo = false;
    };
  }, [abierto, apiClient]);

  const plantilla = plantillas.find((p) => p.id === plantillaId);

  async function exportar() {
    if (!plantillaId) return;
    setBusy(true);
    try {
      const blob = await apiClient.procesadorExportar(rfc, formato, filtros, {
        plantilla: plantillaId,
        porConcepto,
        convertirMxn,
      });
      const fecha = new Date().toISOString().slice(0, 10);
      descargarBlob(blob, `cfdis_${fecha}.${formato}`);
      setAbierto(false);
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={abierto} onOpenChange={(v) => !busy && setAbierto(v)}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Icon icon="ph:download-simple-light" className="size-4" />
          Exportar
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Exportar CFDIs</DialogTitle>
          <DialogDescription>Sale con los filtros que tienes aplicados en la tabla.</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label>Plantilla</Label>
              <Link
                href={`/comprobantes/plantillas${plantillaId ? `?id=${encodeURIComponent(plantillaId)}` : ''}`}
                className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
              >
                Personalizar columnas
              </Link>
            </div>
            <Select value={plantillaId} onValueChange={setPlantillaId}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Cargando plantillas…" />
              </SelectTrigger>
              <SelectContent>
                {plantillas.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.nombre}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {plantilla && (
              <p className="text-xs text-muted-foreground">
                {plantilla.descripcion || `Plantilla propia · ${plantilla.columnas.length} columnas`}
              </p>
            )}
          </div>

          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <Switch
                id="export-por-concepto"
                checked={porConcepto}
                onCheckedChange={setPorConcepto}
                className="mt-0.5"
              />
              <div className="space-y-0.5">
                <Label htmlFor="export-por-concepto" className="font-normal">
                  Una fila por concepto
                </Label>
                <p className="text-xs text-muted-foreground">
                  Repite los datos del CFDI en cada renglón, con la cantidad, el importe y los
                  impuestos de cada concepto. Útil para inventarios.
                </p>
              </div>
            </div>
            <div className="flex items-start gap-3">
              <Switch
                id="export-mxn"
                checked={convertirMxn}
                onCheckedChange={setConvertirMxn}
                className="mt-0.5"
              />
              <div className="space-y-0.5">
                <Label htmlFor="export-mxn" className="font-normal">
                  Convertir a MXN
                </Label>
                <p className="text-xs text-muted-foreground">
                  Los importes en moneda extranjera se multiplican por el tipo de cambio del CFDI.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label>Formato</Label>
            <RadioGroup
              value={formato}
              onValueChange={(v) => setFormato(v as 'xlsx' | 'csv')}
              className="flex gap-6"
            >
              <div className="flex items-center gap-2">
                <RadioGroupItem value="xlsx" id="export-xlsx" />
                <Label htmlFor="export-xlsx" className="font-normal">
                  Excel
                </Label>
              </div>
              <div className="flex items-center gap-2">
                <RadioGroupItem value="csv" id="export-csv" />
                <Label htmlFor="export-csv" className="font-normal">
                  CSV
                </Label>
              </div>
            </RadioGroup>
            {porConcepto && formato === 'xlsx' && (
              <p className="text-xs text-muted-foreground">
                Con muchos conceptos el archivo crece rápido. Una hoja de Excel admite hasta un
                millón de renglones; para más, usa CSV o filtra un periodo más corto.
              </p>
            )}
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setAbierto(false)} disabled={busy}>
            Cancelar
          </Button>
          <Button onClick={exportar} disabled={busy || !plantillaId}>
            <Icon
              icon={busy ? 'ph:circle-notch-light' : 'ph:download-simple-light'}
              className={busy ? 'size-4 animate-spin' : 'size-4'}
            />
            {busy ? 'Exportando…' : 'Exportar'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

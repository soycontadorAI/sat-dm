'use client';

// `useSearchParams` (lee `?id=`) requiere un <Suspense> envolvente bajo
// `output: 'export'`; mismo patrón que /empresas/detalle.
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { toast } from 'sonner';

import { PageHeading } from '@/components/layout/page-heading';
import { ColumnasEditor } from '@/components/plantillas/columnas-editor';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useEmpresas } from '@/hooks/use-empresas';
import { mensajeDeError } from '@/lib/errores';
import type {
  CatalogoCamposExport,
  PlantillaExport,
  PlantillaExportInput,
  PlantillasExportResponse,
  VistaPreviaResponse,
} from '@/lib/types';
import { cn } from '@/lib/utils';
import { useServer } from '@/providers/server-provider';

/** Selección de una plantilla que aún no se guarda (nueva o duplicada). */
const NUEVA = '__nueva__';

export default function PlantillasPage() {
  return (
    <Suspense fallback={null}>
      <PlantillasEditor />
    </Suspense>
  );
}

function aBorrador(p: PlantillaExport): PlantillaExportInput {
  return {
    nombre: p.nombre,
    columnas: p.columnas.map((c) => ({ ...c })),
    detalle_concepto: p.detalle_concepto.map((c) => ({ ...c })),
  };
}

function PlantillasEditor() {
  const { apiClient } = useServer();
  const { empresas } = useEmpresas();
  const rfcActivo = empresas.find((e) => e.default)?.rfc ?? null;
  const idInicial = useSearchParams().get('id');

  const [catalogo, setCatalogo] = useState<CatalogoCamposExport | null>(null);
  const [datos, setDatos] = useState<PlantillasExportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seleccion, setSeleccion] = useState<string | null>(null);
  const [borrador, setBorrador] = useState<PlantillaExportInput | null>(null);
  const [guardando, setGuardando] = useState(false);
  const [confirmarBorrado, setConfirmarBorrado] = useState(false);

  const recargar = useCallback(async () => {
    const [cat, lista] = await Promise.all([
      apiClient.procesadorCamposExport(),
      apiClient.plantillasListar(),
    ]);
    setCatalogo(cat);
    setDatos(lista);
    return lista;
  }, [apiClient]);

  // La selección inicial (`?id=` o la predeterminada) se hace UNA vez: el
  // efecto puede repetirse (cambia la identidad de `apiClient` al conectar)
  // y no debe pisar lo que el usuario ya eligió o está editando.
  const seleccionInicial = useRef(false);
  useEffect(() => {
    let vigente = true;
    recargar()
      .then((lista) => {
        if (!vigente || seleccionInicial.current) return;
        const inicial =
          lista.plantillas.find((p) => p.id === idInicial) ??
          lista.plantillas.find((p) => p.id === lista.predeterminada) ??
          lista.plantillas[0];
        if (inicial) {
          seleccionInicial.current = true;
          setSeleccion(inicial.id);
          setBorrador(aBorrador(inicial));
        }
      })
      .catch((e) => vigente && setError(mensajeDeError(e)));
    return () => {
      vigente = false;
    };
  }, [recargar, idInicial]);

  const actual = datos?.plantillas.find((p) => p.id === seleccion) ?? null;
  const esSistema = actual?.sistema ?? false;
  const sinGuardar = seleccion === NUEVA;
  const cambios = useMemo(() => {
    if (!borrador) return false;
    if (sinGuardar) return true;
    return !!actual && JSON.stringify(aBorrador(actual)) !== JSON.stringify(borrador);
  }, [actual, borrador, sinGuardar]);

  function elegir(p: PlantillaExport) {
    if (p.id === seleccion) return;
    if (cambios && !window.confirm('Tienes cambios sin guardar. ¿Descartarlos?')) return;
    setSeleccion(p.id);
    setBorrador(aBorrador(p));
    setConfirmarBorrado(false);
  }

  function empezarCopia(base: PlantillaExportInput, nombre: string) {
    if (cambios && !window.confirm('Tienes cambios sin guardar. ¿Descartarlos?')) return;
    setSeleccion(NUEVA);
    setBorrador({ ...base, nombre });
    setConfirmarBorrado(false);
  }

  async function guardar() {
    if (!borrador) return;
    setGuardando(true);
    try {
      const guardada = sinGuardar
        ? await apiClient.plantillaCrear(borrador)
        : await apiClient.plantillaActualizar(seleccion!, borrador);
      await recargar();
      setSeleccion(guardada.id);
      setBorrador(aBorrador(guardada));
      toast.success('Plantilla guardada.');
    } catch (e) {
      toast.error(mensajeDeError(e));
    } finally {
      setGuardando(false);
    }
  }

  async function eliminar() {
    if (!actual) return;
    try {
      await apiClient.plantillaEliminar(actual.id);
      const lista = await recargar();
      const siguiente =
        lista.plantillas.find((p) => p.id === lista.predeterminada) ?? lista.plantillas[0];
      setSeleccion(siguiente.id);
      setBorrador(aBorrador(siguiente));
      setConfirmarBorrado(false);
      toast.success('Plantilla eliminada.');
    } catch (e) {
      toast.error(mensajeDeError(e));
    }
  }

  async function hacerPredeterminada() {
    if (!actual) return;
    try {
      await apiClient.plantillaPredeterminada(actual.id);
      await recargar();
      toast.success(`«${actual.nombre}» es ahora la plantilla predeterminada.`);
    } catch (e) {
      toast.error(mensajeDeError(e));
    }
  }

  const clasico = datos?.plantillas.find((p) => p.id === 'clasico');

  return (
    <div className="space-y-6">
      <PageHeading
        title="Plantillas de exportación"
        description="Elige qué columnas lleva el Excel de CFDIs, en qué orden y con qué encabezado."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/comprobantes/cfdi">
              <Icon icon="ph:arrow-left-light" className="size-4" />
              Procesador de CFDI
            </Link>
          </Button>
        }
      />

      {error && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-light" className="size-4" />
          <AlertDescription>No se pudieron cargar las plantillas: {error}</AlertDescription>
        </Alert>
      )}

      {datos && catalogo && borrador && (
        <div className="grid gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
          {/* Lista de plantillas */}
          <aside className="space-y-2">
            <ul className="space-y-1">
              {datos.plantillas.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => elegir(p)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-muted',
                      seleccion === p.id && 'bg-muted font-medium',
                    )}
                  >
                    <span className="min-w-0 flex-1 truncate">{p.nombre}</span>
                    {datos.predeterminada === p.id && (
                      <span title="Predeterminada" aria-label="Predeterminada">
                        <Icon icon="ph:star-fill" className="size-3.5 text-foreground" />
                      </span>
                    )}
                    {p.sistema && <Badge variant="chip">Sistema</Badge>}
                  </button>
                </li>
              ))}
              {sinGuardar && (
                <li className="rounded-md bg-muted px-2.5 py-2 text-sm font-medium">
                  {borrador.nombre || 'Nueva plantilla'}
                  <span className="ml-1 text-xs font-normal text-muted-foreground">(sin guardar)</span>
                </li>
              )}
            </ul>
            {clasico && (
              <Button
                variant="outline"
                size="sm"
                className="w-full"
                onClick={() => empezarCopia(aBorrador(clasico), 'Nueva plantilla')}
              >
                <Icon icon="ph:plus-light" className="size-4" />
                Nueva plantilla
              </Button>
            )}
          </aside>

          {/* Editor */}
          <div className="min-w-0 space-y-8">
            <div className="flex flex-wrap items-end gap-3">
              {esSistema ? (
                <div className="min-w-0 flex-1 space-y-1">
                  <h2 className="text-base font-medium">{actual?.nombre}</h2>
                  <p className="text-sm text-muted-foreground">{actual?.descripcion}</p>
                </div>
              ) : (
                <div className="min-w-[14rem] flex-1 space-y-1.5">
                  <Label htmlFor="plantilla-nombre">Nombre</Label>
                  <Input
                    id="plantilla-nombre"
                    value={borrador.nombre}
                    onChange={(e) => setBorrador({ ...borrador, nombre: e.target.value })}
                  />
                </div>
              )}
              <div className="flex flex-wrap gap-2">
                {!esSistema && (
                  <Button size="sm" onClick={guardar} disabled={!cambios || guardando}>
                    <Icon
                      icon={guardando ? 'ph:circle-notch-light' : 'ph:check-light'}
                      className={guardando ? 'size-4 animate-spin' : 'size-4'}
                    />
                    {sinGuardar ? 'Guardar plantilla' : 'Guardar cambios'}
                  </Button>
                )}
                {!sinGuardar && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => empezarCopia(borrador, `${borrador.nombre} (copia)`)}
                  >
                    <Icon icon="ph:copy-light" className="size-4" />
                    Duplicar
                  </Button>
                )}
                {!sinGuardar && datos.predeterminada !== seleccion && (
                  <Button size="sm" variant="outline" onClick={hacerPredeterminada}>
                    <Icon icon="ph:star-light" className="size-4" />
                    Usar como predeterminada
                  </Button>
                )}
                {!sinGuardar && !esSistema && !confirmarBorrado && (
                  <Button size="sm" variant="ghost" onClick={() => setConfirmarBorrado(true)}>
                    <Icon icon="ph:trash-light" className="size-4" />
                    Eliminar
                  </Button>
                )}
                {confirmarBorrado && (
                  <div className="flex items-center gap-2 text-sm">
                    <span>¿Eliminarla?</span>
                    <Button size="sm" variant="destructive" onClick={eliminar}>
                      Sí, eliminar
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmarBorrado(false)}>
                      No
                    </Button>
                  </div>
                )}
                {sinGuardar && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      const base =
                        datos.plantillas.find((p) => p.id === datos.predeterminada) ??
                        datos.plantillas[0];
                      setSeleccion(base.id);
                      setBorrador(aBorrador(base));
                    }}
                  >
                    Descartar
                  </Button>
                )}
              </div>
            </div>

            {esSistema && (
              <Alert>
                <Icon icon="ph:info-light" className="size-4" />
                <AlertDescription>
                  Las plantillas del sistema no se editan. Duplícala para quitar, agregar o
                  reordenar columnas y guardarla como tuya.
                </AlertDescription>
              </Alert>
            )}

            <ColumnasEditor
              titulo="Columnas"
              descripcion="Un renglón por CFDI. Ordénalas con las flechas y cambia el encabezado aquí mismo."
              nivel="cfdi"
              columnas={borrador.columnas}
              catalogo={catalogo}
              onChange={esSistema ? undefined : (columnas) => setBorrador({ ...borrador, columnas })}
            />

            <ColumnasEditor
              titulo="Detalle por concepto"
              descripcion="Se usa al exportar con «Una fila por concepto»: estas columnas van en el lugar de «Conceptos» (o al final si la plantilla no la tiene)."
              nivel="concepto"
              columnas={borrador.detalle_concepto}
              catalogo={catalogo}
              onChange={
                esSistema ? undefined : (detalle_concepto) => setBorrador({ ...borrador, detalle_concepto })
              }
            />

            <VistaPrevia rfc={rfcActivo} borrador={borrador} />
          </div>
        </div>
      )}
    </div>
  );
}

function VistaPrevia({ rfc, borrador }: { rfc: string | null; borrador: PlantillaExportInput }) {
  const { apiClient } = useServer();
  const [porConcepto, setPorConcepto] = useState(false);
  const [convertirMxn, setConvertirMxn] = useState(false);
  const [vista, setVista] = useState<VistaPreviaResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const columnas = borrador.columnas;
  const detalle = borrador.detalle_concepto;

  useEffect(() => {
    if (!rfc || columnas.length === 0) return;
    let vivo = true;
    const t = setTimeout(() => {
      apiClient
        .procesadorVistaPrevia({
          rfc,
          columnas,
          detalle_concepto: detalle,
          por_concepto: porConcepto,
          convertir_mxn: convertirMxn,
          limite: 5,
        })
        .then((r) => {
          if (!vivo) return;
          setVista(r);
          setError(null);
        })
        .catch((e) => vivo && setError(mensajeDeError(e)));
    }, 400);
    return () => {
      vivo = false;
      clearTimeout(t);
    };
  }, [apiClient, rfc, columnas, detalle, porConcepto, convertirMxn]);

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">Vista previa</h2>
          <p className="text-xs text-muted-foreground">
            Los CFDIs más recientes de la empresa activa, como saldrían en el archivo.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Switch id="vp-por-concepto" size="sm" checked={porConcepto} onCheckedChange={setPorConcepto} />
            <Label htmlFor="vp-por-concepto" className="text-xs font-normal">
              Una fila por concepto
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Switch id="vp-mxn" size="sm" checked={convertirMxn} onCheckedChange={setConvertirMxn} />
            <Label htmlFor="vp-mxn" className="text-xs font-normal">
              Convertir a MXN
            </Label>
          </div>
        </div>
      </div>

      {!rfc ? (
        <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
          Activa una empresa para ver la vista previa con sus CFDIs.
        </p>
      ) : columnas.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
          Agrega al menos una columna.
        </p>
      ) : error ? (
        <Alert variant="warning">
          <Icon icon="ph:warning-light" className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : vista && vista.filas.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-center text-xs text-muted-foreground">
          La empresa activa aún no tiene CFDIs en el procesador.
        </p>
      ) : (
        vista && (
          <div className="overflow-x-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  {vista.encabezados.map((h, i) => (
                    <TableHead key={i} className="whitespace-nowrap">
                      {h}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {vista.filas.map((fila, i) => (
                  <TableRow key={i}>
                    {fila.map((v, j) => (
                      <TableCell
                        key={j}
                        className={cn(
                          'max-w-64 truncate whitespace-nowrap',
                          (vista.tipos[j] === 'importe' || vista.tipos[j] === 'tipo_cambio') &&
                            'text-right tabular-nums',
                        )}
                        title={v}
                      >
                        {v}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )
      )}
    </section>
  );
}

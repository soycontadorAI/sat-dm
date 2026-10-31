'use client';

import { useState } from 'react';

import { PageHeading } from '@/components/layout/page-heading';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Icon } from '@/components/ui/icon';
import { CargarXmlDialog } from '@/components/diot/cargar-xml-dialog';
import { DetalleDrawer } from '@/components/diot/detalle-drawer';
import { DiotEmpty } from '@/components/diot/diot-empty';
import { DiotStats } from '@/components/diot/diot-stats';
import { ExportTxtButton } from '@/components/diot/export-txt-button';
import { SelectorPeriodo } from '@/components/diot/selector-periodo';
import { TablaDiot } from '@/components/diot/tabla-diot';
import { ProcesadorSinEmpresa } from '@/components/shared/procesador-sin-empresa';
import { useDiot } from '@/hooks/use-diot';
import { useEmpresas } from '@/hooks/use-empresas';
import { empresaPresentaDiot } from '@/lib/fiscal/regimenes-fiscales';

export default function DiotPage() {
  const {
    rfcActivo,
    periodo,
    setPeriodo,
    filas,
    errores,
    advertencias,
    origen,
    resumen,
    catalogos,
    cargando,
    guardando,
    prellenando,
    setCampo,
    agregarFila,
    eliminarFila,
    prellenar,
  } = useDiot();

  const [confirmarPrellenado, setConfirmarPrellenado] = useState(false);
  const [detalleIndex, setDetalleIndex] = useState<number | null>(null);

  // Aviso (no bloquea): la empresa activa está relevada de la DIOT — RESICO
  // por régimen configurado, o el override manual de la configuración.
  const { empresas } = useEmpresas();
  const empresaActiva = empresas.find((e) => e.rfc === rfcActivo);
  const relevada = Boolean(empresaActiva) && !empresaPresentaDiot(empresaActiva);

  // Re-prellenar pisa los renglones de origen CFDI. Si el último guardado fue
  // una edición manual, se confirma antes (los agregados a mano sobreviven).
  const prellenarConConfirmacion = () => {
    if (origen === 'manual' && filas.length > 0) setConfirmarPrellenado(true);
    else void prellenar();
  };

  // Al agregar un proveedor a mano, abre su detalle para capturarlo.
  const agregarYAbrir = () => {
    agregarFila();
    setDetalleIndex(filas.length);
  };

  const sinEstado = !cargando && filas.length === 0;

  return (
    <div className="space-y-6">
      <PageHeading
        title="DIOT"
        description="Declaración Informativa de Operaciones con Terceros: prellena desde tus CFDIs, ajusta y genera el TXT de carga masiva."
      />

      {!rfcActivo ? (
        <ProcesadorSinEmpresa listo={!cargando} />
      ) : (
        <>
          {/* Barra de acciones */}
          <div className="flex flex-wrap items-center justify-between gap-3">
            <SelectorPeriodo periodo={periodo} onChange={setPeriodo} disabled={cargando} />
            <div className="flex flex-wrap items-center gap-2">
              {guardando && (
                <span className="text-xs text-muted-foreground">Guardando…</span>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={prellenarConConfirmacion}
                disabled={cargando || prellenando}
              >
                <Icon
                  icon={prellenando ? 'ph:circle-notch-light' : 'ph:sparkle-light'}
                  className={prellenando ? 'size-4 animate-spin' : 'size-4'}
                />
                Prellenar desde comprobantes
              </Button>
              <CargarXmlDialog onCargado={() => void prellenar()} />
              <Button variant="outline" size="sm" onClick={agregarYAbrir} disabled={cargando}>
                <Icon icon="ph:plus-light" className="size-4" />
                Agregar proveedor
              </Button>
              <ExportTxtButton
                rfc={rfcActivo}
                periodo={periodo}
                habilitado={filas.length > 0 && errores.length === 0}
                numErrores={errores.length}
              />
            </div>
          </div>

          {/* Avisos */}
          {relevada && (
            <Alert variant="warning">
              <Icon icon="ph:info-light" className="size-4" />
              <AlertTitle>Esta empresa está relevada de presentar la DIOT</AlertTitle>
              <AlertDescription>
                Según su régimen fiscal configurado (RESICO y otros relevados) o el
                ajuste manual de su configuración, esta empresa no está obligada a
                enviar la DIOT. Puedes generar el TXT de todos modos; si sí presenta,
                actívalo en la configuración de la empresa.
              </AlertDescription>
            </Alert>
          )}
          {(resumen?.cfdis_sin_desglose ?? 0) > 0 && (
            <Alert variant="warning">
              <Icon icon="ph:warning-light" className="size-4" />
              <AlertTitle>Bases estimadas</AlertTitle>
              <AlertDescription>
                {resumen!.cfdis_sin_desglose} CFDIs se cargaron con una versión anterior de la
                app y no traen el desglose de IVA por tasa: la base al 16% se estimó desde el
                IVA. Vuelve a cargar esos XMLs en Comprobantes para el dato exacto.
              </AlertDescription>
            </Alert>
          )}
          {errores.length > 0 && (
            <Alert variant="destructive">
              <Icon icon="ph:warning-circle-light" className="size-4" />
              <AlertTitle>
                {errores.length} error{errores.length === 1 ? '' : 'es'} que bloquean el TXT
              </AlertTitle>
              <AlertDescription>
                <ul className="list-disc pl-4">
                  {errores.slice(0, 6).map((e, i) => (
                    <li key={i}>{e.mensaje}</li>
                  ))}
                  {errores.length > 6 && <li>… y {errores.length - 6} más</li>}
                </ul>
              </AlertDescription>
            </Alert>
          )}

          {/* Tabla o empty-state */}
          {sinEstado ? (
            <DiotEmpty
              onPrellenar={() => void prellenar()}
              prellenando={prellenando}
              onCargado={() => void prellenar()}
            />
          ) : (
            !cargando && (
              <>
                <DiotStats filas={filas} />
                <TablaDiot
                  filas={filas}
                  catalogos={catalogos}
                  errores={errores}
                  advertencias={advertencias}
                  activeIndex={detalleIndex}
                  onCampo={setCampo}
                  onEliminar={eliminarFila}
                  onAbrirDetalle={setDetalleIndex}
                />
                <div className="flex items-start gap-2 text-xs text-muted-foreground">
                  <Icon icon="ph:info-light" className="mt-0.5 size-4 shrink-0" />
                  <span>
                    Criterio del prellenado: CFDIs recibidos emitidos en el periodo (las notas de
                    crédito van a devoluciones); los comprobantes que excluiste con el interruptor
                    DIOT en Comprobantes no se consideran. Todo es editable antes de generar el
                    TXT; verifica el archivo subiéndolo a la aplicación DIOT del SAT.
                  </span>
                </div>
              </>
            )
          )}

          {/* Detalle en panel lateral */}
          <DetalleDrawer
            index={detalleIndex}
            filas={filas}
            catalogos={catalogos}
            errores={errores}
            onCampo={setCampo}
            onClose={() => setDetalleIndex(null)}
          />

          {/* Confirmación de re-prellenado sobre ediciones manuales */}
          <Dialog open={confirmarPrellenado} onOpenChange={setConfirmarPrellenado}>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>¿Volver a prellenar el periodo?</DialogTitle>
                <DialogDescription>
                  Los renglones prellenados desde CFDIs se regenerarán y tus ajustes sobre ellos
                  se perderán. Los proveedores que agregaste a mano se conservan.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setConfirmarPrellenado(false)}>
                  Cancelar
                </Button>
                <Button
                  onClick={() => {
                    setConfirmarPrellenado(false);
                    void prellenar();
                  }}
                >
                  Prellenar
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </>
      )}
    </div>
  );
}

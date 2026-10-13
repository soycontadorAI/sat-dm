'use client';

import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { CfdiCargarMasButton } from '@/components/procesador-cfdi/cfdi-cargar-mas-button';
import { CfdiUploader } from '@/components/procesador-cfdi/cfdi-uploader';
import { CfdiValidarButton } from '@/components/procesador-cfdi/cfdi-validar-button';
import { PagosFiltersPanel } from '@/components/procesador-pagos/pagos-filters';
import { PagosHuerfanosTable } from '@/components/procesador-pagos/pagos-huerfanos-table';
import { PagosIncidenciasPue } from '@/components/procesador-pagos/pagos-incidencias-pue';
import { PagosExportButton } from '@/components/procesador-pagos/pagos-export-button';
import { PagosPPDTable } from '@/components/procesador-pagos/pagos-ppd-table';
import { PagosStatsCards } from '@/components/procesador-pagos/pagos-stats';
import { ProcesadorEstado } from '@/components/shared/procesador-estado';
import { ProcesadorSinEmpresa } from '@/components/shared/procesador-sin-empresa';
import { useProcesadorPagos } from '@/hooks/use-procesador-pagos';

export default function ProcesadorPagosPage() {
  const {
    filtros,
    setFiltro,
    reset,
    filtrosActivos,
    page,
    setPage,
    pageSize,
    data,
    stats,
    loading,
    error,
    recargar,
    hidratado,
    rfcActivo,
    sinEmpresa,
  } = useProcesadorPagos();

  // Empty state = no hay facturas PPD ni complementos cargados en el buffer
  // (no es lo mismo que "filtros muy restrictivos" — eso lo maneja la tabla).
  const bufferVacio = hidratado && stats !== null && stats.total_global_ppd === 0;

  return (
    <div className="space-y-6">
      <PageHeading
        title="Procesador de Pagos"
        description="Concilia facturas PPD con sus complementos de pago. Detecta huérfanos, extemporáneos e incidencias PUE."
        action={
          <Button variant="outline" size="sm" asChild>
            <Link href="/comprobantes">
              <Icon icon="ph:arrow-left-light" className="size-4" />
              Comprobantes
            </Link>
          </Button>
        }
      />

      {/* Sin empresa activa el hook no consulta nada: el buffer vive POR empresa. */}
      {sinEmpresa || !rfcActivo ? (
        <ProcesadorSinEmpresa listo={sinEmpresa} />
      ) : (
        <ProcesadorEstado
          stats={stats}
          error={error}
          loading={loading}
          onReintentar={recargar}
        >
        {/* Empty state: usa el mismo CfdiUploader del procesador CFDI. */}
        {bufferVacio && <CfdiUploader onCargado={recargar} />}

        {/* Estado normal: hay PPDs en el buffer de la empresa. */}
        {!bufferVacio && stats !== null && (
          <>
            <PagosStatsCards stats={stats} />

            <div className="flex flex-wrap items-center justify-end gap-2">
              <CfdiValidarButton rfc={rfcActivo} onValidado={recargar} />
              <CfdiCargarMasButton onCargado={recargar} />
              <PagosExportButton rfc={rfcActivo} filtros={filtros} />
            </div>

            <PagosFiltersPanel
              filtros={filtros}
              setFiltro={setFiltro}
              reset={reset}
              filtrosActivos={filtrosActivos}
            />

            <PagosPPDTable
              rfc={rfcActivo}
              data={data}
              page={page}
              pageSize={pageSize}
              loading={loading}
              onPage={setPage}
            />

            <PagosIncidenciasPue rfc={rfcActivo} filtros={filtros} />
            <PagosHuerfanosTable rfc={rfcActivo} filtros={filtros} />
          </>
        )}
        </ProcesadorEstado>
      )}
    </div>
  );
}

'use client';

import Link from 'next/link';

import { PageHeading } from '@/components/layout/page-heading';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { CfdiCargarMasButton } from '@/components/procesador-cfdi/cfdi-cargar-mas-button';
import { CfdiUploader } from '@/components/procesador-cfdi/cfdi-uploader';
import { CfdiValidarButton } from '@/components/procesador-cfdi/cfdi-validar-button';
import { NominaExportButton } from '@/components/procesador-nomina/nomina-export-button';
import { NominaFiltersPanel } from '@/components/procesador-nomina/nomina-filters';
import { NominaRecibosTable } from '@/components/procesador-nomina/nomina-recibos-table';
import { NominaStatsCards } from '@/components/procesador-nomina/nomina-stats';
import { ProcesadorEstado } from '@/components/shared/procesador-estado';
import { ProcesadorSinEmpresa } from '@/components/shared/procesador-sin-empresa';
import { useProcesadorNomina } from '@/hooks/use-procesador-nomina';

export default function ProcesadorNominaPage() {
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
  } = useProcesadorNomina();

  const bufferVacio = hidratado && stats !== null && stats.total_global_recibos === 0;

  return (
    <div className="space-y-6">
      <PageHeading
        title="Procesador de Nómina"
        description="Recibos de nómina (CFDI 4.0 + Complemento Nómina 1.2)."
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
        {/* Empty state: reusa el mismo CfdiUploader del procesador CFDI. */}
        {bufferVacio && <CfdiUploader onCargado={recargar} />}

        {/* Estado normal: hay recibos en el buffer de la empresa. */}
        {!bufferVacio && stats !== null && (
          <>
            <NominaStatsCards stats={stats} />

            <div className="flex flex-wrap items-center justify-end gap-2">
              <CfdiValidarButton rfc={rfcActivo} onValidado={recargar} />
              <CfdiCargarMasButton onCargado={recargar} />
              <NominaExportButton rfc={rfcActivo} filtros={filtros} />
            </div>

            <NominaFiltersPanel
              filtros={filtros}
              setFiltro={setFiltro}
              reset={reset}
              filtrosActivos={filtrosActivos}
            />

            <NominaRecibosTable
              rfc={rfcActivo}
              data={data}
              page={page}
              pageSize={pageSize}
              loading={loading}
              onPage={setPage}
            />
          </>
        )}
        </ProcesadorEstado>
      )}
    </div>
  );
}

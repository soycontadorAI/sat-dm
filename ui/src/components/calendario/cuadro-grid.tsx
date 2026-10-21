'use client';

import { memo, useMemo, useState } from 'react';

import { Icon } from '@/components/ui/icon';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import {
  celda,
  claseEstado,
  claseTexto,
  diasDelMes,
  esFutura,
  fechaIso,
  MESES,
  type FiltroDireccion,
  type LecturaCelda,
} from '@/lib/calendario';
import type { CalendarioAnio } from '@/lib/types';
import { cn } from '@/lib/utils';

const DIAS = Array.from({ length: 31 }, (_, i) => i + 1);

interface CeldaProps {
  lectura: LecturaCelda;
  esHoy: boolean;
  onAbrir: (fecha: string) => void;
}

const CeldaDia = memo(function CeldaDia({ lectura, esHoy, onAbrir }: CeldaProps) {
  const { estados, contenido, tooltip, fecha } = lectura;
  const partido = estados.length === 2;
  const texto = claseTexto(estados.map((e) => e.estado));

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={tooltip}
          onClick={() => onAbrir(fecha)}
          className={cn(
            'relative size-7 cursor-pointer overflow-hidden rounded-[5px] border border-border/60 outline-none',
            'hover:ring-2 hover:ring-primary/40 focus-visible:ring-2 focus-visible:ring-ring',
            esHoy && 'ring-2 ring-primary ring-offset-1 ring-offset-background',
          )}
        >
          {partido ? (
            <>
              <span className={cn('absolute inset-x-0 top-0 h-1/2', claseEstado(estados[0].estado))} />
              <span className={cn('absolute inset-x-0 bottom-0 h-1/2', claseEstado(estados[1].estado))} />
            </>
          ) : (
            <span className={cn('absolute inset-0', claseEstado(estados[0].estado))} />
          )}
          <span
            className="absolute inset-0 flex items-center justify-center text-[10.5px] leading-none font-medium tabular-nums"
            aria-hidden
          >
            {contenido.tipo === 'total' && <span className={texto}>{contenido.valor}</span>}
            {contenido.tipo === 'error' && <span className={texto}>!</span>}
            {contenido.tipo === 'punto' && <span className="size-1.5 rounded-full bg-sky-600 dark:bg-sky-300" />}
          </span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{tooltip}</TooltipContent>
    </Tooltip>
  );
});

interface MesProps {
  anio: number;
  mes: number;
  onZip: () => void;
  onExcel: () => void;
  ocupado: boolean;
}

function EncabezadoMes({ anio, mes, onZip, onExcel, ocupado }: MesProps) {
  const [abierto, setAbierto] = useState(false);
  return (
    <Popover open={abierto} onOpenChange={setAbierto}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Exportar ${MESES[mes - 1]} ${anio}`}
          className="flex h-7 cursor-pointer items-center justify-between gap-1 rounded-md px-1.5 text-left text-xs font-semibold text-foreground hover:bg-secondary"
        >
          {MESES[mes - 1].slice(0, 3)}
          <Icon icon="ph:caret-down-light" className="size-3 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-56 space-y-1 p-1.5">
        <p className="px-2 py-1 text-xs font-medium text-muted-foreground">
          {MESES[mes - 1]} {anio}
        </p>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start"
          disabled={ocupado}
          onClick={() => {
            setAbierto(false);
            onZip();
          }}
        >
          <Icon icon="ph:file-zip-light" className="size-4" />
          Exportar ZIP de XML
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start"
          disabled={ocupado}
          onClick={() => {
            setAbierto(false);
            onExcel();
          }}
        >
          <Icon icon="ph:file-xls-light" className="size-4" />
          Exportar Excel
        </Button>
        <p className="px-2 pb-1 text-[11px] leading-snug text-muted-foreground">
          El ZIP trae los vigentes del calendario; el Excel es el reporte del procesador e incluye
          los cancelados con su estatus.
        </p>
      </PopoverContent>
    </Popover>
  );
}

interface Props {
  cal: CalendarioAnio;
  filtro: FiltroDireccion;
  sinPiloto: boolean;
  exportando: boolean;
  onAbrirDia: (fecha: string) => void;
  onZip: (mes: number) => void;
  onExcel: (mes: number) => void;
}

/** 12 filas (mes) × 31 columnas (día). Solo este bloque hace scroll horizontal. */
export function CuadroGrid({ cal, filtro, sinPiloto, exportando, onAbrirDia, onZip, onExcel }: Props) {
  const anioHoy = Number(cal.hoy.slice(0, 4));
  const mesHoy = Number(cal.hoy.slice(5, 7));
  const diaHoy = Number(cal.hoy.slice(8, 10));
  const esAnioActual = cal.anio === anioHoy;

  // Una lectura por día visible, estable mientras no cambien el calendario ni el
  // filtro: abrir un día o exportar no vuelve a pintar las ~365 celdas.
  const lecturas = useMemo(() => {
    const out = new Map<string, LecturaCelda>();
    for (let mes = 1; mes <= 12; mes++) {
      for (let d = 1; d <= diasDelMes(cal.anio, mes); d++) {
        const fecha = fechaIso(cal.anio, mes, d);
        if (!esFutura(fecha, cal.hoy)) out.set(fecha, celda(cal, fecha, filtro, { sinPiloto }));
      }
    }
    return out;
  }, [cal, filtro, sinPiloto]);

  return (
    <div className="overflow-x-auto pb-1">
      <div
        className="grid w-max items-center gap-0.5"
        style={{ gridTemplateColumns: '4.25rem repeat(31, 1.75rem)' }}
        role="group"
        aria-label={`Descargas de ${cal.anio}`}
      >
        <div />
        {DIAS.map((d) => (
          <div
            key={d}
            className={cn(
              'flex h-6 items-center justify-center rounded-md text-[10.5px] tabular-nums text-muted-foreground',
              esAnioActual && d === diaHoy && 'bg-primary font-bold text-primary-foreground',
            )}
          >
            {d}
          </div>
        ))}

        {MESES.map((_, i) => {
          const mes = i + 1;
          const total = diasDelMes(cal.anio, mes);
          return (
            <MesFila
              key={mes}
              cal={cal}
              mes={mes}
              total={total}
              lecturas={lecturas}
              exportando={exportando}
              esMesHoy={esAnioActual && mes === mesHoy}
              diaHoy={diaHoy}
              onAbrirDia={onAbrirDia}
              onZip={onZip}
              onExcel={onExcel}
            />
          );
        })}
      </div>
    </div>
  );
}

interface FilaProps {
  cal: CalendarioAnio;
  mes: number;
  total: number;
  lecturas: Map<string, LecturaCelda>;
  exportando: boolean;
  esMesHoy: boolean;
  diaHoy: number;
  onAbrirDia: (fecha: string) => void;
  onZip: (mes: number) => void;
  onExcel: (mes: number) => void;
}

function MesFila({
  cal, mes, total, lecturas, exportando, esMesHoy, diaHoy, onAbrirDia, onZip, onExcel,
}: FilaProps) {
  return (
    <>
      <EncabezadoMes
        anio={cal.anio}
        mes={mes}
        ocupado={exportando}
        onZip={() => onZip(mes)}
        onExcel={() => onExcel(mes)}
      />
      {DIAS.map((d) => {
        if (d > total) return <div key={d} className="size-7" />;
        const lectura = lecturas.get(fechaIso(cal.anio, mes, d));
        if (!lectura) {
          return <div key={d} className="size-7 rounded-[5px] border border-border/30 opacity-40" aria-hidden />;
        }
        return (
          <CeldaDia
            key={d}
            lectura={lectura}
            esHoy={esMesHoy && d === diaHoy}
            onAbrir={onAbrirDia}
          />
        );
      })}
    </>
  );
}

'use client';

import { useMemo, useState } from 'react';

import { useServer } from '@/providers/server-provider';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Icon } from '@/components/ui/icon';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ListaNegraMatch, ListasNegrasMetadata } from '@/lib/types';

import { MatchBadge, etiquetaDeMatch, type EtiquetaLista } from './match-badge';
import { MetadataChip } from './metadata-chip';
import { mensajeDeError } from '@/lib/errores';

/** Trim + upper + dedupe; descarta tokens vacíos. */
function parsearRfcs(texto: string): string[] {
  const visto = new Set<string>();
  const out: string[] = [];
  for (const raw of texto.split(/[\s,;\n\r\t]+/)) {
    const rfc = raw.trim().toUpperCase();
    if (!rfc || visto.has(rfc)) continue;
    visto.add(rfc);
    out.push(rfc);
  }
  return out;
}

function descargarCsv(matches: ListaNegraMatch[]): void {
  const lineas: string[] = [
    'RFC,EnLista69B,Situacion69B,FechaPublicacion69B,EnLista69,Supuestos69,RiskLevel,Etiqueta',
  ];
  for (const m of matches) {
    const fila = [
      m.rfc,
      m.en_lista_69b ? 'Si' : 'No',
      m.situacion_69b ?? '',
      m.fecha_publicacion_69b ?? '',
      m.en_lista_69 ? 'Si' : 'No',
      m.supuestos_69.join('|'),
      m.risk_level,
      etiquetaDeMatch(m),
    ];
    // Escape para CSV: si contiene coma/comilla, envolver y duplicar comillas.
    lineas.push(fila.map((c) => {
      const s = String(c);
      return /[,"\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(','));
  }
  const blob = new Blob(['﻿' + lineas.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `listas-negras-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function ValidarRfcsTab() {
  const { apiClient } = useServer();
  const [texto, setTexto] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [matches, setMatches] = useState<ListaNegraMatch[]>([]);
  const [metadata, setMetadata] = useState<ListasNegrasMetadata | null>(null);

  const rfcsParseados = useMemo(() => parsearRfcs(texto), [texto]);

  async function onConsultar() {
    if (rfcsParseados.length === 0) {
      setError('Pega o escribe al menos un RFC.');
      return;
    }
    setError(null);
    setBusy(true);
    try {
      const res = await apiClient.listasNegrasConsultar(rfcsParseados);
      setMatches(res.matches);
      setMetadata(res.metadata);
    } catch (e) {
      setError(mensajeDeError(e));
    } finally {
      setBusy(false);
    }
  }

  function onLimpiar() {
    setTexto('');
    setMatches([]);
    setError(null);
  }

  const conteos = useMemo(() => {
    const c: Record<EtiquetaLista, number> = { EFOS: 0, Aclarado: 0, '69': 0, Limpio: 0 };
    for (const m of matches) c[etiquetaDeMatch(m)]++;
    return c;
  }, [matches]);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Validar RFCs sueltos</CardTitle>
          <CardDescription>
            Pega una lista de RFCs (uno por línea o separados por coma) y consulta
            contra las listas del SAT (Art. 69 y 69-B). No requiere tener XMLs cargados.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <textarea
            value={texto}
            onChange={(e) => setTexto(e.target.value)}
            placeholder={'AAA010101AAA\nBBB020202BBB\nCCC030303CCC'}
            rows={6}
            className="w-full rounded-md border bg-background p-3 font-mono text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            disabled={busy}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-muted-foreground">
              {rfcsParseados.length} {rfcsParseados.length === 1 ? 'RFC detectado' : 'RFCs detectados'}
            </span>
            <div className="flex gap-2">
              {matches.length > 0 && (
                <Button variant="outline" size="sm" onClick={onLimpiar} disabled={busy}>
                  Limpiar
                </Button>
              )}
              <Button onClick={onConsultar} disabled={busy || rfcsParseados.length === 0}>
                {busy ? (
                  <>
                    <Icon icon="ph:circle-notch-light" className="size-4 animate-spin" />
                    Consultando…
                  </>
                ) : (
                  <>
                    <Icon icon="ph:shield-check-light" className="size-4" />
                    Consultar
                  </>
                )}
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Alert variant="destructive">
          <Icon icon="ph:warning-light" className="size-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {matches.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <CardTitle className="text-base">Resultados</CardTitle>
                <CardDescription>
                  {matches.length} RFC{matches.length === 1 ? '' : 's'} consultado
                  {matches.length === 1 ? '' : 's'}: EFOS {conteos.EFOS}, aclarados{' '}
                  {conteos.Aclarado}, en 69 {conteos['69']} y limpios {conteos.Limpio}.
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <MetadataChip metadata={metadata} />
                <Button variant="outline" size="sm" onClick={() => descargarCsv(matches)}>
                  <Icon icon="ph:download-simple-light" className="size-4" />
                  CSV
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>RFC</TableHead>
                  <TableHead>Resultado</TableHead>
                  <TableHead>Situación 69-B</TableHead>
                  <TableHead>Supuestos 69</TableHead>
                  <TableHead>Publicación</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {matches.map((m) => (
                  <TableRow key={m.rfc}>
                    <TableCell className="font-mono text-xs">{m.rfc}</TableCell>
                    <TableCell>
                      <MatchBadge etiqueta={etiquetaDeMatch(m)} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {m.situacion_69b ?? <span className="text-muted-foreground">–</span>}
                    </TableCell>
                    <TableCell className="text-sm">
                      {m.supuestos_69.length > 0
                        ? m.supuestos_69.join(', ')
                        : <span className="text-muted-foreground">–</span>}
                    </TableCell>
                    <TableCell className="text-sm tabular-nums">
                      {m.fecha_publicacion_69b ?? <span className="text-muted-foreground">–</span>}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

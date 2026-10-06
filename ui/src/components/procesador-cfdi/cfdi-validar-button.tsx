'use client';

import { useState } from 'react';
import { toast } from 'sonner';

import { useServer } from '@/providers/server-provider';
import { Button } from '@/components/ui/button';
import { Icon } from '@/components/ui/icon';
import { mensajeDeError } from '@/lib/errores';

interface Props {
  /** RFC de la empresa activa: se validan solo los CFDIs de su buffer. */
  rfc: string;
  /** Llamado tras una validación exitosa para refrescar el listado. */
  onValidado: () => void;
}

/**
 * Dispara las dos validaciones que el agente hace contra el SAT:
 *  - Estatus del CFDI (Vigente / Cancelado / No encontrado) — endpoint público.
 *  - Listas negras del Art. 69 / 69-B del CFF (EFOS/EDOS) — API de todoconta.
 *
 * Ambas en paralelo para que el usuario las dispare con un solo click. Si una
 * falla, la otra sigue (típicamente listas negras puede fallar con 401 si la
 * sesión expiró; el estatus CFDI siempre funciona porque no requiere auth).
 */
export function CfdiValidarButton({ rfc, onValidado }: Props) {
  const { apiClient } = useServer();
  const [busy, setBusy] = useState(false);

  async function validar() {
    setBusy(true);

    const [estatusRes, listasRes] = await Promise.allSettled([
      apiClient.procesadorValidarSat(rfc),
      apiClient.procesadorValidarListasNegras(rfc),
    ]);

    const partes: string[] = [];
    let huboCambios = false;

    if (estatusRes.status === 'fulfilled') {
      const r = estatusRes.value;
      if (r.validados > 0) {
        huboCambios = true;
        let resumen = `Estatus SAT: ${r.validados} validados (${r.vigentes} vigentes, ${r.cancelados} cancelados`;
        if (r.no_encontrados > 0) resumen += `, ${r.no_encontrados} no encontrados`;
        if (r.errores > 0) resumen += `, ${r.errores} con error`;
        partes.push(`${resumen})`);
      } else {
        partes.push('Estatus SAT: sin CFDIs pendientes.');
      }
    } else {
      const msg = mensajeDeError(estatusRes.reason);
      toast.error(`Estatus SAT falló: ${msg}`);
    }

    if (listasRes.status === 'fulfilled') {
      const r = listasRes.value;
      if (r.validados > 0) {
        huboCambios = true;
        partes.push(
          `Listas 69 y 69-B: ${r.validados} RFCs (EFOS ${r.efos}, aclarados ${r.aclarados}, en 69 ${r.lista_69}, limpios ${r.limpios})`,
        );
      } else {
        partes.push('Listas 69 y 69-B: RFCs verificados (válidos por 30 días).');
      }
    } else {
      const msg = mensajeDeError(listasRes.reason);
      // 401 = sesión no iniciada. Mensaje amable y no rojo, porque el flujo de
      // estatus SAT igual pudo haber funcionado.
      if (/401|sesi[óo]n/i.test(msg)) {
        toast.warning('Listas 69/69-B requieren iniciar sesión en la app.');
      } else {
        toast.error(`Listas 69/69-B fallaron: ${msg}`);
      }
    }

    if (partes.length > 0) {
      toast.success(partes.map((p) => p.replace(/\.$/, '')).join('. ') + '.');
    }
    if (huboCambios) {
      onValidado();
    }

    setBusy(false);
  }

  return (
    <Button variant="outline" size="sm" onClick={validar} disabled={busy}>
      <Icon
        icon={busy ? 'ph:circle-notch-light' : 'ph:shield-check-light'}
        // Lo automático corriendo va en cian (Señal).
        className={busy ? 'size-4 animate-spin text-auto' : 'size-4'}
      />
      {busy ? 'Validando…' : 'Validar contra SAT'}
    </Button>
  );
}

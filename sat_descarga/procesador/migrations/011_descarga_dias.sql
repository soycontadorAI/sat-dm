-- 011_descarga_dias.sql
-- Cuadro de control de descargas (docs/producto/descarga-programada.md,
-- fase 2): una fila por empresa, día de emisión y dirección (E = emitidos,
-- R = recibidos) con el estado de su descarga.
--
-- Lo alimentan las solicitudes al Web Service, las descargas del portal y el
-- propio índice de CFDIs (procesador/calendario.py). Un día sin fila es
-- `pendiente`: la tabla solo guarda lo que ya pasó algo. `total_bd` es el
-- conteo del índice local; `total_sat` lo llena el cierre mensual (metadata).
-- Solo el cierre mensual escribe `consolidado` y `diferencia`.

CREATE TABLE IF NOT EXISTS descarga_dias (
    mi_rfc TEXT NOT NULL,
    fecha TEXT NOT NULL,                 -- YYYY-MM-DD, fecha de emisión (como filtra el SAT)
    direccion TEXT NOT NULL CHECK (direccion IN ('E', 'R')),
    estado TEXT NOT NULL CHECK (estado IN ('pendiente','en_proceso','provisional','consolidado','diferencia','error')),
    total_bd INTEGER NOT NULL DEFAULT 0,
    total_sat INTEGER,
    ultima_solicitud_id TEXT,
    error_codigo TEXT,
    error_mensaje TEXT,
    intentos INTEGER NOT NULL DEFAULT 0,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (mi_rfc, fecha, direccion)
);

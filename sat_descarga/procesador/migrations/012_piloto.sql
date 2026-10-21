-- 012_piloto.sql
-- Descarga automática (piloto, docs/producto/descarga-programada.md fase 4).
--
-- `piloto_ejecuciones`: el candado contra duplicados. Una fila por (empresa,
-- tipo, periodo): la pasada diaria de un día ('diaria', 'YYYY-MM-DD') o el
-- cierre de un mes ('cierre', 'YYYY-MM'). Se reserva ANTES de pedir nada al
-- SAT; si la fila existe, se retoma su paso (`detalle`, JSON) en vez de volver
-- a pedir. `proximo_intento` pospone los reintentos tras una falla del SAT.
-- El candado entre instalaciones (web y escritorio) vivirá en Supabase.
--
-- `piloto_avisos`: lo que el piloto le cuenta al usuario (resumen del cierre,
-- cancelaciones de meses ya cerrados, e.firma que no abre). `clave` evita
-- repetir el mismo aviso.
--
-- `cfdis.fecha_cancelacion`: la llena el cierre con la metadata del SAT.

CREATE TABLE IF NOT EXISTS piloto_ejecuciones (
    mi_rfc TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('diaria', 'cierre')),
    periodo TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('en_curso', 'completa', 'error')),
    intentos INTEGER NOT NULL DEFAULT 0,
    proximo_intento TEXT,
    detalle TEXT NOT NULL DEFAULT '{}',
    error_codigo TEXT,
    error_mensaje TEXT,
    creado_en TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (mi_rfc, tipo, periodo)
);

CREATE TABLE IF NOT EXISTS piloto_avisos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clave TEXT UNIQUE,
    tipo TEXT NOT NULL,
    mi_rfc TEXT,
    periodo TEXT,
    mensaje TEXT NOT NULL,
    creado_en TEXT NOT NULL,
    leido INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE cfdis ADD COLUMN fecha_cancelacion TEXT;

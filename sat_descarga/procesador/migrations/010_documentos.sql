-- 010_documentos.sql
-- El procesador deja de ser un buffer temporal: es el índice permanente de
-- los CFDIs de cada empresa (docs/producto/descarga-programada.md). Cada CFDI
-- guarda tres capas:
--
-- · columnas planas de `cfdis` (filtros, reportes, DIOT) — ya existían;
-- · el XML original, comprimido con zlib: la fuente de verdad, de la que se
--   puede volver a extraer todo si el parser mejora. Vive aquí y no como
--   ruta a la carpeta de descargas porque el organizador mueve, renombra y
--   borra esos archivos;
-- · `nodos`: el XML completo como JSON (procesador/nodos.py), base de los
--   reportes personalizables. También comprimido: en local no se consulta
--   con SQL y pesa casi lo mismo que el XML (medido: ~50 KB por ingreso).
--
-- Va en tabla aparte para que listar `cfdis` no cargue los blobs. Las filas
-- previas a esta migración quedan sin documento hasta que se vuelvan a
-- indexar (el agente lo hace solo con la carpeta de descargas al arrancar).
--
-- `cfdis.origen`: de dónde entró el CFDI — 'sat_ws' (Web Service),
-- 'sat_portal' (portal con contraseña o e.firma), 'carpeta' (indexado de la
-- carpeta de descargas) o 'manual' (el usuario subió los XML). NULL = antes
-- de esta migración.

ALTER TABLE cfdis ADD COLUMN origen TEXT;

CREATE TABLE IF NOT EXISTS cfdi_documentos (
    uuid TEXT NOT NULL,
    mi_rfc TEXT NOT NULL,
    xml_zlib BLOB NOT NULL,
    nodos_zlib BLOB NOT NULL,
    nodos_version INTEGER NOT NULL,
    PRIMARY KEY (uuid, mi_rfc),
    FOREIGN KEY (uuid, mi_rfc) REFERENCES cfdis(uuid, mi_rfc) ON DELETE CASCADE
);

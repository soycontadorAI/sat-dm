# Plantillas de exportación del procesador de CFDI

Cada usuario elige qué columnas lleva el Excel/CSV de CFDIs, en qué orden y con qué
encabezado. Es la fase 7 de [`descarga-programada.md`](descarga-programada.md), adelantada por
una queja real: un contador pidió volver al formato de la app web vieja (todo en una hoja, con
conceptos y datos del pago), y cada despacho quiere columnas distintas.

Código: `sat_descarga/procesador/plantillas.py` (catálogo, plantillas del sistema, motor),
`plantillas_store.py` (las del usuario), `exportar.py` (`plantilla_a_xlsx` / `plantilla_a_csv`),
`api/routers/plantillas.py`. UI: diálogo en `components/procesador-cfdi/cfdi-export-buttons.tsx`
y editor en `/comprobantes/plantillas` (`components/plantillas/columnas-editor.tsx`).

## Modelo

Una plantilla tiene un nombre y dos listas de columnas `{campo, encabezado}`:

- `columnas`: las del CFDI (campos de nivel `cfdi`).
- `detalle_concepto`: el bloque que se usa con "Una fila por concepto" (nivel `concepto`). Va en
  el lugar de la columna "Conceptos"; si la plantilla no la tiene, al final.

Dos opciones se eligen al exportar (no viven en la plantilla) y **arrancan apagadas**:

- **Una fila por concepto** (como XMLSAT Premium): repite los datos del CFDI en cada renglón;
  útil para inventarios. La columna "Concepto #" ("1 de 3") permite filtrar `1 de` para sumar
  importes del CFDI sin multiplicarlos.
- **Convertir a MXN** (la app web vieja lo tenía): importes en moneda extranjera × el tipo de
  cambio del CFDI; los del complemento de pago, × el `TipoCambioP` de cada pago. El encabezado
  lleva " MXN". El tipo de cambio en sí no se convierte.

## Catálogo de campos

~70 campos en grupos (comprobante, emisor y receptor, importes, impuestos por tasa, forma y
método de pago, complemento de pago, conceptos, validación, clasificación y detalle del
concepto). Se leen de las columnas planas del índice o de `nodos`; los de `nodos` caen a lo
plano o a `raw` si el CFDI no tiene documento. Además, cualquier dato del XML por su ruta:
`ruta:Comprobante.Complemento.CartaPorte.Version` o, relativa al concepto,
`ruta_concepto:InformacionAduanera.NumeroPedimento`.

Los datos por concepto que no están en la tabla `conceptos` (No. identificación, objeto de
impuesto, impuestos por concepto, pedimento) salen de `nodos`: es para lo que se guardó el XML
completo en la fase 1.

## Plantillas del sistema

- **Formato clásico** (predeterminada): las 25 columnas del CSV de la app web vieja
  (todoconta-apps `csv-generator.ts`, modo "un renglón por CFDI con pagos", borrado en 481f9cb),
  que es el que mandó el usuario como plantilla. Mejoras sobre aquel: suma **todos** los pagos
  de un REP (el viejo tomaba el primero), fechas e importes como valores de Excel, y las
  descripciones repetidas se agrupan ("Magna ×250": las facturas globales traen cientos).
- **Completo**: las columnas del export anterior del escritorio, en una hoja. Corrige que
  "IVA Trasladado" era solo el 16% y agrega el IVA al 8%.

Las del sistema no se editan ni se borran; se duplican. Las del usuario viven en
`~/.sat-descarga/plantillas-export.json` con `updated_at`, listas para sincronizarse.

## API

- `GET /procesador/cfdi/campos`, `GET|POST /procesador/plantillas`,
  `PUT|DELETE /procesador/plantillas/{id}`, `PUT /procesador/plantillas/{id}/predeterminada`.
- `POST /procesador/cfdi/vista-previa`: renglones más recientes con una plantilla guardada o la
  que se edita.
- `GET /procesador/cfdi/exportar?plantilla=…&por_concepto=…&convertir_mxn=…`. **Sin
  `plantilla` no cambia nada**: sale el export de dos hojas de siempre (API pública y MCP).

## Límites y seguridad

- Una hoja de Excel admite 1,048,575 renglones: antes de generar, `contar_renglones` estima el
  total (exacto en las pruebas con datos reales, 0.3 s) y responde 400 sugiriendo CSV o un
  periodo más corto. El CSV no tiene tope.
- Una celda de Excel admite 32,767 caracteres: se recorta con "…".
- **Los textos vienen del XML (los escribe el emisor) y nunca se escriben como fórmula**: en
  Excel se fuerzan a texto; en CSV, los que empiezan con `= + - @` llevan `'`. El export de dos
  hojas de siempre tenía el hueco (una descripción `=HYPERLINK(…)` quedaba como fórmula) y se
  corrigió igual.

## Rendimiento (carpeta real, 11 RFC)

| Export | Tiempo |
|---|---|
| Formato clásico, gasolinera (4,558 CFDI) | 5.1 s |
| Una fila por concepto, 216,590 renglones, Excel | 56 s |
| Lo mismo en CSV | ~28 s |

El grueso del Excel grande es openpyxl escribiendo celdas; el motor genera los 216 mil
renglones en ~19 s. Las celdas con formato se reutilizan por columna (antes eran 196 s).

## Pendientes

- **Sync desktop ⇄ online** de las plantillas (mismo patrón LWW que las tareas) y compartirlas
  con el equipo del despacho.
- **Medir la adopción**: el evento `excel_exportado` no distingue plantilla ni opciones; ampliar
  la taxonomía en los dos lados (`api/uso.py` y `todoconta-apps/.../uso/taxonomia.ts`).
- **MCP / API pública**: exponer `plantilla`, `por_concepto` y `convertir_mxn`.
- Si los Excel por concepto de cientos de miles de renglones son comunes, evaluar `xlsxwriter`.
- Explorador del árbol de `nodos` de un CFDI de ejemplo para elegir rutas sin teclearlas.

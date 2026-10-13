# Descarga programada de CFDI y cuadro de control (diseño)

> **Estado**: diseño, sin código. Decisiones de Israel del 2026-10-12: índice en **Supabase**,
> automático solo en planes con la capacidad `piloto` y el usuario elige **desde qué fecha** se
> llena el historial.
>
> **Relación con F7** (`todoconta-apps/docs/operacion/plan-app-v3.md`, "Piloto automático"): este
> documento es la versión diaria de F7. El "mes anterior el día que el usuario elija" de F7 se vuelve
> el **cierre mensual** de aquí. Siguen valiendo de F7 el candado `piloto_ejecuciones` contra
> duplicados web/escritorio, el escalonamiento, el despertar por agenda y el manejo de 5002/5005.

## Objetivo

Que los XML de cada empresa lleguen solos todos los días a la base de datos de TodoConta. El
usuario ve en un **cuadro de control** (calendario año × día) qué días ya están completos, cuáles
están en proceso y cuáles fallaron. Al pedir un periodo que ya está en la base, se sirve de ahí sin
ir al SAT.

Referencia: el "Historial Descarga" de Contalink. Frente a la descarga programada de CONTPAQi
(00:00-07:00, equipo encendido, una empresa por RFC, sin histórico), aquí: 24/7 en la nube, todas
las empresas del plan, historial desde la fecha que elija el usuario y verificación contra el
conteo del SAT. Ver `docs/negocio/benchmark-contpaqi.md`.

## Qué cambia frente a hoy

| Hoy | Con este diseño |
|---|---|
| Se guardan el ZIP del SAT y los XML extraídos en carpetas | Cada XML se guarda por UUID en el índice. En la nube el ZIP es solo transporte y no se guarda (en local se conserva: la metadata se lee de él). Para exportar (p. ej. a CONTPAQi) se arma un ZIP del periodo pedido. |
| El índice (`procesador.db`) se llena a mano ("cargar desde empresa") | Se indexa solo al bajar cada paquete |
| `raw_json` = `CfdiData` (solo lo que el parser entiende) | Tres capas por CFDI (abajo); nada se pierde |
| No hay registro por día | Tabla de estado por empresa × día × dirección |
| Cada solicitud va al SAT aunque ya tengamos los datos | Antes de pedir se consulta el calendario |
| Cancelaciones: solo con "validar" manual | Barrido mensual de metadata |

## Planes

| | `gratis` | Esencial | Pro, Completo y prueba |
|---|---|---|---|
| Cuadro de control | Sí, con lo descargado a mano | Sí | Sí |
| Descarga automática diaria + cierre | No (celdas vacías con "Actívalo con Pro") | Candado | **Sí** (capacidad `piloto`) |
| Llenado de historial desde una fecha | No | Candado | Sí |
| Índice y XML en la nube (Supabase) | No: solo local (`procesador.db`) | Sí | Sí |
| Cupo de descargas | 10 al mes (manuales) | Sin límite | Sin límite |

- Lo automático **no consume** el cupo de descargas: solo existe en planes sin tope. Así no hay
  forma de que el piloto agote el cupo de nadie.
- El cuadro de control se muestra en **todos** los planes. En `gratis` las celdas se llenan con
  lo que el usuario baja a mano y el resto queda vacío, con la llamada a Pro. Es la palanca de
  conversión: el usuario ve los huecos.
- La nube es parte del plan de pago: la desktop siempre guarda local; con plan de pago, además,
  sube a Supabase. Al subir de plan se suben los CFDI locales existentes.

## Cómo funciona

### Unidad de trabajo: el día

Estado por `(usuario, rfc, fecha, direccion)` con `direccion ∈ {E, R}`. La celda del calendario
combina E y R.

| Estado | Color | Significado |
|---|---|---|
| `pendiente` | blanco | Nadie lo ha pedido |
| `en_proceso` | azul | Solicitud hecha, esperando al SAT |
| `provisional` | verde claro | Descargado en la pasada diaria; aún puede llegar algo |
| `consolidado` | verde | Cierre mensual hecho y el conteo cuadra con el SAT |
| `diferencia` | ámbar | Cierre hecho pero el conteo no cuadra (p. ej. "SAT 120 · BD 118") |
| `error` | rojo | Falló después de los reintentos, o error del usuario (e.firma) |

Un día sin CFDI se marca `provisional` o `consolidado` con `total = 0`. La celda muestra "0", no
se queda en blanco.

### Pasada diaria (planes con `piloto`)

Cada madrugada, escalonado por cuenta (F7), para cada empresa incluida con e.firma vigente:

1. Toma D-1 y su ventana de rezago (ver abajo), y descarta los días ya `consolidado`.
2. Pide XML de emitidos y de recibidos (recibidos: solo Vigente, regla del WS v1.5).
3. El poller existente verifica y baja. Al bajar cada paquete: indexa (3 capas), hace upsert por
   `(usuario, rfc, uuid)` y marca los días como `provisional`.

**Rezago de timbrado.** Un CFDI se puede timbrar hasta 72 h después de su fecha de emisión y el WS
tarda en reflejarlo. Por eso cada pasada pide `D-3 … D-1` y no solo `D-1`. Son rangos distintos
cada día, así que no choca con 5005. Lo repetido lo absorbe el upsert por UUID.

### Cierre mensual

El día que elija el usuario (default: el 5, alineado con la regla del CFDI Global), para el mes
anterior:

1. Pide la **metadata** del mes (emitidos y recibidos). Da el conteo y el estatus de cada UUID.
2. Compara contra la base, día por día. Si un UUID vigente de la metadata no está en la base, pide
   esos XML (por UUID o por día). Si al final cuadra, el día queda `consolidado`; si no, queda
   `diferencia` con el detalle.
3. Manda un resumen: "Tus 24 empresas tienen septiembre completo; 2 con diferencias".

### Cancelaciones

En el WS v1.5 el XML de un recibido cancelado no se entrega. El estatus llega por metadata. Cada
cierre mensual, además del mes anterior, pide la metadata del **ejercicio en curso** y actualiza
`estado_sat` y `fecha_cancelacion`. Una cancelación nueva de un mes ya cerrado genera un aviso,
porque puede afectar una deducción ya declarada.

### Llenado del historial

Al activar el piloto, el usuario elige **desde qué fecha** (límite del WS v1.5: 5 años). Se pide
mes por mes, del más reciente al más antiguo, a un ritmo pausado (pocas solicitudes por empresa
por noche), y cada mes entra directo como cierre: XML + metadata → `consolidado` o `diferencia`.
El calendario se va pintando hacia atrás.

### Solicitud manual

Cuando el usuario pide un rango a mano (cualquier plan):

- Los días `consolidado` se sirven de la base, sin ir al SAT.
- Solo se pide al SAT el resto, partido en los rangos mínimos que cubren los huecos.
- El resultado también pinta el calendario.

### Errores

| Causa | Qué pasa |
|---|---|
| SAT caído, 404 "Error no controlado", SSL, 5006 | Reintento con espera creciente; la celda sigue `en_proceso`. Pasa a `error` hasta agotar los reintentos (p. ej. 3 días). |
| e.firma vencida o contraseña cambiada | `error` inmediato, con motivo y aviso. La empresa se salta hasta que se corrija. |
| 5002 (solicitudes agotadas para ese rango) | `error` con motivo, sin reintentos (F7). |
| 5005 (solicitud duplicada) | Se toma como "ya pedido" y se espera la existente. |
| 5004 (sin información) | `provisional` o `consolidado` con 0. |

## Modelo de datos (Supabase, migración nueva en todoconta-apps)

No se reutiliza `public.cfdis` del producto web viejo: cuelga de `empresas(id)`, no de
`empresas_catalogo (user_id, rfc)`, y solo tiene columnas de reporte. Tablas nuevas:

**`sat_cfdis`**: un renglón por CFDI y empresa.
- Llave: `(user_id, rfc, uuid)`. `rfc` = la empresa del catálogo; `direccion` E/R respecto a ella.
- Columnas planas para filtros e índices: `fecha_emision`, `fecha_timbrado`, `tipo`, `serie`,
  `folio`, `emisor_rfc/nombre`, `receptor_rfc/nombre`, `total`, `subtotal`, `moneda`,
  `metodo_pago`, `forma_pago`, bases e IVA por tasa, retenciones, `estado_sat`,
  `fecha_cancelacion`, `validado_en`.
- `nodos jsonb`: el XML completo convertido a JSON de forma genérica (todos los nodos, atributos,
  complementos y addendas). Es la base de los **reportes personalizables**: una plantilla es una
  lista de rutas (`Comprobante.Folio`, `Emisor.Nombre`,
  `Complemento.CartaPorte.Mercancias.PesoBrutoTotal`…) con nombre de columna.
- `xml_path`: ruta del XML original en el bucket.
- `parser_version`: para reprocesar cuando mejore la extracción.

**Bucket `sat-xml`** (privado): `{user_id}/{rfc}/{yyyy}/{mm}/{uuid}.xml`. El XML original es la
fuente de verdad.

**`sat_descarga_dias`**: el calendario.
- Llave `(user_id, rfc, fecha, direccion)`.
- `estado`, `total_bd`, `total_sat` (de la metadata, si hay), `ultima_solicitud_id`, `error_codigo`,
  `error_mensaje`, `intentos`, `actualizado_en`.

**`piloto_ejecuciones`**: de F7. Es el candado contra duplicar entre web y escritorio.

RLS: dueño por `user_id`, con la extensión a equipo que ya usan las tablas de la app.

En la desktop, `procesador.db` sigue existiendo como caché local (y como único almacén en
`gratis`). Se le agregan `nodos` y la ruta del XML, con las mismas tres capas.

## Dónde corre

- **Web (agente hosted)**: el planificador corre ahí 24/7. Requiere la e.firma en el espacio
  ("continuidad de credenciales"). Si el contenedor está detenido, el provisioner lo despierta el
  día programado (F2).
- **Escritorio**: con la app abierta, se pone al corriente de los días que falten y respeta el
  candado `piloto_ejecuciones` para no duplicar lo que ya hizo la web.
- Ambos escriben a Supabase. La desktop baja del índice en la nube lo que no tenga local.

## Pantalla: cuadro de control

- En Descargas, por empresa: selector de año, una fila por mes y 31 columnas por día. El
  encabezado resalta el día de hoy.
- Filtro "Emitidos / Recibidos / Ambos".
- Leyenda: por descargar · en proceso · provisional · consolidado · diferencia · error.
- Clic en un día: total de CFDI (E/R), lista, solicitudes al SAT que lo llenaron y error si lo
  hay. Acción "Reintentar" en `error` y `diferencia`.
- Clic en un mes: "Exportar ZIP de XML" (para CONTPAQi) y "Exportar Excel" (plantilla de reporte).
- Arriba: estado del piloto (activo/pausado), próxima corrida, e.firma (semáforo y vencimiento) y
  "Llenar historial desde…".
- En `gratis` y Esencial: el mismo calendario con candado en los controles del piloto.

## Fases de implementación

1. **Tres capas + indexado automático (local).** ✅ Rama `feat/indexado-tres-capas`. Ver
   "Fase 1: lo que se implementó" abajo.
2. **Calendario local.** `descarga_dias` en `procesador.db`, alimentado por descargas manuales y
   por el poller; pantalla del cuadro de control. Visible en todos los planes.
3. **Supabase.** Tablas `sat_cfdis`, `sat_descarga_dias` y el bucket; subida desde el agente con
   plan de pago; la desktop baja lo que no tenga.
4. **Planificador** (`sat_descarga/api/piloto.py`, F7): pasada diaria con rezago, cierre mensual
   con metadata, cancelaciones y candado `piloto_ejecuciones`. Gateado por `piloto`.
5. **Llenado del historial** desde la fecha elegida.
6. **Solicitud manual inteligente**: servir de la base lo consolidado y pedir solo los huecos.
7. **Reportes personalizables** sobre `nodos` (plantillas).

## Fase 1: lo que se implementó

Decisión de Israel (2026-10-12): **un solo almacén**. El procesador de comprobantes deja de ser
un buffer temporal y pasa a ser el índice permanente; se quita "Vaciar el procesador" de la UI
(el endpoint queda para el modo grabación).

- `procesador/nodos.py`: XML → `nodos` (forma documentada en el módulo; `valores()` resuelve
  rutas con o sin listas).
- Migración `010_documentos.sql`: `cfdis.origen` (`sat_ws`, `sat_portal`, `carpeta`, `manual`)
  y `cfdi_documentos` con el XML y los `nodos` **comprimidos** (zlib). El XML vive en la DB y
  no como ruta, porque el organizador mueve, renombra y borra los archivos de la carpeta.
- `procesador/indexar.py`: una sola tubería para descargas del SAT (gancho en
  `_registrar_descarga`, en segundo plano), carpeta existente (una vez por empresa al arrancar),
  subida manual y "cargar desde empresa". Lotes de 500. Kill switch `SAT_DM_SIN_INDEXADO=1`.
- **En local el ZIP del SAT se conserva**: la lectura de metadata (`utils/metadata.py`) lee los
  `.zip` de la carpeta. "No guardar el ZIP" aplica a la nube (fase 3).

**Medido** con la carpeta real de Israel (11 RFC, 13,647 XML → 8,378 CFDI únicos): 61 s de
indexado completo; DB de 442 MB. De eso, los documentos nuevos (XML + `nodos` comprimidos) son
solo 81 MB; el grueso ya venía del diseño anterior: `raw_json` (183 MB) y la tabla `conceptos`
(911 mil filas, 166 MB con su índice), por los CFDI globales de gasolinera. Promedios por CFDI:
ingreso 58 KB de XML (5 KB comprimido), nómina 6 KB, pago 6 KB.

**Pendientes que salieron de la fase 1:**
- `raw_json` ya es redundante con XML + `nodos`; quitarlo (regenerando lo que lo lea) baja la
  DB a menos de la mitad.
- 45 XML reales no se pueden leer: traen un atributo mal formado
  (`xmlns:schemaLocation`, complemento de registro fiscal). El parser ya los rechazaba antes.
  Hay que leerlos en modo tolerante, o el conteo del cierre mensual nunca va a cuadrar.

## Abierto

- Ritmo del llenado del historial frente a los límites reales del SAT por RFC e IP. Medir en el
  VPS (riesgo ya listado en F7).
- Si el cierre mensual pide metadata del ejercicio completo cada mes o solo de los últimos N meses.

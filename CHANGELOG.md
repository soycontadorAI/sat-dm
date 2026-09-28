# Changelog

> **Nota sobre versionado**: Las entradas previas v0.1.0–v1.2.0 corresponden al paquete Python pip-installable y a metadatos desincronizados de subproyectos. **v1.0.0 (esta) inicia la numeración del producto distribuible TodoConta Desktop** (Python + Next + Electron empaquetado). Ver [docs/infra/versionado.md](docs/infra/versionado.md) para la convención SemVer aplicada.

## [Unreleased]

_Cambios mergeados a `main` aún no etiquetados; el release de la semana los promueve._

### Fix

- **La versión web ya no encierra a quien apenas va entrando.** Si tu prueba
  sigue vigente, la web te deja pasar: antes rebotaba a **todos** los usuarios
  en prueba, porque la validación miraba un campo que el servicio de licencias
  nunca devolvió. Y si tu plan sí venció, el aviso ahora trae el enlace para
  activarlo — antes era un callejón sin salida, porque el pago vive dentro de
  la app y a la app no se podía entrar sin plan.

## [2.1.0] - 2026-08-15

### Feature

- **Tus llaves de API y tu conexión con la IA, en Ajustes.** Ya puedes generar y
  revocar llaves de API desde la app, y conectar TodoConta con tu asistente de IA
  (Claude, ChatGPT) sin salir a la web. La llave se muestra una sola vez al
  crearla; después solo ves cuándo la usaste por última vez.
- **Tu equipo, desde la app.** Invita a tus colaboradores, revisa quién tiene
  acceso y retíralo cuando alguien salga del despacho — todo desde Ajustes, sin
  entrar al portal web.
- **`sat-dm diot presentar`: la DIOT se presenta sola.** Nuevo subcomando que
  sube el TXT de carga masiva a la plataforma DIOT del SAT con e.firma (sin
  captcha), coteja los Totales del portal contra el archivo y —solo con
  `--enviar` y confirmación— firma la declaración y descarga el acuse PDF.
  Por seguridad el default solo valida; con discrepancias de totales nunca
  envía. Limitante: solo contribuyentes sin estímulos fiscales (responde «No»
  automáticamente). El comando `sat-dm diot` existente sigue funcionando y
  ahora también existe como `sat-dm diot generar`.


- **Tus tareas te siguen: se sincronizan entre la app de escritorio y la
  versión web.** Las tareas del centro de mando ahora viajan entre tus
  instalaciones igual que el catálogo de empresas: lo que crees, edites,
  completes o borres en un lado aparece en el otro — los borrados también se
  respetan, nada resucita. Los descartes de sugerencias se comparten igual.
  Best-effort y sin credenciales: solo tus tareas.
- **El organizador recuerda tu configuración — una sola vez para todas tus
  empresas.** La estructura de carpetas, el formato de renombrado y la opción
  de copiar/mover ahora se guardan como configuración global: la defines una
  vez y aplica a todas las empresas del despacho, sin re-elegirla en cada RFC
  ni perderla al reiniciar. Funciona igual en la app de escritorio y en la
  versión web; lo que ya tenías configurado se migra solo.

### Fix

- **Las e.firmas emitidas por la autoridad certificadora vieja del SAT ya se
  pueden dar de alta.** Los certificados firmados por «A.C. del Servicio de
  Administración Tributaria» traen acentos en un campo del emisor que su propio
  formato no permite, y la app los rechazaba con un mensaje críptico ("Unable to
  load PEM file… MalformedFraming") que además apuntaba al archivo equivocado:
  parecía un problema de la clave privada cuando era del certificado. Ahora la
  app tolera ese defecto —el certificado se manda al SAT tal cual, sin
  alterarlo— y, si de plano un .cer no se puede leer, el aviso lo dice en
  español y nombra el archivo correcto. Ninguna e.firma estaba dañada: solo no
  se podían registrar.
- **Descarga por e.firma: mensaje claro y reintento automático cuando el portal
  del SAT rechaza la sesión.** Al descargar comprobantes con e.firma, a veces el
  portal rebota la consulta a su página de error y la app fallaba con el mensaje
  confuso "No se encontró el botón de búsqueda". Ahora la app detecta el rechazo,
  vuelve a iniciar sesión una vez de forma automática (el rebote suele ser
  pasajero) y, si aún así persiste, te lo dice claro: reintenta en unos minutos —
  no hace falta borrar la empresa y volverla a dar de alta.
- **Organizador: adiós a la carpeta «Otros» que mezclaba facturas de varias
  empresas.** Al organizar por Emitidos/Recibidos, las facturas que no son de
  la empresa activa ya no se mueven a «Otros»: se quedan en su lugar y el
  resumen te dice cuántas son. Si ninguna factura de la carpeta pertenece a la
  empresa activa, no se organiza nada y la app te pide activar la empresa
  correcta. Además, volver a organizar la misma carpeta ya no reprocesa la
  salida de corridas anteriores (los archivos ya no "rebotan" ni se duplican
  al alternar entre empresas).
- **Cuando el SAT rechaza algo, ahora te dice qué hacer.** Los rechazos del
  servicio de descarga masiva llegaban como códigos crudos ("CodEstatus=305,
  Certificado Inválido") que no orientaban a nadie. Ahora cada rechazo trae la
  acción concreta: si el SAT no acepta un certificado para la descarga masiva,
  la app te dice que uses Descarga rápida —que funciona con esa misma e.firma—
  antes de mandarte a renovar nada.
- **Empresas dadas de alta hace mucho: su e.firma vuelve a cargar.** Las
  empresas registradas en versiones antiguas guardaban la ubicación de su
  e.firma de una forma que dejaba de funcionar al reinstalar o al usar la
  versión web. La app ahora corrige esas ubicaciones sola, la primera vez que
  abre tu catálogo, sin que tengas que volver a cargar nada.
- **Windows: las sesiones largas dejan de cerrarse solas.** El llavero de
  Windows rechaza credenciales por arriba de cierto tamaño, y eso tumbaba la
  sesión de tu cuenta al guardarla. Ahora se guarda partida en pedazos y la
  sesión persiste como debe.
- **macOS: las actualizaciones automáticas vuelven a funcionar.** El instalador
  no publicaba el formato que el actualizador necesita, así que la app nunca
  encontraba la versión nueva.
- **Si el servicio de cuentas no responde, la app te lo dice.** Un corte de red
  al validar tu suscripción se reportaba como una falla de la app; ahora se
  distingue como lo que es —algo temporal— y te invita a reintentar.

### Copy

- **"CIEC" ahora se llama "Contraseña" en toda la app.** Es como la nombra hoy
  el propio SAT, y es lo que el contribuyente reconoce.

### Tooling

- Bump 2.0.0 → 2.1.0 (3 archivos).

## [2.0.0] - 2026-07-14

Versión mayor: llega **TodoConta en línea**. Tu app de escritorio sigue igual y con
tus datos intactos (`~/.sat-descarga/` no se toca); la versión web es adicional.

### Feature

- **Ahora también puedes usar TodoConta desde el navegador (app.todoconta.com).**
  Los mismos trámites del SAT, ahora también en línea. Desde la app de escritorio
  puedes activar **«Usar en la web»** para subir tus credenciales cifradas a tu
  espacio privado y operar desde cualquier equipo; tu **catálogo de empresas y tu
  configuración fiscal se sincronizan** entre la desktop y la versión en línea. Las
  credenciales solo viajan si tú lo eliges: por defecto tu e.firma nunca sale de tu
  equipo.

- **La Opinión de Cumplimiento 32-D ahora pinta el semáforo de la empresa y
  explica por qué sale negativa.** Al descargar la opinión (CIEC o e.firma) el
  agente lee el PDF y detecta su **sentido**: si es **positiva** el semáforo de
  la empresa se pone **verde**, si es **negativa** se pone **rojo**. Cuando es
  negativa, el detalle de la empresa lista **los motivos** que el SAT marca
  (créditos fiscales firmes, omisiones de obligaciones, buzón tributario, listado
  69-B, domicilio no localizado, …) con su descripción y periodos. El análisis es
  agnóstico al tipo de causa: cualquier motivo por el que salga negativa queda
  reflejado. Para opiniones ya descargadas, botón **«Re-analizar opinión»** en el
  detalle (`POST /empresas/{rfc}/parsear-opinion`). Un fallo de lectura nunca
  rompe la descarga.

- **La Constancia de Situación Fiscal ahora rellena sola la configuración de
  la empresa.** Al descargar la CSF (CIEC o e.firma) el agente parsea el PDF
  y aplica al catálogo: el **nombre/razón social** tal cual el SAT (unifica
  empresas que quedaron con el RFC como nombre o con mayúsculas/minúsculas
  inconsistentes), los **regímenes fiscales activos** (mapeados a su clave del
  catálogo c_RegimenFiscal) y las **actividades económicas** con su porcentaje,
  ordenadas de mayor a menor peso y con la principal marcada. La constancia
  manda: cada descarga actualiza estos datos (siguen siendo editables a mano).
  Para constancias ya descargadas, botón **«Rellenar desde la constancia»** en
  la card de Configuración fiscal (`POST /empresas/{rfc}/parsear-csf`), sin
  volver a ir al SAT. Un fallo de parseo nunca rompe la descarga.

- **Al descargar la Constancia o la Opinión 32-D con e.firma ya se ve que está
  trabajando.** El botón muestra «Descargando…» con un indicador de avance y un
  aviso de que puede tardar un momento — antes solo se veía deshabilitado y no
  quedaba claro si seguía en curso o se había quedado atorado.

### Bug fix

- **Descarga WS: el «Estado de la solicitud» ya no se queda «Verificando…»
  sobre una solicitud que el poller ya resolvió.** El flujo activo de la
  página ahora converge con el catálogo local: al montar y en cada tick
  consulta primero el catálogo (barato, sin tocar al SAT) y, si el poller en
  background ya la descargó, cierra el flujo limpio (la fila «Descargada»
  queda en Solicitudes recientes); si venció o fue rechazada, muestra el
  motivo. También evita re-descargar paquetes que el poller ya bajó.

- **Los timeouts del SAT en `/verificar` (y demás endpoints WS) ya no truenan
  como error 500 ni inundan Sentry** (TODOCONTA-DESKTOP-13, 81 eventos en 5
  días): los fallos de red contra el SAT (`requests.RequestException` hereda
  de IOError — el `except RuntimeError` nunca los atrapaba) ahora se traducen
  a **503 «El SAT no respondió»**. Por convención del agente, 503 = «servicio
  externo no disponible, reintenta»: la telemetría lo excluye de
  `failed_request_status_codes` (verificado contra docs de sentry-sdk: el
  filtro solo aplica a HTTPException) y el renderer tampoco lo reporta. La UI
  trata el 503 como transitorio: muestra «El SAT está tardando en responder;
  seguimos verificando» y el polling continúa en lugar de morir en error.

- Bump 1.7.0 → 2.0.0 (3 archivos).

## [1.7.0] - 2026-07-10

### Feature

- **Las solicitudes WS se resuelven solas en background, por todas las
  empresas a la vez.** Un poller del agente (cada 60 s) verifica contra el SAT
  las solicitudes pendientes de TODAS las empresas — cada una con su propia
  e.firma, sin tocar la sesión activa — y cuando una queda lista **descarga los
  paquetes automáticamente** a la carpeta de la empresa y la registra en el
  historial, aunque el usuario haya cambiado de empresa, esté en otra pantalla
  o la app lleve rato abierta en otra cosa. También retoma solicitudes que
  quedaron «Lista» sin bajarse (p. ej. si la app se cerró a media descarga).
  La UI estrena un watcher global que notifica por empresa: toast/notificación
  nativa al completarse una descarga y notificación **en rojo** cuando una
  solicitud falla, es rechazada o vence — con el nombre de la empresa para
  saber a cuál irle a revisar.

- **Comprobantes: control DIOT y deducibilidad por comprobante (Claude
  Design)**: el Procesador de CFDI ahora define qué operaciones pasan al
  generador de la DIOT. Columna **«DIOT»** con interruptor por comprobante
  elegible (recibidos de Ingreso/Egreso; por default todos pasan) — pagos,
  nómina, traslados y emitidos marcan «No aplica» — y columna **«Deducible»**
  con clasificación manual persistida (Sin analizar / Deducible / No
  deducible; el análisis asistido por IA llega en un sprint posterior). El
  panel de filtros se reagrupa por bloques (Búsqueda · Clasificación ·
  Periodo · Importe) e incorpora el filtro **«Estado DIOT»** (Pasa a DIOT /
  Excluidos / No aplica); sobre la tabla vive un contador global («X de Y
  operaciones pasan a la DIOT») y las filas excluidas se atenúan. **El
  prellenado de la DIOT respeta las exclusiones** (el resumen y el toast
  reportan cuántos comprobantes se excluyeron manualmente) y el export
  XLSX/CSV agrega las columnas Deducible y DIOT al final. Migración 009 del
  buffer (`incluir_diot`, `deducible`) + `PATCH /procesador/cfdi/{uuid}`.
  **La obligación DIOT se deriva del régimen fiscal configurado de la
  empresa** (mapeo investigado contra RMF 2025/2026 y RFA 2025 — ver
  docs/producto/diot-2025.md «¿Quién presenta la DIOT?»): RESICO (regla 3.13.19),
  sueldos, RIF y demás relevados no ven columna, filtro ni contador DIOT, y
  la pantalla DIOT lo avisa. Toggle **«Presenta DIOT»** en la configuración
  de la empresa (`presenta_diot`) para los casos condicionales: PF que
  rebasa $4 MDP (regla 2.8.1.17), actividades exentas, coordinado que la
  presenta global, plataformas con retención definitiva (art. 18-M LIVA).

- **Tareas: centro de mando personal (Claude Design)**: nueva sección
  **/tareas** para pendientes fiscales, recordatorios y lo que el usuario
  tenga en mente — **con o sin empresa vinculada**. Vista **lista** agrupada
  por fecha (Vencidas/Hoy/Esta semana/Más adelante/Sin fecha) o por empresa,
  y vista **tablero** (Por hacer / En curso / Hechas); búsqueda, filtro por
  empresa, alta rápida con Enter, modal «Nueva tarea» y drawer de edición
  con eliminar (confirmación inline). **Sugerencias de TodoConta** derivadas
  del catálogo: renovar e.firma por vencer (≤ 30 días) y generar la DIOT del
  mes (vence el 17) — aceptar las convierte en tarea y descartar persiste
  para siempre. Persistencia en el agente
  (`~/.sat-descarga/tareas.json`, endpoints `/tareas*`), no en el navegador;
  el modelo ya reserva `gcal_event_id` para la **sincronización
  unidireccional con Google Calendar** planeada en
  [docs/producto/tareas-gcal-sync.md](docs/producto/tareas-gcal-sync.md). «Tareas» entra al
  sidebar en 2.ª posición: **los atajos ⌘2..⌘9 se recorren un número**
  (decisión de producto; la card de /ayuda se actualiza sola) y desde la
  10.ª página (DIOT) ya no hay dígito — se llega por ⌘K.

- **Inicio: Panel Ejecutivo (Claude Design)**: el dashboard deja las 4 cards de
  accesos y pasa a un **resumen de operación con datos reales** del catálogo y
  el historial: saludo con fecha y nombre de la cuenta, KPIs clicables (CFDIs
  del mes con tendencia vs. el mes anterior, empresas activas, e.firmas por
  vencer), gráfica de **CFDIs descargados por mes** (últimos 6), donut del
  **estado de la cartera** (al día / e.firma por vencer / solo CIEC), lista de
  **próximos vencimientos de e.firma** (liga al detalle de la empresa), **top
  de empresas con más movimiento** del mes y **descargas recientes** con liga
  al historial. Cada panel trae estado vacío propio para instalaciones nuevas.
  El bloque **«Tareas de hoy»** muestra las 5 tareas más urgentes con
  contadores (vencidas / para hoy / esta semana) y sugerencias, sincronizado
  en vivo con la sección Tareas; el KPI «Tareas abiertas» avisa cuántas
  están vencidas.

- **Renovación de e.firma y generación de CSD desde la app (Certifica)**: nuevo
  router del agente (`/renovar`, `/renovar/recuperar`, `/csd`, `/csd/recuperar`)
  que corre cada trámite como **job SSE** de extremo a extremo: genera la
  solicitud (`.ren`/`.sdg` + `.key`), la firma con la e.firma vigente, la envía
  a CertiSAT/Certifica y recupera el certificado emitido. En la UI, asistentes
  de 4 pasos con progreso real por fases: **Renovar e.firma** (confirmación
  explícita del trámite irreversible; sustituye el `.cer`/`.key` del catálogo
  con respaldo de la anterior y recarga la sesión; si venció, dirige al trámite
  presencial + actualizar archivos) y **Generar CSD** («bajar después»
  first-class: el envío devuelve el número de operación al instante y el
  certificado se descarga cuando el SAT lo emite; la contraseña del sello se
  guarda en el keychain y en un `.txt` junto a la `.key` para el timbrado
  futuro). El estado pendiente se persiste en el catálogo por etapas, así que
  la renovación se **reanuda desde donde se atoró** si el portal del SAT falla
  (reenvía el mismo `.ren` si el envío no se logró, o solo descarga el cert si
  ya se envió; incluye un fallback que verifica —por emparejamiento con la
  `.key`— si el SAT ya había procesado el trámite pese al error). FIEL-only
  (CertiSAT no acepta CIEC). **Nota:** la _Renovar e.firma_ se publica
  **deshabilitada** («Disponible próximamente») hasta estabilizar la ejecución
  del agente empacado en Windows; se reactiva con un flag (`features.ts`).

- **Empresas: rediseño de la lista (Claude Design, boceto Desktop v2)**: vistas
  **Activas/Archivadas** como pestañas con contadores (las archivadas explican
  que se conservan por si regresan), barra de totales (activas · morales ·
  físicas · **requieren atención**), toolbar con **búsqueda por nombre/RFC**,
  filtro segmentado Todas/Morales/Físicas, filtro de estado y orden (nombre,
  RFC, e.firma por vencer, requieren atención), columna **Tipo** (Moral/Física
  según el RFC) y chips de estado con fondo suave. La fila expandida pasó a un
  grid de **3 tarjetas**: e.firma (semáforo + **Renovar en línea** o
  **Descargar certificado** pendiente), Constancia de Situación Fiscal y
  Opinión 32-D. En el detalle de empresa, la card de e.firma abre el asistente
  de renovación (resaltada cuando está por vencer) y conserva la vía manual de
  actualizar `.cer`/`.key`.

- **Calculadoras: rediseño de la interfaz (Claude Design)**: el índice pasó a
  tarjetas con ícono en badge y llamada **"Abrir →"** con elevación al hover; en
  cada calculadora los totales se muestran en **cifras grandes monoespaciadas**,
  los interruptores (asimilado, zona fronteriza…) ahora son **filas clicables**
  que se resaltan al activarse, el encabezado es más prominente y el estado vacío
  lleva el ícono de la calculadora. Aplicado en los componentes compartidos
  (`ResumenCards`, `CalculadoraShell`, nuevo `ToggleRow`), por lo que alcanza a
  las 7 calculadoras. Sin cambios en la lógica de cálculo ni en el API: solo
  UX/UI.

- **DIOT: rediseño de la pantalla (Claude Design)**: tarjetas de resumen del
  periodo (proveedores, valor de actos 16%, IVA acreditable, IVA retenido), el
  detalle del renglón pasó de fila expandida a **panel lateral** con secciones
  colapsables que indican cuántos campos tienen valor, montos con separador de
  miles, y un estado vacío con guía de 3 pasos (descarga → prellena → genera).
  Sin cambios en la lógica ni en el TXT: los 54 campos siguen viniendo del
  layout del agente.

- **DIOT 2025 (núcleo): generación del archivo de carga masiva**: nuevo paquete
  `sat_descarga/diot/` que implementa el layout oficial de **54 campos** del
  instructivo del SAT (Enero 2025, documentado en
  [docs/producto/diot-2025.md](docs/producto/diot-2025.md)): prellenado de renglones por
  proveedor desde el buffer del procesador (CFDIs recibidos del periodo; las
  notas de crédito van a los campos de *devoluciones*, sin negativos), estado
  editable por empresa y periodo en `~/.sat-descarga/diot/{RFC}.json`,
  validaciones del instructivo (catálogos por tipo de tercero, RFC,
  devoluciones ≤ valor, montos enteros) y exportación del `.txt` pipe-delimited
  en UTF-8 con BOM. El parser del procesador ahora desglosa las **bases de IVA
  por tasa** (16%, 8%, 0% y exento — migración 008); los CFDIs cargados con
  versiones anteriores se estiman desde el IVA al 16% y se marcan para
  recargar. La pantalla, API y CLI llegan en el siguiente PR.

- **DIOT 2025 (app): pantalla, API y CLI**: nueva página **DIOT** en el sidebar
  (al final — atajo **⌘9**; los atajos existentes no se mueven). Selector de
  mes/año, botón **"Prellenar desde comprobantes"** (agrupa los CFDIs recibidos
  del periodo por proveedor), **"Cargar XMLs"** directo en la pantalla (alimenta
  el mismo buffer por empresa, sin duplicar folios, y re-prellena), tabla
  **editable** (montos inline, fila expandida con los 54 campos por sección,
  datos de proveedor extranjero, catálogos oficiales en selects) con totales al
  pie, renglones manuales que sobreviven al re-prellenado (con confirmación), y
  validaciones en vivo (los errores del instructivo bloquean el TXT; las
  advertencias no). **Generar TXT** es premium (patrón calculadoras); nombra el
  archivo `{RFC}_diot_{YYYY-MM}.txt`. API: `/diot/{estado,prellenar,exportar,
  catalogos}`. CLI: `sat-dm diot --rfc RFC --periodo YYYY-MM [--salida …]
  [--forzar]`. El TXT generado debe verificarse subiéndolo a la aplicación DIOT
  del SAT (ver "Pendiente de validar" en docs/producto/diot-2025.md).

- **Organizador: estructura de carpetas y nombre de archivo personalizados**
  (rediseño Claude Design): junto a las estructuras predefinidas hay una opción
  **"Personalizada…"** con un constructor visual — paleta de variables (Año,
  Mes, Día, **Emitidos/Recibidos**, Tipo de comprobante, RFC de la empresa,
  RFC emisor, RFC receptor y **carpetas de texto fijo**), niveles reordenables
  arrastrándolos y **vista previa tipo Finder** de la ruta resultante (ej.
  `CULL551116HM8 › 2026 › 05 › Emitidos › factura.xml`); los presets también
  muestran su vista previa. En **Renombrar**, el nombre del archivo ahora se
  puede componer por partes (Fecha, RFC/Nombre del emisor, Folio fiscal, Serie
  y folio, Tipo, Total, texto fijo) con **separador a elegir** (`-`, `_`,
  espacio, `·`) y vista previa. La clasificación Emitidos/Recibidos compara
  cada CFDI contra el RFC de la **empresa activa**; las composiciones
  personalizadas se recuerdan entre sesiones. Desde CLI:
  `sat-dm organizar carpetas -e "txt:Facturas/anio/flujo" --rfc XXX` y
  `sat-dm organizar renombrar --partes "fecha,rfc_emisor,folio_fiscal"
  --separador "-"`. Los nombres generados se sanean para Windows (caracteres
  inválidos, valores vacíos).

- **Procesador de comprobantes aislado por empresa (RFC)**: el buffer, los
  filtros, reportes y exportaciones de CFDI/Pagos/Nómina ahora viven POR
  empresa — al cambiar de empresa activa solo ves sus comprobantes y al
  regresar (A→B→A) se recupera lo que esa empresa tenía cargado, igual que
  las calculadoras. La carga de XML exige empresa activa y la vía "Examinar"
  **omite los comprobantes que no correspondan a su RFC** (ni emisor ni
  receptor) reportando el conteo. "Borrar todo" vacía solo el buffer de la
  empresa activa. Los buffers existentes se asignan automáticamente a la
  empresa predeterminada al primer arranque (si no hay empresa registrada,
  se vacían — el buffer es una caché re-cargable desde los XMLs).

- **Calculadoras fiscales y laborales** (PRs #110–#113): nueva sección
  **Calculadoras** con 7 herramientas de libre acceso — aguinaldo, SBC, ISR de
  sueldos, finiquito, liquidación, carga patronal y **PTU** (con la lógica de
  la plantilla Excel de TodoConta: año de pago = ejercicio+1, tope de confianza
  al 120%, criterio de exención UMA-SAT vs SMG-PRODECON y fecha límite legal).
  Todo el cálculo vive en el agente Python con indicadores por año (UMA, SMG,
  tarifas ISR del Anexo 8, subsidio al empleo por decreto del DOF, cuotas IMSS
  2026) y **el estado se guarda por empresa**: cambiar de empresa nunca pisa
  los cálculos de otra (`~/.sat-descarga/calculadoras/{RFC}.json`). La
  **exportación a Excel/PDF es premium**, incluyendo para PTU los recibos
  imprimibles por trabajador y la hoja de pre-nómina (percepción 003 /
  deducción 002) lista para timbrado.

### Bug fix

- **Descarga WS: las solicitudes ya no se mezclan entre empresas y ninguna se
  queda «Procesando» para siempre.** El «Estado de la solicitud» se guardaba en
  una llave global de localStorage, así que al cambiar de empresa la página
  retomaba el polling de una solicitud de OTRA empresa (y `/verificar` iba
  firmado con la e.firma equivocada) — la misma solicitud aparecía «Verificando
  estado…» en todas las empresas. Ahora el flujo activo va aislado por RFC (la
  llave legacy se limpia sola al actualizar). Además: (1) los estados de falla
  del SAT (4=error, 5=rechazada, 6=vencida) ahora SÍ se persisten en el
  catálogo — antes `/verificar` los convertía en HTTP 400 y la solicitud jamás
  salía de «Procesando»; (2) toda solicitud pendiente con más de **72 h** (el
  SLA del SAT) se marca **«Vencida»** automáticamente, con su badge rojo y el
  aviso de volver a solicitar el periodo.

- **Descarga CIEC: el login ya no truena con «Execution context was destroyed»
  cuando el SAT tarda en responder el captcha** (TODOCONTA-DESKTOP-T): si el
  aterrizaje post-submit no llegaba en 25 s, se leía el mensaje de error del
  DOM justo mientras la navegación seguía en vuelo — el contexto se destruía y
  el job moría, casi siempre cuando el login SÍ iba a entrar. Ahora hay una
  gracia de aterrizaje de 10 s antes de dar el intento por fallido y la lectura
  del mensaje de error es a prueba de navegaciones (se trata como "sin mensaje"
  y aplica la política normal de reintentos del captcha).

- **Opinión 32-D con e.firma: el login ya no reporta éxito sin haber aterrizado**
  (TODOCONTA-DESKTOP-Z/-X/-Y/-W/-10/-11, corrida real jul 2026): el predicado de
  aterrizaje comparaba por substring y la página de login de loginda lleva un
  `target=` codificado que contiene el hostname de ptsc32d literal — disparaba
  "Login exitoso" en el propio login y luego esperaba un PDF imposible. Ahora se
  compara el host parseado. Además, el click del submit e.firma ya no revienta
  por navegación lenta (`no_wait_after=True`, mismo patrón que el submit CIEC de
  TODOCONTA-DESKTOP-9): la firma client-side + POST podían tardar más que el
  timeout del click, y el fallback esperaba 30 s un botón que ya había navegado.
  El diagnóstico de captura del PDF ahora sale como UN solo evento (antes creaba
  3-4 issues de Sentry por fallo) e incluye la danza OAuth (authz/callback) para
  rastrear en qué salto se atora el visor del SAT.

### Tooling

- Bump 1.6.0 → 1.7.0 (3 archivos).

## [1.6.0] - 2026-07-02

### Bug fix

- **Ya no se pierde el catálogo de empresas al actualizar desde ≤v1.3.0 en
  Windows** (TODOCONTA-DESKTOP-V): esas versiones escribían los JSON de
  `~/.sat-descarga/` sin `encoding=` (code page ANSI, cp1252), y v1.4.0/v1.5.0
  los leía con UTF-8 estricto — un nombre de empresa con acentos o Ñ (lo normal
  en una razón social) se trataba como corrupción: cuarentena a
  `empresas.json.corrupto` y catálogo vacío. Ahora la lectura prueba los
  encodings legacy (UTF-8 → locale → cp1252 → latin-1), migra el archivo a
  UTF-8 en disco y, si encuentra una cuarentena de v1.4.0/v1.5.0 sin catálogo
  vigente, **la restaura automáticamente** (queda archivada como `.rescatado`).
  Aplica a empresas, solicitudes, historial y settings; la corrupción real
  (archivo lleno de NUL tras un apagado abrupto) sigue yendo a cuarentena.

- **El auto-updater ya no truena en silencio en instalaciones sin firma**
  (TODOCONTA-DESKTOP-8/-A): las instalaciones de v1.4.0 y anteriores (con
  `publisherName` "TodoConta" grabado) rechazan los updates firmados con el
  certificado nuevo, y ese rechazo se perdía como `unhandledRejection` rumbo a
  Sentry. Ahora se atrapa en ambos checks (silencioso y manual) y muestra un
  diálogo accionable una vez por sesión: "Ir a la descarga" →
  todoconta.com/descargar para reinstalar a mano.

### Feature

- **Atajos de teclado + buscador de páginas (⌘K / Ctrl+K)**: la app ya se puede
  recorrer sin mouse. Un command palette busca páginas y acciones (con hints de
  cada atajo y footer de navegación); `⌘E / Ctrl+E` abre el cambio de empresa
  activa directo, `⇧⌘L / Ctrl+Shift+L` alterna claro/oscuro, `⌘1..⌘7 / Ctrl+1..7`
  saltan a las páginas del menú en su orden, `⌘, / Ctrl+,` abre Ajustes,
  `⌘B / Ctrl+B` colapsa el menú lateral, `⌘N / Ctrl+N` abre el alta de empresa,
  `⇧⌘D / Ctrl+Shift+D` va a Descarga rápida y `F1` abre la Ayuda. El sidebar
  ganó un ítem "Buscar" y la página de Ayuda una card con la referencia
  completa de atajos. Nota: los atajos numéricos siguen el ORDEN del sidebar;
  si se reordenan páginas, el número cambia con ellas.

- **Versión y actualizaciones en el status bar**: un chip siempre visible
  muestra la versión actual y permite buscar actualizaciones sin ir a Ajustes.
  La descarga automática arranca solo al detectar versión nueva (el chip
  muestra el %); cuando está lista, el chip se pinta en ámbar y confirma antes
  de reiniciar para no interrumpir descargas largas. En instalaciones viejas
  sin firma, el chip ámbar lleva a todoconta.com/descargar para reinstalar.

### Tooling

- Bump 1.5.0 → 1.6.0 (3 archivos).

## [1.5.0] - 2026-07-01

### Feature

- **Inicio de sesión con Google (OAuth PKCE) en el desktop**: la pantalla de
  acceso ahora ofrece "Continuar con Google" además del correo. El flujo corre por
  un broker PKCE en el agente local y regresa a la app por el deep link
  `todoconta://auth-callback`; si ya existe una cuenta con ese correo, se vincula
  con la identidad de Google en vez de duplicarla.

### Tooling

- **Firma de código activada en Windows (SSL.com eSigner)**: el instalador NSIS,
  `TodoConta.exe` y el agente `sat-agent.exe` ahora se firman con el certificado
  IV de SSL.com. Elimina el aviso de "editor desconocido" de SmartScreen y reduce
  el escaneo en frío de Windows Defender (que congelaba el arranque y la primera
  navegación ~1-2 min). `publisherName` quedó fijado al CN del certificado y
  `forceCodeSigning` evita volver a publicar un instalador sin firma en silencio;
  esto además repara la cadena de auto-update de `electron-updater`, que valida
  cada actualización contra la firma del publisher.

- Bump 1.4.0 → 1.5.0 (3 archivos).

## [1.4.0] - 2026-06-30

### Feature

- **Autocorrección del nombre de la empresa al cargar la e.firma**: al dar de
  alta o recargar una FIEL, el nombre del contribuyente se toma del certificado,
  recuperando el CN del DER cuando el subject es ilegible. Así el catálogo deja de
  mostrar el RFC como nombre provisional o un nombre truncado.

### Bug fix

- **`empresas.json` a prueba de corrupción**: tras un apagado abrupto en Windows
  el catálogo quedaba lleno de bytes NUL (`\x00`) y reventaba **cada** llamada a
  `/empresas` y `/empresas/fiel` con un 500 — la app quedaba inservible. La
  escritura ahora hace `fsync` antes del rename atómico (raíz del problema) y la
  lectura tolera corrupción: aísla el archivo dañado en `.corrupto` y reinicia el
  catálogo en vez de tumbar cada request.
- **Lectura del RFC y nombre desde certificados problemáticos**: se extrae el RFC
  directo del DER cuando `cryptography` no puede parsear el subject (certs con
  Ñ/acentos tipados como T61String) o cuando el OID viene como `bytes`; se recupera
  el nombre (CN) del mismo DER cuando el subject es ilegible.
- **`<Paquete/>` vacío del SAT sin tronar**: cuando el Web Service devuelve un
  paquete vacío ya no revienta con el `TypeError` de `b64decode(None)`; ahora lanza
  un error accionable que invita a reintentar.
- **Estado de carga + auto-reintento al abrir los procesadores**: la pantalla de
  procesadores muestra su estado de carga y reintenta sola en vez de quedarse en
  blanco.
- **Truncado del nombre de archivo en el alta por e.firma**: el `FileField` y el
  grid item truncan correctamente los nombres largos (el truncado real era
  `min-w-0` en el grid item, no el span interno).

### Tooling

- **Errores de usuario fuera de Sentry**: la contraseña de la `.key` incorrecta y
  demás validaciones del alta por e.firma devuelven 400 sin reportarse a Sentry,
  que estaba inundándose de eventos que no son bugs.

- Bump 1.3.0 → 1.4.0 (3 archivos).

## [1.3.0] - 2026-06-24

### Feature

- **Suscripción dentro de la app**: banner de promo (50% anual de por vida) y
  badges de plan (Fundador / premium / prueba / free) en el titlebar, más una
  página interna `/suscripcion` para pagar con tarjeta (Stripe), por transferencia
  o cancelar sin salir de la app. El agente expone los endpoints
  `/auth/{subscribe,cancel-subscription,transfer-intent}` con refresh-on-401 y
  mensajes de error amigables. El `FounderBanner` se conserva pero se auto-oculta.
- **Rediseño de la página de suscripción (dos columnas)**: tarjeta principal de
  plan por estado (oferta de prueba/free · premium activo · Miembro Fundador) con
  precio + ahorro, lista de incluidos y selector de método tipo radio (tarjeta /
  transferencia, que carga los datos bancarios al elegir transferencia); rail con
  cuenta regresiva de la prueba, tarjeta de cuenta y nota de ayuda.
- **BrandMark reutilizable**: se extrae el lockup de marca (icono + wordmark con
  el punto `.` en cian, igual que el canónico de todoconta-apps) a un componente
  compartido; se usa en el sidebar (con `iconOnly` al colapsar) y en el login.
- **Reconciliación del license al arranque + auto-refresh cada 6 h con force**:
  antes un cambio en el servidor (cerrar la ventana de fundadores, activar la
  promo) tardaba hasta 24 h en reflejarse por el cache del agente. Ahora el
  arranque pinta el cache al instante y reconcilia en background con force, el
  auto-refresh de 6 h ignora el cache, y `/suscripcion` fuerza refresh al montar
  para que el precio mostrado coincida con el que cobra el checkout.

### Bug fix

- **Pesos tipográficos correctos en la app empacada**: el `@font-face` declaraba
  el rango `100 900` pero apuntaba a un único woff2 de Inter Regular (peso 400),
  así que 600/700/800 se renderizaban como 400. Se auto-hospeda Inter Variable
  (eje `wght` 100–900) en `public/fonts/`, lo que además quita la dependencia de
  red en Electron offline. Los primitivos shadcn se suben para coincidir con el
  design system (Button/Badge/Label → semibold; CardTitle/AlertTitle → bold;
  DialogTitle → extrabold; PageHeading h1 y precio → extrabold).
- **License: descartar respuestas obsoletas (request-id guard)**: con varios
  fetches en vuelo (cache+force del arranque, intervalo de 6 h, refresh manual,
  reconexión que recrea el `apiClient`) un resultado viejo podía pisar al más
  reciente. Cada fetch lleva ahora un id monotónico y solo el último aplica su
  resultado (patrón canónico de React para effects con fetch).

### Copy

- **Copy de promo enfocado**: el `PromoBanner` pasa a una sola fila horizontal
  (% en cuadro azul con icono blanco + botón de cerrar por sesión) sin recortar
  los días restantes; el copy del banner y de la página enfatiza «aprovecha el
  50 %», «te quedan N días para aprovecharlo» y «se te respeta para siempre
  mientras no canceles».

### Tooling

- **`design/` ignorado**: el boceto de diseño local (Claude Design) queda fuera
  del repo.

- Bump 1.2.2 → 1.3.0 (3 archivos).

## [1.2.2] - 2026-06-22

### Bug fix

- **Login CIEC ya no crashea por timeout del clic de envío**: el `page.click` del
  submit esperaba, por default, a que la navegación del POST terminara dentro del
  propio clic (timeout 30 s). Si el SAT tardaba en responder, el clic reventaba con
  `TimeoutError` y tumbaba el job en vez de caer en el reintento de captcha. Ahora el
  clic no bloquea esperando la navegación (`no_wait_after`); la espera del aterrizaje
  la hace `wait_for_url` con su propio timeout y la lógica de reintentos.
- **No se reporta a Sentry la carrera de arranque del agente** (falsos positivos al
  inicio) y se **auto-cura `/empresas`** ante catálogos inconsistentes.
- **Descarga de Chromium robusta a `TMPDIR` restringido** en macOS (`EACCES`): el
  portal ya no falla al bajar el navegador cuando el temporal del sistema es de
  solo-lectura o restringido.

### Tooling

- **Identificación del usuario autenticado en Sentry** (id + email) para correlacionar
  cada reporte con la cuenta que lo originó.
- **Build de macOS solo arm64**: se dejaron de construir los binarios x64/Intel (los
  runners de CI estaban saturados); docs de CI aclaradas (`macos-latest` es arm64,
  labels de Intel modernos).

- Bump 1.2.1 → 1.2.2 (3 archivos).

## [1.2.1] - 2026-06-18

### Tooling

- **Build de macOS arreglado**: el agente Python ahora se empaca en **onefile solo
  en macOS**, para que la firma de notarización no recorra cientos de binarios
  anidados (cada `codesign --timestamp` pega al servidor de Apple, que estrangula a
  los runners de CI). El build de mac de v1.2.0 se cancelaba a los 45 min atorado en
  `signing`; con onefile es un solo binario a firmar. Windows/Linux siguen en onedir
  (ahí onefile dispara más antivirus y arranque más lento). `extraResources` pasó a
  ser por plataforma y el timeout del job de mac subió a 90 min.

- Bump 1.2.0 → 1.2.1 (3 archivos).

## [1.2.0] - 2026-06-18

### Feature

- **Botón "Buscar actualizaciones" en Ajustes** (fila Versión): consulta el
  release más reciente de GitHub (lo mismo que el auto-update), descarga en
  background mostrando el progreso y ofrece "Reiniciar ahora" cuando está lista.
  Solo visible en la app instalada (en dev el updater no opera).
- **El auto-update ya no es un intento único**: además del check a los 30 s del
  arranque, se re-consulta cada 4 horas. Antes, si ese único check fallaba
  (red lenta, antivirus, GitHub caído) la sesión completa se quedaba sin
  enterarse del update — la causa de que una máquina actualizara y otra no.
- **Respaldo local de la e.firma**: al registrar una empresa por e.firma, además
  de la copia de trabajo en `~/.sat-descarga/efirma/`, se guarda una copia visible
  de los `.cer`/`.key` en `<descargas>/fiel/<RFC>/` (junto a CFDI/constancia/
  opinión) con un `LÉEME.txt`. La contraseña **nunca** se escribe en disco — sigue
  solo en el llavero del SO. Best-effort: si la carpeta de descargas no es
  escribible, no rompe el alta. La nota de privacidad en el alta va como tooltip
  (?) junto a la contraseña, para no gastar espacio en el modal.
- **Reporte de errores con Sentry**: captura automática de errores (renderer, main
  y agente Python) + botón "Reportar un problema" junto a la campana. Apagado salvo
  que haya DSN configurado; envía solo diagnóstico técnico **scrubbeado** (RFC,
  rutas con nombre de usuario y credenciales redactadas) — nunca la e.firma, las
  contraseñas ni datos fiscales.

### Bug fix

- **Corregido el alta de empresa por e.firma en Windows** (`[WinError 5] Acceso
  denegado: 'efirma'`): la carpeta de certificados era una ruta **relativa** que, en
  el build empaquetado, caía en el directorio de instalación (solo-lectura por UAC).
  Ahora se ancla a `~/.sat-descarga/efirma/` (absoluta y siempre escribible); de
  paso, las rutas guardadas en `empresas.json` quedan absolutas.

### Tooling

- **Notarización de macOS activada** en electron-builder.

- Bump 1.1.1 → 1.2.0 (3 archivos).

## [1.1.1] - 2026-06-12

### Corregido

- **El navegador de descargas ya no se pierde tras actualizar la app** (el
  "Executable doesn't exist… playwright install" al descargar vía portal). La
  verificación ahora valida la revisión exacta que pide la versión empaquetada de
  Playwright — incluido el binario headless shell — en vez de aceptar cualquier
  carpeta `chromium-*` vieja. Además: el agente descarga/actualiza Chromium en
  background al arrancar (warm-up en el lifespan), `/health` reporta el estado
  (`navegador: instalando|listo|error`), la UI muestra un banner "Preparando el
  navegador…" y los jobs del portal avisan por SSE si tienen que esperar la
  instalación. Si aun así el launch falla por binario ausente, se reinstala y
  reintenta solo; cualquier error residual de Playwright se traduce a un mensaje
  en español.

### Infra

- **Pipeline de firma de Windows migrado a SSL.com eSigner** (Azure Trusted Signing
  descartado: no acepta entidades de México). `release.yml` descarga CodeSignTool y
  firma `sat-agent.exe`; electron-builder firma TodoConta.exe + uninstaller +
  instalador vía el hook `desktop/scripts/esigner-sign.js`. Todo auto-saltable hasta
  que existan los secrets (`ES_USERNAME`, `ES_PASSWORD`, `CREDENTIAL_ID`,
  `ES_TOTP_SECRET`). Decisiones, costos y checklists en
  [docs/infra/firma-codigo.md](docs/infra/firma-codigo.md): cert IV comprado (validación en
  curso) + Apple Developer Program iniciado.

### Docs

- Guion de presentación de venta (versión corta + demo en vivo) en
  [docs/negocio/presentacion-pitch.md](docs/negocio/presentacion-pitch.md).

- Bump 1.1.0 → 1.1.1 (3 archivos).

## [1.1.0] - 2026-06-10

### Rediseño de la interfaz (v2)

- **Sidebar nuevo** colapsable: marca arriba, **selector de empresa** con badge PF/PM a
  color y RFC, navegación plana de 7 secciones, y footer con Ayuda + menú de cuenta
  (plan, email, suscripción, cerrar sesión; corona de Fundador con tooltip).
- **Barra de estado inferior**: conexión con el agente, CFDIs del mes y última descarga
  de la empresa activa, y semáforo de vencimiento de su e.firma (o "Acceso con CIEC").
- **Pantalla de Ayuda** nueva: FAQ con buscador, contacto de soporte y guías.
- **Alta de empresa simplificada**: ya no pide nombre — se completa solo con la razón
  social del certificado (e.firma) o el RFC (CIEC).
- **Quitar e.firma** desde el detalle de empresa (con confirmación): la empresa queda
  solo-CIEC y deja de intentarse la FIEL vencida.
- **Filtros de comprobantes colapsables** con contador de filtros activos.
- **Ajustes en rejilla de tarjetas** (Almacenamiento, Apariencia, Notificaciones,
  Acerca de).
- **Titlebar de Windows sin marco** con controles propios (minimizar/maximizar/cerrar,
  Aero Snap y doble-click conservados); macOS intacto.
- **Copy depurado en toda la app**: fuera tecnicismos de implementación (keychain,
  servidor, localhost); se quedan los términos fiscales (CFDI, RFC, e.firma, CIEC,
  EFOS, Art. 69-B).

### Login en-app (reemplaza el device-code flow)

- **Inicia sesión sin salir de la app**: pantalla de login estilo Notion con correo +
  contraseña o **código de acceso de 6 dígitos** que se teclea en la misma ventana
  (auto-avance, pegar el código completo, reenviar con timer). Antes había que abrir el
  navegador, confirmar un código de activación y esperar el polling.
- **Crear cuenta desde el desktop**: registro con nombre + correo (+ contraseña o por
  código), contra la misma base de cuentas de app.todoconta.com — la cuenta sirve igual
  en la app en línea. Botón de Google visible pero deshabilitado (próximamente).
- **La sesión ya no se cae ante un 401**: el agente renueva la sesión con el
  `refresh_token` guardado antes de desloguear (esto deslogueó a un usuario en vivo el
  2026-06-10). Aplica al license check y al checkout de Fundador.
- El device-code flow sigue disponible en el agente como fallback (`/auth/init` +
  `/auth/poll`), pero la UI ya no lo usa.

### Copy

- **Descripción de la app unificada en todas las distribuciones.** El tooltip del acceso directo en Windows mostraba un texto interno/técnico (`TodoConta Desktop — app de escritorio (Electron) sobre el agente SAT (Python)`). Ahora dice **«TodoConta Desktop — Administración de CFDIs y herramientas fiscales»** (`description` en `desktop/package.json`, mapeado al `FileDescription` del `.exe`). El `Comment` del desktop entry de Linux (`electron-builder.yml`) se alinea con el mismo copy (sin el prefijo del nombre, que el campo `Name` ya provee). Toma efecto en el próximo build del instalador.

### Rendimiento

- **El registry de jobs ya no crece sin tope**: los jobs terminados se podan al crear nuevos (se conservan los últimos 20 para `/jobs/{id}`); antes cada descarga de la sesión dejaba su job y su cola de eventos en memoria para siempre.
- **Log de jobs CIEC acotado a 500 entradas (FIFO)** en la UI: un job largo emitía miles de eventos y cada uno re-renderizaba una lista cada vez más grande.
- **El polling de `/health` se pausa con la ventana oculta** (minimizada o en background) y ya no encima requests si el agente tarda más que el intervalo; al volver el foco dispara un check inmediato. Mismo guard anti-encimado en el polling de verificación WS y en el del login.
- **Listas largas con render acotado**: paginación local opcional en `ResourceList` (aplicada a solicitudes WS) y "Mostrar más" incremental en el historial — pintar cientos de filas de golpe congelaba equipos modestos.

### Arranque y resiliencia

- **La ventana abre de inmediato.** Antes, Electron esperaba el `/health` completo del agente antes de crear la ventana: en equipos con HDD + antivirus escaneando el binario sin firma eso eran 30-60 segundos sin NADA en pantalla (la app parecía rota). Ahora el spawn asigna puerto/token, la ventana se crea al instante y el `StartupSplash` del renderer (que ya tenía mensajes por fases) por fin se ve durante el arranque real.
- **Monitor del agente con reinicio automático.** Si el agente muere después del arranque (crash, OOM), el shell lo detecta (3 checks fallidos ≈ 30s) y lo reinicia en el mismo puerto y con el mismo token, hasta 3 veces consecutivas; el renderer se recupera solo vía su polling de `/health`. Antes un crash dejaba la app muda hasta reiniciarla a mano.
- **Cierre sin huérfanos**: al salir, si el agente no responde al SIGTERM en 2 segundos se le manda SIGKILL — un Python colgado ya no queda vivo consumiendo memoria tras cerrar la app.

### Interno

- **`api/server.py` partido en routers por dominio** (`api/routers/{webservice,portal,empresas,procesador,utilidades,system}.py` + `api/state.py` para la sesión FIEL y helpers compartidos). El monolito de 2,579 líneas quedó en 177; las rutas HTTP no cambiaron ni un carácter (verificado contra snapshot pre-refactor). Sin impacto para UI/CLI.

### Interno (UI)

- **Hook genérico `useProcesadorGenerico`**: los 3 hooks de procesador (CFDI/pagos/nómina, ~135 líneas c/u con el mismo patrón de filtros + persistencia debounced + refetch) quedaron como wrappers de ~45 líneas sobre un genérico tipado. Un bug del patrón ahora se corrige en un solo lugar.
- **`lib/errores.ts` con `mensajeDeError()`**: 42 call sites dejaron de repetir `e instanceof Error ? e.message : String(e)`.

### UX

- **Captcha expirado ya no deja el modal abierto**: al agotarse los 5 minutos, el modal se cierra de inmediato y se muestra "El captcha expiró… Inicia la descarga de nuevo" en lugar de un modal congelado esperando un input que ya no sirve.

### Infra

- **Pipeline de firma de código Windows listo** (certificado pendiente): `release.yml` trae los steps de firma de `sat-agent.exe` (Azure Trusted Signing) y verificación post-build, ambos auto-saltables hasta que existan los secrets; `electron-builder.yml` documenta el bloque `azureSignOptions` + `forceCodeSigning`. ⚠️ Documentado en [docs/infra/firma-codigo.md](docs/infra/firma-codigo.md): la vía `WIN_CSC_LINK` (PFX) ya no aplica a certs OV/EV modernos — decidir entre Azure Trusted Signing (~$10/mes) y EV+firma en nube del CA antes de comprar. Firmar el agente, además de SmartScreen, reduce el escaneo de Defender que causa los 30-60 s del primer arranque.

### Infra (macOS)

- **El release ahora construye DMG de macOS por arquitectura** (job `release-macos`: Intel x64 en `macos-13`, Apple Silicon arm64 en `macos-latest` — PyInstaller no cross-compila el agente), con smoke test de `/health` del binario empacado. Sin los secrets de Apple salen sin firmar (QA con clic-derecho → Abrir); la config de hardened runtime + entitlements (Electron JIT + dylibs del agente PyInstaller) ya está lista y la notarización se activa descomentando `notarize` al tener el Developer ID. Checklist en [docs/infra/firma-codigo.md](docs/infra/firma-codigo.md).

### Seguridad

- **Token efímero entre Electron y el agente local.** El shell genera un token aleatorio por arranque y se lo pasa al agente (env `SAT_AGENT_TOKEN`) y al renderer (preload → `window.satAgent.token`); un middleware del agente rechaza con 401 cualquier request sin él (header `X-Agent-Token`, o `?token=` en SSE porque `EventSource` no acepta headers). Cierra el hueco de que cualquier otro proceso local del usuario usara el agente — que mantiene la FIEL cargada en sesión. Sin la env (CLI o `uvicorn` manual en dev) no se exige nada.
- **Anti zip-slip en la descarga WS**: los miembros del ZIP que regresa el SAT se validan antes de extraer; una ruta `../` o absoluta rechaza el paquete completo (`webservice/descarga.py`).
- **Parser lxml endurecido** para todo XML de origen externo (respuestas SOAP del SAT, CFDIs del usuario): sin resolución de entidades, sin DTD y sin red (anti-XXE). Helper central `core/xml_seguro.py` aplicado en `webservice/`, `utils/xml_reader.py` y el parser del procesador.
- **Catálogo a prueba de concurrencia**: `empresas.json`, `historial/*.json` y `settings.json` ahora se escriben de forma atómica (`.tmp` + `os.replace`) y los read-modify-write van serializados con lock — mismo patrón que ya tenían las solicitudes. Evita altas perdidas y JSON corrupto con requests concurrentes.
- **`/abrir` canonicaliza rutas** (resuelve symlinks y `..`) antes de compararlas contra la lista blanca del historial.
- **Electron**: el handler del protocolo `app://` valida el path con `path.relative`; `shell.openExternal` solo acepta `http(s):`/`mailto:`; el `code` del deep link `todoconta://` se valida con charset estricto antes de cruzar al renderer.

- Bump 1.0.6 → 1.1.0 (3 archivos; `pyproject.toml` venía desincronizado en 1.0.4).

---

## [1.0.6] - 2026-06-08

Cierra los **huecos de navegación en subrutas (2 segmentos)** que quedaron tras el protocolo `app://` de v1.0.5, y agrega un flujo para **depurar el bundle empacado en Mac sin instalador**.

### Bug fix

- **Detalle de empresa (engrane) ya no manda al dashboard.** `/empresas/[rfc]` era una ruta dinámica con `dynamicParams: false` y un único placeholder `_`. Bajo `output: 'export'`, cualquier RFC real es **404** → el handler `app://` caía al `index.html` raíz → se veía el inicio. Se reemplazó por una **ruta estática `/empresas/detalle?rfc=…`** que lee el RFC con `useSearchParams()` dentro de `<Suspense>`. Funciona igual en navegación SPA y en reload; se elimina el hack del placeholder y la limitación de 404 en reload.
- **Subrutas estáticas en blanco** (`/comprobantes/cfdi`, `/comprobantes/{nomina,pagos}`, `/descarga/rapida`): artefacto de un build sin `trailingSlash` (se exportaban como `cfdi.html`, no `cfdi/index.html`), así que el handler `app://` no las encontraba y caía al index. Con el build de v1.0.5 (`trailingSlash: true`) cada subruta exporta su `index.html`; se verificó que el handler las resuelve sin fallback.
- **Error boundaries** (`app/error.tsx` + `app/global-error.tsx`): un error de runtime ya no deja pantalla en blanco (que se confundía con "página perdida"); muestra mensaje + reintentar conservando el shell.
- **Copy**: `e-firma` → `e.firma` en la UI (consistencia con el resto del producto; el guion permitía un quiebre de línea "e-/firma").

### Tooling

- **`pnpm debug:packaged`** (en `desktop/`): hace `next build` del UI y levanta Electron sirviendo `ui/out` por `app://` con DevTools y logging del handler (vía `SAT_RENDERER_BUNDLE_DIR` + `SAT_DEBUG_RENDERER`). Reproduce el entorno empacado en Mac **sin** construir un instalador, para validar el routing de subrutas antes del build.
- Bump 1.0.5 → 1.0.6 (ui + desktop).

---

## [1.0.5] - 2026-06-06

Fix de **navegación entre secciones (white-screen), imágenes e íconos** en el bundle empacado. Continúa el diagnóstico de v1.0.4: el `assetPrefix: './'` arreglaba los chunks `_next/` del index, pero `file://` no puede servir paths absolutos ni navegación SPA.

### Bug fix

- **Protocolo propio `app://` en lugar de `file://`** (`desktop/main.js`). El renderer empacado ahora se sirve por un esquema privilegiado (`standard` + `secure`) con un **origen real**, registrado vía `protocol.handle`. El handler mapea el pathname al archivo dentro de `<resources>/ui` con fallback SPA a `index.html` (cubre reload de rutas dinámicas como `/empresas/<RFC>/`) y guarda anti path-traversal.
  - **Causa del white-screen**: `next/link` emite `href` absolutos (`/empresas`, `/comprobantes`, …). Sobre `file://`, el prefetch y la navegación resolvían a `file:///C:/empresas` → `ERR_FILE_NOT_FOUND` → pantalla blanca. Con origen `app://` resuelven contra la raíz del bundle.
  - **Causa de imágenes rotas**: `next/image src="/icon.png"` (login) → `file:///C:/icon.png`. Igual: con `app://` resuelve correctamente.

- **`next.config.ts`**: se **elimina** `assetPrefix: './'` (era frágil: `./_next` se rompía al navegar a subrutas como `/comprobantes/cfdi/`; con `app://` los paths absolutos ya son correctos en toda ruta) y se añade **`trailingSlash: true`** (cada ruta exporta como `<ruta>/index.html`, uniforme y fácil de mapear por el handler).

- **Íconos 100% offline** (`ui/src/lib/icons.ts`): se registran los 39 íconos Phosphor que faltaban en el registro `addIcon`. Sin esto, Iconify caía a su API remota (`api.iconify.design/ph.json`), que falla en el bundle empacado, y los íconos (`star-fill`, `bell-light`, `files-light`, `rocket-light`, …) no aparecían.

### Nota sobre CORS (v1.0.3)

Sigue vigente: con `allow_origins=["*"]` el cambio de origen `file://` → `app://` no afecta el acceso del renderer al agente local.

---

## [1.0.4] - 2026-06-05

**ROOT CAUSE REAL** del *"Cargando…" infinito en Windows*. Diagnóstico definitivo desde DevTools del renderer empacado.

### Bug fix

- **`assetPrefix: './'` en `next.config.ts`** para builds de producción. Por default, Next.js emite paths absolutos (`/_next/static/chunks/abc.js`) que el browser, al servirse desde `file://...resources/ui/index.html`, resuelve como `file:///C:/_next/...` — raíz del disco. **Ningún chunk de JS/CSS cargaba** (17 × `ERR_FILE_NOT_FOUND`). React jamás arrancaba; lo que el usuario veía como *"TodoConta / Cargando…"* era el HTML pre-renderizado del SSG inicial, sin hidratación nunca.

  Cómo nos despistó: el `/health 200` que vimos en logs del agente venía del `waitForHealth()` del proceso main de Electron (Node, no browser), no del renderer. Por eso parecía que el renderer estaba conectado cuando en realidad ni siquiera había ejecutado un solo byte de JavaScript.

  Fix: `assetPrefix: process.env.NODE_ENV === 'production' ? './' : undefined` — paths relativos en `pnpm build`, sin afectar `pnpm dev` (donde el HMR de Next requiere paths absolutos).

  Validado: tras el build, `out/index.html` ahora referencia `./_next/static/chunks/...` (paths relativos).

### Nota sobre v1.0.3 (CORS)

El fix de CORS sigue vigente y es necesario — cuando v1.0.4 finalmente arranque React en el bundle empacado, los `fetch()` desde `file://` enviarán `Origin: null` y necesitan estar permitidos. No remover.

---

## [1.0.3] - 2026-06-05

Fix RAÍZ del bug *"Cargando…" infinito en Windows*. Diagnóstico confirmado por logs reales del agente en producción (v1.0.2 instalada).

### Bug fix

- **CORS bloqueaba al renderer en producción**: la `allow_origins` del agente FastAPI incluía `localhost:3000/3001` (dev) y `app.todoconta.com` (cloud) pero **NO** `null`/`file://`, que es el origin que envía el navegador cuando Electron sirve el bundle empacado desde `file://...resources/ui/index.html`. Resultado:
  - El renderer hacía `GET /health` → llegaba al agente → uvicorn respondía 200.
  - **El navegador descartaba el response por CORS** antes de entregarlo al JS.
  - `useServerHealth` se quedaba con `isConnected=false`.
  - `AuthProvider` jamás invocaba `/auth/license` (espera `isConnected===true`).
  - `loading` quedaba `true` → splash infinito.
  - Logs del agente confirman: una sola línea `GET /health 200` por arranque, cero llamadas a `/auth/license`.

  Fix: `allow_origins=["*"]` + `allow_credentials=False`. Es seguro porque el agente bindea SOLO a `127.0.0.1` (sin exposición a red externa) y el renderer no envía cookies ni credenciales (el Bearer token de Supabase vive solo en el agente Python).

  El bug no salió en dev porque el renderer se sirve desde `http://localhost:3001` (en la allow-list); solo aparecía en el bundle empacado.

---

## [1.0.2] - 2026-06-05

Fix raíz del bug *"Cargando…" infinito* reportado por dos testers en Windows tras v1.0.1.

### Bug fix

- **Lifespan no-bloqueante**: el agente ya no carga la FIEL al arranque dentro del `lifespan` de FastAPI. La llamada a `keyring.get_password()` que hacía el autoload colgaba indefinidamente en Windows con binario sin firma (Credential Manager espera un prompt UI que nunca llega en proceso non-interactive), impidiendo que uvicorn aceptara conexiones → `/health` jamás respondía → renderer atrapado en "Cargando…". Ahora `lifespan` completa de inmediato, uvicorn arranca, `/health` responde en <100ms.

- **Endpoint `/auth/autocargar-fiel`**: nuevo endpoint POST que reemplaza al autoload del lifespan. El renderer lo invoca en background después del login exitoso. Si falla (FIEL faltante, keyring inaccesible), la app sigue funcional — el usuario carga la FIEL a mano desde Empresas como ya hacía hoy.

- **Bootstrap log temprano**: `__main__.py` ahora loguea PID, argv, cwd y `sys.executable` como **primera línea** del agente. Si un usuario reporta que la app no arranca, podemos pedirle `%LOCALAPPDATA%\TodoConta\logs\agent.log` y saber EXACTAMENTE en qué etapa murió.

- **Hiddenimports defensivos en PyInstaller**: agregados `keyring.backends.{Windows,macOS,SecretService,fail}`, `lxml.html`, `email.mime.application`. Sin los keyring backends, `keyring` caía a un backend null que silenciosamente retornaba None — fuente potencial de bugs en distintos perfiles de Windows.

---

## [1.0.1] - 2026-06-04

Bug fixes detectados en QA del primer release público.

### Cambios

- **UI**: el título de la ventana y el titlebar ahora dicen *"TodoConta"* (antes mostraba *"SAT Descarga Masiva"*, sobra de antes del rebrand).
- **Agente**: el `.exe` ya no abre una ventana de consola DOS negra paralela al iniciar (`console=False` en el spec de PyInstaller). Los logs se persisten a `%LOCALAPPDATA%\TodoConta\logs\agent.log` para diagnóstico.
- **Startup más tolerante**: el shell Electron ahora espera hasta 60s a que el agente responda `/health` (antes 30s), por si Windows Defender está escaneando los DLLs del PyInstaller en el primer arranque.
- **Splash informativo**: la pantalla "Cargando…" muestra ahora un mensaje útil después de 15s indicando que el primer arranque puede tardar mientras AV escanea los archivos, y a los 60s ofrece un botón "Reintentar" en lugar de quedarse en blanco para siempre.

---

## [1.0.0] - 2026-06-03

Primer release público del producto **TodoConta Desktop** — instalador Windows distribuible, login obligatorio integrado con `todoconta-apps`, ventana de **Fundadores** (licencia de por vida) para los primeros usuarios.

### Empaquetado y distribución

- Versionado unificado de los 3 subproyectos (`pyproject.toml`, `ui/package.json`, `desktop/package.json`) a `1.0.0`. A partir de aquí, los 3 archivos se sincronizan en cada release.
- Convención SemVer documentada en `docs/infra/versionado.md`.

### Cambios incompatibles

- **Re-base de numeración**: el paquete Python interno venía en `1.2.0`; el producto distribuible arranca su numeración en `1.0.0`. No hay cambios funcionales — solo el número.

---

## v1.2.0 (2026-05-25)

Reorganización del proyecto **por canal de acceso** y **CLI unificado**.

### Cambios

- **Estructura por subpaquetes** en `sat_descarga/`: `core/` (config, fiel, http_client),
  `webservice/` (auth, solicitud, verificacion, descarga, client), `portal/`
  (login, cfdi, constancia), `utils/` (xml_reader, metadata, organizador, validacion),
  `api/` (server, hosted). El paquete `cli/` se movió dentro de `sat_descarga/cli/`.
- **Login SSO extraído** a `portal/login.py` (`iniciar_sesion_ciec` / `iniciar_sesion_fiel`),
  compartido por todos los scrapers del portal.
- **CLI unificado**: las descargas son subcomandos del grupo `descargar`:
  `sat-dm descargar cfdi` (Web Service), `sat-dm descargar ciec` (portal CFDIs) y
  `sat-dm descargar constancia --metodo ciec|fiel`. Se eliminaron los scripts
  `prueba_*.py` de la raíz (eran los runners reales, no tests).
- **API pública estable** re-exportada en `sat_descarga/__init__.py`:
  `descargar_cfdi`, `FIEL`, `descargar_cfdi_ciec`, `descargar_constancia_ciec/fiel`, etc.
- **Tests**: actualizados a las nuevas rutas + nuevos tests de portal (lógica pura) y CLI.

### Cambios incompatibles

- `sat-dm descargar` ahora es un **grupo**: usar `sat-dm descargar cfdi` para el flujo
  anterior de Web Service.
- Los imports por submódulo cambian (p. ej. `sat_descarga.ciec` → `sat_descarga.portal.cfdi`,
  `sat_descarga.validacion` → `sat_descarga.utils.validacion`). La API por la raíz
  (`from sat_descarga import ...`) se mantiene.

---

## v1.1.0 (2026-05-25)

Descarga de la **Constancia de Situación Fiscal (CSF)** vía el portal del SAT, con
login CIEC o e.firma.

### Nuevas funcionalidades

- **Constancia de Situación Fiscal**: descarga el PDF de la constancia mediante
  scraping del portal (sin Web Service), con dos métodos de login:
  - **CIEC** (RFC + contraseña; el usuario resuelve el captcha).
  - **e.firma / FIEL** (`.cer` + `.key` + contraseña): **100% automático, sin
    captcha** — ideal para automatización/desatendido.
  - API: `descargar_constancia_ciec(rfc, ciec)` y `descargar_constancia_fiel(cer, key, password)`.
  - Endpoint `POST /constancia/descargar`; runners `prueba_constancia.py` y `prueba_constancia_fiel.py`.
- **Login SSO reutilizable**: `iniciar_sesion_ciec()` e `iniciar_sesion_fiel()` en
  `sat_descarga/ciec.py`, compartidos por los scrapers (CFDI, constancia y futuros).
  El flujo CFDI delega en el helper sin cambiar su comportamiento.

### Notas técnicas

- El botón "Generar Constancia" es JSF/PrimeFaces dentro de un iframe (`rfcampc.siat`);
  el PDF abre en un popup (`IdcGeneraConstancia.jsf`). e.firma entra por el lanzador
  (`tipoLogeo=c`) + botón `#buttonFiel`.
- El servidor del SAT usa TLS con clave DH muy pequeña que Node rechaza; el PDF se
  captura desde el navegador (Chromium) en vez de una petición HTTP separada.

### Archivos nuevos

- `sat_descarga/constancia.py` — cliente de la CSF (CIEC + e.firma)
- `prueba_constancia.py` / `prueba_constancia_fiel.py` — runners

---

## v1.0.0 (2026-05-24)

Interfaz web (UI + API), descarga vía CIEC sin e-firma, y madurez del proyecto.

### Nuevas funcionalidades

- **Descarga vía CIEC (portal web, sin e-firma)**: para contribuyentes que no cuentan con FIEL
  - `sat_descarga/ciec.py` — cliente Playwright headful (el usuario resuelve el captcha)
  - Recibidos (día por día) y Emitidos (rango); modo "ambos" con un solo captcha
  - Descarga item por item vía `RecuperaCfdi.aspx?Datos=`; subcarpetas `recibidos/` y `emitidos/`
  - Detección de cuota diaria del portal (se detiene tras 3 fallos seguidos)
  - Runner de ejemplo: `prueba_ciec.py RFC CIEC desde hasta [R|E|RE]`
- **Servidor FastAPI** (`localhost:8787`): expone SATDescarga vía HTTP sin que la e-firma salga de la máquina (compatible con apps web como todoconta)
  - Auth (e-firma en memoria), solicitar/verificar/descargar, folio, metadata, validación, descarga-completa, descarga-inteligente y `/ciec/descargar`
- **UI web (Next.js)**: interfaz para descarga, validación y organización de CFDIs

### Archivos nuevos

- `sat_descarga/ciec.py` — descarga vía portal CIEC (Playwright)
- `sat_descarga/server.py` — servidor FastAPI
- `ui/` — aplicación web Next.js
- `docs/producto/protocolo-sat.md` — detalle del protocolo SOAP del Web Service y de la mecánica del portal CIEC

---

## v0.2.0 (2026-04-01)

Validación, metadata, descarga por UUID, y herramientas de organización de XMLs.

### Nuevas funcionalidades

- **Validación de CFDI ante el SAT**: verifica estatus (Vigente/Cancelado/No Encontrado) sin FIEL
  - `sat-dm validar ./xmls/` con export a CSV
  - Validación masiva con ThreadPoolExecutor (10 hilos en paralelo)
  - Endpoint `POST /validar` en FastAPI (compatible con todoconta-apps)
- **Descarga de metadata**: resumen rápido de CFDIs sin descargar XMLs
  - Hasta 1,000,000 registros por solicitud, procesados en segundos
  - Parser automático del CSV del SAT (separador `~`, encoding auto-detect)
  - `sat-dm metadata --desde --hasta --csv-export reporte.csv`
  - Flag `--local` para re-parsear metadata ya descargada
  - Deduplicación automática por UUID
- **Descarga por UUID**: `SolicitaDescargaFolio` para descargar CFDIs específicos
  - `descargar_por_uuid()` en la API Python
  - Endpoint `POST /solicitar-folio` en FastAPI
- **Organizador de XMLs**: herramientas para ordenar archivos descargados
  - `sat-dm organizar carpetas` — 9 estructuras de carpetas (RFC/año/mes, tipo/año/mes, etc.)
  - `sat-dm organizar renombrar` — 5 patrones de renombrado por contenido del XML
  - `sat-dm organizar deduplicar` — elimina duplicados por UUID (con dry-run)
  - Agrupador por versión CFDI y tipo de comprobante
- **Parser ligero de XML CFDI**: extrae headers (emisor, receptor, fecha, UUID, total) sin parseo completo, namespace-agnostic

### Correcciones

- **RFC de personas morales**: el certificado FIEL contiene `RFC_EMPRESA / RFC_REPRESENTANTE` en UniqueIdentifier; ahora toma correctamente el primero (antes tomaba el del representante legal)
- **Auto-detección de FIEL**: excluye directorios `tests/`, `.venv/` y archivos CSD del globbing

### Archivos nuevos

- `sat_descarga/validacion.py` — validación de estatus CFDI contra SAT
- `sat_descarga/metadata.py` — parser de metadata CSV del SAT
- `sat_descarga/xml_reader.py` — parser ligero de CFDI XML
- `sat_descarga/organizador.py` — organizar, renombrar, deduplicar XMLs
- `cli/validar.py` — CLI de validación masiva
- `cli/metadata_cmd.py` — CLI de descarga de metadata
- `cli/organizar.py` — CLI de organización de archivos

---

## v0.1.0 (2026-03-30)

Primera versión funcional. Descarga masiva de CFDIs del SAT vía Web Service oficial (API v1.5).

### Funcionalidades

- **Descarga masiva vía e-firma (FIEL)**: flujo completo solicitar -> verificar -> descargar
- **CLI multi-empresa**: registrar múltiples FIELs, seleccionar interactivamente o por argumentos
- **Gestión de empresas**: `empresas add`, `list`, `remove`, `default`
- **Auto-detección de FIEL**: busca archivos `.cer`, `.key` y `password.txt` automáticamente
- **Organización por RFC**: archivos FIEL en `./efirma/{RFC}/`, descargas en `./descargas/{RFC}/`
- **Fecha de vencimiento**: visible en el listado de empresas con indicador de color
- **Retomar solicitudes**: `retomar <RequestID>` para descargas interrumpidas
- **Emitidos y recibidos**: descarga individual o ambos en una sola ejecución
- **Polling automático**: backoff exponencial (30s a 5min) durante el procesamiento del SAT
- **Reintentos HTTP**: 6 reintentos con backoff para la inestabilidad SSL del SAT
- **Renovación de token**: automática antes de cada descarga (token dura ~5 min)

### Detalles técnicos

- API v1.5 del SAT (mayo 2025): firma xmldsig enveloped con C14N inclusiva
- `EstadoComprobante`: `"Vigente"`, `"Cancelado"`, `"Todos"`
- Recibidos requiere `RfcReceptor` explícito
- SOAPAction de descarga: `IDescargaMasivaTercerosService/Descargar`
- Probado con descarga real de ~950 CFDIs (emitidos + recibidos)

# Protocolo del SAT — notas de implementación

Detalle técnico del protocolo del SAT (conocimiento de dominio que NO se necesita
en cada sesión; por eso vive aquí y no en CLAUDE.md). Dos vías: Web Service (FIEL)
y portal CIEC (scraping).

## Web Service oficial (e-firma / FIEL)

Protocolo SOAP sobre HTTPS (WCF/Microsoft `.svc`). Autenticación **solo con e-firma**
(`.cer` + `.key` + contraseña); NO funciona con CIEC. Flujo asíncrono.

```
1. FIEL.sign()  →  auth.obtener_token()              →  Token UUID (~5 min)
2. solicitud.solicitar_descarga()                    →  RequestID
3. verificacion.verificar_solicitud() [polling]      →  PackageIDs (cuando CodEstado=3)
4. descarga.descargar_todos()                        →  ZIPs con XMLs
```

El token dura ~5 min y se renueva antes de cada descarga (el polling puede durar horas).
SSL inestable (~25% de fallos): se fuerza TLS 1.2 con `check_hostname=False` y
`verify=False`, 6 reintentos con backoff (`http_client.py`). Cliente SOAP manual con
`lxml` (`huge_tree=True`) — sin zeep/suds — para controlar namespaces y firma.

### Estados de VerificaSolicitud

| CodEstado | Significado |
|---|---|
| 1 | En cola |
| 2 | Procesando |
| 3 | Lista (PackageIDs listos) |
| 4 | Error del SAT |
| 5 | Rechazada |

### Códigos de estatus (`CodEstatus`) — tabla oficial del SAT

Los `3xx` son comunes a las tres operaciones (Solicita / Verifica / Descarga); los `5xxx`
son propios de cada una. Transcritos de la documentación del SAT (fuentes al final).

**Comunes (3xx) — validación de la petición y del certificado**

| Código | Mensaje | Observaciones del SAT |
|---|---|---|
| 300 | Usuario No Válido | |
| 301 | XML Mal Formado | "cuando el request posee información invalida, ejemplo: un RFC de receptor no valido" |
| 302 | Sello Mal Formado | |
| 303 | Sello no corresponde con RfcSolicitante | |
| 304 | Certificado Revocado o Caduco | "El certificado fue revocado o bien la fecha de vigencia expiró" |
| 305 | Certificado Inválido | "El certificado puede ser invalido por múltiples razones como son el tipo, **codificación incorrecta**, etc." |
| 404 | Error no Controlado | Genérico y **transitorio** del SAT; reintentar (ver `webservice/errores.py`) |

**SolicitaDescarga (5xxx)**

| Código | Mensaje | Observaciones del SAT |
|---|---|---|
| 5000 | Solicitud de descarga recibida con éxito | |
| 5001 | Tercero no autorizado | "El solicitante no tiene autorización de descarga de xml de los contribuyentes" |
| 5002 | Se han agotado las solicitudes de por vida | "Se ha alcanzado el límite de solicitudes, con el mismo criterio" |
| 5005 | Ya se tiene una solicitud registrada | "Ya existe una solicitud activa con los mismos criterios" |
| 5006 | Error interno en el proceso | |

**Descargar (5xxx)**

| Código | Mensaje | Observaciones del SAT |
|---|---|---|
| 5000 | Solicitud de descarga recibida con éxito | |
| 5004 | No se encontró la información | |
| 5007 | No existe el paquete solicitado | "Los paquetes solo tienen un periodo de vida de 72hrs" |
| 5008 | Máximo de descargas permitidas | "Un paquete solo puede descargarse un total de 2 veces" |

**Orden de validación (importante al depurar):** el SAT valida **parámetros antes que
certificado**. Una petición con parámetros inválidos devuelve `301` y **nunca llega a
evaluar el certificado** — es fácil concluir "el certificado pasó" cuando ni se revisó.
Hay que llegar a una petición con parámetros válidos para que aparezca un `304`/`305`.

**Sobre el `305`:** la observación "codificación incorrecta" es literal y aplica a un caso
real — los certificados de la CA del SAT de mayo 2023 traen un `PrintableString` con bytes
UTF-8 y **el WS de descarga masiva los rechaza con 305**, aunque el portal (login por
e.firma, CSF, 32-D, descarga de CFDIs) y `Autenticacion.svc` los aceptan. Detalle completo:
[certificados-sat-printablestring-mayo-2023.md](certificados-sat-printablestring-mayo-2023.md).
Ojo con la discrepancia de la propia documentación del SAT: en el doc de Solicitud, el `304`
repite palabra por palabra la observación del `305`; la redacción buena (la que distingue
revocado/caduco de codificación) está en el doc de Descarga.

**Fuentes** (PDFs del portal del SAT, sección Factura Electrónica → Consulta y Recuperación
de Comprobantes):
- *Documentación del Servicio de Solicitud de Descarga Masiva de CFDI y CFDI de Retenciones*,
  11 de mayo de 2022, versión 1.2 — tabla de Solicita.
- *Documentación para la implementación del Servicio Web de Descarga Masiva de CFDI y
  retenciones — Servicio de Descarga de Solicitudes Exitosas*, agosto 2018, versión 1.1 —
  tabla de Descargar (es la que trae "codificación incorrecta" en el 305).

### Endpoints (ver `sat_descarga/config.py`)

```
autenticacion:      https://cfdidescargamasivasolicitud.clouda.sat.gob.mx/Autenticacion/Autenticacion.svc
solicita_descarga:  https://cfdidescargamasivasolicitud.clouda.sat.gob.mx/SolicitaDescargaService.svc
verifica_solicitud: https://cfdidescargamasivasolicitud.clouda.sat.gob.mx/VerificaSolicitudDescargaService.svc
descarga_masiva:    https://cfdidescargamasiva.clouda.sat.gob.mx/DescargaMasivaService.svc
```

### API v1.5 — cambios confirmados (mayo 2025)

**Autenticación:** WS-Security SOAP. Namespace `http://DescargaMasivaTerceros.gob.mx`.
Devuelve WRAP token URL-encoded (`JWT%26wrap_subject%3dSERIAL`) que va en el header
`Authorization: WRAP access_token="{token}"`.

**Solicitud / Verificación / Descarga:**
- Nuevo namespace body: `http://DescargaMasivaTerceros.sat.gob.mx` (con `.sat`).
- NO hay token SOAP (se eliminó `SolicitaDescargaHeader`).
- Cada request lleva firma **xmldsig enveloped** (firmada con la FIEL).
- El elemento firmado es el **padre** de `<solicitud>` (ej. `SolicitaDescargaEmitidos`);
  la `<Signature>` se añade como **hijo de `<solicitud>`**.
- C14N **inclusiva** (`...REC-xml-c14n-20010315`), no exclusiva.
- Referencia `URI=""` + transform `enveloped-signature`.
- KeyInfo: `X509IssuerSerial` (issuer RFC4514 + serial decimal) + `X509Certificate`.

### Detalles descubiertos en pruebas reales (marzo 2026)

- `EstadoComprobante` usa texto: `"Vigente"`, `"Cancelado"`, `"Todos"` (no numérico) y
  debe ir **primero** en el orden de atributos.
- Recibidos requiere `RfcReceptor` explícito (= RFC del solicitante), sino error 301.
- Recibidos + CFDI solo acepta `"Vigente"` (cancelados son rechazados).
- SOAPAction de descarga: `IDescargaMasivaTercerosService/Descargar`.
- Elemento de descarga: `PeticionDescargaMasivaTercerosEntrada` (con "s" en "Terceros").
- `IdsPaquetes`: cada paquete es un `<IdsPaquetes>` separado, no hijos de un contenedor.
- "Solicitudes agotadas de por vida" (CodEstatus=5002): el SAT limita por rango exacto
  de fechas+segundos; variar los segundos genera una solicitud nueva.
- Respuesta de descarga: el `<Paquete>` (ZIP Base64) está en
  `<RespuestaDescargaMasivaTercerosSalida>`.

## Portal CIEC (scraping, sin FIEL) — `sat_descarga/portal/cfdi.py`

Para contribuyentes sin e-firma. Playwright headful: el usuario resuelve el captcha en
el browser; el resto es automático. Portal `portalcfdi.facturaelectronica.sat.gob.mx`.

- **Login:** pre-llena RFC + contraseña; espera el redirect a portalcfdi (cfdiau → SSO).
- **Radio "Fecha":** requiere **click NATIVO** (`page.click`); setear `.checked` + invocar
  `__doPostBack` por JS NO basta (el server re-renderiza con los campos disabled).
- **Emitidos:** rango de fechas; el input de fecha es disabled-por-diseño (date-picker),
  se fuerza por JS. **Recibidos:** filtra un día a la vez, se itera día por día.
- **Render AJAX:** la búsqueda usa UpdatePanel; hay que esperar a que el spinner
  `UpdateProgress1` se oculte y aparezcan filas (`networkidle` da falsos 0).
- **Descarga:** cada fila trae `RecuperaCfdi.aspx?Datos=<token>` (devuelve el XML como
  adjunto). La paginación es client-side (todas las filas en el DOM, máx 500/consulta).
- **Cuota diaria:** el portal limita descargas (`hfDescarga` = CuotaParcial/CuotaCompleta);
  el cliente se detiene tras 3 fallos seguidos.

## Constancia de Situación Fiscal (CSF) — `sat_descarga/portal/constancia.py`

Mismo login CIEC reutilizado (`iniciar_sesion_ciec`), solo cambia entrada + navegación.

- **Entrada estable:** el "lanzador" `wwwmat.sat.gob.mx/app/seg/faces/pages/lanzador.jsf
  ?url=/operacion/43824/reimprime-tus-acuses-del-rfc&tipoLogeo=c&target=principal&hostServer=...`
  (es el href del enlace «servicio» del trámite). `tipoLogeo=c` = CIEC. NO reusar las URLs
  NIDP ya logueadas: traen parámetros de sesión efímeros (cargan en blanco).
- **Login:** redirige al NIDP (captcha), aterriza en `wwwmat.sat.gob.mx/operacion/43824`.
- **Botón "Generar Constancia"**: JSF/PrimeFaces (id dinámico), vive **dentro de un iframe**
  servido por `rfcampc.siat.sat.gob.mx/PTSC/...` → buscarlo en todos los frames por texto.
- **Descarga:** el onclick hace AJAX + `window.open('/PTSC/IdcSiat/IdcGeneraConstancia.jsf')`
  → un **popup con el PDF**.
- **TLS débil:** `rfcampc.siat.sat.gob.mx` usa una clave Diffie-Hellman muy pequeña; el
  `APIRequestContext` de Playwright (Node/OpenSSL) la rechaza (`dh key too small`). Solución:
  capturar el PDF **desde el navegador** (Chromium la tolera) con un listener `response` en
  el popup que guarda los bytes (`%PDF-`), en vez de re-pedir la URL aparte.

## Opinión de Cumplimiento 32-D (pendiente)

Mismo patrón. Entrada OAuth2/OIDC (PKCE) → `ptsc32d.clouda.sat.gob.mx/#/reporteOpinion32DContribuyente`;
el PDF se abre directo al aterrizar (sin botón). Los params PKCE/state son efímeros: entrar por
la página del trámite que inicia el SSO fresco.

## Portal DIOT (pstcdi, carga masiva)

Entrada `pstcdi.clouda.sat.gob.mx` vía lanzador NIDP, e.firma sin captcha. SPA; la
declaración se arma como "temporal" y solo el acuse PDF prueba la presentación (una firma
fallida puede consumir la temporal SIN presentar — comprobado 2026-07-31). La e.firma del
envío se carga por el botón «Buscar» (file chooser): inyectar al input oculto deja `#txtRFC`
vacío y truena con "RFC de la sesión no coincide". El validador recalcula el IVA por renglón
como `round((valor−devol)×0.16)` e ignora el campo de IVA del TXT. Formulario clásico
(ejercicios ≤2024): pantalla única, sin tabs, no pregunta estímulos. Detalle completo:
`docs/producto/diot-2025.md` §Presentación.

## Portal Contabilidad Electrónica (DOS hosts)

Envío en `ceportalenvioprod.clouda.sat.gob.mx`; consulta de acuses en
`ceportalconsultaextprod.clouda.sat.gob.mx` (el host de envío sirve una copia de
/ConsultaAcuses visualmente idéntica pero rota: `$ is not defined` + BuscaAcuses→500). La
sesión SSO sirve en ambos. El portal de envío se traga interacciones en silencio (primer
«Agregar» tras la e.firma, radio de sellado, lista de motivos reemplazada) y su error
transitorio del xmlTemp es la norma (1-4 intentos por archivo). La búsqueda de acuses es un
POST JSON ejecutado DESDE la página (same-origin). Detalle completo y tabla de hallazgos:
`docs/producto/contabilidad-electronica.md`.

## Portal de declaraciones (pstcdypisr) — `sat_descarga/portal/declaraciones.py`

Consulta y descarga de declaraciones presentadas y sus acuses (sep 2026, recorrido real):

- **Entrada**: `https://pstcdypisr.clouda.sat.gob.mx/` → redirige a
  `loginda.siat.sat.gob.mx/nidp/wsfed/ep?id=ciec...` (mismo widget NIDP: `form#IDPLogin`,
  `#rfc`/`#password`/`#userCaptcha`, o e.firma vía `#buttonFiel`). Aterriza de vuelta en
  `pstcdypisr` (predicado: host parseado, excluyendo `/nidp`).
- **Menú Consultas**: `/Consulta/Consulta?tipoDocumento=1` (De la declaración), `=2`
  (Declaraciones pagadas), `=3` (Acuse de recibo de la declaración), `=4` (Por obligación).
- **Form** (`#cDataConsulta data-tipodocumento`): `#IdDeclaracion` (001 Provisionales y
  Definitivas), `#TipoDeclaracion` (opcional), `#Ejercicio`, `#Periodicidad` (M/T/S/B/N; al
  elegir M se llena y habilita `#Periodo` con 001..012), `#NumeroOperacion`, `#LineaCaptura`,
  `#btnBuscar`.
- **Resultado**: `#tableResult tbody#tableBody`, una `<tr>` por declaración: link
  `a#linkDescargaPDF` (`/Consulta/RecuperarArchivo?enLinea=0&tipoDocumento=N&numeroOperacion=X&ejercicio=AAAA`),
  No. de operación, tipo (Normal/Complementaria), tipo de complementaria, línea de captura,
  fecha de presentación, periodicidad, periodo, fecha de causación y un `td.d-none` Estado.
  El link descarga el PDF directo (Content-Disposition); nombres tipo `RFC.38.AAAA.pdf` y
  `Acuse.RFC.38.AAAA.pdf`. Si no hay registros, el portal avisa con un bootbox.

### Consulta de DIOT presentadas (pstcdi) — `sat_descarga/portal/diot_consulta.py`

Recorrido real (sep 2026), gemelo del portal de pagos provisionales:

- **Entrada** `https://pstcdi.clouda.sat.gob.mx/` → mismo widget NIDP (loginda); aterriza en
  `pstcdi` (host parseado, sin `/nidp`). Menú: «Presentar declaración» (`/Declaracion/Temporales`),
  «Consultar declaración» (`/Consulta/Consulta/1`) e «Impresión de acuse» (`/Consulta/Consulta/3`).
- **Form** (`#bodyDiv`): `#IdDeclaracion` (001 Declaraciones Informativas), `#TipoDeclaracion`
  (opcional), `#Ejercicio`, `#Periodicidad` (M/T/Q/S/L/Y/B; M habilita `#Periodo` 001..012),
  `#NumeroOperacion`, `#TipoConcepto` (9002 DIEMSE, 9003 Forma 81, 9004 Forma 63, 9005 Forma 76,
  **9006 DIOT**), `#btnBuscar`.
- **Resultado** `#tableResult tbody#tableBody`: [link PDF, link Excel (`td.descargaExcel`, oculto
  en acuses), No. de Operación, Estatus (Vigente), Tipo de Declaración, Tipo de Complementaria,
  Fecha de Presentación, Periodicidad, Período]. El PDF va en
  `onclick="abrirArchivoPDF('/Consulta/RecuperarArchivo?enLinea=0&tipoDocumento=1&numeroOperacion=X&ejercicio=AAAA&tipoArchivo=0&periodo=001&tipoConcepto=9006')"`
  (descarga directa); el Excel en `onclick="buscarArchivoExcel(crear, recuperar, estado)"`
  (`CrearArchivoExcelDiot` → modal «Generando archivo» 3-4 s → `RecuperarArchivo?...tipoArchivo=1`).
- **Nombres que entrega el SAT**: `Decla_<op>_0MMAAAA.pdf` (declaración), `Detalle_<op>_0MMAAAA.xlsx`
  (Excel con las operaciones) y `Acuse_<op>_0MMAAAA.pdf` (acuse). Las descargas se indexan en
  `descargas/diot/consultas/{RFC}/diot.json`.

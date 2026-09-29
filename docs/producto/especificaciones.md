# TodoConta Desktop: especificaciones del producto

> **Versión del documento**: 2 · **Fecha**: 2026-09-28 · **Versión del producto**: v2.2.0
>
> Este documento describe el producto en tres partes: **Parte I** para perfiles técnicos, **Parte II** para el contador que va a usarlo y **Parte III** con el roadmap (lo entregado y lo que sigue pendiente).

---

## Resumen ejecutivo

**TodoConta Desktop** es una aplicación de escritorio para Windows y macOS (Apple Silicon) que el contador instala en su equipo para automatizar el trabajo recurrente con el SAT: descargar CFDIs, obtener la Constancia de Situación Fiscal y la Opinión 32-D, procesar comprobantes (CFDI, Pagos y Nómina), preparar la DIOT, validar contra listas negras, usar calculadoras fiscales y laborales, llevar sus pendientes y mantener un historial de cada operación. En la app de escritorio **la e.firma del cliente no sale del equipo del contador**, salvo que él active, empresa por empresa, el uso en la web.

Desde v2.0 el mismo producto también corre en el navegador (**app.todoconta.com**): mismo renderer y mismo agente, con un espacio privado por usuario en la nube. La cuenta es una sola, y el catálogo de empresas, la configuración fiscal, las tareas y la configuración del organizador se sincronizan entre ambas.

El producto cubre los dos canales del SAT (Web Service oficial con e.firma y portal con Contraseña del SAT o e.firma). Por línea de comandos y API, el agente además envía la contabilidad electrónica, presenta la DIOT por carga masiva y descarga declaraciones y DIOT ya presentadas; esas funciones todavía no tienen pantalla (ver Parte II). Una parte de estos servicios (documentos del SAT, CFDIs y sus reportes, calculadoras y listas negras) también se ofrece a integradores y asistentes de IA mediante una API pública y un servidor MCP.

---

# Parte I: Especificación técnica

## Arquitectura

El mismo código se distribuye en dos modos:

1. **Desktop**: instalador nativo con el shell Electron, el renderer (`ui/`) y el agente Python empaquetado. Todo corre en el equipo del usuario.
2. **Versión web**: el mismo `ui/` compilado en modo web y servido desde Vercel en `app.todoconta.com`. El mismo agente corre en un contenedor Docker por usuario en un VPS, detrás de `agente.todoconta.com`.

### Modo desktop

```
┌────────────────────────────────────────────────────────────────┐
│  Instalador: Windows NSIS x64 · macOS DMG/ZIP arm64            │
│                                                                │
│  ┌────────────────────┐    ┌──────────────────────────────┐    │
│  │  Electron 33       │    │  Agente Python (FastAPI)     │    │
│  │  (shell nativo)    │◄──►│  sat-agent (PyInstaller)     │    │
│  │  app:// → ui/      │    │  127.0.0.1:<puerto efímero>  │    │
│  │  Next.js 16        │    │  token efímero por arranque  │    │
│  │  React 19          │    │                              │    │
│  │  Tailwind 4        │    │  • Web Service SAT (SOAP)    │    │
│  └────────────────────┘    │  • Portal SAT (Playwright)   │    │
│                            │  • Procesador (SQLite)       │    │
│                            │  • DIOT · CE · calculadoras  │    │
│                            │  • Poller en background      │    │
│                            └──────────────────────────────┘    │
└────────────────────────────────────────────────────────────────┘
                              │
                              │ HTTPS (Bearer de la cuenta, solo en el agente)
                              ▼
                ┌────────────────────────────────────┐
                │  api.todoconta.com                 │
                │  (proyecto todoconta-apps, Vercel) │
                │                                    │
                │  • Cuentas (Supabase Auth)         │
                │  • Licencias y pagos (Stripe)      │
                │  • Listas negras (cron mensual)    │
                │  • Sync de catálogo y tareas       │
                │  • Equipos y API keys              │
                └────────────────────────────────────┘
```

### Versión web

```
[navegador] ── https://app.todoconta.com       (Vercel: ui/ en build web)
     │            └─ /api/*, /auth/*, /desktop/* → api.todoconta.com
     │
     ├── https://agente.todoconta.com/provision/*  → provisioner
     │        (primer login: valida cuenta y plan, crea o enciende el contenedor)
     │
     └── https://agente.todoconta.com/u/{slug}/*   → agente-{slug}
              (mismo agente en modo hosted, con su propio volumen /data)

[integrador o asistente de IA]
     ├── https://api.todoconta.com/v1/*    → gateway ─┐
     └── https://agente.todoconta.com/mcp  → gateway ─┴→ agente del usuario → SAT
```

- **Un contenedor por usuario**: el mismo aislamiento que da la máquina del usuario en desktop, sin reescribir el agente a multi-tenant. La sesión de e.firma en memoria, el catálogo JSON, los jobs y el poller funcionan igual.
- **Provisioner** (`deploy/provisioner/`): resuelve el primer login de la web, cuando el navegador todavía no conoce su agente. Autentica contra Supabase, valida el plan, crea o arranca el contenedor y entrega a la UI la dirección y el token de su agente; la sesión pasa al agente con `POST /auth/adopt-session`. El slug, el token y la clave de secretos se derivan de forma determinista por usuario, así que un login desde otro navegador recupera el mismo contenedor. También registra cuentas nuevas desde la web (`POST /provision/signup` con contraseña, u `otp-send` con `crear_cuenta` por código): al confirmar el correo, la licencia arranca la prueba de 15 días y se abre el espacio. Antiabuso: límite por IP y por correo, correos temporales bloqueados y un tope de espacios nuevos (`MAX_AGENTES`); quien ya tiene su contenedor siempre entra.
- **Modo hosted del agente** (`SAT_DM_MODO=hosted`): secretos en `secretos.enc`, cifrado con AES-256-GCM dentro del volumen del usuario (en lugar del llavero del SO); descargas en `/data/descargas` servidas por `GET /descargas/*` (en lugar de `POST /abrir`); CORS restringido a `app.todoconta.com`; poller activo 24/7.
- **Gateway** (`deploy/gateway/`): API pública REST v1 y servidor MCP (Streamable HTTP en `/mcp`). Acepta una API key (en la base compartida solo vive su hash) o un token OAuth 2.1 para conectores como claude.ai y ChatGPT; deriva el agente del usuario, lo enciende si hace falta y le rutea la operación. Los archivos se entregan con un enlace de descarga firmado que expira en 1 h. Documentación interactiva en `https://api.todoconta.com/v1/docs`.

| Superficie del gateway | Operaciones |
|---|---|
| REST v1 | `GET /v1/health`, `GET /v1/empresas`, `POST /v1/csf`, `POST /v1/opinion`, `POST /v1/cfdi/solicitudes`, `GET /v1/cfdi/solicitudes/{rfc}/{id}` (y `/zip`), `POST /v1/cfdi/procesar`, `GET /v1/cfdi/{resumen,excel}`, `GET /v1/cfdi/reporte/{nombre}`, `POST /v1/calculadoras/{tipo}`, `POST /v1/listas-negras` |
| Tools MCP | `listar_empresas`, `descargar_csf`, `descargar_opinion`, `solicitar_cfdis`, `estado_solicitud`, `descargar_zip_cfdis`, `procesar_cfdis`, `resumen_cfdis`, `reporte_cfdis`, `excel_cfdis`, `consultar_listas_negras`, `calcular_sbc`, `calcular_isr_salarios`, `calcular_aguinaldo`, `calcular_finiquito`, `calcular_carga_patronal`, `indicadores_fiscales` |

Cómo se despliega y se opera: [despliegue-vps.md](../infra/despliegue-vps.md).

### Stack

| Componente | Tecnología | Versión |
|---|---|---|
| Agente | Python + FastAPI + uvicorn | Python 3.12 en los builds; `fastapi>=0.104`, `uvicorn>=0.24` |
| Portal del SAT | Playwright + Chromium (se descarga en el primer uso; en la imagen web viene incluido) | `playwright>=1.40` |
| Persistencia local | JSON en `~/.sat-descarga/` + SQLite (`procesador.db`) + llavero del SO (`keyring`) | `keyring>=24` |
| Renderer | Next.js (App Router, `output: 'export'`) + React | 16.1.1 / 19.2.3 |
| Estilos y UI | Tailwind + Radix UI + Iconify (Phosphor) + cmdk + sonner | Tailwind 4.2 |
| Shell | Electron + electron-builder + electron-updater | 33.4 / 25.1 / 6.8 |
| Telemetría | Sentry en renderer, main y agente (apagado sin DSN) | `@sentry/electron` 7.13 / `sentry-sdk>=2.0` |
| Empaquetado | PyInstaller (onedir en Windows y Linux, onefile en macOS) + electron-builder | PyInstaller sin versión fija (última en cada build) |
| Versión web | `ui/` en Vercel + agente en Docker (`python:3.12-slim`) por usuario + Traefik + provisioner + gateway (FastAPI + SDK oficial de MCP) | Python 3.12 en la imagen del agente |
| Backend de cuentas | Next.js + Supabase + Stripe (proyecto `todoconta-apps`, en `api.todoconta.com`) | Se versiona en su propio repo |

> Las versiones de JavaScript salen de los lockfiles (el CI instala con `--frozen-lockfile`). Las de Python son los mínimos de `pyproject.toml`: el build del release las resuelve con `pip`.

### Decisiones arquitectónicas firmes

- **En desktop, la e.firma no sale del equipo**: los archivos `.cer`/`.key` viven localmente y las contraseñas en el llavero del SO (Windows Credential Manager, macOS Keychain, Linux Secret Service) vía `keyring`. La única salida es opcional y por empresa: "Usar en la web" sube las credenciales cifradas por HTTPS directo al contenedor personal del usuario, nunca a la base de datos compartida (`api/espacio_online.py`).
- **En la versión web, las credenciales sí viven en el servidor**, cifradas en el espacio propio del usuario. Es la condición de la movilidad y se comunica así, nunca como equivalente a la promesa desktop.
- **Cero exposición de red en desktop**: el agente escucha solo en `127.0.0.1` y exige un token aleatorio por arranque (header `X-Agent-Token`, o `?token=` en SSE) que Electron comparte con el renderer. Otro proceso local del usuario no puede usar el agente.
- **La sesión de la cuenta vive solo en el agente**: el token de Supabase nunca llega al renderer, ni en desktop ni en web. El renderer solo conoce estado derivado (plan, prueba, vigencia).
- **`appId` inmutable**: `com.todoconta.desktop`. Cambiarlo rompería el auto-update en equipos ya instalados.
- **Multi-empresa first-class**: el catálogo (`~/.sat-descarga/empresas.json`) soporta múltiples RFCs con e.firma, Contraseña o ambas; la empresa activa controla la sesión. Procesador, calculadoras y flujos de descarga se aíslan por RFC.
- **Mismo codebase, dos empaques**: el agente detecta el modo por variable de entorno y el renderer por build (`NEXT_PUBLIC_MODO_WEB`). No existe un agente multi-tenant.
- **Dos canales en cada consulta**: Contraseña (con captcha) y e.firma (sin captcha) en CFDIs, Constancia, Opinión 32-D, declaraciones y DIOT presentadas. Los envíos al SAT (contabilidad electrónica, DIOT, renovación de e.firma y CSD) son solo con e.firma. El Web Service queda para volumen alto con e.firma.
- **Lo irreversible solo valida por default**: presentar la DIOT, enviar la contabilidad electrónica y renovar la e.firma exigen confirmación explícita (`--enviar` en el CLI, `confirmar=true` en la API).

## Componentes del agente Python

### `sat_descarga/webservice/`: Web Service oficial del SAT

Cliente SOAP manual con `lxml` (sin zeep ni suds) sobre la API v1.5 del SAT:

- **Autenticación WS-Security** firmada con la e.firma (el token dura unos 5 minutos y se renueva).
- **Solicitudes** por rango de fechas (emitidos o recibidos) o por lista de UUIDs (`SolicitaDescargaFolio`).
- **Tipos**: CFDIs completos o solo metadata (el listado).
- **TLS 1.2 como mínimo** con un adaptador propio para la inestabilidad del certificado del SAT, más 6 reintentos con backoff.
- Verificación, descarga de paquetes ZIP con extracción segura (anti zip-slip) y manejo de errores que separa las fallas transitorias del SAT (se reportan como "El SAT no respondió", reintentable) de los rechazos de la solicitud, a los que la app agrega la acción concreta.

### `sat_descarga/portal/`: portal del SAT con Playwright

Scraping headless con selectores confirmados contra el SAT real:

- `login.py`: login SSO reutilizable, con Contraseña (captcha) o e.firma.
- `captcha.py`: la imagen del captcha viaja al renderer por SSE, el usuario la resuelve en una modal de la app y la respuesta regresa por `POST /jobs/{id}/captcha`. Sin OCR.
- `setup.py`: descarga o actualiza Chromium en background al arrancar (`/health` reporta `navegador: instalando|listo|error`), en `%LOCALAPPDATA%\TodoConta\playwright-browsers\` (Windows) o `~/.cache/todoconta/playwright-browsers/` (macOS y Linux).
- `cfdi.py`: CFDIs emitidos y recibidos por Contraseña o e.firma, con un reintento automático cuando el portal rechaza la sesión.
- `constancia.py`: Constancia de Situación Fiscal por ambos canales.
- `opinion.py`: Opinión de Cumplimiento 32-D por ambos canales (captura del PDF en el visor del SAT).
- `declaraciones.py`: declaraciones presentadas (provisionales y definitivas, periodos mensuales; normal y complementarias) y sus acuses de recibo.
- `diot_consulta.py`: DIOT ya presentadas: PDF de la declaración, Excel de detalle y acuse.
- `diot_presentacion.py`: presentación de la DIOT por carga masiva con e.firma. Coteja los Totales del portal contra el TXT antes de firmar (layouts 2025 en adelante y 2024 y anteriores). Solo para declaraciones sin estímulos fiscales. Ver [diot-2025.md](diot-2025.md).
- `contabilidad_electronica.py`: envío de la contabilidad electrónica (Anexo 24) con e.firma y consulta de acuses (Recibido, Aceptado o Rechazado). Ver [contabilidad-electronica.md](contabilidad-electronica.md).
- `reanudar_envios.py`: reanudación idempotente de envíos de contabilidad electrónica que quedaron en cola por lentitud o mantenimiento del SAT (la usan el CLI y el poller).
- `csd.py` y `renovacion.py`: envío de la solicitud de CSD (`.sdg`) y de la renovación de e.firma (`.ren`) a CertiSAT Web, seguimiento, acuse y recuperación del certificado emitido. Ver [renovacion-efirma-csd.md](renovacion-efirma-csd.md).

### `sat_descarga/procesador/`: análisis de comprobantes

Carga los XMLs en una base SQLite local (`~/.sat-descarga/procesador.db`, migraciones versionadas 001 a 009) con buffer aislado por empresa, y genera reportes.

- **Parser CFDI 4.0**: emisor y receptor, conceptos, impuestos (IVA con bases por tasa 16%, 8%, 0% y exento; IEPS; ISR), forma y método de pago, uso del CFDI, complementos.
- **Por comprobante**: interruptor de "pasa a la DIOT" y clasificación manual de deducibilidad (Sin analizar, Deducible, No deducible).
- **Procesador de Pagos** (complemento 2.0): concilia facturas PPD contra complementos y detecta pagos parciales, extemporáneos (después del día 5 del mes siguiente), huérfanos e incidencias PUE.
- **Procesador de Nómina** (CFDI 4.0 + complemento 1.2): ISR teórico con tarifas vigentes (incluye subsidio para el empleo), IMSS (SBC, SDI, cuotas patronal y obrera), deducibilidad por empleado y mes, comparativo periodo contra periodo y alertas (empleados sin NSS, SBC fuera de límites, días anómalos, periodos incompletos).
- **Validación de estatus** (vigente o cancelado) contra el SAT y **cruce contra listas negras** 69 y 69-B.
- **Reportes** Excel (`openpyxl`) multi-hoja y CSV.

### `sat_descarga/diot/`: DIOT 2025

Implementa el layout oficial de 54 campos (instructivo del SAT de enero 2025): prellenado por proveedor desde los CFDIs recibidos del periodo (las notas de crédito van a devoluciones), estado editable por empresa y periodo en `~/.sat-descarga/diot/{RFC}.json`, validaciones del instructivo y exportación del TXT en UTF-8 con BOM. La obligación de presentar se deriva del régimen fiscal configurado en la empresa, con un interruptor manual ("Presenta DIOT") para los casos condicionales.

### `sat_descarga/calculadoras/`

Aguinaldo, SBC, ISR de sueldos, finiquito, liquidación, carga patronal y PTU. Los indicadores por año (UMA, salarios mínimos, tarifas ISR del Anexo 8, subsidio para el empleo, cuotas IMSS) viven en una sola tabla de 2021 a 2026; si un dato no está verificado, el año lleva una advertencia en lugar de heredar el anterior. El estado se guarda por empresa en `~/.sat-descarga/calculadoras/{RFC}.json`. Exportación a Excel y PDF (incluye recibos de PTU y hoja de pre-nómina).

### `sat_descarga/certifica/`

Genera en local los archivos de la app Certifica del SAT: `.req` (e.firma nueva), `.ren` (renovación) y `.sdg` (CSD), cada uno con un par RSA-2048 nuevo. Portado de `satcfdi.certifica` (licencia MIT).

### `sat_descarga/tareas/`

Tareas personales, con o sin empresa, en `~/.sat-descarga/tareas.json`. Incluye sugerencias derivadas del catálogo y se sincronizan entre instalaciones (`api/sync_tareas.py`).

### `sat_descarga/utils/`

- `validacion.py`: estatus masivo de CFDIs contra el servicio público del SAT (no requiere e.firma).
- `metadata.py`: parser del CSV de metadata del SAT.
- `organizador.py`: estructuras de carpetas (predefinidas o personalizadas) y renombrado por partes, con clasificación Emitidos/Recibidos contra la empresa activa.
- `csf_parser.py` y `opinion_parser.py`: lectura de la CSF (razón social, regímenes, actividades económicas) y de la Opinión 32-D (sentido y motivos).
- `listas_negras.py`: consulta a las listas 69 y 69-B que materializa el backend (cron mensual); detecta EFOS y EDOS.
- `regimenes_fiscales.py` y `xml_reader.py`: catálogo de regímenes y parser tolerante de XML CFDI.

### `sat_descarga/core/`

Configuración y detección de modo (desktop u hosted), e.firma (`fiel.py`), cliente HTTP del SAT, rutas, secretos (`keyring` o `secretos.enc`), parser XML endurecido contra XXE (`xml_seguro.py`), errores esperados y telemetría.

### `sat_descarga/api/`: API REST (FastAPI)

`server.py` solo arma la app (CORS, middleware del token, lifespan) e incluye los routers por dominio de `api/routers/`. Además:

- `jobs.py`: trámites largos como jobs con eventos SSE (`GET /events/{id}`).
- `poller.py`: cada 60 s verifica las solicitudes WS pendientes de todas las empresas (cada una con su propia e.firma, sin tocar la sesión activa), descarga los paquetes listos y los registra en el historial. También reintenta la cola de contabilidad electrónica, con 30 minutos de espera entre intentos.
- `license_client.py` y `supabase_auth.py`: cuenta, licencia y sesión contra `api.todoconta.com`.
- `sync_empresas.py` y `sync_tareas.py`: sync best-effort del catálogo (solo metadata, nunca credenciales) y de las tareas.
- `espacio_online.py`: puente de "Usar en la web".

Endpoints (rutas reales de los routers):

| Grupo | Endpoints |
|---|---|
| **Sistema** | `GET /health`, `POST /abrir`, `GET/PUT /config/{descargas-dir,organizador,sync-credenciales}` |
| **Cuenta** | `POST /auth/{login-password,otp-send,otp-verify,signup,logout}`, `POST /auth/oauth/{start,callback}`, `POST /auth/adopt-session` (solo web), `GET /auth/license`, `POST /auth/{upgrade,subscribe,cancel-subscription,transfer-intent}`; `POST /auth/{init,poll}` (device code, fallback que la UI ya no usa) |
| **API keys y equipo** | `GET/POST/DELETE /cuenta/api-keys`, `GET /cuenta/teams`, `GET /cuenta/teams/empresas`, `POST/DELETE /cuenta/teams/members`, `PATCH /cuenta/teams/members/permissions`, `POST /cuenta/teams/leave` |
| **e.firma en sesión** | `POST /auth/cargar-fiel`, `DELETE /auth/fiel`, `POST /auth/autocargar-fiel` |
| **Web Service** | `POST /solicitar`, `POST /solicitar-folio`, `POST /verificar`, `POST /descargar`, `POST /descarga-completa`, `POST /descarga-inteligente` |
| **Portal (jobs + SSE)** | `POST /ciec/{cfdi,constancia,opinion}`, `POST /cfdi/fiel` (job), `POST /constancia/fiel` y `POST /opinion/fiel` (síncronos), `GET /jobs/{id}`, `GET /events/{id}`, `POST /jobs/{id}/captcha`; síncronos originales: `POST /ciec/descargar`, `POST /constancia/descargar` |
| **Empresas** | `GET /empresas`, `POST /empresas/{fiel,ciec}`, `PATCH /empresas/{rfc}`, `DELETE /empresas/{rfc}`, `DELETE /empresas/{rfc}/fiel`, `POST /empresas/{rfc}/{activar,default,archive,unarchive}`, `POST /empresas/{rfc}/{parsear-csf,parsear-opinion,subir-al-espacio}`, `GET /empresas/{rfc}/credenciales` |
| **Solicitudes e historial** | `GET /empresas/{rfc}/solicitudes`, `DELETE /empresas/{rfc}/solicitudes/{id}`, `GET /solicitudes/actividad`, `GET /empresas/{rfc}/historial`, `GET /historial` |
| **Archivos** | `GET /descargas/archivo`, `GET /descargas/zip` (los usa la versión web) |
| **Utilidades** | `POST /metadata`, `POST /validar`, `POST /organizar`, `POST /renombrar`, `POST /deduplicar` |
| **Procesador CFDI** | `POST /procesador/cfdi/{cargar,cargar-desde-empresa,validar-sat,validar-listas-negras}`, `GET /procesador/cfdi`, `GET /procesador/cfdi/{stats,filtros,exportar}`, `GET /procesador/cfdi/reporte/{nombre}`, `PUT /procesador/cfdi/filtros`, `PATCH /procesador/cfdi/{uuid}`, `DELETE /procesador/cfdi` |
| **Procesador Pagos** | `GET /procesador/pagos`, `GET /procesador/pagos/{stats,filtros,exportar}`, `GET /procesador/pagos/factura/{uuid}/pagos`, `GET /procesador/pagos/reporte/{nombre}`, `PUT /procesador/pagos/filtros` |
| **Procesador Nómina** | `GET /procesador/nomina`, `GET /procesador/nomina/{stats,filtros,exportar}`, `GET /procesador/nomina/recibo/{uuid}/conceptos`, `GET /procesador/nomina/reporte/{nombre}`, `PUT /procesador/nomina/filtros` |
| **Listas negras** | `POST /listas-negras/consultar`, `GET /listas-negras/metadata`, `GET /procesador/cfdi/listas-negras/{stats,por-emisor}` (Art. 69 y 69-B) |
| **Calculadoras** | `POST /calculadoras/{aguinaldo,sbc,isr,finiquito,liquidacion,carga-patronal,ptu}`, `GET /calculadoras/indicadores/{anio}`, `GET /calculadoras/estado/{rfc}` (y `/{calculadora}`), `POST /calculadoras/guardados/{rfc}`, `DELETE /calculadoras/guardados/{rfc}/{id}`, `POST /calculadoras/exportar/{formato}` |
| **DIOT** | `GET/PUT /diot/estado`, `POST /diot/prellenar`, `GET /diot/exportar`, `GET /diot/catalogos`, `POST /diot/presentar` (job), `POST /diot/acuse` (job) |
| **Contabilidad electrónica** | `POST /ce/enviar` (job), `POST /ce/acuses` (job), `GET /ce/pendientes`, `POST /ce/reanudar` (job) |
| **Renovación de e.firma y CSD** | `POST /renovar` (job), `GET /renovar/estado`, `GET /renovar/respaldo`, `POST /renovar/recuperar` (job), `POST /csd` (job), `POST /csd/recuperar` (job) |
| **Tareas** | `GET/POST /tareas`, `PATCH/DELETE /tareas/{id}`, `POST /tareas/sugerencias/descartar` |

### `sat_descarga/cli/`: `sat-dm`

Todo lo del agente también se ejecuta desde la terminal, sin la UI:

```
sat-dm empresas {add,list,remove,default}
sat-dm descargar cfdi                        # Web Service con e.firma
sat-dm descargar {ciec,fiel}                 # CFDIs por el portal
sat-dm descargar {constancia,opinion}        # --metodo ciec|fiel
sat-dm descargar declaraciones               # declaraciones presentadas y acuses, por periodo
sat-dm descargar diot                        # DIOT presentadas: PDF, Excel y acuse
sat-dm retomar <id-solicitud>                # retoma una solicitud WS
sat-dm validar                               # estatus vigente/cancelado contra el SAT
sat-dm metadata                              # listado (CSV) de CFDIs
sat-dm organizar {carpetas,renombrar,deduplicar}
sat-dm listas-negras                         # Art. 69 y 69-B
sat-dm diot [generar]                        # TXT de carga masiva (54 campos)
sat-dm diot presentar                        # sube el TXT con e.firma; solo envía con --enviar
sat-dm diot acuse                            # reimprime el acuse de una DIOT presentada
sat-dm ce {inventario,enviar,acuses,pendientes,reanudar}   # contabilidad electrónica
sat-dm generar fiel                          # requerimiento de e.firma nueva (.req + .key)
sat-dm renovar fiel                          # renovación (.ren + .key); --enviar la tramita
sat-dm solicitar csd                         # solicitud de CSD (.sdg + .key); --enviar la tramita
sat-dm enviar {csd,ren}                      # sube a CertiSAT Web un .sdg o .ren ya generado
sat-dm recuperar {csd,ren}                   # baja el certificado emitido
```

> Nota: los comandos `sat-dm descargar *` guardan en `./descargas` relativo al directorio actual; la API usa la carpeta de descargas configurada en la app.

## Renderer (UI)

Bundle estático de Next.js (`output: 'export'`, `trailingSlash: true`). En desktop, Electron lo sirve por el protocolo propio `app://` (no `file://`); en web lo sirve Vercel. Rutas:

- `/`: Inicio, panel ejecutivo con datos reales del catálogo y el historial.
- `/tareas`: centro de mando de pendientes (lista o tablero) con sugerencias.
- `/empresas` y `/empresas/detalle?rfc=…`: catálogo (activas y archivadas, búsqueda y filtros) y ficha de la empresa (e.firma, CSF, Opinión 32-D, configuración fiscal).
- `/descarga`: solicitudes al Web Service (CFDIs o solo el listado) y su seguimiento.
- `/descarga/rapida`: CFDIs por el portal (Contraseña o e.firma) con captcha dentro de la app.
- `/comprobantes` y `/comprobantes/{cfdi,pagos,nomina}`: procesadores con filtros, validación contra el SAT y exportación.
- `/listas-negras`: Art. 69 y 69-B, con pestañas "Mis CFDIs" (cruce automático) y "Validar RFCs" (manual).
- `/organizador`: carpetas, renombrado y duplicados.
- `/historial`: registro de descargas con apertura del archivo o de la carpeta.
- `/calculadoras` y `/calculadoras/{aguinaldo,sbc,isr,finiquito,liquidacion,carga-patronal,ptu}`.
- `/diot`: prellenado, edición, validaciones y TXT de carga masiva.
- `/ajustes`, `/ajustes/equipo` y `/ajustes/api`: preferencias, equipo del despacho, API keys y conexión MCP.
- `/suscripcion` (y `/planes`, alias para links externos): plan, pago con tarjeta o transferencia, cancelación.
- `/ayuda`: preguntas frecuentes, contacto y referencia de atajos.
- `/login`: correo y contraseña, código de 6 dígitos o Google (Google solo en desktop por ahora); también alta de cuenta.
- `/conectar`: solo en web; conexión manual con el agente, para soporte.

**Navegación**: sidebar con 10 secciones (los atajos ⌘1..⌘9 / Ctrl+1..9 siguen su orden; DIOT se abre desde el buscador), buscador de páginas y acciones (⌘K / Ctrl+K), y barra de estado con la conexión, las estadísticas de la empresa activa, el semáforo de su e.firma y el chip de versión y actualización.

**Patrón estándar para trámites del portal**: los hooks `use-job` y `use-ciec-job` consumen el SSE del agente, traducen los eventos a progreso y a un log, y presentan el captcha en una modal cuando hace falta. Los asistentes de varios pasos (renovación de e.firma, CSD) usan nombres de fase estables que emite el agente.

## Distribución y operación

- **GitHub Releases** hospeda los instaladores y los feeds del auto-updater (`latest.yml`, `latest-mac.yml`). `todoconta.com/descargar` detecta el SO y redirige al instalador del último release publicado.
- **CI** (`.github/workflows/release.yml`): al empujar un tag `v*.*.*` construye Windows (`windows-latest`, NSIS x64) y macOS (Apple Silicon, DMG + ZIP), corre un smoke test del agente empacado y deja el release en **borrador** para QA. Se publica a mano.
- **Firma de código**: en Windows, certificado IV de SSL.com (eSigner) para el instalador, `TodoConta.exe` y `sat-agent.exe`, con `forceCodeSigning` y verificación de firmas en el CI. En macOS, hardened runtime y notarización. Ver [firma-codigo.md](../infra/firma-codigo.md).
- **Linux**: la configuración de AppImage existe en `electron-builder.yml`, pero el CI todavía no la construye.
- **electron-updater**: revisa 30 s después del arranque y cada 4 h, descarga en background y pide confirmación antes de reiniciar. También hay "Buscar actualizaciones" en Ajustes y en el chip de versión.
- **Cadencia**: release semanal. Los cambios se acumulan bajo `## [Unreleased]` del CHANGELOG y un branch `release/vX.Y.Z` hace el bump. SemVer con los tres archivos de versión sincronizados (`pyproject.toml`, `ui/package.json`, `desktop/package.json`). Ver [versionado.md](../infra/versionado.md).
- **Monitor del agente**: si el agente muere, el shell lo reinicia en el mismo puerto y con el mismo token (hasta 3 veces seguidas). Al cerrar la app no quedan procesos huérfanos.
- **Logs del agente**: `%LOCALAPPDATA%\TodoConta\logs\agent.log` (Windows), `~/Library/Logs/TodoConta/agent.log` (macOS), `~/.local/state/TodoConta/agent.log` (Linux).
- **Reporte de errores**: Sentry en renderer, main y agente, con datos scrubbeados (RFC, rutas con nombre de usuario y credenciales redactadas; nunca la e.firma, contraseñas ni datos fiscales), más el botón "Reportar un problema".
- **Versión web**: `ui/` se despliega en Vercel como build web; la imagen del agente (`docker/agente/`) se actualiza en el VPS recreando los contenedores sin perder su volumen.

## Seguridad

- **Token efímero** entre shell, renderer y agente en desktop. CORS abierto solo porque el agente escucha en loopback; en web, CORS restringido a `app.todoconta.com`.
- **TLS 1.2 como mínimo** en las llamadas al SAT.
- **Parser XML endurecido** para todo XML externo (respuestas del SAT y CFDIs del usuario): sin resolución de entidades, sin DTD y sin red.
- **Anti zip-slip** en los paquetes del Web Service.
- **Escrituras atómicas** (`fsync` + rename) y locks en catálogo, historial, solicitudes y settings; lectura tolerante a encodings antiguos y a archivos corruptos (cuarentena en lugar de tumbar la app).
- **`/abrir` canonicaliza rutas** y solo abre lo que está en la lista blanca del historial.
- **Electron**: el handler de `app://` valida la ruta; `shell.openExternal` solo acepta `http(s):` y `mailto:`; los deep links `todoconta://` se validan con charset estricto.
- **Validación de la e.firma** al darla de alta: el `.cer` y la `.key` deben corresponder y la contraseña abrir la llave; la fecha de vencimiento se registra para el semáforo. Los certificados de la autoridad certificadora antigua del SAT con defectos de codificación se aceptan sin alterarlos.
- **Secretos en web**: AES-256-GCM con clave derivada por usuario; tránsito por TLS hasta el VPS.
- **API pública**: en la base compartida solo se guarda el hash (SHA-256) de cada API key; OAuth 2.1 con PKCE y refresh rotativo; enlaces de descarga firmados con expiración.
- **Irreversibles con confirmación explícita**: DIOT, contabilidad electrónica y renovación de e.firma.
- **Telemetría**: los errores de usuario (contraseña de la `.key` incorrecta y demás validaciones) no se reportan a Sentry.

---

# Parte II: Especificación para el contador

## El problema que resuelve

El contador atiende decenas de contribuyentes a la vez. Las tareas recurrentes le consumen horas todas las semanas:

- Descargar CFDIs del SAT (uno por uno, esperando captchas, peleando con el portal).
- Pedir la Constancia o la Opinión 32-D cada vez que un cliente la necesita.
- Cuadrar pagos (PPD contra complementos) para detectar facturas que el cliente nunca cobró.
- Revisar recibos de nómina para validar ISR, IMSS y deducibilidad antes de declararlos.
- Revisar que emisores y receptores **no estén en listas negras** (Art. 69-B, EFOS: facturas de operaciones simuladas, riesgo de no deducibilidad).
- Armar y presentar la DIOT cada mes y enviar la contabilidad electrónica.
- Llevar la cuenta de qué e.firma vence, qué declaración falta y qué acuse no ha llegado.

Hoy muchos despachos combinan varias herramientas para cubrir partes de este flujo y siguen entrando al portal del SAT trámite por trámite.

## Dos formas de usarlo

| | App de escritorio | Versión web (app.todoconta.com) |
|---|---|---|
| **Dónde corre** | En tu computadora (Windows o Mac con Apple Silicon) | En tu navegador, desde cualquier equipo |
| **Dónde viven tu e.firma y tus contraseñas** | En tu equipo, en el llavero del sistema | Cifradas en tu espacio privado en la nube, que no se comparte con nadie |
| **Descargas pendientes del Web Service** | Se resuelven solas mientras la app está abierta | Se resuelven solas aunque cierres el navegador |
| **Archivos** | En tu carpeta de descargas (configurable); se abren directo | Se descargan desde el navegador |

Es la misma cuenta en las dos: empresas, configuración fiscal, tareas y la configuración del organizador se sincronizan. Desde la app de escritorio, cada empresa tiene la opción **"Usar en la web"**, que sube sus credenciales cifradas a tu espacio para operarla también en línea; si no la activas, la e.firma no sale de tu equipo. La versión web requiere plan activo o prueba vigente.

## Qué hace TodoConta hoy (v2.2)

### Lo que el contador ve en la app

Una aplicación en español, con interfaz limpia y rápida. **Una sola ventana** para el flujo del SAT.

| Sección | Qué hace |
|---|---|
| **Inicio** | Panel con datos reales: CFDIs del mes contra el anterior, empresas activas, e.firmas por vencer, CFDIs descargados por mes, estado de la cartera, próximos vencimientos, empresas con más movimiento y las tareas de hoy. |
| **Tareas** | Pendientes fiscales y recordatorios, con o sin empresa, en lista o en tablero. TodoConta sugiere tareas (renovar una e.firma por vencer, generar la DIOT del mes) que aceptas o descartas. Se sincronizan entre la app y la web. |
| **Empresas** | Das de alta a tus clientes una sola vez (RFC más e.firma, Contraseña del SAT o ambas) y cambias entre ellos desde el menú. Activas y archivadas, búsqueda y filtros por tipo y estado. Cada empresa muestra el semáforo de su e.firma, su Constancia y su Opinión 32-D. |
| **Descargar CFDIs** | Solicitudes al Web Service del SAT (CFDIs completos o solo el listado). Las solicitudes de todas tus empresas se revisan y descargan solas en segundo plano, y la app te avisa cuando terminan o fallan. |
| **Descarga rápida** | CFDIs directo del portal con Contraseña o e.firma, sin esperar al Web Service. El captcha aparece dentro de la app. Limitada a lo que el portal permite por día. |
| **Comprobantes** | Procesadores de CFDI, Pagos y Nómina por empresa: filtros, validación de vigencia contra el SAT, control de qué pasa a la DIOT, clasificación de deducibilidad y exportación a Excel o CSV. |
| **Listas negras** | Cruce de tus CFDIs contra los Art. 69 y 69-B, y validación manual de una lista de RFCs. |
| **Organizador** | Ordena en carpetas (estructuras predefinidas o la tuya), renombra por partes y quita duplicados. La configuración se define una vez para todo el despacho. |
| **Historial** | Cada descarga con fecha, canal (Web Service, Contraseña o e.firma) y acceso directo al archivo o a la carpeta. |
| **Calculadoras** | Aguinaldo, SBC, ISR de sueldos, finiquito, liquidación, carga patronal y PTU, con indicadores oficiales por año. |
| **DIOT** | Prellenado desde los CFDIs recibidos, edición de los 54 campos, validaciones del instructivo y el TXT de carga masiva listo para subir. |
| **Ajustes** | Carpeta de descargas, tema claro u oscuro, notificaciones, **Equipo** (invitar colaboradores, permisos por empresa, retirar acceso) y **API y conexiones** (llaves de API, que se muestran una sola vez, y conexión de tu asistente de IA por MCP). |
| **Suscripción** | Tu plan, pago con tarjeta o transferencia y cancelación, sin salir de la app. |
| **Ayuda** | Preguntas frecuentes, contacto y la lista de atajos. |

Además: buscador de páginas y acciones (⌘K / Ctrl+K) y atajos de teclado; un aviso diario si alguna e.firma vence en 30 días o menos; barra de estado con la empresa activa; tema claro y oscuro que respeta el del sistema; y actualizaciones automáticas.

### Beneficios concretos por trámite

#### Descargar CFDIs

- Una solicitud al Web Service del SAT cubre **hasta 200,000 CFDIs** (hasta 1,000,000 de registros si pides solo el listado). La solicitud se resuelve sola en segundo plano, aunque cambies de empresa o de pantalla, y queda registrada en el historial.
- Para pocos comprobantes, la Descarga rápida trae las facturas del portal sin esperar al SAT.
- Si el SAT rechaza una solicitud, la app te dice qué hacer (por ejemplo, usar Descarga rápida con la misma e.firma) en lugar de mostrar un código. Las solicitudes que llevan más de 72 horas pendientes se marcan como vencidas.

#### Constancia de Situación Fiscal

- Se descarga desde Empresas, con e.firma o Contraseña, y queda rastreada en el historial. Cero entrar al portal del SAT a mano.
- Al descargarla, la app lee el PDF y actualiza la razón social, los regímenes fiscales y las actividades económicas de la empresa. Para constancias ya descargadas existe "Rellenar desde la constancia".

#### Opinión de Cumplimiento 32-D

- Mismo flujo. La app lee el PDF: si es positiva, el semáforo de la empresa se pone verde; si es negativa, se pone rojo y la ficha lista los motivos que marca el SAT, con su descripción y periodos.

#### Procesador de Nómina

- Carga los CFDI de nómina del periodo.
- Obtiene un Excel con resumen, percepciones y deducciones, ISR teórico (tarifa del año más subsidio para el empleo) contra el retenido, IMSS (SBC, SDI, cuotas patronal y obrera) y deducibilidad por empleado.
- Alertas de empleados sin NSS, SBC fuera de límites, días pagados anómalos y periodos incompletos, más un comparativo periodo contra periodo.

#### Procesador de Pagos

- Carga los complementos de pago (CFDI tipo P) junto con las facturas.
- Detecta pagos parciales y completos, facturas PPD con saldo, complementos huérfanos (sin su factura), complementos extemporáneos e incidencias PUE (factura PUE con complemento, riesgo ante el SAT).

#### DIOT

- Prellenado por proveedor desde los CFDIs recibidos del periodo. En Comprobantes decides qué operaciones pasan a la DIOT, y los renglones que agregas a mano se conservan al volver a prellenar.
- Validaciones en vivo: los errores del instructivo bloquean el TXT, las advertencias no.
- Si el régimen de la empresa no la obliga a presentar DIOT (por ejemplo, RESICO), la app lo avisa; para los casos condicionales existe el interruptor "Presenta DIOT".

#### Listas negras (Art. 69 y 69-B)

- "Mis CFDIs": en un clic cruza emisores y receptores del procesador contra las listas y marca EFOS y EDOS.
- "Validar RFCs": pegas una lista de RFCs y exportas un CSV con la situación de cada uno.
- Las listas se actualizan mensualmente desde la nube (requiere sesión iniciada).

#### Calculadoras

- De uso libre, con el estado guardado por empresa: cambiar de empresa nunca pisa los cálculos de otra.
- Exportar a Excel o PDF (incluye recibos de PTU por trabajador y la hoja de pre-nómina) es parte del plan.

### Solo por línea de comandos o API (todavía sin pantalla)

Estas funciones ya viven en el agente y se usan con `sat-dm` o con la API local. Ponerles pantalla en la app es el siguiente paso.

| Función | Cómo se usa hoy | Qué hace |
|---|---|---|
| **Contabilidad electrónica (Anexo 24)** | `sat-dm ce …` y `/ce/*` | Revisa tus ZIPs (catálogo de cuentas y balanzas), omite lo ya presentado, los envía con e.firma y baja los acuses con su estatus: Recibido, Aceptado o Rechazado. Solo "Aceptado" ampara el cumplimiento. Lo que falla por lentitud o mantenimiento del SAT queda en cola y la app lo reintenta cada 30 minutos. TodoConta no genera los XML: salen de tu sistema contable. |
| **Presentación de la DIOT** | `sat-dm diot presentar` y `/diot/presentar` | Sube el TXT con e.firma, coteja los Totales del portal contra el archivo y solo firma y envía con confirmación explícita; después baja el acuse. Solo para empresas sin estímulos fiscales. |
| **Declaraciones presentadas** | `sat-dm descargar declaraciones` | Baja el PDF de cada declaración provisional o definitiva del periodo (normal y complementarias) y su acuse, con un índice por RFC. Con Contraseña o e.firma. |
| **DIOT presentadas** | `sat-dm descargar diot` | Baja la declaración, el Excel de detalle y el acuse de cada DIOT del periodo. |
| **Renovación de e.firma** | `sat-dm renovar fiel` y `/renovar*` | Genera el `.ren`, lo envía a CertiSAT con la e.firma vigente y recupera el certificado nuevo; si el portal falla, se reanuda desde donde se quedó, y deja un respaldo ZIP con la llave nueva. En la app el asistente ya existe, pero está apagado ("Disponible próximamente") hasta estabilizar su ejecución en Windows. |
| **Solicitud de CSD** | `sat-dm solicitar csd` y `/csd*` | Genera el `.sdg`, lo tramita y recupera el sello cuando el SAT lo emite. En la app solo existe como asistente en pruebas, fuera de la navegación normal. |

## Planes

- **15 días gratis de prueba**, con todo incluido.
- **Anual: $2,990 MXN al año.** App de escritorio y versión web, empresas ilimitadas, exportaciones del plan (Excel y PDF de calculadoras, TXT de la DIOT) y sincronización entre escritorio y web.
- **Anual con IA: $4,990 MXN al año.** Todo lo del plan Anual más las funciones con IA.
- **Miembros Fundador** (la ventana cerró el 2026-06-18): conservan de por vida las funciones del plan que no son de IA; el plan con IA les cuesta $2,490 MXN al año.
- El precio con el que te suscribes se respeta mientras tu suscripción siga activa. Pagas con tarjeta (Stripe) o transferencia, y cancelas desde la app.

Son los precios de lista publicados en [todoconta.com/planes](https://todoconta.com/planes). El precio final lo calcula el servidor al pagar, así que puede reflejar una promoción vigente.

## Lo que distingue a TodoConta

Esta tabla describe solo lo que TodoConta hace hoy; no incluye precios ni funciones de otros productos.

| Capacidad | TodoConta v2.2 |
|---|---|
| **Contraseña del SAT y e.firma** | Las dos sirven en cada consulta: CFDIs, Constancia, Opinión 32-D, declaraciones y DIOT presentadas |
| **Captcha** | Se resuelve dentro de la app, sin abrir otro navegador |
| **Descargas del Web Service** | Se verifican y descargan solas, para todas las empresas a la vez |
| **Constancia y Opinión 32-D** | Se leen solas: actualizan la ficha y el semáforo de la empresa, con los motivos de una opinión negativa |
| **Procesador de Nómina** | ISR teórico contra retenido, IMSS y deducibilidad por empleado, en Excel |
| **Procesador de Pagos** | PPD contra complementos, extemporáneos, huérfanos e incidencias PUE |
| **DIOT** | Prellenado desde CFDIs y TXT de carga masiva en la app; presentación automatizada por CLI y API |
| **Semáforo de e.firma** | Por empresa, con aviso diario si alguna vence en 30 días o menos |
| **Escritorio y web** | La misma cuenta, con catálogo y tareas sincronizados |
| **Privacidad** | En la app de escritorio, la e.firma y las contraseñas no salen de tu equipo |
| **Integraciones** | API pública y servidor MCP para conectar sistemas propios o asistentes de IA |

## Lo que NO cubre todavía

Para ser transparentes, esto es lo que falta (ver Parte III):

- Pantallas para la contabilidad electrónica, la presentación de la DIOT y la descarga de declaraciones y DIOT presentadas (hoy solo por CLI o API).
- Renovación de e.firma y solicitud de CSD dentro de la app (la lógica está lista; la pantalla sigue apagada).
- Verificar en el portal el estatus de la DIOT ya presentada: hoy se baja el acuse en PDF, pero no se lee su estatus.
- DIOT de empresas que aplican estímulos fiscales.
- Generar el TXT de la DIOT en el layout de 2024 y anteriores (la presentación sí lo acepta).
- Generar los XML de la contabilidad electrónica: TodoConta los revisa y los envía, pero salen del sistema contable.
- Declaraciones anuales y DEM.
- Listas negras distintas de los Art. 69 y 69-B.
- Clasificación de deducibilidad asistida por IA (hoy es manual).
- Conciliación bancaria.
- Enviar documentos por correo desde el historial.
- Sincronizar las tareas con Google Calendar.
- Expediente fiscal por empresa (el acceso ya aparece como "próximamente").
- Inicio de sesión con Google en la versión web (en la app de escritorio sí está).
- Aplicación para Linux.

---

# Parte III: Roadmap

## Entregado (junio a septiembre de 2026)

| Versión | Fecha | Lo principal |
|---|---|---|
| **v1.0.x** | 2026-06-03 a 2026-06-08 | Primer instalador de Windows con auto-update; arreglos de arranque en distintos perfiles de Windows (lifespan no bloqueante, CORS, protocolo `app://`). |
| **v1.1.0** | 2026-06-10 | Rediseño de la interfaz (sidebar con selector de empresa, barra de estado, Ayuda); login dentro de la app (contraseña o código de 6 dígitos) y alta de cuenta; token efímero entre shell y agente; endurecimiento de seguridad; monitor y reinicio automático del agente. |
| **v1.1.1 a v1.2.2** | 2026-06-12 a 2026-06-22 | Chromium verificado y actualizado en background; respaldo local de la e.firma; reporte de errores con Sentry; "Buscar actualizaciones" y nueva revisión cada 4 h; build de macOS (Apple Silicon) notarizado. |
| **v1.3.0** | 2026-06-24 | Suscripción dentro de la app (tarjeta, transferencia, cancelación) y badges de plan. |
| **v1.4.0** | 2026-06-30 | Catálogo de empresas a prueba de corrupción; nombre de la empresa tomado del certificado. |
| **v1.5.0** | 2026-07-01 | Inicio de sesión con Google en desktop; instaladores de Windows firmados. |
| **v1.6.0** | 2026-07-02 | Atajos de teclado y buscador ⌘K; versión y actualizaciones en la barra de estado; rescate de catálogos guardados con encodings antiguos. |
| **v1.7.0** | 2026-07-10 | Panel ejecutivo en Inicio; Tareas; procesadores aislados por empresa; control DIOT y deducibilidad por comprobante; DIOT 2025 (pantalla, API y CLI); calculadoras fiscales y laborales; organizador con estructuras personalizadas; descargas del Web Service resueltas en background para todas las empresas; renovación de e.firma y CSD en el agente (pantalla apagada). |
| **v2.0.0** | 2026-07-14 | Versión web (app.todoconta.com) con sincronización del catálogo; lectura automática de la CSF y de la Opinión 32-D. |
| **v2.1.0** | 2026-08-15 | API keys, conexión MCP y equipo desde Ajustes; `sat-dm diot presentar`; tareas y organizador sincronizados entre escritorio y web; "CIEC" pasa a llamarse "Contraseña". |
| **v2.2.0** | 2026-09-28 | Contabilidad electrónica (envío, acuses y cola de reintento); descarga de declaraciones y DIOT presentadas; CE y presentación de DIOT como jobs de la API; estado y respaldo de la renovación de e.firma; la versión web ya deja entrar a quien está en periodo de prueba. |

Fuera del instalador, en julio de 2026 entraron en operación la API pública REST v1 y el servidor MCP del gateway.

Del roadmap publicado en junio quedaron cumplidos: suscripciones de pago (como plan anual), lectura del PDF de la CSF y de la Opinión 32-D, respaldo local de la e.firma, atajos de teclado, DIOT (generación en la app; presentación por CLI y API), descarga de declaraciones provisionales y definitivas (por CLI), build y notarización de macOS, uso desde la web con la misma cuenta y firma de código en Windows.

## Pendiente (sin fecha comprometida)

**Envíos al SAT**

- Pantallas de contabilidad electrónica (selección de ZIPs, decisión de sellado explícita, progreso por fases, estatus de acuses y cola de pendientes) y botón "Presentar en el SAT" en DIOT, con validación previa de totales. Ver [pendientes-envios-sat.md](pendientes-envios-sat.md).
- Verificación del estatus de la DIOT presentada y soporte de estímulos fiscales.
- Habilitar en la app la renovación de e.firma y la solicitud de CSD.
- Pantalla para descargar declaraciones y DIOT presentadas.

**Declaraciones y listas**

- Declaraciones anuales y DEM.
- Listas negras adicionales (cancelados, condonados, no localizados, sentencias firmes, entre otras).
- Validación masiva de RFC (estructura y existencia) por plantilla de Excel.

**Producto**

- Clasificación de deducibilidad asistida por IA.
- Conciliación bancaria automática (CFDI contra estado de cuenta).
- Enviar documentos por correo desde el historial ([mejoras-futuras.md](mejoras-futuras.md)).
- Sincronización de tareas con Google Calendar, en una sola dirección ([tareas-gcal-sync.md](tareas-gcal-sync.md)).
- Expediente fiscal por empresa.
- Pestañas internas para tener varias vistas abiertas.
- Inicio de sesión con Google en la versión web.

**Plataforma**

- Build de Linux (AppImage) en el CI.
- Tests de UI (Vitest + React Testing Library) en hooks y componentes críticos.

> **Las funciones con IA siempre son de pago**, también para los Miembros Fundador (que tienen precio especial en el plan con IA).

## Firma de código

- **Windows**: desde v1.5.0 el instalador, `TodoConta.exe` y `sat-agent.exe` se firman con un certificado IV de SSL.com (firma en la nube con eSigner). Quita el aviso de "editor desconocido" de SmartScreen y reduce el escaneo en frío de Windows Defender en el primer arranque. `forceCodeSigning` impide publicar un instalador sin firma.
- **macOS**: hardened runtime y notarización con Apple Developer Program.
- Las instalaciones de v1.4.0 o anteriores (sin firma) no pueden actualizarse solas a una versión firmada: la app avisa y lleva a `todoconta.com/descargar` para reinstalar.

---

## Apéndice: estado actual del release

| | Estado |
|---|---|
| **Versión del producto** | v2.2.0 (entrada del CHANGELOG del 2026-09-28) |
| **Cómo se publica** | Tag `vX.Y.Z` → el CI construye Windows y macOS → release en borrador en GitHub → se publica tras QA |
| **Descarga** | `todoconta.com/descargar` redirige, según el SO, al instalador del último release publicado |
| **Plataformas** | Windows x64 (firmado) y macOS Apple Silicon (notarizado); Linux pendiente |
| **Auto-update** | electron-updater contra GitHub Releases: 30 s después del arranque y cada 4 h |
| **Versión web** | `app.todoconta.com`, con un agente por usuario en `agente.todoconta.com` |
| **API pública y MCP** | `api.todoconta.com/v1` (documentación en `/v1/docs`) y `agente.todoconta.com/mcp` |
| **Ventana de fundadores** | Cerrada desde el 2026-06-18 |
| **Renovación de e.firma en la app** | Detrás del feature flag `RENOVACION_EFIRMA_HABILITADA` (apagado) |

---

*Documento mantenido en `docs/producto/especificaciones.md`. Actualizar con cada release que cambie alcance.*

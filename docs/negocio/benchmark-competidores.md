# Benchmark: sat-descarga-masiva vs Competidores

> Investigación inicial: 2026-03-30
> **Última revisión: 2026-06-03** — tras release v1.0.0 (procesador CFDI/Pagos/Nómina, constancia, opinión 32-D, organizador, validación masiva)

---

## Referencia Principal: XMLSAT Premium (Construsoft)

Software comercial de Windows ($2,200 MXN/año) que hemos distribuido por años.
Es el estándar de features que sat-descarga-masiva busca replicar como open-source Python.

### Features completas de XMLSAT Premium

#### Descarga Masiva
- Web Service FIEL: hasta 200k XML por solicitud, solicitudes ilimitadas
- CIEC portal: hasta 10k XML/día por contribuyente
- Multi-RFC: descarga todos los RFCs registrados con un clic
- Descarga por listado de UUID (sin límite)
- Descarga por listado de RFC
- 4 modos de descarga (el más usado: "+500xDía")
- Descarga de PDF del SAT, acuse de cancelación, solicitudes de cancelación
- Descarga de XML de retenciones (plataformas digitales, casas de bolsa)
- Historial de descargas para retomar incompletas
- Reportes de incidencias y tiempos de descarga
- Identifica días donde se superan 500 XML/segundo
- Modo navegador web embebido (tradicional)

#### Validación y Listas Negras
- 17 listas negras del SAT (Cancelados, Condonados, Exigibles, Firmes, No Localizados, Con sentencia, Eliminados, Definitivos, Desvirtuados, Presuntos...)
- Artículo 69 y 69-B del CFF
- Validación masiva de RFCs por plantilla Excel
- Validación de estructura y existencia de RFC
- Validación masiva de estatus (Vigente/Cancelado) de CFDI
- Validación masiva de Razón Social REPSE
- Actualización instantánea cuando cambian los listados

#### Herramientas XML (v3.2, 3.3 y 4.0)
- Lectura masiva de todos los nodos del XML
- Validación en tiempo real con el SAT
- Export a Excel de todos los nodos
- Conversión a moneda extranjera (moneda + tipo de cambio del XML)
- Reporte de nodo de conceptos (con claves SAT)
- Visor XML integrado (PDF, XML, acuse SAT)
- Organizador de XML en carpetas (20 formas: RFC/año/mes/día)
- 6 estilos de árboles de carpetas
- Agrupador Vigentes/Cancelados
- Agrupador por versión y tipo de comprobante
- Renombrado masivo de XML (por emisor, receptor, total, fecha, etc.)
- Eliminación de duplicados
- XML a PDF masivo (Ingreso, Egreso, Traslado, Nómina, Pagos) con colores/logo personalizables

#### Reportes Fiscales
- IVA: concentrado por emisor/receptor, tasa 0/16/exento, acreditable/no acreditable
- ISR: agrupado por emisor/receptor por tasa
- IEPS: hasta 20 tasas diferentes
- Impuestos locales
- Concentrado IVA ingresos y gastos
- Acumulación de ingresos y gastos factura por factura
- Recepción de pagos 1.0
- Validación CFDI régimen RESICO
- Conciliación PPD vs Pagos (encuentra faltantes de complemento de pago)

#### Nómina
- Reporte simple de nómina 1.2
- Reporte extendido horizontal: 223 columnas (percepciones/deducciones gravadas y exentas + otros pagos)
- Reporte vertical de percepciones, deducciones y otros pagos
- Organización de nómina por fecha de pago (útil para retimbrados)

#### Complementos CFDI
- Impuestos Locales 1.0
- Carta Porte (1.0, 2.0, 3.0)
- Comercio Exterior 1.1
- Vales de Despensa 1.0
- Cuenta de Combustibles 1.2
- Consumo de Combustible (1.1, 1.2)
- Leyendas Fiscales 1.0
- Donatarias 1.1

#### DIOT
- Generación automática con XMLs del periodo
- Filtro por fecha de pago para complementos de Pago
- Proveedores extranjeros
- Modificación de cálculos
- Archivo batch para DEM del SAT

#### Auditoría Electrónica
- Consulta de declaraciones normales y complementarias (últimos 6 meses, tiempo real)
- Consulta de DIOT enviadas por año (tiempo real)
- Descarga de contabilidad electrónica enviada (catálogos, balanzas, pólizas, auxiliares)
- Analizador de contabilidad electrónica (cruces catálogo vs balanza, perspectiva SAT vs contribuyente)
- Descarga de Constancia de Situación Fiscal
- Descarga de Opinión de Cumplimiento (SAT e IMSS)
- Conciliación sistema interno vs archivos SAT (reportes de inconsistencias e integridad)
- Correos apócrifos del SAT

#### Contabilidad Electrónica 1.3
- Generador de catálogo de cuentas (interfaz o plantilla Excel)
- Generador de balanza de comprobación
- Genera archivos XML de catálogo y balanza
- Conversión XML ↔ plantilla Excel
- Validación antes de envío al SAT

#### Catálogos SAT
- Catálogo de productos y servicios del SAT integrado

---

## Proyectos Open-Source Python

### 1. cfdiclient (python-cfdiclient)

| Campo | Detalle |
|---|---|
| **Repositorio** | [github.com/luisiturrios1/python-cfdiclient](https://github.com/luisiturrios1/python-cfdiclient) |
| **Autor** | Luis Iturrios |
| **Stars** | 131 |
| **Último release** | v1.6.2 — junio 2025 |
| **Licencia** | GPL-3.0 |
| **PyPI** | `pip install cfdiclient` |
| **Python** | 2.7, 3.6-3.9 |
| **Dependencias** | lxml, requests, pycryptodome, pyOpenSSL |

**Features:** FIEL auth, descarga XMLs, validación CFDI ante SAT.
**No tiene:** CIEC, metadata, retry, async, CLI, reportes, exports.
**Valoración:** La más popular y enfocada. Simple pero sin reintentos, Python viejo, GPL.

---

### 2. satcfdi (python-satcfdi)

| Campo | Detalle |
|---|---|
| **Repositorio** | [github.com/SAT-CFDI/python-satcfdi](https://github.com/SAT-CFDI/python-satcfdi) |
| **Autor** | SAT-CFDI (organización) |
| **Stars** | 125 |
| **Último release** | v4.9.9 — marzo 2026 |
| **Licencia** | MIT |
| **PyPI** | `pip install satcfdi` |
| **Python** | >=3.11 |
| **Docs** | [satcfdi.readthedocs.io](https://satcfdi.readthedocs.io/) |

**Features:** FIEL, metadata, XMLs, async parcial, generación CFDI (v3.2-4.0), PDF/HTML/JSON/Excel, PACs (Comercio Digital, Diverza, Finkok, Prodigia, SW Sapien), nómina, pagos, carta porte, retenciones, contabilidad electrónica, Lista 69B.
**No tiene:** CIEC, CLI, TLS workarounds, multi-empresa.
**Valoración:** La más completa. Descarga masiva es un módulo dentro de una librería enorme. MIT, Python moderno.

---

### 3. sat-ws

| Campo | Detalle |
|---|---|
| **Repositorio** | [gitlab.com/HomebrewSoft/sat_ws_api](https://gitlab.com/HomebrewSoft/sat_ws_api) (GitLab) |
| **Autor** | Moises Navarro (AfroMonkey) |
| **Último release** | v3.25.0 — enero 2024 |
| **Licencia** | MIT |
| **PyPI** | `pip install sat-ws` |
| **Python** | >=3.6 |

**Features:** FIEL (token automático), metadata, XMLs, retenciones.
**No tiene:** CIEC, retry, async, CLI, reportes.
**Valoración:** Limpia, inspirada en phpcfdi (PHP). MIT. Posiblemente sin soporte API v1.5.

---

### 4. sat-descarga-masiva-python

| Campo | Detalle |
|---|---|
| **Repositorio** | [github.com/guillermo11bq/sat-descarga-masiva-python](https://github.com/guillermo11bq/sat-descarga-masiva-python) |
| **Stars** | 27 |
| **Último commit** | abril 2019 |
| **Licencia** | GPL-3.0 |

Abandonado. Depende de Chilkat2 (propietario). Solo interés histórico.

---

### 5. admin-cfdi

| Campo | Detalle |
|---|---|
| **Repositorio** | [github.com/LinuxCabal/admin-cfdi](https://github.com/LinuxCabal/admin-cfdi) |
| **Stars** | 35 |
| **Último update** | ~2015 |

Archivado. Selenium + Firefox scraping. No usa web service SOAP.

---

### 6. fiscalapi

SDK comercial SaaS (MPL-2.0). `pip install fiscalapi`. Proxy al SAT, no directo. Caso de uso diferente.

---

## Referencia: Otros Lenguajes

| Proyecto | Lenguaje | Stars | URL | Notas |
|---|---|---|---|---|
| phpcfdi/sat-ws-descarga-masiva | PHP | 164 | [GitHub](https://github.com/phpcfdi/sat-ws-descarga-masiva) | La más madura. v1.5. 578 commits. |
| ARSoftware.Cfdi.DescargaMasiva | C# | — | [GitHub](https://github.com/AndresRamos/ARSoftware.Cfdi.DescargaMasiva) | .NET |
| mikkezavala/SatWebService | Java | 6 | [GitHub](https://github.com/mikkezavala/SatWebService) | Actualizado mar 2026 |

---

## Tabla Comparativa General

| Feature | XMLSAT Premium | sat-descarga-masiva | cfdiclient | satcfdi | sat-ws |
|---|---|---|---|---|---|
| **Plataforma** | Windows desktop | Python (cross-platform) | Python lib | Python lib | Python lib |
| **Precio** | $2,200 MXN/año | Open source | Open source (GPL) | Open source (MIT) | Open source (MIT) |
| **API v1.5 SAT** | ✅ | ✅ | ❌ | ❓ | ❌ |
| **FIEL auth** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **CIEC/portal** | ✅ | ✅ (Playwright) | ❌ | ❌ | ❌ |
| **Multi-empresa** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **TLS + retry** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Descarga metadata** | ✅ | ✅ | ❌ | ✅ | ✅ |
| **Descarga retenciones** | ✅ | ❌ | ❌ | ✅ | ✅ |
| **Descarga por UUID** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Descarga por RFC** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Descarga PDF SAT** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Historial descargas** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **CLI** | N/A (GUI) | ✅ | ❌ | ❌ | ❌ |
| **Server HTTP** | ❌ | ✅ (FastAPI) | ❌ | ❌ | ❌ |
| **GUI** | ✅ | ✅ (Electron + Next.js) | ❌ | ❌ | ❌ |
| **Validación CFDI** | ✅ (masiva) | ✅ (masiva concurrente + listas 69/69-B en un solo botón) | ✅ | ✅ | ❌ |
| **Listas negras (17)** | ✅ | 🟡 (69 + 69-B unificadas) | ❌ | ❌ (solo 69B) | ❌ |
| **Art. 69 y 69-B** | ✅ | ✅ (EFOS/EDOS, cron mensual) | ❌ | ✅ (69B) | ❌ |
| **Validación REPSE** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Validación RFC** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Export Excel** | ✅ | ✅ (CFDI/Pagos/Nómina) | ❌ | ✅ | ❌ |
| **XML → PDF** | ✅ (masivo, personalizable) | ❌ | ❌ | ✅ | ❌ |
| **Reporte IVA** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Reporte ISR** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Reporte IEPS** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Impuestos locales** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Concentrado IVA** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Acumulados** | ✅ | 🟡 (totales/mes) | ❌ | ❌ | ❌ |
| **Conciliación PPD/Pagos** | ✅ | ✅ (+huérfanos, extemporáneos, incidencias PUE) | ❌ | ❌ | ❌ |
| **Validación RESICO** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Nómina (reporte)** | ✅ (223 cols) | 🟡 (recibos + deductibilidad + IMSS + periodo-vs-periodo) | ❌ | ✅ | ❌ |
| **Complementos CFDI** | ✅ (8 tipos) | 🟡 (Pagos + Nómina) | ❌ | ✅ | ❌ |
| **DIOT automática** | ✅ (+batch) | ❌ | ❌ | ❌ | ❌ |
| **Contabilidad electrónica** | ✅ (1.3) | ❌ | ❌ | ✅ | ❌ |
| **Auditoría electrónica** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Opinión cumplimiento** | ✅ | ✅ (CIEC + e.firma) | ❌ | ❌ | ❌ |
| **Constancia sit. fiscal** | ✅ | ✅ (CIEC + e.firma) | ❌ | ❌ | ❌ |
| **Opinión IMSS** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Catálogo SAT** | ✅ | 🟡 (lookup interno) | ❌ | ✅ | ❌ |
| **Organizador carpetas** | ✅ (20 formas) | ✅ (9 estructuras) | ❌ | ❌ | ❌ |
| **Renombrado masivo** | ✅ | ✅ (5 patrones) | ❌ | ❌ | ❌ |
| **Eliminación duplicados** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Correos apócrifos** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Conciliación int/SAT** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **PyPI** | N/A | ❌ | ✅ | ✅ | ✅ |

---

## Qué Hacemos Mejor (sat-descarga-masiva)

### Vs. la competencia open-source Python
1. **API v1.5 del SAT** — Único proyecto Python actualizado (namespace `.sat`, firma xmldsig enveloped, `EstadoComprobante` texto)
2. **Resiliencia SSL** — TLSv1.2 forzado + 6 reintentos con backoff exponencial
3. **CIEC + FIEL** — Único proyecto con ambos métodos de acceso
4. **CLI multi-empresa con keychain del SO** — Múltiples RFCs/FIELs; contraseñas nunca en JSON
5. **Server HTTP (FastAPI)** — API REST con OpenAPI auto-documentada; habilita integraciones con ERPs sin que la FIEL salga
6. **Cross-platform** — Python (Mac/Windows/Linux) vs XMLSAT Premium solo Windows
7. **Open source** — vs $2,200 MXN/año de XMLSAT Premium
8. **SOAP manual con lxml** — Control total sin zeep/suds

### Vs. XMLSAT Premium (diferenciadores que ningún competidor tiene)
9. **Agente local + UI nativa** — Electron 33 + Next.js 16 + Tailwind v4. UX moderna vs GUI de Windows clásica.
10. **Captcha CIEC in-app por SSE** — El browser corre headless; el captcha se sirve a la UI como base64 y se resuelve en una mini-ventana dentro de la app. XMLSAT abre Internet Explorer embebido.
11. **Semáforo de e.firma** con autocarga al arranque — Vencimiento visible siempre (🟢 >30d / 🟡 ≤30d / 🔴 ≤5d o vencida); ningún competidor lo destaca.
12. **Buffer SQLite persistente** del procesador — Los CFDIs cargados y los filtros se conservan entre sesiones de la app.
13. **Procesador Pagos** con detección de **extemporáneos** e **incidencias PUE+complemento** — XMLSAT solo concilia PPD vs Pagos.
14. **Procesador Nómina** con tres reportes específicos: **deductibilidad fiscal**, **conciliación IMSS** y **periodo-vs-periodo**.
15. **Drag & drop** + carga desde empresa (`/procesador/cfdi/cargar*`) — No tienes que organizar carpetas antes.
16. **Validación masiva concurrente** — 10 hilos default, configurable; persiste `estado_sat` en el buffer.
17. **Login portal vía e.firma sin captcha** (`/cfdi/fiel`, `/constancia/fiel`, `/opinion/fiel`) — Flujos 100% desatendidos; XMLSAT requiere CIEC + captcha siempre.
18. **Historial de descargas por empresa + global** con apertura segura (`/abrir`) restringida a rutas registradas.
19. **Un solo botón para validar contra el SAT** — "Validar contra SAT" del procesador dispara en paralelo el estatus CFDI (Vigente/Cancelado/No encontrado) **y** el cruce contra listas 69/69-B (EFOS/EDOS). XMLSAT separa ambas validaciones en módulos distintos.
20. **Vista agregada por proveedor** — La página de Listas Negras muestra una fila por `emisor_rfc` con total acumulado y conteo de CFDIs, ordenada por riesgo monetario. XMLSAT lista los movimientos sin colapsar por contraparte.
21. **Paleta tonal consistente** entre badges del procesador — Vigente ↔ Limpio (verde), Cancelado ↔ EFOS (rojo), No encontrado ↔ 69/Aclarado (amber). El usuario lee de un vistazo el riesgo combinado.

## Qué Nos Falta vs XMLSAT Premium

> Estado actualizado el 2026-10-12 contra el código de `main`. Desde la primera versión de este
> documento ya se cerraron DIOT, envío de contabilidad electrónica, consulta de declaraciones y
> DIOT presentadas, el índice permanente de CFDIs y el export con plantillas. Comparativa contra
> CONTPAQi: [`benchmark-contpaqi.md`](benchmark-contpaqi.md).

La brecha que queda está en **reportes fiscales** (IVA, ISR, IEPS), el **visor XML → PDF**, los
**complementos** fuera de Pagos y Nómina, y la **auditoría** (catálogo vs balanza).

---

## Roadmap: Features a Implementar

### ✅ Fase 1 — Core de Descarga (CERRADA en v1.0.0)
| Feature | Estado |
|---|---|
| Descarga de **metadata** | ✅ `/metadata`, `sat-dm metadata` |
| Descarga por **listado de UUID** | ✅ `/solicitar-folio`, `descargar_por_uuid` |
| Historial completo de descargas | ✅ per-RFC + global, con SQLite |
| Descarga de **retenciones** | ❌ pendiente |
| Descarga por **listado de RFC** | ❌ pendiente |
| Publicar en **PyPI** | ❌ pendiente |

### 🟡 Fase 2 — Validación y Consultas SAT (parcial)
| Feature | Estado | Complejidad |
|---|---|---|
| **Validación de CFDI** (Vigente/Cancelado) | ✅ `/validar` + procesador `validar-sat` | — |
| **Constancia de situación fiscal** | ✅ CIEC + e.firma | — |
| **Opinión de cumplimiento** SAT (32-D) | ✅ CIEC + e.firma | — |
| **Listas negras** Art. 69 y 69-B | ✅ EFOS/EDOS vía API de todoconta (cron mensual) | — |
| **Validación REPSE** | ❌ | Media |
| **Validación de RFC** (estructura + existencia) | ❌ | Baja |
| **Opinión de cumplimiento IMSS** | ❌ | Media |

### 🟡 Fase 3 — Lectura y Export de XML (parcial)
| Feature | Estado | Complejidad |
|---|---|---|
| **Parser de XML** CFDI v3.3 y 4.0 | ✅ `procesador/cfdi_parser.py` | — |
| **Export a Excel** de datos de CFDIs | ✅ `/procesador/cfdi/exportar` (xlsx/csv) | — |
| **Export personalizable** (plantillas, una fila por concepto, convertir a MXN) | ✅ `/comprobantes/plantillas` (docs/producto/plantillas-export.md) | — |
| **Índice permanente** de CFDIs (XML original + todos los nodos) | ✅ cada descarga se indexa sola (`procesador/indexar.py`) | — |
| **Catálogo productos/servicios SAT** | 🟡 lookup interno, sin catálogo navegable | Media |
| **Lectura de complementos** (Pagos, Nómina) | ✅ (parcial) | — |
| **Lectura de complementos** (Carta Porte, Comercio Ext, Donatarias, etc.) | ❌ | Alta |
| **XML → PDF** masivo (personalizable) | ❌ | Alta |
| **Visor XML integrado** | ❌ | Media |

### ❌ Fase 4 — Reportes Fiscales (CRÍTICA — la mayor brecha vs XMLSAT)
| Feature | Estado | Complejidad |
|---|---|---|
| **Conciliación PPD vs Pagos** | ✅ `/procesador/pagos` (+huérfanos, extemporáneos, incidencias PUE) | — |
| **Reporte nómina** (deductibilidad + IMSS + periodo-vs-periodo) | ✅ `/procesador/nomina` | — |
| **Acumulación ingresos/gastos** | 🟡 `totales_por_mes`; falta desglose ingresos vs gastos | Media |
| **Reporte IVA** (concentrado por emisor/receptor, por tasa) | ❌ | Alta |
| **Reporte ISR** (agrupado por tasa) | ❌ | Alta |
| **Reporte IEPS** (hasta 20 tasas) | ❌ | Alta |
| **Concentrado IVA** ingresos y gastos | ❌ | Alta |
| **Impuestos locales** | ❌ | Media |
| **Validación RESICO** (retención correcta) | ❌ | Media |
| **Reporte nómina extendido** (223 columnas) | ❌ | Alta |

### 🟡 Fase 5 — DIOT y Contabilidad Electrónica
| Feature | Estado | Complejidad |
|---|---|---|
| **DIOT automática** + archivo batch | ✅ prellenado desde CFDIs, TXT de carga masiva, presentación y acuse (`/diot/*`) | — |
| **Contabilidad electrónica 1.3**: envío y acuses | ✅ `/ce/enviar`, `/ce/acuses` | — |
| **Contabilidad electrónica 1.3**: generar catálogo y balanza | ❌ (salen del sistema contable del usuario) | Alta |

### ✅ Fase 6 — Herramientas de Organización (CERRADA)
| Feature | Estado |
|---|---|
| **Organizador de XML** en carpetas | ✅ `/organizar` — 9 estructuras |
| **Renombrado masivo** | ✅ `/renombrar` — 5 patrones |
| **Eliminación de duplicados** | ✅ `/deduplicar` |
| **Agrupador** Vigentes/Cancelados | 🟡 filtro `estado_sat` en procesador; no en organizador |
| **Agrupador** por versión y tipo | ✅ filtro `tipo` en procesador |

### 🟡 Fase 7 — Auditoría Electrónica
| Feature | Estado | Complejidad |
|---|---|---|
| Consulta de **declaraciones** (normales + complementarias) | ✅ CLI `descargar declaraciones` (PDF + acuses); falta UI | Baja |
| Consulta de **DIOT enviadas** por año | ✅ CLI `descargar diot` (PDF + Excel + acuses); falta UI | Baja |
| Descarga de **contabilidad electrónica enviada** al SAT | 🟡 acuses (`/ce/acuses`); el XML enviado no | Media |
| **Analizador** catálogo vs balanza | ❌ | Alta |
| **Conciliación** sistema interno vs archivos SAT | ❌ | Alta |
| **Correos apócrifos** del SAT | ❌ | Baja |

### ✅ Fase 8 — GUI (CERRADA en v1.0.0)
| Feature | Estado |
|---|---|
| **Electron shell** | ✅ Electron 33 + Next.js 16 + Tailwind v4 + Radix + Phosphor |
| **Captcha in-app** (SSE) | ✅ — diferenciador único; XMLSAT abre IE embebido |
| **Semáforo de e.firma** | ✅ con autocarga al arranque |
| **Multi-empresa** con keychain del SO | ✅ |
| **Drag & drop** de XMLs al procesador | ✅ |
| **Visor XML integrado** | ❌ pendiente |

---

## Prioridades sugeridas para post-v1.0.0

1. **Fase 4 (Reportes Fiscales IVA/ISR/IEPS)** — la brecha más vendedora; sin esto, somos descarga + organización, no suite fiscal.
2. **Validación REPSE** (cierra Fase 2 junto con listas negras ya hechas) — diferenciador vs todos los Python.
3. **Descarga de retenciones + por RFC** (cierra Fase 1) — bajo esfuerzo, completa el core de WS.
4. **Lectura de complementos** (Carta Porte sobre todo) — alto valor para transportistas.
5. **DIOT automática** — feature ancla para personas morales.

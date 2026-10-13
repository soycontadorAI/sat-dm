# Benchmark: TodoConta vs CONTPAQi (Contabilidad, Bancos, Descarga de CFDI, XML en línea+)

Matriz de funciones de CONTPAQi (familia 19.x) contra lo que **hoy** tiene TodoConta, para decidir
qué implementar. Complementa a [`benchmark-competidores.md`](benchmark-competidores.md) (XMLSAT) y a
[`../integraciones/contpaqi/`](../integraciones/contpaqi/README.md) (cómo **integrarnos** con CONTPAQi;
este doc trata de **qué funciones tiene**, no de cómo conectarse).

> **Fuentes**: solo información pública (páginas de producto contpaqi.com, cartas técnicas 2026,
> manual del módulo de descarga, blogs de distribuidores), consultada el 2026-10-12. Lo marcado
> *(dist.)* viene de un distribuidor y no está confirmado en carta técnica. **No** se analizó el
> código de CONTPAQi: los instaladores 19.3.1 del zip son InstallShield cifrado y su EULA no
> permite ingeniería inversa. La **fase 2** de este análisis (recorrer la app instalada en una VM
> Windows con licencia de prueba) queda pendiente.
>
> **Estado de TodoConta**: verificado contra el código de `main` (v2.4.0 más el índice permanente
> de #224 y las plantillas de exportación de #225/#226), no contra
> `benchmark-competidores.md`, que está desactualizado (marca como faltantes DIOT, consulta de
> declaraciones y contabilidad electrónica, que ya existen).

Leyenda: ✅ lo tiene · 🟡 parcial · ❌ no lo tiene · — no aplica

## 1. Descarga de CFDI

| Función | CONTPAQi | TodoConta | Nota |
|---|---|---|---|
| Web Service SAT con e.firma (XML) | ✅ "Servicios del SAT" | ✅ `webservice/` | Paridad |
| Metadata (estatus, fecha de cancelación) | ✅ | ✅ `/metadata` | Paridad |
| Portal SAT con CIEC / e.firma (inmediata, tope 2,000/día) | ✅ "Portal del SAT" | ✅ CIEC (captcha in-app) + e.firma | Paridad |
| Descarga por UUID | No confirmado | ✅ `/solicitar-folio` | |
| Seguimiento de solicitudes pendientes (hasta 72 h) | ✅ historial manual | ✅ poller cada 60 s, descarga sola y marca vencidas | **Ventaja nuestra** |
| Mensajes legibles de los códigos SAT (5002, 5004, 5005…) | ✅ | ✅ `webservice/errores.py` | Paridad |
| **Descarga programada recurrente** (diaria/semanal) | ✅ ventana 00:00-07:00, **1 empresa por RFC**, sin histórico, servidor encendido | ❌ | **Hueco nuestro, fácil de superar**: el modo hosted corre 24/7 sin equipo encendido y sin tope de empresas |
| Compatible con WS v1.5 del SAT | ✅ requiere XML en línea+ 6.1.2 | ✅ | |
| Visor de documentos / XML → PDF | ✅ Visor de Documentos Digitales | ❌ | Ya estaba en el backlog de XMLSAT |
| Repositorio central de XML (ADD) con verificación SAT | ✅ ADD por empresa | ✅ índice permanente por empresa (XML original + nodos), alimentado solo por cada descarga; `/procesador/cfdi/validar-sat` | Local hoy; en la nube con planes de pago (fase 3 de `docs/producto/descarga-programada.md`) |
| Exportar a Excel con columnas a elegir | ✅ vistas personalizadas (XML en línea+) | ✅ plantillas, una fila por concepto y convertir a MXN | Paridad; el detalle por concepto trae impuestos y SKU |
| Multi-RFC / multiusuario | ✅ (XML en línea+, licencia multi) | ✅ catálogo multi-empresa + equipo + sync desktop ⇄ web | Paridad |

## 2. Riesgo fiscal y validación

| Función | CONTPAQi | TodoConta | Nota |
|---|---|---|---|
| Estatus SAT (vigente / cancelado) | ✅ | ✅ | Paridad |
| Listas 69-B por CFDI (presunto, definitivo, desvirtuado, sentencia) | ✅ reportes "CFDI asociados a EFOS/EDOS" | ✅ `/procesador/cfdi/validar-listas-negras`, por emisor | Paridad |
| **No localizados / 49 Bis** | ✅ desde 19.2.0 (jul-2026) | ❌ (solo 69-B) | Revisar si la API de listas de todoconta-apps ya trae Art. 69 / 49 Bis |
| Alerta cuando el **RFC propio** aparece en una lista | ✅ | ❌ | Barato: cruzar el catálogo de empresas al actualizar la lista mensual |
| Aviso de publicación nueva de la lista | ✅ | 🟡 `/listas-negras/metadata` (fecha), sin aviso | |
| Conciliación EFOS vs pólizas | ✅ | — | Depende de tener pólizas |
| Opinión 32-D / CSF (descarga + parser + semáforo) | ❌ | ✅ | **Ventaja nuestra** |

## 3. Obligaciones y reportes fiscales

| Función | CONTPAQi | TodoConta | Nota |
|---|---|---|---|
| DIOT 2025 (54 campos) + TXT de carga masiva | ✅ | ✅ prellenado desde CFDIs, tabla editable | Paridad |
| DIOT formato de 23 campos | ✅ | ❌ | Validar si aún se usa |
| Proporción de IVA masiva en DIOT | ✅ | No verificado | Revisar en `diot/` |
| Presentar DIOT y bajar acuse | No confirmado (se carga en el portal) | ✅ `/diot/presentar`, `/diot/acuse` | **Ventaja nuestra** |
| Contabilidad electrónica: **generar** catálogo y balanza XML | ✅ | ❌ (recibe los XML de otro sistema) | Requiere módulo contable |
| Contabilidad electrónica: **enviar** y consultar acuses | No confirmado | ✅ `/ce/enviar`, `/ce/acuses` (42/42 aceptados en prod) | **Ventaja nuestra** |
| **Papel de IVA R21** (autodeterminación por conceptos 100s/200s/301) | ✅ desde 19.0.1, Excel | ❌ (sí guardamos bases e IVA por tasa en `procesador.db`) | **Prioridad alta**: los datos ya están, falta el reporte. Ver `docs/producto/metodologia-calculo-impuestos.md` |
| Pago provisional / cálculo de IVA | ✅ | ❌ | Mismo motor que R21; ojo con "copiloto, no autopiloto" (sugerir, no determinar) |
| Declaración anual PM + planeación + NIF | ✅ | ❌ | Fuera de alcance corto |
| Consulta de declaraciones presentadas + acuses | ❌ | ✅ CLI (`descargar declaraciones`), sin UI | **Ventaja nuestra**; falta subirlo a la UI |
| Complementos: Pagos, Nómina | ✅ | ✅ reportes PPD vs pagos y nómina | Paridad |
| Complementos: Carta Porte, Comercio Exterior, Hidrocarburos | ✅ | ❌ | |

## 4. Contabilidad (pólizas)

| Función | CONTPAQi | TodoConta | Nota |
|---|---|---|---|
| Pólizas automáticas desde XML (contabilizador, más de 2,000 CFDI por póliza) | ✅ | ❌ (diseñado: `integraciones/contpaqi/06`) | El Contabilizador TXT es el puente: generamos y CONTPAQi importa |
| Pólizas desde Excel | ✅ | ❌ | |
| Catálogo de cuentas, balanza, auxiliares | ✅ | ❌ | No competir aquí; integrarse |

## 5. Bancos

| Función | CONTPAQi | TodoConta | Nota |
|---|---|---|---|
| Conexión directa con bancos (Banamex, BBVA, Banorte, Banregio, Scotiabank) | ✅ "Conecta tu Banco" $1,990/credencial | ❌ | Caro y con convenios bancarios; no es el primer paso |
| Lectura de estado de cuenta **PDF** | ✅ desde 18.2.3 | ❌ | **Prioridad media-alta**: es el flujo real de los clientes RESICO (BBVA, deposit-by-deposit) |
| Asociar movimiento bancario ↔ uno o varios CFDI, con dispersión del pago | ✅ 19.3.1 (ago-2026) | ❌ | Encaja con el reporte de pagos PPD que ya existe |
| Conciliación bancaria | ✅ | ❌ | |
| Flujo de efectivo proyectado | ✅ | ❌ | Baja prioridad |
| Tablero REP "como lo ve el SAT" | ✅ | 🟡 reporte de pagos PPD, huérfanos e incidencias PUE | Casi paridad |

## 6. Plataforma y precio

| | CONTPAQi | TodoConta |
|---|---|---|
| Sistema operativo | Windows (escritorio); nube aparte, con funciones distintas | **Mac + Windows + web**, mismo agente |
| Precio anual para cubrir descarga + validación + DIOT | Contabilidad Mono-RFC $4,590 (Multi $6,190) + XML en línea+ $1,790 | Ver `planes` |
| Bancos | +$4,890 (+$1,990 por banco conectado) | — |
| API / integraciones | SDK COM sin documentación oficial | **API REST pública + MCP** |
| Trámites (renovación e.firma, CSD) | ❌ | ✅ `certifica/` |
| Calculadoras laborales | ❌ (es Nóminas, aparte) | ✅ |

## Lo que conviene implementar, en orden

1. **Descarga programada en la nube.** Es nuestro producto central y CONTPAQi lo hace mal: ventana de
   madrugada, PC encendida, una empresa por RFC y sin histórico. Lo nuestro: una regla por empresa
   (diaria o semanal), en el agente hosted, con el poller que ya existe. Esfuerzo bajo o medio.
2. **Papel de trabajo de IVA (R21) + pago provisional sugerido.** Es lo que CONTPAQi más empujó en
   2026 y ya tenemos los datos por tasa. Se entrega como papel de trabajo editable, no como
   determinación.
3. **Estado de cuenta PDF → movimientos → asociar CFDI.** Une el procesador de pagos con el trabajo
   real de conciliación de depósitos. Empezar por BBVA.
4. **Alertas de riesgo**: RFC propio en listas, 49 Bis / no localizados y aviso de publicación nueva.
   Esfuerzo bajo; cierra la paridad con el Tablero fiscal.
5. **Visor XML → PDF.** Pendiente desde el benchmark de XMLSAT; CONTPAQi lo trae en la descarga
   nueva.
6. **Contabilizador TXT** (ya diseñado en `integraciones/contpaqi/`). No competimos con la
   contabilidad: alimentamos la de CONTPAQi.

**No perseguir**: contabilidad completa (catálogo, balanza, auxiliares), Conecta tu Banco,
declaración anual PM, flujo de efectivo.

## Pendiente: fase 2 (app instalada)

En una VM Windows con licencia de prueba de 30 días, instalar Contabilidad + Bancos 19.3.1 del zip
y documentar:

- Pantallas reales de la nueva Descarga de CFDI (v1.5): credencial que pide, filtros, límites.
- El ADD: cómo se ve, cómo se asocia un UUID a una póliza.
- Reportes R21 y EFOS: columnas exactas (para que nuestro Excel sea familiar al contador).
- Lectura de PDF bancario: qué bancos y formatos acepta.
- Esquemas de importación vigentes (`CT_EST_Poliza_NG` en la 19) para cerrar la brecha 14 → 19
  de `integraciones/contpaqi/05-roadmap.md`.

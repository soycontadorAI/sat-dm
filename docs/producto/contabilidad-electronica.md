# Contabilidad electrónica (Anexo 24): envío y consulta de acuses

Cómo TodoConta envía la contabilidad electrónica al SAT y verifica que quedó
**aceptada**. Todo lo de este documento está medido contra los portales de
producción (sesión del 2026-08-29: 42 envíos reales, 42 aceptados, dos
empresas). Código: `sat_descarga/portal/contabilidad_electronica.py`,
`sat_descarga/portal/reanudar_envios.py`, `sat_descarga/cli/contabilidad.py`,
`sat_descarga/api/routers/ce.py`.

## La obligación

Personas morales (y PF con actividad empresarial obligadas) envían por el
Buzón Tributario, conforme al Anexo 24 y la RMF (reglas 2.8.1.6 / 2.8.1.7):

- **Catálogo de cuentas (CT)**: la primera vez, y cada vez que se modifique.
  No es anual.
- **Balanza de comprobación (BN/BC)**: mensual — vence el **día 3 del segundo
  mes siguiente** al que corresponde (la de junio, el 3 de agosto). La del
  **cierre del ejercicio (periodo 13)** vence el **20 de abril** del año
  siguiente.
- Pólizas (PL) y auxiliares (XF/XC): solo a requerimiento (fiscalización,
  devolución, compensación).

TodoConta **no genera** estos XML (salen del software contable del usuario);
los revisa y los envía. Si algún día la app trae módulo de contabilidad, la
integración es directa: este flujo recibe rutas a ZIPs.

## Nomenclatura y revisión previa

Un envío = un ZIP con exactamente un XML, ambos nombrados
`{RFC}{AAAA}{MM}{TIPO}` (`SSA980330HU1202606BN.zip`). Tipos: `CT`, `BN`, `BC`,
`PL`, `XF`, `XC`. Mes `13` = ajuste al cierre.

`inspeccionar_zip()` abre cada ZIP **antes** de tocar el portal y coteja
nomenclatura vs contenido: RFC/Anio/Mes del XML contra el nombre, raíz esperada
por tipo (un `<Catalogo>` dentro de un `*BN.zip` se rechaza aquí), un solo
archivo interno con el mismo nombre. Motivo: el portal **acepta** un ZIP malo y
el rechazo llega hasta la validación posterior — el acuse de recepción no avisa.

El inventario ordena **CT antes que BN del mismo periodo** (el catálogo debe
entrar antes que la primera balanza; alfabéticamente sería al revés).

## Los DOS portales (esto es lo que más cuesta descubrir)

| | host |
|---|---|
| Envío | `https://ceportalenvioprod.clouda.sat.gob.mx/` |
| Consulta de acuses | `https://ceportalconsultaextprod.clouda.sat.gob.mx/` |

El host de **envío** sirve una copia de `/ConsultaAcuses` visualmente idéntica
pero **inservible**: su script inline engancha los eventos antes de que cargue
el bundle de jQuery y truena con `$ is not defined` (la página se ve bien y no
responde a un solo clic), y su `BuscaAcuses` contesta 500 con la pantalla
genérica de "sistema no disponible". La consulta buena vive en el otro host, y
la **sesión SSO del login de envío sirve ahí sin re-autenticar**.

Login: e.firma vía el NIDP (`iniciar_sesion_fiel` de `portal/login.py`), sin
captcha. El NIDP falla suelto (~2 de cada 15 entradas se quedan en
`/nidp/wsfed/ep`); **no** es rate-limit (13 logins seguidos en 28 min salieron
bien) → se reintenta (3 intentos), no se espera. Sesión del portal: 15 min.

## Flujo de envío — comportamientos silenciosos del portal

Todos sin error, sin petición de red y sin alerta; cada uno costó una corrida:

| # | Comportamiento | Mitigación |
|---|---|---|
| 1 | Modal «Contribuyente Amparado» al entrar; su botón es `#btnLogout` pero postea a `/Envio/RedirecAmparados` y es el camino normal | clic y seguir |
| 2 | El radio de sellado es input+label estilizado: `check("#rbSi")` marca el input pero `#divEFirma` sigue oculto | despachar `change`/`click` por JS |
| 3 | El **primer** clic en «Agregar» tras cargar la e.firma se consume procesándola (`#modifiedFiel` 1→0) y no crea renglón | reintentar el clic (hasta 3) |
| 4 | Al leer el ZIP, el portal **reemplaza** la lista de motivos por los válidos para ese tipo; balanza normal = una sola opción («Envio Mensual», value=7) | esperar "hay opción real", no "hay más de una" |
| 5 | `#status<ID>` reusa el mismo span para TODO el ciclo: «Enviando… espere», «N% completado.», y al final folio o error | esperar señal TERMINAL (`es_estado_terminal`, testeada); lista negra de mensajes NO sirve |
| 6 | `Could not find file …xmlTemp\*.xml`: el SAT descomprime el ZIP a un temporal y a veces lo lee antes de que exista. **Es la norma**: 1-4 intentos por archivo en la corrida real | reintentar el archivo (default 8, pausa 2.5 s). Los errores de fondo (RFC que no corresponde, ZIP inválido) NO se reintentan |

Sellado: `¿Desea sellar su información?` — la e.firma del sellado se carga vía
el botón «Buscar» (file chooser real), no inyectando al input oculto: el JS que
parsea el `.cer` y llena `#txtRfc` solo corre por el camino manual (misma
lección que la DIOT). Candados antes de subir: `#hfRfc` de la sesión y RFC del
`.cer` deben coincidir con el RFC de los ZIPs. **El sellado es decisión visible
del usuario**: viaja en el request/fases/resultado; el camino "no sellar"
también está verificado contra el portal.

## Consulta de acuses

La pantalla `/ConsultaAcuses` no se maneja por la UI (ver arriba). Su búsqueda
es un **POST JSON** a `/ConsultaAcuses/BuscaAcuses/` que devuelve el HTML del
grid; se llama con `fetch` **desde la página** (same-origin: cookie, origen y
Referer como el `$.ajax` del portal) — desde el contexto de Playwright da 500.
Detalles del formulario, por si algún día hay que tocarlo: la validación lee
`$("#rdo…").attr("checked")` (el **atributo**, que un clic normal nunca toca) y
`#ddlTipoEnvio` solo se habilita —y se vuelve obligatorio— al elegir Balanzas
en `#ddlTipoArchivo`. El grid escapa acentuadas (`Comprobaci&#243;n`) →
`html.unescape`.

## Recepción vs aceptación (la semántica que importa)

- `AR_{folio}.pdf` — acuse de **recepción**: "su archivo fue recibido y será
  procesado". **NO ampara el cumplimiento** (lo dice el propio PDF).
- `AP_{folio}.pdf` — acuse de **aceptación**: "el documento fue aceptado".
  Este es el que ampara.
- Estatus: `Recibido` (el SAT aún valida) → `Aceptado` o `Rechazado` (corregir
  y reenviar; los rechazados NO se omiten al reenviar).
- El folio codifica tipo y periodo: `0001`=catálogo / `0002`=balanza + `AAMM`
  + consecutivo. La URL directa del AR es
  `/ConsultaAcuses/AR_{folio}?folio={folio}&tipoAcuse=1`; la del AP se obtiene
  disparando `VerAcuseProcesamiento(folio, true, true, 2)` del grid y leyendo
  el `src` del iframe que abre.
- **El SAT acepta el mismo archivo dos veces sin chistar** → siempre se
  consulta el portal antes de enviar (`omitir_enviados`); apuntar a la carpeta
  completa es seguro.

Los acuses caen en `<descargas>/ce/<RFC>/<ejercicio>/` (convención TodoConta,
`core/paths.dir_ce`); `--junto-al-zip` los deja con los papeles de trabajo.

## Cola de reintento diferido

El SAT se pone lento o entra en mantenimiento **sin anunciarlo jamás**. Cuando
un envío agota reintentos por errores transitorios (o el login/portal están
caídos → `ErrorEsperado`), queda en `~/.sat-descarga/envios/{RFC}.json` y se
retoma con `sat-dm ce reanudar` o solo, por el poller de la app (enfriamiento
30 min, respeta jobs activos, kill switch `SAT_DM_SIN_REANUDAR_ENVIOS=1`).
Reanudar es idempotente: consulta el portal antes de subir.

## Comandos y API

```bash
sat-dm ce inventario <carpeta|zips>          # revisión previa, sin portal
sat-dm ce enviar <carpeta> --rfc X           # dry-run: valida y cancela
sat-dm ce enviar <carpeta> --rfc X --enviar  # envío real (--si, --sin-sellar,
                                             #  --junto-al-zip, --reenviar)
sat-dm ce acuses --rfc X --anio N --bajar    # estatus + AR_/AP_ por folio
sat-dm ce pendientes                         # la cola
sat-dm ce reanudar                           # retomarla (idempotente)
```

API (jobs + SSE, patrón certifica; FIEL del keychain): `POST /ce/enviar`
(`confirmar=true` obligatorio o `solo_validar=true`), `POST /ce/acuses`,
`GET /ce/pendientes`, `POST /ce/reanudar`. Fases estables para la checklist de
la UI en los docstrings de `EnviadorCE`/`ConsultorCE`.

Apoyos de la UI (sin portal): `POST /ce/inventario` (revisión previa de ZIPs ya
en el equipo), `POST /ce/subir` (la web no tiene rutas: sube los ZIP a
`ce_subidos/` del agente y devuelve el mismo inventario), `GET /ce/acuses`
(última consulta guardada en `ce/{RFC}/{año}/consulta.json`, con `tiene_ar` /
`tiene_ap` calculados contra el disco) y `GET /ce/acuse?rfc&anio&folio&tipo=AR|AP`
(sirve el PDF; la ruta se deriva de RFC+año+folio, nunca del cliente, y el folio
solo admite dígitos — no usa la lista blanca del historial).

## UI (`/contabilidad`)

Dos pantallas sobre la empresa activa (requiere e.firma), cada una con su entrada en el menú
bajo Contabilidad electrónica, como en la DIOT:

- **Enviar** (`/contabilidad`): wizard Archivos → Opciones → Validar → Enviar. Desktop elige los
  ZIP con el diálogo nativo (`satDesktop.elegirZips`); la web y arrastrar-y-soltar usan
  `/ce/subir`. El sellado es una decisión explícita (sin valor por default), se valida primero
  sin enviar (`solo_validar`) y el envío real exige confirmar que es irreversible. Un ZIP con
  problemas, de varios RFC o de un RFC distinto al de la empresa activa bloquea el avance
  (`lib/contabilidad-electronica.ts`). Al terminar, "Ver acuses" lleva a Presentadas en ese
  ejercicio.
- **Presentadas** (`/contabilidad/presentadas?anio=`): ejercicio + "Actualizar desde el SAT"
  (job), tabla con estatus y los PDF de recepción y de aceptación/rechazo. Rechazado ofrece
  "Corregir y reenviar" (lleva a Enviar).
- El banner de la cola de pendientes, con "Reintentar ahora", aparece en las dos.

Hasta el 2026-10-31, Enviar y Acuses eran pestañas de una sola página (con `forceMount` para no
perder el wizard al cambiar); se separaron en rutas para que el menú pueda marcar cada una.

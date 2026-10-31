# Pendientes: envíos al SAT (DIOT + contabilidad electrónica)

Roadmap con TODO el contexto necesario para retomar cada punto sin re-descubrir
nada. Origen: sesión de integración 2026-08-29 (42 envíos CE reales, los
hallazgos en `docs/producto/contabilidad-electronica.md`).

## (a) Acuse de aceptación de la DIOT — el pendiente grande

**Problema.** `PresentadorDiot` maneja UN artefacto: el PDF que emite
`GeneraArchivoAcuse` al firmar. No hay concepto de estatus ni verificación
posterior. Cuando el flujo termina en `"desconocido"` (sin acuse y la temporal
desapareció) se le dice al usuario "verifica en el portal" **sin darle
herramienta** — y está comprobado (2026-07-31) que una firma fallida puede
consumir la temporal sin presentar.

**Lo que ya se sabe** (para no re-mapear):
- Pantalla: menú «Impresión de acuse» → `/Consulta/Consulta/3` del portal DIOT
  (`pstcdi.clouda.sat.gob.mx`).
- Selectores confirmados: `#TipoDeclaracion`, `#Ejercicio`, `#Periodicidad`
  (="M"), `#Periodo`, `#TipoConcepto` (=9006, `CONCEPTO_DIOT`), `#btnBuscar`,
  y el grid `#tableResult`.
- `descargar_acuse()` hoy es **ciego al grid**: no lee columnas (ni estatus,
  ni folio, ni fecha); clickea el primer control de descarga que encuentra.
  Sirve para bajar un PDF, no para VERIFICAR.

**Lo que falta.**
1. Recon en vivo del grid `#tableResult`: columnas exactas, cómo se ve una
   declaración normal vs una complementaria vs un periodo sin presentar.
   Método probado en la sesión CE: script de captura frame-aware (login
   automático con e.firma + el usuario navega + snapshot de HTML/campos/red
   por cada pantalla). El molde está en la memoria del proyecto `diot`.
2. `parsear_grid_diot()` + un `sat-dm diot acuses --anio N` equivalente a
   `sat-dm ce acuses`: lista periodos presentados con fecha/folio y baja los
   PDFs. Resuelve el estado `desconocido` de una vez.
3. Cablearlo a `POST /diot/acuse` (hoy documenta su ceguera en el docstring).

## (b) Estímulos fiscales en la DIOT — con su camino de producto

Hoy el flujo solo soporta responder **«No»** a «¿Aplicaste estímulos
fiscales?». La limitante es **contractual** en toda la superficie: campo
`sin_estimulos: bool` obligatorio en `POST /diot/presentar` (400 si falta),
aviso permanente en el CLI — una empresa que sí aplica estímulos no llega al
portal por esta vía.

**El plan NO es solo mapear el flujo del portal**: es construir en NUESTRA app
el formulario que capture la información de estímulos y la pueble en la
declaración previo a su llenado, de modo que esas empresas también presenten
desde la app. Requiere: (1) recon del formulario de estímulos del portal,
(2) modelo de captura en la app, (3) extender `_responder_estimulos()`.

## (c) Suspend/resume genérico de confirmación en jobs

La API resuelve la irreversibilidad con `confirmar=true` en el request (patrón
certifica) + two-step `solo_validar`. Lo ideal a futuro: pausar el job cuando
los totales del portal ya se leyeron y preguntar al usuario en vivo —
`jobs.py` ya tiene toda la maquinaria (el suspend/resume del captcha,
`_captcha_resp: queue.Queue`); generalizarla a `pedir_confirmacion(resumen)`.

## (d) UI (siguiente iteración)

- ✅ **Pantalla CE hecha** (`/contabilidad`, ver `docs/producto/contabilidad-electronica.md`):
  selector de ZIPs, resumen del inventario, decisión de sellado explícita,
  progreso por fases, tabla de estatus (Recibido/Aceptado/Rechazado) y cola de
  pendientes visible. Falta QA con una corrida real contra el SAT desde la UI.
- Botón «Presentar en el SAT» en `/diot` junto a `ExportTxtButton`, con el
  two-step (validar → mostrar totales del portal → confirmar) y la pregunta
  de estímulos SIEMPRE visible.
- Los nombres de fase ya están definidos y estables en
  `portal/contabilidad_electronica.py` y `portal/diot_presentacion.py`;
  mapearlos a `FasesProgreso` como en `renovar-efirma-wizard.tsx`.

## (e) Preexistente, fuera de alcance

- `sat-dm descargar *` usa `./descargas` relativo al cwd en vez de
  `get_descargas_dir()` (la API sí usa la carpeta TodoConta). Arreglarlo
  implica migrar lo ya descargado; decisión aparte.

# Migración del front de la app a `ui/` (app.todoconta.com)

> Plan redactado 2026-07-21, en ejecución. Arquitectura y dominios:
> [docs/producto/especificaciones.md](../producto/especificaciones.md) (Parte I).

## Estado (2026-09-28)

| Fase | Página legacy | Estado |
|---|---|---|
| 1 | `/cuenta/api` (API keys y conexión MCP) | ✅ En `ui/` como **Ajustes → API** desde v2.1.0. Falta el retiro del legacy (1.4). |
| 2 | `/cuenta/equipo` | ✅ En `ui/` como **Ajustes → Equipo** desde v2.1.0. Falta retirar la página legacy. |
| 3 | `/cuenta` (billing, portal de Stripe) | ⏳ Pendiente. |
| 4 | `/planes` | ⏳ Pendiente de decidir: página pública o flujo in-app. |
| 5 | Cleanup final | ⏳ Pendiente. `todoconta-apps` todavía sirve `apps/web/src/app/cuenta/api` y `cuenta/equipo`, y `ui/vercel.json` conserva el rewrite `/cuenta/*`. |

## Objetivo

Toda la **UI** de la app (`app.todoconta.com`) se construye en el renderer
`ui/` (el mismo de la app Desktop, diseño actual). El proyecto legacy
`todoconta-apps/apps/web` (`api.todoconta.com`) se queda **solo con API**
(rutas `route.ts`) y con el plumbing que no es UI de app. Se abandona el diseño
viejo. Motor del cambio: hoy `/cuenta/*` (incluida la página de API keys) la
sirve el legacy con diseño viejo y **el usuario Desktop no la ve** (Electron
solo renderiza `ui/`).

## Arquitectura confirmada (leída en código, 2026-07-21)

El renderer NUNCA habla directo con `api.todoconta.com`. Habla con **su agente**
(local en Electron; `agente.todoconta.com/u/{slug}` en web) autenticando con el
**agent token** (`X-Agent-Token`, `lib/conexion-web.ts`). El **agente** es quien
tiene la **sesión de Supabase** y proxya a la API de servicios con Bearer:

```
Renderer ui/  ──X-Agent-Token──▶  Agente (Python)  ──Bearer <access_token>──▶  api.todoconta.com/api/*
(mismo en Desktop y Web)          tiene la sesión Supabase                     servicios (legacy)
```

Evidencia:
- `ui/src/providers/auth-provider.tsx` → `apiClient.authLicense()` pega al
  agente, no a servicios. El renderer no tiene el `access_token`.
- `sat_descarga/api/license_client.py` → `load_session()` guarda
  `access_token`+`refresh_token` en el backend de secretos; `fetch_license_remote(session)`
  hace `GET api.todoconta.com/api/desktop/license` con `Authorization: Bearer
  <access_token>` y hay refresh-on-401 (`_fetch_license_con_refresh`).
- `todoconta-apps/apps/web/src/lib/desktop/auth.ts::getDesktopUser(req)` valida
  el Bearer JWT (`supabase.auth.getUser(token)`) — patrón de todos los
  `/api/desktop/*`, con `corsJson`/`corsPreflightResponse` (`lib/desktop/cors.ts`).

**Implicación de diseño**: la forma correcta y uniforme (misma en Desktop y Web)
es **renderer → agente → servicios**. No exponemos el `access_token` al
renderer ni dependemos de cookies cross-domain (que es justo lo que hace fea la
`/cuenta/api` legacy hoy: usa la sesión web por cookies de otro dominio).

### Nota de doc (Context7 — Supabase SSR)

Para validar un Bearer en el servidor, Supabase recomienda `auth.getUser(token)`
(recupera el user; hace red al auth server) o `auth.getClaims()` (verifica el JWT
localmente vía JWKS, sin red, para decisiones de autorización). `getDesktopUser`
ya usa `getUser(token)`, que es correcto para nuestro caso (necesitamos el
`user.id` verificado). No usar `getSession()` para autorizar (spoofeable).

## Patrón de migración por página (3 capas)

Cada página que se mueve del legacy a `ui/` sigue el mismo molde:

1. **API (se queda en `todoconta-apps`)** — exponer la operación como endpoint
   **Bearer + CORS** bajo `/api/desktop/*`, reusando `getDesktopUser` + `corsJson`
   (patrón existente). La lógica de negocio no cambia (mismo service client,
   mismas tablas). Si ya existe una versión por cookies para la página legacy,
   se deja intacta hasta el cutover.
2. **Agente (`sat_descarga/api/server.py`)** — endpoint proxy que llama al
   endpoint de servicios con `Authorization: Bearer <load_session().access_token>`,
   reusando el refresh-on-401 de `license_client.py`. Funciona en ambos modos
   porque el agente siempre tiene la sesión.
3. **Renderer (`ui/`)** — método(s) en `api-client.ts` que pegan al agente +
   pantalla nueva con el diseño actual. Sin `esWeb()` gating salvo que algo no
   aplique (la gestión de keys aplica en ambos modos → Desktop por fin la ve).

## Fase 1 — `/cuenta/api` → gestión de API keys / conexión MCP en `ui/`

Primera y más acotada (fue el disparador). Valida el patrón completo.

### 1.1 API (todoconta-apps)
- Nuevo `app/api/desktop/api-keys/route.ts` con `GET` (listar), `POST` (emitir),
  `DELETE` (revocar) + `OPTIONS`, autenticando con `getDesktopUser` y
  respondiendo con `corsJson`. Copiar la lógica de
  `app/api/cuenta/api-keys/route.ts` (service client, hash SHA-256, `MAX_KEYS_ACTIVAS=10`,
  scopes default). **Sin migración nueva** — la tabla `api_keys` (migración 030)
  ya existe.
- La ruta legacy por cookies (`/api/cuenta/api-keys`) se deja igual hasta retirar
  la página `/cuenta/api` legacy.

### 1.2 Agente (sat_descarga/api/server.py)
- `GET/POST/DELETE /cuenta/api-keys` que proxya a
  `{TODOCONTA_API_BASE_URL}/api/desktop/api-keys` con el Bearer de la sesión +
  refresh-on-401 (extraer el helper de `license_client.py` o reusarlo). Devuelve
  el JSON tal cual. Disponible en local y hosted (ambos tienen sesión).

### 1.3 Renderer (ui/)
- `api-client.ts`: `listApiKeys()`, `createApiKey(nombre)`, `revokeApiKey(id)`.
- **Ruta nueva estática** `ui/src/app/ajustes/api/page.tsx` (NO `[param]`; export
  la emite como `ajustes/api/index.html`). Enlazada desde una card nueva **"API y
  conexiones (MCP)"** en `ui/src/app/ajustes/page.tsx` (patrón `AjCard`).
- Contenido: lista de keys (prefijo, último uso, revocar) con `ResourceList`;
  crear (nombre → se muestra la key **una sola vez** + botón copiar); bloque de
  **conexión MCP** con `https://agente.todoconta.com/mcp` + "Agregar conector
  personalizado" y link a `todoconta.com/mcp`. Copy en español, iconos Phosphor
  light (registrar los que falten en `lib/icons.ts`).
- Funciona en Desktop y Web (el agente tiene la sesión en ambos).

### 1.4 Retiro del legacy (cleanup, al final de la fase)
- Quitar la card agregada en PR apps#244 y la página `/cuenta/api` legacy, o
  dejar un redirect. Revisar el rewrite `/cuenta/*` de `ui/vercel.json` cuando ya
  no queden páginas `/cuenta/*` que sirva el legacy.

## Fases siguientes (mismo molde, una por una)

- **`/cuenta/equipo`** (equipo, despachos/empresarial): endpoints `/api/teams/*`
  (ya existen varios) → Bearer + agente proxy → página en `ui/`.
- **`/cuenta`** (cuenta/billing): buena parte ya vive en `ui/` Ajustes → "Acerca
  de" (correo, logout, plan vía `license`). Falta el **portal de facturación de
  Stripe**: endpoint Bearer que devuelva la URL del customer portal → agente
  proxya → `ui/` abre la URL.
- **`/planes`** (pricing + checkout Stripe) — **caso especial, decidir aparte**:
  es página pública (la linkea la landing, la usa Desktop para upgrade). Opciones:
  (a) dejarla como página pública (landing o legacy) y solo abrir checkout desde
  `ui/`; (b) flujo de upgrade in-app en `ui/` con endpoint de checkout-session
  Bearer. Recomendado decidir cuando lleguemos aquí.

## Se quedan en `todoconta-apps` (no son UI de app)

- `/api/*` — todos los servicios (desktop, sat, cron, cfdis, cartas-sat, teams,
  stripe, session, fiscal, etc.).
- `/auth/{callback,error,confirm}` — callbacks de Supabase; sus redirect URLs
  están configuradas ahí. **No mover** (rompería login/magic link).
- `/desktop/activate` — puente del device-code flow de la Desktop.
- `/admin`, `/admin/usuarios` — ops interno, no el usuario final (migrar es
  opcional y de baja prioridad).

## Consideraciones / riesgos

- **Routing bajo `output: 'export'`** (ui/CLAUDE.md): rutas **estáticas** (sin
  `[param]`), cada una con su `index.html`; si usa `useSearchParams`, envolver en
  `<Suspense>`. Validar con `cd desktop && pnpm debug:packaged` antes de empacar.
- **Desktop-first**: la gestión de keys es una GANANCIA para Desktop (hoy no la
  ve). Verificar en Electron empacado, no solo en dev.
- **Refresh de token**: reusar el refresh-on-401 de `license_client.py` para que
  un `access_token` vencido no rompa el proxy.
- **Seguridad**: la key se muestra UNA vez; en la tabla solo vive el hash. El
  one-time-reveal + copiar se maneja en `ui/`. Nunca loguear la key.
- **No romper el legacy en transición**: mantener la ruta por cookies y la página
  `/cuenta/api` legacy hasta el cutover de la fase.
- **CORS**: `agente→servicios` es server-to-server (sin CORS de browser); aun así
  el endpoint reusa `corsJson`/`OPTIONS` por consistencia con `/api/desktop/*`.
- **Git**: ramas por PR, nunca commitear en main; `ui/` y `apps/web` viven en
  repos distintos → probablemente **dos PRs coordinados** por fase (API en
  todoconta-apps, agente+UI en sat-descarga-masiva).

## Orden propuesto

1. Fase 1 completa (`/cuenta/api` → `ui/`), incluye retiro del legacy de esa página.
2. `/cuenta/equipo`.
3. `/cuenta` (billing/Stripe portal) — consolidar en Ajustes.
4. `/planes` — decidir público vs in-app.
5. Cleanup final: remover páginas legacy migradas + rewrite `/cuenta/*`.

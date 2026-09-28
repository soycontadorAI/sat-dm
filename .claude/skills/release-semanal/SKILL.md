---
name: release-semanal
description: Corta el release semanal de TodoConta Desktop (típicamente el viernes). Encuentra el último tag, consolida los commits de la semana, propone y aplica el bump de versión en los 3 archivos, actualiza el CHANGELOG y abre el PR de release. Tras el merge, etiqueta. Acepta un argumento opcional con el tipo de bump (patch|minor|major) o una versión explícita (X.Y.Z).
---

# Release semanal — TodoConta Desktop

Automatiza el corte de release de la semana. Modelo: durante la semana los branches **no**
bumpean versión (sus notas van a `## [Unreleased]` del CHANGELOG); este skill consolida todo
en un solo release. Convención completa en [docs/infra/versionado.md](../../../docs/infra/versionado.md).

El argumento del skill (`$ARGUMENTS`) es opcional:
- vacío → propones el bump y lo confirmas con el usuario.
- `patch` | `minor` | `major` → usa ese tipo de bump.
- `X.Y.Z` (ej. `1.0.7`) → usa esa versión exacta.

Sigue estos pasos en orden. Si algo falla una precondición, **detente y avisa** (no fuerces).

## 0. Precondiciones

1. Sitúate en `main` actualizado: `git checkout main && git pull --ff-only`.
2. Working tree limpio: `git status --porcelain` debe estar vacío. Si no, detente y avisa.
3. Fecha del release: `date +%F` (formato `YYYY-MM-DD`).

## 1. Reunir insumos

1. Último tag (versión actual):
   `LAST=$(git tag | sort -V | tail -1)` — ej. `v1.0.6`. La versión base es `${LAST#v}`.
2. Commits desde el último tag (lo que entra en este release):
   - `git log "$LAST"..main --no-merges --pretty=format:'- %s%n%b'`
   - `git log "$LAST"..main --merges --pretty=format:'- %s'` (títulos de PRs mergeados).
3. Lee la sección `## [Unreleased]` de `CHANGELOG.md` (notas curadas durante la semana).
4. Si **no hay commits nuevos** desde `$LAST` **y** `[Unreleased]` no tiene notas reales →
   no hay nada que releasear. Avisa y detente.

## 2. Decidir la versión

1. Relee la tabla de decisión de [docs/infra/versionado.md](../../../docs/infra/versionado.md):
   - **PATCH** — solo fixes, copy, performance, refactor invisible.
   - **MINOR** — al menos una feature nueva visible (pantalla, trámite, capacidad).
   - **MAJOR** — rompe datos del usuario (`~/.sat-descarga/`), cambia `appId`, etc.
2. Calcula la versión objetivo `X.Y.Z` a partir de `${LAST#v}` y el bump:
   - Si `$ARGUMENTS` es `X.Y.Z` → úsala tal cual.
   - Si es `patch|minor|major` → aplica ese bump.
   - Si está vacío → **propón** el bump según los commits/`[Unreleased]` y **confírmalo con
     AskUserQuestion** (pon la opción sugerida primero), mostrando la versión resultante.

## 3. Bump de versión en los 3 archivos (SIEMPRE sincronizados)

Pon el **mismo** `X.Y.Z` en los tres, aunque vengan desincronizados (p. ej. `pyproject.toml`
arrastra `1.0.4`): este release los re-sincroniza.

- `pyproject.toml` → la línea `version = "X.Y.Z"` (hay una sola, en `[project]`).
- `ui/package.json` → `"version": "X.Y.Z"`.
- `desktop/package.json` → `"version": "X.Y.Z"`.

Tras el bump de `pyproject.toml`, corre `uv lock` y **commitea también `uv.lock`**:
registra la versión del propio paquete (`[[package]] name = "sat-descarga-masiva"`) y
si no se regenera queda desincronizado (se nos escapó en v1.1.0).

## 4. CHANGELOG

1. Construye las notas del release tomando como base lo que ya está en `## [Unreleased]`
   (primario, curado) y **complementa** revisando los commits del paso 1 para no perder nada.
2. Renombra `## [Unreleased]` → `## [X.Y.Z] - <fecha>` con esas notas. Estilo igual a las
   entradas previas: español, agrupado en `### Bug fix` / `### Feature` / `### Copy` /
   `### Tooling` según aplique, con la línea final `- Bump <anterior> → X.Y.Z (3 archivos).`
3. Inserta un `## [Unreleased]` **nuevo y vacío** arriba, con el placeholder estándar:
   `_Cambios mergeados a `main` aún no etiquetados; el release de la semana los promueve._`

## 5. Branch + commit + PR

1. `git checkout -b release/vX.Y.Z` (verifica con `git branch --show-current`).
2. `git add pyproject.toml uv.lock ui/package.json desktop/package.json CHANGELOG.md`
3. Commit: título `release: vX.Y.Z` + cuerpo con el resumen de la semana.
   Cierra el mensaje con el trailer `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
4. `git push -u origin release/vX.Y.Z`.
5. `gh pr create --base main` con:
   - título `release: vX.Y.Z`
   - body = las notas del CHANGELOG de esta versión + una sección "Commits incluidos"
     (`git log "$LAST"..main --oneline`).

Reporta el link del PR. **No mergees tú** — el humano revisa y mergea.

## 6. Tras el merge — etiquetar

Cuando el usuario confirme que el PR de release está mergeado:

1. `git checkout main && git pull --ff-only`.
2. Verifica que `desktop/package.json` ya tenga `X.Y.Z` en `main`.
3. `git tag vX.Y.Z && git push origin vX.Y.Z`.

El tag dispara el build del instalador (workflow `release.yml` cuando exista) que sube un
**draft release**; el humano lo publica. El link público de descarga
(`todoconta.com/descargar`) resuelve solo al nuevo `latest` — no hay que tocar nada más.

## 7. Mismo día: una versión en todos lados

Todo lo que lleva versión va en `X.Y.Z` el mismo día (regla 4 de
[docs/infra/despliegue-vps.md](../../../docs/infra/despliegue-vps.md)). Con el tag
ya empujado y el build del CI terminado (deja el release en **borrador**):

1. **QA del borrador** si el release trae cambios de riesgo (migraciones que
   reescriben datos del usuario, algo que firme o envíe al SAT). Pregúntale al
   usuario y no publiques sin su visto bueno: publicar manda la versión por
   auto-update a todos.
2. **Publicar:** `gh release edit vX.Y.Z --draft=false --latest`. Si quedó un
   borrador viejo que esta versión reemplaza, díselo al usuario.
3. `deploy/desplegar.sh ui vX.Y.Z`: la UI web desde el tag.
4. `deploy/desplegar.sh agente vX.Y.Z`: la imagen del agente desde el tag, los
   contenedores de los usuarios web y el piloto. Recrear corta unos segundos a
   cada usuario web, así que mejor en horas valle.
5. Si el release trae cambios en `deploy/` (gateway, provisioner, ops), despliega
   cada servicio tocado con `deploy/desplegar.sh <servicio>`.
6. `deploy/desfase.sh` debe salir en verde: release publicado, UI web, agentes
   y piloto en `X.Y.Z`. Reporta su salida al usuario.

Publicar, desplegar la UI y escribir en el VPS son acciones de producción: si
la sesión no tiene permiso, dale los comandos al usuario para que los corra
con `!`.

## Recordatorios

- Nunca commitees directo en `main` (rama → PR → merge). Corre `git branch --show-current`
  antes de cada commit.
- Los **3** archivos de versión van siempre al mismo número.
- Si el usuario solo quiere preparar el PR (no etiquetar aún), haz hasta el paso 5 y deja el
  paso 6 para cuando confirme el merge.

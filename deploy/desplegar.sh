#!/usr/bin/env bash
# Único camino para desplegar al VPS. Ver docs/infra/despliegue-vps.md.
#
# Uso (desde tu máquina, en cualquier rama del repo):
#   deploy/desplegar.sh <servicio> [ref]
#
#   servicio  gateway | provisioner | ops | sendy | agente | ui
#   ref       lo que se despliega. Default: origin/main. Para `agente` y `ui`,
#             el tag del release de desktop (vX.Y.Z): una sola versión en
#             todos lados (desktop, UI web, agentes web y piloto).
#
# Lo que hace, en orden:
#   1. Se niega si `ref` no está en origin/main (nada sin mergear llega al VPS).
#   2. Manda el contenido de git (git archive), nunca el working tree.
#   3. Respalda en /docker/backups/ los archivos que va a pisar y etiqueta la
#      imagen actual como :pre-<fecha> para regresar en segundos.
#   4. Construye, levanta y deja /docker/<servicio>/.deployed con el commit.
#   5. Prueba lo que usan los clientes (no solo el healthcheck) y revisa que
#      OpenClaw siga vivo. Si algo falla, imprime cómo regresar.
#
# El .env de cada servicio no está en git y no se toca.
set -euo pipefail

VPS="${VPS:-root@187.77.152.160}"
DOMINIO="${DOMINIO:-agente.todoconta.com}"
SERVICIO="${1:-}"
REF="${2:-origin/main}"
# --probar: no despliega nada; solo corre las pruebas (solo lectura) contra lo
# que corre hoy. Sirve para validar el script y para revisar un servicio.
SOLO_PROBAR=0
[ "$REF" = --probar ] && { SOLO_PROBAR=1; REF=origin/main; }

case "$SERVICIO" in
  gateway|provisioner|ops|sendy|agente|ui) ;;
  *) echo "uso: deploy/desplegar.sh <gateway|provisioner|ops|sendy|agente|ui> [ref|--probar]" >&2; exit 2 ;;
esac

cd "$(git rev-parse --show-toplevel)"
git fetch -q origin --tags
SHA=$(git rev-parse --verify "${REF}^{commit}")
CORTO=$(git rev-parse --short "$SHA")
if ! git merge-base --is-ancestor "$SHA" origin/main; then
  echo "✗ $REF ($CORTO) no está en origin/main. Mergea el PR primero." >&2
  exit 1
fi
TS=$(date -u +%Y%m%d-%H%M%S)
POR=$(git config user.email 2>/dev/null || whoami)
VERSION=$(git show "$SHA:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)
MARCA="version=$VERSION sha=$SHA ref=$REF fecha=$TS por=$POR"
echo "→ $SERVICIO desde $REF ($CORTO: $(git log -1 --format=%s "$SHA"))"

falla() {
  echo "✗ $1" >&2
  [ "$SOLO_PROBAR" = 1 ] && exit 1   # nada que regresar: no se desplegó nada
  if [ "$SERVICIO" = ui ]; then
    echo "  Si ya se publicó: en Vercel (todoconta-app-web), promueve el despliegue" >&2
    echo "  anterior a producción, o corre: vercel rollback" >&2
  elif [ "$SERVICIO" = agente ]; then
    echo "  Para regresar: en el VPS, docker tag todoconta/agente:pre-$TS todoconta/agente:dev," >&2
    echo "  corre de nuevo deploy/vps/actualizar-agentes.sh y, en /docker/agentes," >&2
    echo "  docker compose -f docker-compose.piloto.yml up -d." >&2
  else
    echo "  Para regresar: en el VPS, /docker/backups/$SERVICIO-$TS.tgz tiene los archivos" >&2
    echo "  anteriores (tar -xzf en /docker/$SERVICIO) y las imágenes previas quedaron" >&2
    echo "  como <imagen>:pre-$TS. Luego: docker tag <imagen>:pre-$TS <imagen>:latest" >&2
    echo "  && docker compose up -d (sin --build)." >&2
  fi
  exit 1
}

openclaw_vivo() {
  # OpenClaw (WhatsApp) corre FUERA de Docker, como servicio systemd del host,
  # y escucha en 127.0.0.1:18789. Ningún despliegue debe tumbarlo.
  ssh "$VPS" 'pgrep -f openclaw >/dev/null && ss -tlnp | grep -q ":18789 "' \
    || falla "OpenClaw no responde (pgrep o puerto 18789). Revisa el host."
  echo "  ✓ OpenClaw vivo"
}

# ── Servicios con docker compose ─────────────────────────────────────────────
# El script remoto viaja codificado en el argumento de ssh porque la entrada
# estándar ya la ocupa el tar de git archive.
IFS= read -r -d '' REMOTO_COMPOSE <<'REMOTO' || true
set -euo pipefail
tmp=$(mktemp -d)
tar -x -C "$tmp" -f -
src="$tmp/deploy/$SERVICIO"
mkdir -p "$DIR" /docker/backups
cd "$DIR"

# Respaldo solo de lo que se va a pisar (el .env y los datos no se tocan).
# La lista sale de lo que trae git, pero la existencia se revisa en $DIR: un
# archivo nuevo (que aún no está en el VPS) no tiene nada que respaldar.
existentes=$( (cd "$src" && find . -type f | sed 's|^\./||') | while read -r f; do [ -f "$DIR/$f" ] && echo "$f"; done || true)
[ -n "$existentes" ] && tar -czf "/docker/backups/$SERVICIO-$TS.tgz" $existentes
[ -f .deployed ] && cp .deployed "/docker/backups/$SERVICIO-$TS.deployed"

# Etiqueta las imágenes que construye este compose (las que traen tag, como
# mariadb:11, vienen de un registry y no cambian con el build).
for img in $(docker compose config --images 2>/dev/null); do
  case "$img" in *:*) continue ;; esac
  docker image inspect "$img" >/dev/null 2>&1 && docker tag "$img" "$img:pre-$TS"
done

cp -R "$src/." "$DIR/"
rm -rf "$tmp"

log="/docker/backups/$SERVICIO-$TS.build.log"
if ! docker compose build >"$log" 2>&1; then
  tail -30 "$log"
  echo "✗ el build falló; no se levantó nada nuevo (log: $log)"
  exit 1
fi
docker compose up -d 2>&1 | tail -3
echo "$MARCA" > .deployed
REMOTO

desplegar_compose() {
  local b64
  b64=$(printf '%s' "$REMOTO_COMPOSE" | base64 | tr -d '\n')
  git archive "$SHA" "deploy/$SERVICIO" | ssh "$VPS" \
    "echo $b64 | base64 -d > /tmp/desplegar-$TS.sh && SERVICIO=$SERVICIO TS=$TS DIR=/docker/$SERVICIO MARCA='$MARCA' bash /tmp/desplegar-$TS.sh; r=\$?; rm -f /tmp/desplegar-$TS.sh; exit \$r" \
    || falla "falló el despliegue en el VPS (ver arriba)"
}

esperar_sano() {
  local contenedor="$1" estado=""
  for _ in $(seq 1 24); do
    estado=$(ssh "$VPS" "docker inspect -f '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}sin-healthcheck{{end}}' $contenedor" 2>/dev/null || true)
    case "$estado" in running/healthy|running/sin-healthcheck) echo "  ✓ $contenedor $estado"; return 0 ;; esac
    sleep 5
  done
  falla "$contenedor no quedó sano (estado: ${estado:-desconocido})"
}

codigo() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

probar() {
  case "$SERVICIO" in
    gateway)
      esperar_sano gateway
      [ "$(codigo "https://$DOMINIO/v1/health")" = 200 ] || falla "/v1/health no responde 200"
      # /mcp debe existir: 401 sin token. Un 404 es el gateway arrancado sin SDK.
      local mcp
      mcp=$(codigo -X POST "https://$DOMINIO/mcp" -H 'content-type: application/json' -d '{}')
      [ "$mcp" != 404 ] || falla "/mcp responde 404: el gateway arrancó sin MCP"
      echo "  ✓ /v1/health 200 · /mcp $mcp"
      ;;
    provisioner)
      esperar_sano provisioner
      curl -s "https://$DOMINIO/provision/health" | grep -q '"ok"' || falla "/provision/health no responde ok"
      echo "  ✓ /provision/health ok"
      ;;
    ops)
      esperar_sano ops
      sleep 3
      # Todo el log del contenedor: tras un despliegue es un contenedor nuevo, así
      # que la línea es de este arranque; en --probar, del arranque vigente.
      ssh "$VPS" 'docker logs ops 2>&1 | grep -q "read crontab"' || falla "supercronic no cargó el crontab"
      echo "  ✓ supercronic cargó el crontab"
      ;;
    sendy)
      esperar_sano sendy
      esperar_sano sendy-cron
      ;;
  esac
}

# ── Agente por usuario (versión web) ─────────────────────────────────────────
avisar_si_no_es_tag() {
  if ! git describe --exact-match --tags "$SHA" >/dev/null 2>&1; then
    echo "  ⚠ $REF no es un tag de release. La regla es desplegar $SERVICIO con el"
    echo "    mismo tag que desktop (vX.Y.Z). Sigo porque lo pediste explícito."
  fi
}

version_del_ultimo_tag() {
  local tag
  tag=$(git tag --merged origin/main | sort -V | tail -1)
  git show "$tag:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1
}

desplegar_agente() {
  local version="$VERSION"
  avisar_si_no_es_tag
  echo "  imagen: todoconta/agente:$version (+ :dev)"
  ssh "$VPS" "docker image inspect todoconta/agente:dev >/dev/null 2>&1 && docker tag todoconta/agente:dev todoconta/agente:pre-$TS || true"
  # El build no toca a nadie: los agentes siguen con la imagen vieja hasta el
  # paso siguiente. Si falla, se detiene aquí.
  git archive --format=tar "$SHA" | ssh "$VPS" \
    "docker build -q -f docker/agente/Dockerfile -t todoconta/agente:$version -t todoconta/agente:dev -" \
    || falla "falló el build de la imagen del agente; ningún contenedor se tocó"
  # Recrea cada agente-<slug> con la imagen nueva (conserva volumen y claves).
  # Cada usuario web pierde unos segundos de servicio: mejor en horas valle.
  git show "$SHA:deploy/vps/actualizar-agentes.sh" | ssh "$VPS" 'bash -s' \
    || falla "actualizar-agentes.sh terminó con error; revisa los contenedores"
  # El piloto (fase 1 de la versión web, /u/piloto) tiene compose propio y
  # también va a la misma versión: la imagen :dev ya es la nueva, así que
  # `up -d` lo recrea.
  git show "$SHA:deploy/vps/docker-compose.piloto.yml" | ssh "$VPS" "set -e
    cd /docker/agentes
    [ -f docker-compose.piloto.yml ] && cp docker-compose.piloto.yml /docker/backups/piloto-$TS.yml
    cat > docker-compose.piloto.yml
    docker compose -f docker-compose.piloto.yml up -d 2>&1 | tail -2" \
    || falla "no se pudo actualizar agente-piloto"
  ssh "$VPS" "mkdir -p /docker/agentes && echo '$MARCA' > /docker/agentes/.deployed"

  echo "  esperando a que los agentes queden sanos (60s)…"
  sleep 60
  probar_agente "$version"
}

probar_agente() {
  local esperada="$1" resumen sanos total uno corre
  resumen=$(ssh "$VPS" 'docker ps --filter label=todoconta.agente=1 --format "{{.Status}}" | grep -c healthy; docker ps --filter label=todoconta.agente=1 -q | wc -l')
  sanos=$(echo "$resumen" | sed -n 1p); total=$(echo "$resumen" | sed -n 2p | tr -d ' ')
  [ "$sanos" = "$total" ] || falla "solo $sanos de $total agentes están healthy"
  uno=$(ssh "$VPS" 'docker ps --filter label=todoconta.agente=1 --format "{{.Names}}" | head -1')
  corre=$(ssh "$VPS" "docker exec $uno python -c \"from importlib.metadata import version; print(version('sat-descarga-masiva'))\"")
  [ "$corre" = "$esperada" ] || falla "$uno corre v$corre, se esperaba v$esperada"
  echo "  ✓ $sanos/$total agentes healthy en v$esperada"
  if ssh "$VPS" 'docker inspect agente-piloto >/dev/null 2>&1'; then
    corre=$(ssh "$VPS" "docker exec agente-piloto python -c \"from importlib.metadata import version; print(version('sat-descarga-masiva'))\"")
    [ "$corre" = "$esperada" ] || falla "agente-piloto corre v$corre, se esperaba v$esperada"
    echo "  ✓ agente-piloto en v$esperada"
  fi
}

# ── UI web (app.todoconta.com en Vercel) ─────────────────────────────────────
# La UI de la versión web se construye desde el mismo tag que desktop. El
# proyecto de Vercel se toma del link local ui/.vercel/project.json (gitignored).
desplegar_ui() {
  avisar_si_no_es_tag
  local proyecto="ui/.vercel/project.json" tmp
  [ -f "$proyecto" ] || falla "falta $proyecto. Una vez: cd ui && vercel link --project todoconta-app-web"
  tmp=$(mktemp -d)
  git archive "$SHA" ui | tar -x -C "$tmp"
  mkdir -p "$tmp/ui/.vercel" && cp "$proyecto" "$tmp/ui/.vercel/"
  if ! (cd "$tmp/ui" && vercel deploy --prod --yes); then
    rm -rf "$tmp"
    falla "vercel deploy falló; producción sigue en el despliegue anterior"
  fi
  rm -rf "$tmp"
  probar_ui "$VERSION"
}

# La versión viaja dentro del bundle (NEXT_PUBLIC_APP_VERSION, ui/next.config.ts).
probar_ui() {
  local esperada="$1" c
  for c in $(curl -s "https://app.todoconta.com/ajustes" | grep -o '/_next/static/chunks/[^"]*\.js' | sort -u); do
    if curl -s "https://app.todoconta.com$c" | grep -q "\"$esperada\""; then
      echo "  ✓ app.todoconta.com sirve v$esperada"
      return 0
    fi
  done
  falla "app.todoconta.com no sirve v$esperada"
}

if [ "$SOLO_PROBAR" = 1 ]; then
  case "$SERVICIO" in
    agente) probar_agente "$(version_del_ultimo_tag)" ;;
    ui) probar_ui "$(version_del_ultimo_tag)" ;;
    *) probar ;;
  esac
  [ "$SERVICIO" = ui ] || openclaw_vivo
  echo "✓ pruebas de $SERVICIO en verde (no se desplegó nada)"
  exit 0
fi

if [ "$SERVICIO" = ui ]; then
  desplegar_ui
  echo "✓ ui desplegada (v$VERSION, $CORTO). Revisa el desfase con deploy/desfase.sh"
  exit 0
elif [ "$SERVICIO" = agente ]; then
  desplegar_agente
else
  desplegar_compose
  probar
fi
openclaw_vivo
echo "✓ $SERVICIO desplegado ($CORTO). Revisa el desfase con deploy/desfase.sh"

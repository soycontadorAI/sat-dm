#!/usr/bin/env bash
# ¿Lo que corre en el VPS es lo que dice git? Solo lee: se puede correr cuando
# sea (y se corre en cada release). Ver docs/infra/despliegue-vps.md.
#
# Uso: deploy/desfase.sh [ref]      # default: origin/main
#
# Por servicio compara, archivo por archivo, lo trackeado en deploy/<servicio>/
# contra /docker/<servicio>/ y muestra el .deployed (qué commit se subió y
# cuándo). Luego revisa que todo lo que lleva versión (release publicado,
# UI web, agentes web y piloto) esté en la del último tag de release.
#
# Sale con 1 si hay desfase funcional. Un README o .gitignore distinto se
# reporta, pero no cuenta como desfase.
set -o pipefail   # sin -u: el bash 3.2 de macOS truena con arreglos vacíos

VPS="${VPS:-root@187.77.152.160}"
REF="${1:-origin/main}"

cd "$(git rev-parse --show-toplevel)"
git fetch -q origin --tags
SHA=$(git rev-parse --verify "${REF}^{commit}")
echo "Referencia: $REF ($(git rev-parse --short "$SHA"))"
echo

md5_de() { if command -v md5sum >/dev/null; then md5sum | cut -d' ' -f1; else md5 -q; fi; }
es_doc() { case "$1" in *.md|.gitignore) return 0 ;; *) return 1 ;; esac; }

desfase=0
for s in gateway provisioner ops sendy; do
  lista=$(git ls-tree -r --name-only "$SHA" "deploy/$s" | sed "s|^deploy/$s/||")
  vps=$(printf '%s\n' "$lista" | ssh "$VPS" "cd /docker/$s 2>/dev/null || exit 0
    while read -r f; do
      if [ -f \"\$f\" ]; then echo \"\$(md5sum < \"\$f\" | cut -d' ' -f1) \$f\"; else echo \"FALTA \$f\"; fi
    done")
  iguales=0; distintos=(); faltan=(); docs=()
  for f in $lista; do
    esperado=$(git show "$SHA:deploy/$s/$f" | md5_de)
    real=$(printf '%s\n' "$vps" | awk -v f="$f" '$2==f {print $1}')
    if [ "$real" = "$esperado" ]; then
      iguales=$((iguales + 1))
    elif es_doc "$f"; then
      docs+=("$f")
    elif [ "$real" = FALTA ] || [ -z "$real" ]; then
      faltan+=("$f")
    else
      distintos+=("$f")
    fi
  done
  marca=$(ssh "$VPS" "cat /docker/$s/.deployed 2>/dev/null" || true)
  if [ ${#distintos[@]} -eq 0 ] && [ ${#faltan[@]} -eq 0 ]; then
    echo "✅ $s: $iguales archivos iguales"
  else
    desfase=1
    echo "❌ $s: $iguales iguales · ${#distintos[@]} distintos · ${#faltan[@]} faltan en el VPS"
    for f in "${distintos[@]}"; do echo "     distinto: $f"; done
    for f in "${faltan[@]}"; do echo "     falta:    $f"; done
  fi
  [ ${#docs[@]} -gt 0 ] && echo "     (solo docs, no cuenta: ${docs[*]})"
  echo "     desplegado: ${marca:-sin .deployed (desplegado a mano, antes de desplegar.sh)}"
done

echo
# ── Una versión en todos lados ───────────────────────────────────────────────
# Todo lo que lleva versión debe ir en la del último tag de release: el release
# publicado (lo que baja desktop y su auto-update), la UI web, los agentes web
# y el piloto.
ultimo_tag=$(git tag --merged origin/main | sort -V | tail -1)
esperada=$(git show "$ultimo_tag:pyproject.toml" | sed -n 's/^version = "\(.*\)"/\1/p' | head -1)
echo "Versión: último tag $ultimo_tag (v$esperada)"

ok() { echo "✅ $1"; }
mal() { desfase=1; echo "❌ $1"; }

if command -v gh >/dev/null; then
  publicado=$(gh release view --json tagName --jq .tagName 2>/dev/null || echo "?")
  [ "$publicado" = "$ultimo_tag" ] && ok "release publicado (desktop, auto-update): $publicado" \
    || mal "release publicado (desktop, auto-update): $publicado, se esperaba $ultimo_tag"
  borradores=$(gh release list --limit 20 --json tagName,isDraft --jq '[.[]|select(.isDraft)|.tagName]|join(", ")' 2>/dev/null)
  [ -n "$borradores" ] && echo "     borradores sin publicar: $borradores"
else
  echo "ℹ️  sin gh: no se revisa el release publicado"
fi

ui_ok=0
for c in $(curl -s "https://app.todoconta.com/ajustes" | grep -o '/_next/static/chunks/[^"]*\.js' | sort -u); do
  curl -s "https://app.todoconta.com$c" | grep -q "\"$esperada\"" && { ui_ok=1; break; }
done
[ "$ui_ok" = 1 ] && ok "UI web (app.todoconta.com): v$esperada" || mal "UI web (app.todoconta.com): no sirve v$esperada"

versiones=$(ssh "$VPS" 'for c in $(docker ps --filter label=todoconta.agente=1 --format "{{.Names}}"); do
    docker exec "$c" python -c "from importlib.metadata import version; print(version(\"sat-descarga-masiva\"))" 2>/dev/null || echo "?"
  done | sort | uniq -c')
total=$(printf '%s\n' "$versiones" | awk '{n+=$1} END {print n+0}')
en_version=$(printf '%s\n' "$versiones" | awk -v v="$esperada" '$2==v {print $1}')
if [ "${en_version:-0}" = "$total" ] && [ "$total" -gt 0 ]; then
  ok "agentes web: $total en v$esperada"
else
  mal "agentes web: se esperaba v$esperada y corren:"
  printf '%s\n' "$versiones" | sed 's/^/     /'
fi
echo "     desplegado: $(ssh "$VPS" 'cat /docker/agentes/.deployed 2>/dev/null' || true)"

piloto=$(ssh "$VPS" 'docker exec agente-piloto python -c "from importlib.metadata import version; print(version(\"sat-descarga-masiva\"))" 2>/dev/null' || true)
if [ -n "$piloto" ]; then
  [ "$piloto" = "$esperada" ] && ok "agente-piloto: v$piloto" || mal "agente-piloto: v$piloto, se esperaba v$esperada"
fi

exit $desfase

# Runbook del VPS — versión online

VPS Hostinger (`root@187.77.152.160`, Ubuntu 24.04, Docker + Traefik). Arquitectura
completa: [docs/infra/despliegue-web.md](../../docs/infra/despliegue-web.md).

## ⚠️ Reglas del host (SIEMPRE)

En este VPS también vive **OpenClaw (agente de WhatsApp), FUERA de Docker**
(proceso node, loopback 18789/18791) y **Traefik** (compose en `/docker/traefik/`,
`network_mode: host`, resolver `letsencrypt`).

1. Cambios **solo aditivos**: contenedores/redes/volúmenes nuevos. Nada bajo
   `/root/`, ni procesos node, ni `/docker/traefik/` (salvo con respaldo previo).
2. **Reboot: es seguro** (verificado 2026-07-13). OpenClaw corre como servicio
   **systemd de usuario** (`openclaw-gateway.service`, `enabled`) con **linger
   activado** para root (`loginctl show-user root` → `Linger=yes`), así que
   systemd lo relanza tras un reboot aunque no haya sesión abierta. Los
   contenedores tienen `restart: unless-stopped`. Aun así: reboot solo si hace
   falta, y verifica el checklist post-reboot (abajo).
3. Tras cada cambio: `pgrep -f openclaw` y `ss -tlnp | grep 1878` deben responder.
4. RAM disponible ≈ 6 GB para agentes (uso real del stack ≈ 1.6 GB con OpenClaw;
   cada agente idle ≈ 55 MB) — vigilar `docker stats`.

Coexistencia: OpenClaw ("Abacus") tiene su **propio** backup con `restic`
(`abacus-backup.timer`, 03:30 UTC, a `/var/backups/abacus`; password en
`/root/.config/restic/password` + 1Password). NO tocar; es independiente del
backup de TodoConta (abajo). Otros crons del host: `docker-image-prune` (diario,
limpia imágenes viejas), `69b-update` (mensual).

## Piezas

| Pieza | Dónde | Qué es |
|---|---|---|
| Imagen del agente | `todoconta/agente:<tag>` | `docker/agente/Dockerfile` (repo) |
| Agente piloto (F1) | `/docker/agentes/` | `deploy/vps/docker-compose.piloto.yml` |
| Provisioner (F2) | `/docker/provisioner/` | `deploy/provisioner/` |
| Agentes por usuario | contenedores `agente-<slug>` | los crea el provisioner |

## Setup inicial (una vez)

```bash
# 1. DNS (Cloudflare): A record agente.todoconta.com → 187.77.152.160
#    ⚠️ DNS-only (nube GRIS): el proxy naranja corta el SSE de jobs largos.

# 2. Construir la imagen del agente (desde la máquina de dev):
git archive --format=tar <branch> | ssh root@187.77.152.160 \
  'docker build -f docker/agente/Dockerfile -t todoconta/agente:dev -'

# 3. Red compartida (si no existe):
docker network ls | grep agentes || docker network create agentes

# 4. Provisioner:
mkdir -p /docker/provisioner   # copiar deploy/provisioner/* aquí
cd /docker/provisioner
cat > .env <<EOF
SAT_DM_MASTER_KEY=$(python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")
AGENTE_IMAGEN=todoconta/agente:dev
# ALLOWLIST_EMAILS=correo1@x.mx,correo2@x.mx   # beta cerrada
# EXIGIR_LICENCIA=0                            # kill switch (beta)
# CORS_ORIGINS=https://app.todoconta.com,https://<preview>.vercel.app
EOF
chmod 600 .env
docker compose up -d --build
curl -s https://agente.todoconta.com/provision/health
```

## La master key (`SAT_DM_MASTER_KEY`)

De ella se derivan (HMAC por `user_id`): el slug del contenedor, el token del
agente y la clave AES de `secretos.enc` de cada usuario.

- **Respáldala** (password manager). Si se pierde el `.env`, con el respaldo
  todo se recupera.
- **NO la rotes** salvo compromiso: rotarla invalida los secretos de TODOS los
  usuarios (recapturarían contraseñas FIEL/CIEC). No hay re-cifrado automático.

## Actualizar la imagen de los agentes

Con el **mismo tag del release de desktop**, el mismo día (reglas en
[docs/infra/despliegue-vps.md](../../docs/infra/despliegue-vps.md)):

```bash
deploy/desplegar.sh agente vX.Y.Z   # build + actualizar-agentes.sh + verificación
deploy/desfase.sh                    # confirma que web == último release
```

El script construye `todoconta/agente:X.Y.Z` (y `:dev`), recrea cada
`agente-<slug>` con `actualizar-agentes.sh` y verifica que todos queden
healthy en esa versión. El provisioner solo crea contenedores nuevos: los que
ya existen siguen con la imagen vieja hasta que se recrean.

Los volúmenes (`agente-datos-*`) y las claves derivadas no cambian, así que las
credenciales guardadas siguen legibles tras recrear el contenedor.

## Backups (ACTIVOS desde 2026-07-13)

Cron diario (`/etc/cron.d/todoconta-backups`, 09:00 UTC) ejecuta
`/docker/backups/respaldar-agentes.sh`: tar cifrado (AES-256, passphrase en
`/docker/backups/.backup-pass`) de los volúmenes `agente-datos-*` (FIELs,
descargas, secretos.enc), el registro del provisioner y los `.env` (master key
incluida) → `/backups/agentes-<fecha>.tar.gz.enc`. Retención 7 días; log y
alerta de disco ≥80 % en `/docker/backups/backups.log`.

- ⚠️ Respaldar **fuera del VPS** la passphrase (`.backup-pass`) y la master key
  (password manager): los backups viven en el mismo disco — cubren errores
  operativos, no la pérdida del disco.
- **Backup manual** (uno extra ahora): `/docker/backups/respaldar-agentes.sh`
- **Copia off-site** (recomendado periódico, desde tu máquina):
  `scp root@187.77.152.160:/backups/agentes-$(date +%F).tar.gz.enc ~/backups-todoconta/`
- **Restaurar**: `openssl enc -d -aes-256-cbc -pbkdf2 -pass file:/docker/backups/.backup-pass < /backups/agentes-<fecha>.tar.gz.enc | tar xzf - -C /`
  (recrea los volúmenes en su sitio; luego `actualizar-agentes.sh` o recrear
  provisioner/gateway para que los monten).

## Mantenimiento — checklist operativo

### Salud rápida (cuando quieras)
```bash
ssh root@187.77.152.160 'free -h; df -h /; docker ps --format "{{.Names}}\t{{.Status}}"; docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}"'
```
Baseline sano (2026-07-13): RAM usada ≈ 1.6/7.8 GB, disco 38 %, carga < 0.1,
cada agente ≈ 55 MB. Si un agente crece mucho es un job CIEC (Chromium) en curso.

### Post-reboot (si alguna vez hay que reiniciar)
```bash
pgrep -f openclaw >/dev/null && echo "openclaw OK"     # systemd user lo relanza (linger=yes)
ss -tlnp | grep -E '1878|:443'                          # openclaw + traefik escuchando
docker ps                                                # provisioner, gateway, agentes arriba
curl -s https://agente.todoconta.com/provision/health    # provisioner responde
```
Si OpenClaw NO volvió: `systemctl --user start openclaw-gateway.service` (como root
con `XDG_RUNTIME_DIR=/run/user/0`), y revisar `loginctl show-user root | grep Linger`.

### Actualizar la imagen de los agentes (tras un release)
Ver sección "Actualizar la imagen de los agentes" arriba (rebuild + `actualizar-agentes.sh`).
El provisioner y el gateway comparten la `AGENTE_IMAGEN`; los agentes ya creados se
recrean con el script (conserva volúmenes y claves derivadas).

### Actualizaciones del SO
`apt update && apt upgrade -y` cada tanto. Evita el `apt full-upgrade`/kernel si no
quieres reboot; si actualizas kernel, reboot es seguro (ver regla 2) pero valida el
checklist post-reboot.

### Limpieza de disco
`docker-image-prune` ya corre diario. Si el disco sube (los ZIP de descargas se
acumulan en los volúmenes): `docker system df` y revisar `/var/lib/docker/volumes/agente-datos-*`.

## Servicios en el VPS (mapa)

| Servicio | Tipo | Puerto/ruta | Notas |
|---|---|---|---|
| Traefik | Docker (host net) | :80/:443 | reverse proxy + Let's Encrypt de TODO |
| OpenClaw | systemd **user** | loopback 18789/18791 | bot WhatsApp; backup restic propio; no tocar |
| provisioner | Docker | `agente.todoconta.com/provision` | login web → enciende agentes |
| gateway | Docker | `agente.todoconta.com/{v1,mcp}` | API pública + MCP |
| agente-`<slug>` | Docker | `agente.todoconta.com/u/<slug>` | uno por usuario |
| (futuro) Sendy | Docker | `sendy.todoconta.com` | ver deploy/sendy/ cuando exista |

## Troubleshooting

- **502 en /u/{slug}**: `docker ps` — ¿el contenedor corre? `docker logs agente-<slug>`.
- **Cert no emitido**: el A record debe existir y estar en DNS-only; revisar
  logs de Traefik (`docker logs traefik-traefik-1 | grep -i acme`).
- **"Tu espacio está arrancando"** persistente: primer arranque descargando algo
  o contenedor en crash-loop → `docker logs agente-<slug>`.
- **SSE se corta en jobs largos**: revisar `respondingTimeouts` del entrypoint
  websecure de Traefik (editar su compose CON RESPALDO y `docker compose up -d`).
- **secretos.enc ilegible** ("¿cambió SAT_DM_SECRETS_KEY?"): la master key no
  corresponde — ¿se restauró un .env viejo?

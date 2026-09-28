# Agente en Docker (modo hosted)

Imagen del agente Python para la **versión online**: en el VPS corre un
contenedor de esta imagen POR USUARIO, detrás de Traefik. La arquitectura (provisioner,
Traefik, modo hosted) está en
[docs/producto/especificaciones.md](../../docs/producto/especificaciones.md) y cómo se
despliega en [docs/infra/despliegue-vps.md](../../docs/infra/despliegue-vps.md).

## Build

```bash
# Desde la raíz del repo
docker build -f docker/agente/Dockerfile -t todoconta/agente:dev .
```

## Correr local (QA de F0)

```bash
# Clave de secretos de prueba (32 bytes en base64)
export SECRETS_KEY=$(python3 -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())")

docker run --rm -p 8787:8787 \
  -e SAT_DM_SECRETS_KEY="$SECRETS_KEY" \
  -e SAT_AGENT_TOKEN=token-de-prueba \
  -e SAT_DM_CORS_ORIGINS=http://localhost:3001 \
  -v agente-datos-dev:/data \
  todoconta/agente:dev
```

- `SAT_DM_MODO=hosted` ya viene en la imagen; para simular el modo desktop
  dentro del contenedor, pásalo vacío (`-e SAT_DM_MODO=`).
- La UI en dev se conecta con `NEXT_PUBLIC_SAT_API_URL=http://localhost:8787`
  (y el token en la página /conectar cuando exista el modo web).

## Qué cambia respecto al agente desktop

| | Desktop | Hosted (esta imagen) |
|---|---|---|
| Secretos | Keychain del SO | `secretos.enc` (AES-256-GCM) en /data |
| Descargas | Carpeta elegida por el usuario | `/data/descargas` (env) |
| `/abrir` | Abre en el SO | 501 → la UI usa `/descargas/*` |
| CORS | `*` (solo loopback) | `SAT_DM_CORS_ORIGINS` |
| Chromium | Descarga on-demand | Horneado en `/ms-playwright` |

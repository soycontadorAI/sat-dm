# Despliegue al VPS: reglas

El VPS corre la parte de servidor de TodoConta: el agente de cada usuario de la
versión web, el provisioner, el gateway (API pública y MCP), los agentes de
operación (`ops`) y Sendy. Todo vive en `/docker/<servicio>/` y se construye
desde este repo.

Hasta septiembre de 2026 se desplegaba copiando carpetas a mano. El resultado
fue un VPS desfasado del repo sin que nadie lo supiera: los agentes web en
v2.0.0 con desktop en v2.1.0, `ops` con el código de julio y agentes enteros
sin desplegar. Además, un rebuild del gateway instaló `mcp` 2.x por no tener
versiones fijas y dejó `/mcp` en 404 con el healthcheck en verde. Estas reglas
existen para que eso no vuelva a pasar.

## Las reglas

1. **Un solo camino: `deploy/desplegar.sh`.** Nada de `scp`, ni `git archive`
   a mano, ni editar archivos en `/docker/`. La única excepción es el `.env`
   de cada servicio, que no está en git; si cambias uno, anota el nombre de la
   variable (nunca el valor) en el README del servicio el mismo día.
2. **Solo se despliega lo que está en `main`.** El script se niega si el commit
   no está en `origin/main`. Primero se mergea el PR, luego se despliega.
3. **Cada despliegue deja huella.** El script escribe `/docker/<servicio>/.deployed`
   con el commit, la fecha y quién lo subió. Si falta ese archivo, ese
   servicio se desplegó a mano.
4. **Una versión en todos lados.** Todo lo que lleva número de versión va en
   la del último tag de release, el mismo día:

   | Dónde vive la versión | Cómo llega | Cómo se revisa |
   |---|---|---|
   | `pyproject.toml`, `ui/package.json`, `desktop/package.json`, `uv.lock` | PR de release (skill `release-semanal`) | el PR |
   | Tag `vX.Y.Z` | `git tag` tras mergear el release | `git tag` |
   | Release publicado en GitHub (lo que baja desktop y su auto-update) | CI crea el borrador; se publica tras el QA | `desfase.sh` |
   | UI web (app.todoconta.com) | `deploy/desplegar.sh ui vX.Y.Z` | `desfase.sh` (versión dentro del bundle) |
   | Agentes web (`agente-<slug>`) y `agente-piloto` | `deploy/desplegar.sh agente vX.Y.Z` | `desfase.sh` |

   Un tag sin publicar también es desfase: v2.1.0 se quedó en borrador un mes
   y los usuarios de desktop siguieron en v2.0.0 sin que nada lo marcara.
   Gateway, provisioner, ops y sendy no llevan número de versión propio: se
   despliegan desde `main` cuando cambian, y su `.deployed` guarda la versión
   del repo en ese commit como control interno.
   Hoy ni desktop ni la imagen del agente instalan desde `uv.lock` (los dos
   hacen `pip install ".[server,ciec]"`), así que construirlos el mismo día
   es lo que hace que resuelvan las mismas dependencias.
5. **Versiones fijas en todos los Dockerfile de `deploy/`.** Nada de `>=`.
   Subir una dependencia es un PR aparte que prueba lo que toca.
6. **Después de desplegar se prueba lo que usan los clientes**, no solo el
   healthcheck: `/mcp` debe contestar 401 (no 404), `/provision/health` debe
   decir ok, los agentes web deben quedar healthy y en la versión esperada.
   El script lo hace solo y, si algo falla, dice cómo regresar.
7. **OpenClaw no se toca.** Corre fuera de Docker (servicio systemd del host,
   puerto 18789). El script verifica que siga vivo al final de cada despliegue.
8. **`deploy/desfase.sh` en cada release**, y cuando haya duda. Compara archivo
   por archivo lo que corre contra git y la versión de los agentes contra el
   último tag. Solo lee, así que se puede correr cuando sea.

## Uso

```bash
# Un servicio desde main:
deploy/desplegar.sh gateway        # o provisioner | ops | sendy

# El día del release, con el tag (UI web y agentes web + piloto):
deploy/desplegar.sh ui v2.2.0
deploy/desplegar.sh agente v2.2.0

# Solo probar lo que corre hoy (no despliega nada):
deploy/desplegar.sh gateway --probar

# ¿Hay desfase?
deploy/desfase.sh
```

Qué hace `desplegar.sh`, en orden:

1. Verifica que el commit esté en `origin/main`.
2. Manda el contenido de git (`git archive`), nunca tu working tree.
3. Respalda en `/docker/backups/<servicio>-<fecha>.tgz` los archivos que va a
   pisar y etiqueta la imagen actual como `:pre-<fecha>`.
4. Construye (si el build falla, no levanta nada), levanta y escribe
   `.deployed`.
5. Corre las pruebas del servicio y la de OpenClaw.

Para `agente`: construye `todoconta/agente:<versión>` (y `:dev`), recrea cada
contenedor `agente-<slug>` con `deploy/vps/actualizar-agentes.sh` (conserva
volumen y claves, así que las credenciales siguen legibles) y verifica que
todos queden healthy en la versión esperada. Cada usuario web pierde unos
segundos de servicio mientras se recrea su contenedor: mejor en horas valle.

## Regresar un despliegue

Si una prueba falla, el script imprime el comando exacto. En general, en el VPS:

```bash
# Servicios con compose:
cd /docker/<servicio>
tar -xzf /docker/backups/<servicio>-<fecha>.tgz
docker tag <imagen>:pre-<fecha> <imagen>:latest
docker compose up -d            # sin --build

# Agentes web:
docker tag todoconta/agente:pre-<fecha> todoconta/agente:dev
bash deploy/vps/actualizar-agentes.sh   # desde el repo, por ssh
```

## Fuera del script (por ahora)

- **`agente-piloto`** (`/u/piloto`) es el agente de prueba de la fase 1 de la
  versión web, de antes del provisioner. No tiene tráfico real, pero mientras
  exista sigue la regla 4: `desplegar.sh agente` lo actualiza junto con los
  demás.
- **Sendy** se actualiza de versión con su propio procedimiento (rsync del zip
  oficial). `desplegar.sh sendy` solo sube el Dockerfile y el compose de este repo.
- **Fijar la imagen del agente y el build de desktop al `uv.lock`.** Hoy el
  lock no refleja lo que se instala (está más viejo). Cuando se haga, los dos
  builds deben usar el mismo lock y el CI debe correr los tests contra él.

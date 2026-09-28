# deploy/ops — agentes operativos del ecosistema de ventas

Un solo contenedor ligero en el VPS (`/docker/ops/`) donde **supercronic** dispara
scripts Python transitorios (sin daemons; apto para las 2 CPU del VPS). Es la capa
de "departamentos" automatizados del plan de ventas jul–dic 2026:

| Agente | Estado | Qué hace |
|---|---|---|
| `agents/reporte_semanal.py` | ✅ | Lunes 07:00 CDMX: métricas de Supabase (usuarios/planes/CRM 034) + Stripe (suscripciones/ARR) + Sendy (listas) → deltas vs semana pasada → narrativa con Claude → correo SES a Israel. |
| `agents/contenido_semanal.py` | ⛔ | **Dado de baja el 2026-09-28**: los PRs `drafts/semana-NN` se acumulaban sin revisar ni pasar al blog (se cerraron siete, de la semana 31 a la 39). Sale del crontab y `OPS_CONTENIDO_ENABLED=0`; el script se queda por si se retoma. Lo que hacía: lunes 06:30 CDMX generaba con Claude (Sonnet) el paquete semanal — post de blog con frontmatter listo, ficha SEO + heroImage y guion de video — y abre PR `drafts/semana-NN` en todoconta-apps. Los 3 posts sociales NO van en el PR: se crean como filas en la base de Notion **Contenido social — TodoConta** (`NOTION_DB_SOCIALES`), en `Borrador`. El correo tampoco: la newsletter se arma con la skill `/partida-doble` usando este post como hero. Los archivos viven en `drafts/`: **mergear tampoco publica**; Israel mueve el post al blog cuando lo aprueba. Fuente de temas: **el calendario editorial del repo** (`apps/landing/editorial/calendario-editorial-2026.csv`, leído en runtime — editarlo NO requiere redeploy; toma la fila más próxima con `publicado=no` y usa su brief/fuentes); backlog embebido solo como respaldo. Lee además el listado del blog para interlinkear con slugs reales y no repetir temas ya publicados. |
| `agents/sdr_inbound.py` | ✅ | Cada hora (9:15–17:15 CDMX): lee `crm_leads` etapa=lead con fuente en `SDR_FUENTES` (SOLO gente que llenó un formulario — opt-in estricto; hoy solo `abacus`), puntúa y redacta con Claude **respondiendo a la intención real de la fuente** (abacus → ayudar a activar su prueba de WhatsApp; diagnostico → entregar el plan prometido), manda el correo por SES como Israel (BCC al buzón del CRM), etapa→`mql` + evento `email_enviado` con el **cuerpo completo**. Secuencia de 3 toques (día 0, 3 y 7) que se corta sola si el lead responde, crea cuenta o sale de `mql`. |
| `agents/soporte.py` | ✅ | Cada hora: busca correos dirigidos a soporte@todoconta.com (que es un ALIAS dentro de la cuenta real de Israel — el agente entra por IMAP a esa cuenta pero SOLO procesa lo dirigido al alias, INBOX en readonly, banderas intactas), descarta auto-correos, clasifica y redacta BORRADOR con Claude, lo deja hilado en Borradores (sale como el alias) y avisa a Israel. Dedupe por Message-ID en `/data`. **No auto-responde a nadie** (v1). |
| `agents/cotizaciones.py` | ⚪ | Cada 15 min en horas hábiles: busca correos a cotizaciones@todoconta.com (send-as sobre la MISMA cuenta real que soporte@; INBOX readonly). Dos modos — **directo** (cliente escribe: cotiza con precios del catálogo `data/productos.json`, arma bitácora del historial) y **forward** (Israel reenvía con contexto: su texto puede fijar concepto/precio libre). Renderiza el **PDF de marca** (Chromium/Playwright, plantilla del design-system) y deja el **borrador con el PDF adjunto** hilado en Borradores (sale como el alias), avisando a Israel. Precios del catálogo o del forward de Israel; datos bancarios SIEMPRE de `data/emisor.json`, nunca del correo. Dedupe por Message-ID en `/data`. **No envía nada solo** (v1). |
| `agents/sync_abacus_waitlist.py` | ⚪ | Diario 08:10 CDMX: lee la waitlist de Abacus en Notion y la registra en `crm_leads` (`fuente=abacus`, nombre, teléfono en E.164, etapa según el Estado de Notion sin retroceder). Cierra el hueco por el que 114 personas en Sendy nunca llegaron al CRM. Solo lee Notion y escribe `crm_*`: la allowlist de OpenClaw NO se toca. |

## Despliegue (patrón de deploy/{gateway,provisioner,sendy})

```bash
# 1. Copiar la carpeta al VPS (o git archive del branch):
scp -r deploy/ops root@187.77.152.160:/docker/ops
# 2. Crear /docker/ops/.env (chmod 600) — ver abajo.
# 3. Usuario MySQL de SOLO LECTURA en sendy-db (una vez):
docker exec -it sendy-db mariadb -uroot -p"$MARIADB_ROOT_PASSWORD" -e \
  "CREATE USER IF NOT EXISTS 'ops_ro'@'%' IDENTIFIED BY '<password>';
   GRANT SELECT ON sendy.* TO 'ops_ro'@'%'; FLUSH PRIVILEGES;"
# 4. Levantar:
cd /docker/ops && docker compose up -d --build
# 5. Probar sin efectos (ninguno manda nada en --dry-run):
docker compose run --rm ops python agents/reporte_semanal.py --dry-run
docker compose run --rm ops python agents/sdr_inbound.py --dry-run
docker compose run --rm ops python agents/soporte.py --dry-run
docker compose run --rm ops python agents/cotizaciones.py --dry-run
```

## `.env` (chmod 600, NUNCA al repo)

```bash
# Kill switches (1 = encendido). SDR/soporte/contenido nacen APAGADOS:
# se encienden uno por uno cuando Israel valida su dry-run.
OPS_REPORTE_ENABLED=1
OPS_CONTENIDO_ENABLED=0   # dado de baja 2026-09-28; no volver a encender
OPS_SDR_ENABLED=0
OPS_SOPORTE_ENABLED=0
OPS_COTIZACIONES_ENABLED=0
OPS_PRIMER_CONTACTO_ENABLED=0

# Primer contacto de soycontador.ai (agents/primer_contacto.py). Reutiliza
# SOPORTE_EMAIL/SOPORTE_APP_PASSWORD: los alias de soycontador.ai entregan en la
# misma cuenta real. Los tres alias caen en el mismo grupo, así que se pueden
# atender juntos; empieza solo con hola@ y agrega los otros cuando valides.
PRIMER_CONTACTO_ALIASES=hola@soycontador.ai
PRIMER_CONTACTO_VENTANA_DIAS=2
PRIMER_CONTACTO_LLMS_URL=https://soycontador.ai/llms-full.txt

# Supabase (mismo proyecto que todoconta-apps; service role)
TODOCONTA_SUPABASE_URL=https://pyyyzvicjpffohwjsmzi.supabase.co
SUPABASE_SERVICE_KEY=

# Stripe — crear una RESTRICTED KEY de solo lectura (Developers → API keys →
# Create restricted key: Subscriptions/Customers/Charges en "Read"). NUNCA la
# secret key completa.
STRIPE_RESTRICTED_KEY=rk_live_...

# Sendy (MariaDB read-only, resuelto por la red sendy-internal)
SENDY_DB_HOST=sendy-db
SENDY_DB_USER=ops_ro
SENDY_DB_PASSWORD=
SENDY_DB_NAME=sendy

# SES (mismas credenciales y nombres que apps/web)
AWS_SES_REGION=us-east-1
AWS_SES_ACCESS_KEY_ID=
AWS_SES_SECRET_ACCESS_KEY=
REPORTE_FROM=no-reply@todoconta.com
REPORTE_TO=israel.castro@gmail.com

# Claude (reporte/SDR/soporte usan LLM_MODEL; contenido usa Sonnet)
ANTHROPIC_API_KEY=
LLM_MODEL=claude-haiku-4-5-20251001
LLM_MODEL_CONTENIDO=claude-sonnet-5

# Contenido semanal — fine-grained PAT con Contents:write + Pull requests:write
# SOLO sobre el repo de contenido.
GITHUB_PAT=
CONTENIDO_REPO=soyisracastro/todoconta-apps

# heroImage automática (opcional — sin estas keys el PR sale sin imagen y la
# ficha trae el prompt para generarla a mano). Modelo económico a propósito
# (Nano Banana 2 Lite ~$0.03/imagen); TinyPNG comprime y convierte a JPG.
GEMINI_API_KEY=
GEMINI_IMAGE_MODEL=gemini-3.1-flash-lite-image
TINYPNG_API_KEY=

# SDR inbound
SDR_FROM="Israel Castro <israel@todoconta.com>"
SDR_BCC=israel+crm@todoconta.com   # buzón del CRM, separado del correo directo
OPS_SDR_MAX_DIA=5        # tope de correos por día (primeros toques + seguimientos)
SDR_MAX_EDAD_DIAS=14     # no contactar leads más viejos que esto
# Secuencia: días DESDE EL PRIMER correo para el 2º y 3er toque. Vacío = solo
# un toque. La secuencia se corta sola si el lead responde (IMAP, mismas
# credenciales de soporte), si crea cuenta o si sale de la etapa mql.
SDR_SEGUIMIENTOS_DIAS=3,7
SDR_SEGUIMIENTO_VENTANA_DIAS=30    # secuencias más viejas no reviven por un redeploy
# Fuentes de crm_leads que el SDR puede contactar (coma-separadas). Solo
# abacus por ahora (qualifier = campaña saldo a favor pausada, fuera del ICP;
# se retomaría en sicastro.com). Al lanzar /diagnostico: "abacus,diagnostico".
SDR_FUENTES=abacus

# Waitlist de Abacus (Notion → CRM). El token es el MISMO que usa el script de
# OpenClaw (workspace-personal/abacus/secrets/notion.env): copiarlo aquí.
OPS_WAITLIST_ENABLED=0
NOTION_API_KEY=
# NOTION_ABACUS_DB_ID=   # solo si cambia la base (default en el agente)

# Base "Contenido social — TodoConta": ahí caen los 3 posts sociales de la
# semana (una fila por red, en Borrador) en vez de un .md dentro del PR.
# OJO: la integración detrás de NOTION_API_KEY se llama "Ada" (la misma del
# script de OpenClaw), NO "Newsletter Automation". Toda base nueva hay que
# compartirla con ELLA: abrirla en Notion → ••• → Connections → Ada. Para
# confirmar de quién es un token: GET https://api.notion.com/v1/users/me
# devuelve el nombre de la integración. Sin esta env (o sin el Connection)
# el agente sigue dejando drafts/semana-NN/posts-sociales.md como antes.
NOTION_DB_SOCIALES=35ecb37ed5544c88b965ed82bcf297c2

# Soporte (Google Workspace). soporte@todoconta.com es un ALIAS que entrega en
# la cuenta real (@sicastro.com): el login IMAP va con la CUENTA REAL y su app
# password (myaccount.google.com → Seguridad → Verificación en 2 pasos →
# Contraseñas de aplicaciones); el agente solo procesa lo dirigido al alias.
SOPORTE_IMAP_HOST=imap.gmail.com
SOPORTE_EMAIL=israel@sicastro.com        # cuenta real (login IMAP)
SOPORTE_APP_PASSWORD=                    # app password de ESA cuenta
SOPORTE_ALIAS=soporte@todoconta.com      # dirección que filtra y desde la que responde
SOPORTE_VENTANA_DIAS=2   # qué tan atrás busca (no barre correo viejo al encender)
OPS_SOPORTE_MAX=10       # mensajes por corrida

# Cotizaciones. cotizaciones@todoconta.com es OTRO send-as sobre la MISMA cuenta
# real que soporte@ (reutiliza SOPORTE_EMAIL/SOPORTE_APP_PASSWORD). Crear el
# alias en Workspace y configurarlo como "Enviar como" en la cuenta real, o el
# borrador no saldrá con el alias. El emisor/banco/catálogo viven en data/*.json
# (versionados, no aquí).
COTIZACIONES_ALIAS=cotizaciones@todoconta.com
COTIZACIONES_VENTANA_DIAS=2
OPS_COTIZACIONES_MAX=10
# Direcciones que activan el modo forward (confianza). Vacío = cuenta real +
# israel@todoconta.com + REPORTE_TO. Coma-separadas.
# COTIZACIONES_REMITENTES_ISRAEL=
```

## Reglas del contenedor

- **Escritura mínima y acotada**: Supabase solo a tablas `crm_*` (SDR); GitHub
  solo PRs de borradores con PAT fine-grained (contenido); Gmail solo APPEND a
  la carpeta Borradores — INBOX se abre readonly y las banderas de leído son de
  Israel, no del agente (soporte y cotizaciones; este último además adjunta el
  PDF al borrador). Stripe con restricted key RO, Sendy con
  usuario MySQL `SELECT`-only. Nada de docker.sock, nada de Traefik (sin inbound).
- **Nadie recibe correo sin humano o sin opt-in**: el SDR solo escribe a quien
  llenó un formulario (máximo 3 correos y para en cuanto haya respuesta, con
  BCC al buzón del CRM); soporte solo deja
  borradores; cotizaciones también. Los envíos masivos siguen siendo territorio de Sendy.
- **Sin daemons**: supercronic dispara procesos que terminan. `mem_limit: 1g`
  (subió de 256m para el Chromium headless del PDF de cotizaciones; render
  ocasional/bursty, el VPS tiene ~6GB libres).
- **Cada agente con kill switch por env** (SDR/soporte/contenido/cotizaciones nacen apagados)
  y horarios escalonados en el crontab. Todos aceptan `--dry-run`.
- **OpenClaw intocable**: este contenedor no toca nada de /root ni del host.
- El estado de cada agente (snapshots, candados diarios, procesados) vive en el
  volumen `ops-data` (`/data`).

## Verificación post-deploy

```bash
docker logs ops --tail 20              # supercronic cargó el crontab
docker compose run --rm ops python agents/reporte_semanal.py --dry-run
docker compose run --rm ops python agents/sdr_inbound.py --dry-run         # imprime correos, sin mandar
docker compose run --rm ops python agents/soporte.py --dry-run             # imprime clasificación, sin tocar el buzón
docker compose run --rm ops python agents/cotizaciones.py --dry-run        # imprime el plan de cotización, sin tocar nada
pgrep -f openclaw                      # checklist del host (runbook deploy/vps)
```

Secuencia de encendido sugerida: validar cada dry-run → `OPS_SOPORTE_ENABLED=1` y `OPS_COTIZACIONES_ENABLED=1`
(solo borradores) → `OPS_SDR_ENABLED=1` al final (este sí manda correo a leads;
empezar con `OPS_SDR_MAX_DIA=2` y subir cuando el tono esté validado).

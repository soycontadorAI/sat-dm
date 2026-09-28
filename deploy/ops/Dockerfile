# Contenedor de operaciones (agentes programados del ecosistema de ventas).
# Un solo contenedor ligero: supercronic dispara scripts Python transitorios
# (sin daemons — apto para el VPS de 2 CPU). Ver README.md de esta carpeta.

FROM python:3.12-slim

# supercronic: cron para contenedores (corre como no-root, loguea a stdout).
ARG SUPERCRONIC_VERSION=v0.2.34
ADD https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64 /usr/local/bin/supercronic
RUN chmod +x /usr/local/bin/supercronic

# Chromium de Playwright horneado FUERA de $HOME, para el PDF de cotizaciones
# (agents/cotizaciones.py → lib/cotizacion_pdf.py). Se lanza con --no-sandbox
# (el contenedor corre como root). El render es ocasional/bursty; el resto de
# los agentes no lo usan.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Versiones FIJAS (ver deploy/gateway/Dockerfile): las cuatro primeras son las
# que corrían en el contenedor ops del VPS en sep 2026; playwright es la misma
# que usa la imagen del agente, así que su Chromium ya está probado.
RUN pip install --no-cache-dir \
    "requests==2.34.2" "pymysql==1.2.0" "boto3==1.43.50" "anthropic==0.117.0" \
    "playwright==1.62.0" \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /app
COPY crontab ./crontab
COPY lib ./lib
COPY agents ./agents
COPY data ./data
COPY assets ./assets

# Los snapshots semanales (para deltas) y el estado de los agentes viven en /data.
RUN mkdir -p /data

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

# Ruta ABSOLUTA obligatoria: como PID 1, supercronic se re-ejecuta a sí mismo
# vía argv[0] sin resolver PATH — con "supercronic" a secas entra en crash-loop
# ("Failed to fork exec: no such file or directory").
CMD ["/usr/local/bin/supercronic", "-passthrough-logs", "/app/crontab"]

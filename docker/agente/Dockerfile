# Imagen del agente en modo hosted (versión online): un contenedor POR USUARIO
# detrás de Traefik en el VPS. Arquitectura: docs/producto/especificaciones.md;
# despliegue: docs/infra/despliegue-vps.md.
#
# Build (desde la raíz del repo):
#   docker build -f docker/agente/Dockerfile -t todoconta/agente:dev .
#
# Nota: el Dockerfile de la raíz es otra cosa (variante Railway de api/hosted.py).
FROM python:3.12-slim

# Chromium de Playwright horneado en la imagen, en una ruta fija FUERA de $HOME
# (para que no caiga al volumen de datos del usuario). portal/setup.py respeta
# esta env y desactiva su recolección de basura de navegadores.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Código + dependencias: extras server (FastAPI/uvicorn) y ciec (Playwright).
# `--with-deps` instala las librerías de sistema que Chromium headless necesita.
COPY pyproject.toml ./
COPY sat_descarga/ sat_descarga/
RUN pip install --no-cache-dir ".[server,ciec]" \
    && playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/* /root/.cache

# El healthcheck NO conoce SAT_AGENT_TOKEN: un 401 también prueba que el agente
# está vivo (solo el fallo de conexión cuenta como unhealthy). Importa porque
# Traefik IGNORA contenedores unhealthy y el router jamás se registraría.
RUN printf 'import urllib.request, urllib.error\n\
try:\n\
    urllib.request.urlopen("http://127.0.0.1:8787/health", timeout=4)\n\
except urllib.error.HTTPError:\n\
    pass\n' > /usr/local/bin/healthcheck.py

# Usuario sin privilegios. TODO el estado del usuario vive en /data (volumen):
# HOME=/data ⇒ ~/.sat-descarga = /data/.sat-descarga (catálogo, secretos.enc,
# solicitudes, historial) y las descargas en /data/descargas.
RUN useradd --uid 1000 --create-home --home-dir /data agente \
    && chmod -R a+rX /ms-playwright
ENV HOME=/data \
    SAT_DM_MODO=hosted \
    SAT_DM_DESCARGAS_DIR=/data/descargas
VOLUME /data
USER agente

# El resto de la configuración llega por env al crear el contenedor:
#   SAT_AGENT_TOKEN      — token de auth del agente (derivado por usuario)
#   SAT_DM_SECRETS_KEY   — clave AES-256 (base64) del archivo de secretos
#   SAT_DM_CORS_ORIGINS  — p. ej. https://app.todoconta.com

EXPOSE 8787
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python /usr/local/bin/healthcheck.py

CMD ["uvicorn", "sat_descarga.api.server:app", "--host", "0.0.0.0", "--port", "8787"]

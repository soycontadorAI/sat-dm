# Gateway de la API pública + servidor MCP. Corre como root (necesita el
# socket de Docker para encender agentes). Ver deploy/vps/README.md.
FROM python:3.12-slim

WORKDIR /app

# Versiones FIJAS: son las que corrieron en producción de jul a sep 2026. Con
# ">=" un rebuild sin caché instaló mcp 2.x, cuyo import cambió; el gateway
# atrapa el ImportError y arranca sin /mcp (healthcheck en verde, MCP en 404).
# Subir una versión es un cambio deliberado: probar /mcp antes de desplegar.
RUN pip install --no-cache-dir \
    "fastapi==0.139.2" "starlette==1.3.1" "pydantic==2.13.4" \
    "uvicorn[standard]==0.51.0" "requests==2.34.2" "docker==7.2.0" "mcp==1.28.1"

COPY main.py oauth.py capacidades.py uso.py ./

EXPOSE 8795
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8795/v1/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8795"]

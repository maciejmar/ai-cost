# Budowany z katalogu głównego repo (potrzebuje database/gateway.sql):
#   docker build -f gateway/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway/app ./app
COPY gateway/routing.yml ./routing.yml
COPY database/gateway.sql ./database/gateway.sql

ENV GATEWAY_ROUTING_PATH=/app/routing.yml \
    GATEWAY_SCHEMA_PATH=/app/database/gateway.sql

RUN useradd --uid 10001 --no-create-home gateway
USER gateway

EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8090/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]

"""AIGateway-X — wejście aplikacji (uvicorn app.main:app)."""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from . import db, providers
from .config import get_settings
from .routers import apps, auth, credentials, pricing, proxy, stats

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)
log = structlog.get_logger().bind(service="gateway")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    if s.gateway_jwt_secret == "change-me" or len(s.gateway_jwt_secret) < 32:
        raise RuntimeError("GATEWAY_JWT_SECRET must be set to a random string of at least 32 characters")
    if not s.gateway_encryption_key:
        raise RuntimeError("GATEWAY_ENCRYPTION_KEY must be set (Fernet key) to store provider credentials")
    await db.init()
    await providers.init()
    log.info("Gateway ready")
    yield
    await providers.close()
    await db.close()


app = FastAPI(title="AIGateway-X", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
app.mount("/metrics", make_asgi_app())


@app.exception_handler(HTTPException)
async def http_error(_request: Request, exc: HTTPException):
    # Błędy proxy mają już kształt OpenAI {"error": {...}} — nie owijaj ich w "detail"
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(exc.detail, status_code=exc.status_code, headers=exc.headers)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.get("/health")
async def health():
    await db.pool().fetchval("SELECT 1")
    await db.redis().ping()
    return {"status": "ok", "service": "aigateway-x"}


for r in (proxy.router, auth.router, apps.router, credentials.router, pricing.router, stats.router):
    app.include_router(r)

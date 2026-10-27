"""AIGateway-X — wejście aplikacji (uvicorn app.main:app)."""
from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app

from . import db, providers
from .config import get_settings, validate_settings
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
    problems = validate_settings(get_settings())
    if problems:
        raise RuntimeError("Invalid configuration: " + "; ".join(problems))
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

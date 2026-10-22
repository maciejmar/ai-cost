"""
OpenAI-kompatybilne proxy: POST /v1/chat/completions, GET /v1/models.

Agent zmienia tylko base_url na bramkę, klucz na agx_… i dodaje X-App-ID.
Opcjonalnie X-Gateway-Strategy: cheap | smart | fast | auto.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import structlog
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .. import catalog, db, ledger, limits
from ..config import get_settings
from ..deps import app_from_key, openai_error
from ..providers import PROVIDERS, StreamHandle, UpstreamError, Usage
from ..security import decrypt_secret

router = APIRouter(tags=["proxy"])
log = structlog.get_logger()

# Referencje do zadań księgujących strumienie (żeby GC ich nie ubił)
_background: set[asyncio.Task] = set()


async def resolve_credentials(user_id) -> dict[str, str]:
    s = get_settings()
    creds: dict[str, str] = {}
    if s.gateway_allow_env_credentials:
        if s.openai_api_key:
            creds["openai"] = s.openai_api_key
        if s.anthropic_api_key:
            creds["anthropic"] = s.anthropic_api_key
    rows = await db.pool().fetch(
        "SELECT provider_name, encrypted_api_key FROM gw_provider_credentials WHERE user_id = $1", user_id,
    )
    for r in rows:
        key = decrypt_secret(r["encrypted_api_key"])
        if key:
            creds[r["provider_name"]] = key
    if s.litellm_url:
        creds["litellm"] = s.litellm_master_key or "none"
    return creds


async def _account(
    app: dict, spec: catalog.ModelSpec, plan: catalog.RoutingPlan, usage: Usage,
    started: float, fallbacks: int, window_cfg: dict | None,
    status: str = "success", error: str | None = None,
):
    await limits.record_app_usage(app, usage.total)
    await limits.record_provider_usage(str(app["user_id"]), spec.provider, usage.total, window_cfg)
    return await ledger.record(
        app=app, provider=spec.provider, model=spec.name, requested_model=plan.requested,
        strategy=plan.strategy, usage=usage, latency_ms=int((time.monotonic() - started) * 1000),
        status=status, fallback_count=fallbacks, error=error,
    )


@router.get("/v1/models")
async def list_models(_app: dict = Depends(app_from_key)):
    names = ["auto", *catalog.get_catalog().models]
    return {"object": "list", "data": [{"id": n, "object": "model", "owned_by": "aigateway-x"} for n in names]}


@router.post("/v1/chat/completions")
async def chat_completions(
    request:            Request,
    app:                dict = Depends(app_from_key),
    x_gateway_strategy: str = Header(default=""),
):
    started = time.monotonic()
    body = await request.json()
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise openai_error(400, "'messages' must be a non-empty array", "invalid_request")

    strategy = (x_gateway_strategy or app["default_strategy"]).lower()
    if strategy not in catalog.STRATEGIES:
        raise openai_error(400, f"X-Gateway-Strategy must be one of {', '.join(catalog.STRATEGIES)}", "invalid_strategy")

    # ─── Kwoty aplikacji ────────────────────────────────────────────────
    quota = await limits.app_quota(app)
    if quota.hard_exceeded:
        raise openai_error(
            429, f"Token budget for '{app['app_name']}' exhausted ({quota.used}/{quota.limit}); "
                 f"resets at {quota.resets_at.isoformat()}", "app_quota_exceeded",
        )
    if quota.tpm_exceeded:
        raise openai_error(429, f"TPM limit {quota.tpm_limit} exceeded for '{app['app_name']}'", "app_tpm_exceeded")

    cat = catalog.get_catalog()
    try:
        plan = catalog.resolve_plan(
            model=body.get("model"), strategy=strategy, messages=body["messages"],
            tools=body.get("tools"), response_format=body.get("response_format"),
            force_strategy=cat.soft_limit_strategy if quota.soft_exceeded else None,
        )
    except KeyError:
        raise openai_error(404, f"Model '{body.get('model')}' is not in the gateway catalog", "model_not_found")

    user_id = str(app["user_id"])
    credentials = await resolve_credentials(app["user_id"])
    window_cfgs = await limits.load_window_configs(user_id)
    stream = bool(body.get("stream"))
    attempts: list[dict] = []

    for spec in plan.candidates:
        api_key = credentials.get(spec.provider)
        if not api_key:
            attempts.append({"model": spec.name, "skipped": f"no {spec.provider} credential"})
            continue
        blocked = await limits.provider_blocked(user_id, spec.provider, window_cfgs.get(spec.provider))
        if blocked:
            attempts.append({"model": spec.name, "skipped": blocked})
            continue

        provider = PROVIDERS[spec.provider]
        fallbacks = sum(1 for a in attempts if "error" in a)
        try:
            if stream:
                handle = await provider.stream(spec, api_key, body)
            else:
                result = await provider.complete(spec, api_key, body)
        except UpstreamError as e:
            await limits.record_ratelimit(user_id, spec.provider, e.ratelimit, throttled=e.status == 429)
            attempts.append({"model": spec.name, "error": e.status, "message": e.message})
            log.warning("upstream failed", app=app["app_name"], model=spec.name, status=e.status)
            if not e.retryable:
                await _account(app, spec, plan, Usage(), started, fallbacks, None, "error", e.message)
                raise openai_error(e.status, e.message, "upstream_error")
            continue
        except httpx.TransportError as e:
            attempts.append({"model": spec.name, "error": "transport", "message": type(e).__name__})
            log.warning("upstream unreachable", app=app["app_name"], model=spec.name, error=repr(e))
            continue

        headers = {
            "X-Gateway-Model":     spec.name,
            "X-Gateway-Provider":  spec.provider,
            "X-Gateway-Strategy":  plan.strategy,
            "X-Gateway-Fallbacks": str(fallbacks),
        }
        if plan.complexity is not None:
            headers["X-Gateway-Complexity"] = str(plan.complexity)
        if quota.soft_exceeded:
            headers["X-Gateway-Quota-Warning"] = f"soft limit reached ({quota.used}/{quota.limit})"

        if stream:
            await limits.record_ratelimit(user_id, spec.provider, handle.ratelimit)
            return StreamingResponse(
                _relay(handle, app, spec, plan, started, fallbacks, window_cfgs.get(spec.provider)),
                media_type="text/event-stream",
                headers={**headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        await limits.record_ratelimit(user_id, spec.provider, result.ratelimit)
        cost = await _account(app, spec, plan, result.usage, started, fallbacks, window_cfgs.get(spec.provider))
        headers["X-Gateway-Cost-USD"] = f"{cost:.8f}"
        return JSONResponse(result.body, headers=headers)

    # ─── Żaden kandydat nie zadziałał ───────────────────────────────────
    last = next((c for c in reversed(plan.candidates) if any(a["model"] == c.name and "error" in a for a in attempts)), None)
    if last:
        await _account(app, last, plan, Usage(), started, len(attempts), None, "error", "all candidates failed")
    raise openai_error(503, f"No upstream model available. Attempts: {attempts}", "no_upstream_available")


async def _relay(
    handle: StreamHandle, app: dict, spec: catalog.ModelSpec, plan: catalog.RoutingPlan,
    started: float, fallbacks: int, window_cfg: dict | None,
) -> AsyncIterator[bytes]:
    status, error = "success", None
    try:
        async for chunk in handle.chunks:
            yield chunk
    except (httpx.TransportError, asyncio.CancelledError) as e:
        status, error = "error", f"stream interrupted: {type(e).__name__}"
        raise
    finally:
        try:
            await handle.aclose()
        except Exception:
            pass
        # Księgowanie poza kontekstem generatora — działa też po rozłączeniu klienta
        task = asyncio.create_task(
            _account(app, spec, plan, handle.usage, started, fallbacks, window_cfg, status, error),
        )
        _background.add(task)
        task.add_done_callback(_background.discard)

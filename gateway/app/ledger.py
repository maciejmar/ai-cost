"""Cennik + zapis kosztów (gw_token_logs) + liczniki zgodne z shared/cost_gate.py."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from decimal import Decimal

from . import db
from .providers.base import Usage

_PRICING_TTL_S = 60
_pricing: dict[str, dict[str, Decimal]] = {}
_pricing_loaded_at = 0.0


async def pricing() -> dict[str, dict[str, Decimal]]:
    global _pricing, _pricing_loaded_at
    if time.monotonic() - _pricing_loaded_at > _PRICING_TTL_S:
        rows = await db.pool().fetch("SELECT * FROM gw_model_pricing")
        _pricing = {r["model"]: dict(r) for r in rows}
        _pricing_loaded_at = time.monotonic()
    return _pricing


def invalidate_pricing() -> None:
    global _pricing_loaded_at
    _pricing_loaded_at = 0.0


def calculate_cost(price: dict | None, usage: Usage) -> Decimal:
    if not price:
        return Decimal(0)
    per_tok = Decimal(1_000_000)
    return (
        usage.input_tokens       * Decimal(price["input_per_mtok"])
        + usage.output_tokens    * Decimal(price["output_per_mtok"])
        + usage.cached_tokens    * Decimal(price["cached_input_per_mtok"])
        + usage.cache_write_tokens * Decimal(price["cache_write_per_mtok"])
    ) / per_tok


async def record(
    *,
    app:             dict,
    provider:        str,
    model:           str,
    requested_model: str | None,
    strategy:        str,
    usage:           Usage,
    latency_ms:      int,
    status:          str,
    fallback_count:  int,
    error:           str | None = None,
) -> Decimal:
    cost = calculate_cost((await pricing()).get(model), usage)
    await db.pool().execute(
        """
        INSERT INTO gw_token_logs (
            app_id, user_id, provider_name, model_used, requested_model, strategy,
            input_tokens, output_tokens, cached_tokens, cache_write_tokens,
            calculated_cost, latency_ms, status, fallback_count, error)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        """,
        app["id"], app["user_id"], provider, model, requested_model, strategy,
        usage.input_tokens, usage.output_tokens, usage.cached_tokens, usage.cache_write_tokens,
        cost, latency_ms, status, fallback_count, error,
    )

    if cost > 0:
        # Te same klucze co CostGate — budżety agentów widzą wydatki z bramki
        now = datetime.now(timezone.utc)
        today, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
        pipe = db.redis().pipeline()
        pipe.incrbyfloat(f"cost:daily:{app['app_name']}:{today}", float(cost))
        pipe.incrbyfloat(f"cost:daily:__global__:{today}", float(cost))
        pipe.incrbyfloat(f"cost:monthly:{month}", float(cost))
        pipe.expire(f"cost:daily:{app['app_name']}:{today}", 86400 * 7)
        pipe.expire(f"cost:daily:__global__:{today}", 86400 * 7)
        await pipe.execute()
    return cost

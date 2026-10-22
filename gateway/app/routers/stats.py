"""Dane do dashboardu: okna limitów, ledger kosztów, podgląd routingu."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .. import catalog, db, limits
from ..config import get_settings
from ..deps import current_user

router = APIRouter(prefix="/api", tags=["stats"])

PROVIDERS = ["anthropic", "openai", "litellm"]


def _totals(row) -> dict:
    return {
        "cost_usd": float(row["cost"] or 0),
        "tokens":   int(row["tokens"] or 0),
        "requests": int(row["requests"] or 0),
    }


@router.get("/stats/overview")
async def overview(user: dict = Depends(current_user)):
    pool = db.pool()
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)
    q = """
        SELECT SUM(calculated_cost) AS cost,
               SUM(input_tokens + output_tokens + cached_tokens + cache_write_tokens) AS tokens,
               COUNT(*) AS requests
          FROM gw_token_logs WHERE user_id = $1 AND timestamp >= $2
    """
    today = await pool.fetchrow(q, user["id"], day_start)
    month = await pool.fetchrow(q, user["id"], month_start)
    recent = await pool.fetch(
        """
        SELECT l.timestamp, a.app_name, l.provider_name, l.model_used, l.strategy,
               l.input_tokens, l.output_tokens, l.cached_tokens, l.calculated_cost,
               l.latency_ms, l.status, l.fallback_count
          FROM gw_token_logs l JOIN gw_applications a ON a.id = l.app_id
         WHERE l.user_id = $1 ORDER BY l.timestamp DESC LIMIT 25
        """,
        user["id"],
    )
    return {
        "usd_pln":  get_settings().usd_pln_rate,
        "today":    _totals(today),
        "month":    _totals(month),
        "windows":  await limits.provider_windows(str(user["id"]), PROVIDERS),
        "recent":   [{**dict(r), "calculated_cost": float(r["calculated_cost"])} for r in recent],
        "server_time": now.isoformat(),
    }


@router.get("/stats/costs")
async def costs(
    granularity: Literal["day", "week", "month"] = "day",
    days:        int = Query(default=30, ge=1, le=366),
    user:        dict = Depends(current_user),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.pool().fetch(
        """
        SELECT date_trunc($3, l.timestamp) AS bucket, a.app_name,
               SUM(l.calculated_cost) AS cost,
               SUM(l.input_tokens + l.output_tokens + l.cached_tokens + l.cache_write_tokens) AS tokens,
               COUNT(*) AS requests
          FROM gw_token_logs l JOIN gw_applications a ON a.id = l.app_id
         WHERE l.user_id = $1 AND l.timestamp >= $2
         GROUP BY 1, 2 ORDER BY 1, 2
        """,
        user["id"], since, granularity,
    )
    by_model = await db.pool().fetch(
        """
        SELECT model_used, provider_name, SUM(calculated_cost) AS cost,
               SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
               SUM(cached_tokens) AS cached_tokens, COUNT(*) AS requests
          FROM gw_token_logs WHERE user_id = $1 AND timestamp >= $2
         GROUP BY 1, 2 ORDER BY 3 DESC
        """,
        user["id"], since,
    )
    return {
        "usd_pln":     get_settings().usd_pln_rate,
        "granularity": granularity,
        "rows": [
            {"bucket": r["bucket"].date().isoformat(), "app_name": r["app_name"], **_totals(r)}
            for r in rows
        ],
        "by_model": [
            {
                "model": r["model_used"], "provider": r["provider_name"], "cost_usd": float(r["cost"] or 0),
                "input_tokens": int(r["input_tokens"] or 0), "output_tokens": int(r["output_tokens"] or 0),
                "cached_tokens": int(r["cached_tokens"] or 0), "requests": int(r["requests"]),
            }
            for r in by_model
        ],
    }


@router.get("/routing")
async def routing_table(_user: dict = Depends(current_user)):
    cat = catalog.get_catalog()
    return {
        "strategies": cat.strategies,
        "models": {n: {"provider": m.provider, "equivalents": list(m.equivalents)} for n, m in cat.models.items()},
        "auto": {"smart_threshold": cat.smart_threshold, "balanced_threshold": cat.balanced_threshold},
    }


class PreviewIn(BaseModel):
    prompt:   str
    strategy: Literal["auto", "cheap", "smart", "fast"] = "auto"
    model:    str | None = None


@router.post("/routing/preview")
async def routing_preview(body: PreviewIn, _user: dict = Depends(current_user)):
    try:
        plan = catalog.resolve_plan(
            model=body.model, strategy=body.strategy, messages=[{"role": "user", "content": body.prompt}],
        )
    except KeyError:
        raise HTTPException(404, f"Model '{body.model}' is not in the catalog")
    return {
        "strategy":   plan.strategy,
        "complexity": plan.complexity,
        "reasons":    plan.reasons,
        "candidates": [{"model": c.name, "provider": c.provider} for c in plan.candidates],
    }

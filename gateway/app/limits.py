"""
Limity tokenów.

Aplikacja (agent):
  * token_budget_limit / budget_period — twardy limit (429) + miękki próg (soft_limit_pct → tańszy tier)
  * tpm_limit — tokeny/minutę, okno przesuwne przybliżone dwoma kubełkami minutowymi

Provider (per użytkownik):
  * własne okno subskrypcji, np. 1M tokenów / 3h — stałe okno zakotwiczone przy pierwszym użyciu
  * snapshot nagłówków x-ratelimit-* / anthropic-ratelimit-* — gdy remaining == 0 do czasu resetu,
    provider jest pomijany w routingu
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import db
from .providers.base import RateLimitSnapshot


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── Okresy budżetu aplikacji ─────────────────────────────────────────────

def period_bounds(period: str, now: datetime | None = None) -> tuple[str, datetime]:
    """Zwraca (klucz okresu, moment resetu)."""
    now = now or _now()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return day.strftime("%Y-%m-%d"), day + timedelta(days=1)
    if period == "week":
        start = day - timedelta(days=day.weekday())
        iso = now.isocalendar()
        return f"{iso.year}-W{iso.week:02d}", start + timedelta(days=7)
    month_start = day.replace(day=1)
    next_month = (month_start + timedelta(days=32)).replace(day=1)
    return now.strftime("%Y-%m"), next_month


@dataclass
class QuotaStatus:
    used:          int
    limit:         int | None
    soft_limit:    int | None
    resets_at:     datetime
    tpm_used:      int
    tpm_limit:     int | None

    @property
    def hard_exceeded(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    @property
    def soft_exceeded(self) -> bool:
        return self.soft_limit is not None and self.used >= self.soft_limit

    @property
    def tpm_exceeded(self) -> bool:
        return self.tpm_limit is not None and self.tpm_used >= self.tpm_limit


async def app_quota(app: dict) -> QuotaStatus:
    r = db.redis()
    key, resets_at = period_bounds(app["budget_period"])
    minute = int(time.time() // 60)
    used, cur, prev = await r.mget(
        f"gw:app:{app['id']}:tokens:{key}",
        f"gw:app:{app['id']}:tpm:{minute}",
        f"gw:app:{app['id']}:tpm:{minute - 1}",
    )
    elapsed = (time.time() % 60) / 60
    tpm = int(int(cur or 0) + int(prev or 0) * (1 - elapsed))

    limit = app["token_budget_limit"]
    return QuotaStatus(
        used=int(used or 0),
        limit=limit,
        soft_limit=int(limit * app["soft_limit_pct"] / 100) if limit else None,
        resets_at=resets_at,
        tpm_used=tpm,
        tpm_limit=app["tpm_limit"],
    )


async def record_app_usage(app: dict, tokens: int) -> None:
    key, resets_at = period_bounds(app["budget_period"])
    minute = int(time.time() // 60)
    period_key = f"gw:app:{app['id']}:tokens:{key}"
    tpm_key = f"gw:app:{app['id']}:tpm:{minute}"
    pipe = db.redis().pipeline()
    pipe.incrby(period_key, tokens)
    pipe.expireat(period_key, resets_at + timedelta(days=1))
    pipe.incrby(tpm_key, tokens)
    pipe.expire(tpm_key, 180)
    await pipe.execute()


# ─── Okna providerów ──────────────────────────────────────────────────────

def _win_key(user_id: str, provider: str) -> str:
    return f"gw:win:{user_id}:{provider}"


def _rl_key(user_id: str, provider: str) -> str:
    return f"gw:rl:{user_id}:{provider}"


async def load_window_configs(user_id: str) -> dict[str, dict]:
    rows = await db.pool().fetch(
        "SELECT provider_name, token_limit, window_seconds FROM gw_rate_limit_windows WHERE user_id = $1",
        user_id,
    )
    return {r["provider_name"]: dict(r) for r in rows}


def _ts(dt: datetime | None) -> str:
    return dt.isoformat() if dt else ""


def _parse_ts(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


async def provider_blocked(user_id: str, provider: str, config: dict | None) -> str | None:
    """Powód pominięcia providera albo None, gdy można go użyć."""
    r = db.redis()
    if config and config.get("token_limit"):
        used = int(await r.get(_win_key(user_id, provider)) or 0)
        if used >= config["token_limit"]:
            ttl = await r.ttl(_win_key(user_id, provider))
            return f"subscription window exhausted ({used}/{config['token_limit']}), resets in {max(ttl, 0)}s"

    snap = await r.hgetall(_rl_key(user_id, provider))
    now = _now()
    for kind in ("tokens", "requests"):
        remaining = snap.get(f"{kind}_remaining")
        reset_at = _parse_ts(snap.get(f"{kind}_reset_at"))
        if remaining == "0" and reset_at and reset_at > now:
            return f"upstream {kind} limit hit, resets at {reset_at.isoformat()}"
    return None


async def record_ratelimit(user_id: str, provider: str, snap: RateLimitSnapshot, *, throttled: bool = False) -> None:
    """Zapisz snapshot nagłówków. 429 bez nagłówków → krótka kwarantanna providera."""
    if snap.is_empty() and throttled:
        snap = RateLimitSnapshot(requests_remaining=0, requests_reset_at=_now() + timedelta(seconds=30))
    if snap.is_empty():
        return
    mapping = {
        "tokens_limit":       snap.tokens_limit,
        "tokens_remaining":   snap.tokens_remaining,
        "tokens_reset_at":    _ts(snap.tokens_reset_at),
        "requests_limit":     snap.requests_limit,
        "requests_remaining": snap.requests_remaining,
        "requests_reset_at":  _ts(snap.requests_reset_at),
    }
    # Scalanie: brakujące nagłówki nie kasują wcześniej znanych wartości
    mapping = {k: str(v) for k, v in mapping.items() if v not in (None, "")}
    pipe = db.redis().pipeline()
    pipe.hset(_rl_key(user_id, provider), mapping=mapping)
    pipe.expire(_rl_key(user_id, provider), 86400)
    await pipe.execute()

    await db.pool().execute(
        """
        INSERT INTO gw_rate_limit_windows (
            user_id, provider_name,
            upstream_tokens_limit, upstream_tokens_remaining, upstream_tokens_reset_at,
            upstream_requests_limit, upstream_requests_remaining, upstream_requests_reset_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        ON CONFLICT (user_id, provider_name) DO UPDATE SET
            upstream_tokens_limit       = COALESCE(EXCLUDED.upstream_tokens_limit,       gw_rate_limit_windows.upstream_tokens_limit),
            upstream_tokens_remaining   = COALESCE(EXCLUDED.upstream_tokens_remaining,   gw_rate_limit_windows.upstream_tokens_remaining),
            upstream_tokens_reset_at    = COALESCE(EXCLUDED.upstream_tokens_reset_at,    gw_rate_limit_windows.upstream_tokens_reset_at),
            upstream_requests_limit     = COALESCE(EXCLUDED.upstream_requests_limit,     gw_rate_limit_windows.upstream_requests_limit),
            upstream_requests_remaining = COALESCE(EXCLUDED.upstream_requests_remaining, gw_rate_limit_windows.upstream_requests_remaining),
            upstream_requests_reset_at  = COALESCE(EXCLUDED.upstream_requests_reset_at,  gw_rate_limit_windows.upstream_requests_reset_at),
            updated_at                  = NOW()
        """,
        user_id, provider,
        snap.tokens_limit, snap.tokens_remaining, snap.tokens_reset_at,
        snap.requests_limit, snap.requests_remaining, snap.requests_reset_at,
    )


async def record_provider_usage(user_id: str, provider: str, tokens: int, config: dict | None) -> None:
    if not config or not config.get("token_limit") or not config.get("window_seconds"):
        return
    r = db.redis()
    key = _win_key(user_id, provider)
    # Okno startuje przy pierwszym użyciu i wygasa po window_seconds
    await r.set(key, 0, ex=config["window_seconds"], nx=True)
    used = await r.incrby(key, tokens)
    ttl = await r.ttl(key)
    await db.pool().execute(
        """
        UPDATE gw_rate_limit_windows
           SET current_token_count = $3, window_reset_at = $4, updated_at = NOW()
         WHERE user_id = $1 AND provider_name = $2
        """,
        user_id, provider, used, _now() + timedelta(seconds=max(ttl, 0)),
    )


async def provider_windows(user_id: str, providers: list[str]) -> list[dict]:
    """Stan okien do dashboardu (pierścienie + odliczanie)."""
    configs = await load_window_configs(user_id)
    r = db.redis()
    out = []
    for provider in providers:
        cfg = configs.get(provider) or {}
        used = int(await r.get(_win_key(user_id, provider)) or 0)
        ttl = await r.ttl(_win_key(user_id, provider))
        snap = await r.hgetall(_rl_key(user_id, provider))

        def _int(v: str | None) -> int | None:
            return int(v) if v not in (None, "") else None

        # Po minięciu resetu snapshot jest nieaktualny — okno providera jest znowu pełne
        now = _now()
        for kind in ("tokens", "requests"):
            reset_at = _parse_ts(snap.get(f"{kind}_reset_at"))
            if reset_at and reset_at <= now and snap.get(f"{kind}_limit"):
                snap[f"{kind}_remaining"] = snap[f"{kind}_limit"]
                snap[f"{kind}_reset_at"] = ""

        out.append({
            "provider": provider,
            "subscription": {
                "token_limit":    cfg.get("token_limit"),
                "window_seconds": cfg.get("window_seconds"),
                "used":           used,
                "resets_at":      (_now() + timedelta(seconds=ttl)).isoformat() if ttl and ttl > 0 else None,
            },
            "upstream": {
                "tokens_limit":       _int(snap.get("tokens_limit")),
                "tokens_remaining":   _int(snap.get("tokens_remaining")),
                "tokens_reset_at":    snap.get("tokens_reset_at") or None,
                "requests_limit":     _int(snap.get("requests_limit")),
                "requests_remaining": _int(snap.get("requests_remaining")),
                "requests_reset_at":  snap.get("requests_reset_at") or None,
            },
        })
    return out

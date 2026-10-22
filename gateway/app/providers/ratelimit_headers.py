"""Parsowanie nagłówków rate-limit OpenAI i Anthropic do wspólnego RateLimitSnapshot."""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from .base import RateLimitSnapshot

_DURATION = re.compile(r"(\d+(?:\.\d+)?)(ms|h|m|s)")
_UNIT_SECONDS = {"h": 3600, "m": 60, "s": 1, "ms": 0.001}


def parse_duration(value: str) -> timedelta | None:
    """OpenAI: '1s', '6m0s', '20ms', '1h2m3.5s'."""
    parts = _DURATION.findall(value or "")
    if not parts:
        return None
    return timedelta(seconds=sum(float(n) * _UNIT_SECONDS[u] for n, u in parts))


def _int(headers: Mapping[str, str], name: str) -> int | None:
    v = headers.get(name)
    try:
        return int(v) if v is not None else None
    except ValueError:
        return None


def parse_openai(headers: Mapping[str, str], now: datetime | None = None) -> RateLimitSnapshot:
    now = now or datetime.now(timezone.utc)

    def reset(name: str) -> datetime | None:
        d = parse_duration(headers.get(name, ""))
        return now + d if d is not None else None

    return RateLimitSnapshot(
        tokens_limit=_int(headers, "x-ratelimit-limit-tokens"),
        tokens_remaining=_int(headers, "x-ratelimit-remaining-tokens"),
        tokens_reset_at=reset("x-ratelimit-reset-tokens"),
        requests_limit=_int(headers, "x-ratelimit-limit-requests"),
        requests_remaining=_int(headers, "x-ratelimit-remaining-requests"),
        requests_reset_at=reset("x-ratelimit-reset-requests"),
    )


def _rfc3339(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_anthropic(headers: Mapping[str, str]) -> RateLimitSnapshot:
    # Preferuj łączny limit tokenów; starsze konta mają tylko input/output osobno
    tok = "tokens" if "anthropic-ratelimit-tokens-limit" in headers else "input-tokens"
    return RateLimitSnapshot(
        tokens_limit=_int(headers, f"anthropic-ratelimit-{tok}-limit"),
        tokens_remaining=_int(headers, f"anthropic-ratelimit-{tok}-remaining"),
        tokens_reset_at=_rfc3339(headers.get(f"anthropic-ratelimit-{tok}-reset")),
        requests_limit=_int(headers, "anthropic-ratelimit-requests-limit"),
        requests_remaining=_int(headers, "anthropic-ratelimit-requests-remaining"),
        requests_reset_at=_rfc3339(headers.get("anthropic-ratelimit-requests-reset")),
    )

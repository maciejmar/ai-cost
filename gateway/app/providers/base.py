from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

import httpx

# 400/413/422 — błąd w samym zapytaniu, inny provider też go odrzuci.
# Wszystko inne (auth, brak modelu, limity, 5xx) → próbujemy następnego kandydata.
NON_RETRYABLE = {400, 413, 422}


@dataclass
class Usage:
    input_tokens:       int = 0     # bez tokenów z cache
    output_tokens:      int = 0
    cached_tokens:      int = 0     # odczyt z cache
    cache_write_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens + self.cached_tokens + self.cache_write_tokens


@dataclass
class RateLimitSnapshot:
    tokens_limit:       int | None = None
    tokens_remaining:   int | None = None
    tokens_reset_at:    datetime | None = None
    requests_limit:     int | None = None
    requests_remaining: int | None = None
    requests_reset_at:  datetime | None = None

    def is_empty(self) -> bool:
        return all(v is None for v in self.__dict__.values())


@dataclass
class CompletionResult:
    body:      dict                 # odpowiedź w formacie OpenAI
    usage:     Usage
    ratelimit: RateLimitSnapshot


class UpstreamError(Exception):
    def __init__(self, status: int, message: str, ratelimit: RateLimitSnapshot | None = None):
        super().__init__(f"upstream {status}: {message}")
        self.status    = status
        self.message   = message
        self.ratelimit = ratelimit or RateLimitSnapshot()

    @property
    def retryable(self) -> bool:
        return self.status not in NON_RETRYABLE


@dataclass
class StreamHandle:
    """Otwarty, zaakceptowany (2xx) strumień upstream. `usage` wypełnia się w trakcie iteracji."""
    response:  httpx.Response
    ratelimit: RateLimitSnapshot
    chunks:    AsyncIterator[bytes] = field(repr=False)
    usage:     Usage = field(default_factory=Usage)

    async def aclose(self) -> None:
        await self.response.aclose()


def sse(data: dict | str) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    return f"data: {payload}\n\n".encode()


async def raise_for_upstream(resp: httpx.Response, ratelimit: RateLimitSnapshot) -> None:
    if resp.status_code < 400:
        return
    body = (await resp.aread()).decode(errors="replace")
    await resp.aclose()
    try:
        err = json.loads(body).get("error", {})
        message = err.get("message", body) if isinstance(err, dict) else str(err)
    except (json.JSONDecodeError, AttributeError):
        message = body
    raise UpstreamError(resp.status_code, message[:500], ratelimit)

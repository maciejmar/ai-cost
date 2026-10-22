"""Rejestr providerów upstream (współdzielony klient HTTP)."""
from __future__ import annotations

import httpx

from ..config import get_settings
from .anthropic import AnthropicProvider
from .base import CompletionResult, RateLimitSnapshot, StreamHandle, UpstreamError, Usage
from .openai_compat import OpenAICompatProvider

PROVIDERS: dict[str, OpenAICompatProvider | AnthropicProvider] = {}
_client: httpx.AsyncClient | None = None


async def init() -> None:
    global _client
    s = get_settings()
    _client = httpx.AsyncClient(timeout=httpx.Timeout(s.upstream_timeout_s, connect=10.0))
    PROVIDERS["openai"]    = OpenAICompatProvider(_client, s.openai_base_url)
    PROVIDERS["anthropic"] = AnthropicProvider(_client, s.anthropic_base_url, s.anthropic_version)
    # LiteLLM (Ollama na serwerze GPU) nie zwraca znaczących limitów providera
    PROVIDERS["litellm"]   = OpenAICompatProvider(_client, f"{s.litellm_url.rstrip('/')}/v1", parse_headers=False)


async def close() -> None:
    if _client:
        await _client.aclose()


__all__ = [
    "PROVIDERS", "init", "close",
    "CompletionResult", "RateLimitSnapshot", "StreamHandle", "UpstreamError", "Usage",
]

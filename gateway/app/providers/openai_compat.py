"""Upstream zgodny z OpenAI (api.openai.com oraz LiteLLM/Ollama) — przekazanie 1:1."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..catalog import ModelSpec
from .base import (
    CompletionResult, RateLimitSnapshot, StreamHandle, Usage, raise_for_upstream,
)
from .ratelimit_headers import parse_openai


def usage_from_openai(u: dict | None) -> Usage:
    if not u:
        return Usage()
    cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return Usage(
        input_tokens=max((u.get("prompt_tokens") or 0) - cached, 0),
        output_tokens=u.get("completion_tokens") or 0,
        cached_tokens=cached,
    )


def build_body(body: dict, spec: ModelSpec, stream: bool) -> dict:
    out = {k: v for k, v in body.items() if k not in spec.drop_params}
    out["model"] = spec.upstream_model
    if stream:
        out["stream"] = True
        # Potrzebujemy usage na końcu strumienia, żeby policzyć koszt
        out["stream_options"] = {**(body.get("stream_options") or {}), "include_usage": True}
    else:
        out.pop("stream", None)
        out.pop("stream_options", None)
    return out


class OpenAICompatProvider:
    def __init__(self, client: httpx.AsyncClient, base_url: str, parse_headers: bool = True):
        self.client        = client
        self.base_url      = base_url.rstrip("/")
        self.parse_headers = parse_headers

    def _ratelimit(self, resp: httpx.Response) -> RateLimitSnapshot:
        return parse_openai(resp.headers) if self.parse_headers else RateLimitSnapshot()

    def _request(self, api_key: str, body: dict) -> httpx.Request:
        return self.client.build_request(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )

    async def complete(self, spec: ModelSpec, api_key: str, body: dict) -> CompletionResult:
        resp = await self.client.send(self._request(api_key, build_body(body, spec, stream=False)))
        rl = self._ratelimit(resp)
        await raise_for_upstream(resp, rl)
        data = resp.json()
        return CompletionResult(body=data, usage=usage_from_openai(data.get("usage")), ratelimit=rl)

    async def stream(self, spec: ModelSpec, api_key: str, body: dict) -> StreamHandle:
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        resp = await self.client.send(
            self._request(api_key, build_body(body, spec, stream=True)), stream=True,
        )
        rl = self._ratelimit(resp)
        await raise_for_upstream(resp, rl)

        handle = StreamHandle(response=resp, ratelimit=rl, chunks=None)  # type: ignore[arg-type]
        handle.chunks = self._passthrough(resp, handle, include_usage)
        return handle

    async def _passthrough(
        self, resp: httpx.Response, handle: StreamHandle, include_usage: bool,
    ) -> AsyncIterator[bytes]:
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    chunk = {}
                if chunk.get("usage"):
                    handle.usage = usage_from_openai(chunk["usage"])
                    # Klient nie prosił o usage → nie wysyłaj mu dodatkowego chunka
                    if not include_usage and not chunk.get("choices"):
                        continue
            yield f"data: {payload}\n\n".encode()

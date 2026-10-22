"""
Anthropic Messages API ⇄ OpenAI Chat Completions.

Tłumaczy zapytanie (system, treści multimodalne, tools, tool results) oraz
odpowiedź — także strumieniową — tak, żeby klient widział wyłącznie format OpenAI.
"""
from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import httpx

from ..catalog import ModelSpec
from .base import CompletionResult, StreamHandle, Usage, raise_for_upstream, sse
from .ratelimit_headers import parse_anthropic

DEFAULT_MAX_TOKENS = 16000

FINISH_REASONS = {
    "end_turn":      "stop",
    "stop_sequence": "stop",
    "max_tokens":    "length",
    "tool_use":      "tool_calls",
    "refusal":       "content_filter",
    "pause_turn":    "stop",
}


# ─── Zapytanie ────────────────────────────────────────────────────────────

def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _convert_part(part: dict) -> dict | None:
    kind = part.get("type")
    if kind == "text":
        return {"type": "text", "text": part.get("text", "")}
    if kind == "image_url":
        url = (part.get("image_url") or {}).get("url", "")
        if url.startswith("data:") and ";base64," in url:
            media_type, data = url[5:].split(";base64,", 1)
            return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _convert_content(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if isinstance(content, list):
        return [c for c in (_convert_part(p) for p in content if isinstance(p, dict)) if c]
    return []


def _append(messages: list[dict], role: str, blocks: list[dict]) -> None:
    """Scala kolejne wiadomości tej samej roli (np. kilka tool results pod rząd)."""
    if not blocks:
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
    else:
        messages.append({"role": role, "content": blocks})


def to_anthropic_request(body: dict, spec: ModelSpec, stream: bool) -> dict:
    system_parts: list[str] = []
    messages: list[dict] = []

    for m in body.get("messages", []):
        role = m.get("role")
        if role in ("system", "developer"):
            system_parts.append(_text(m.get("content")))
        elif role == "user":
            _append(messages, "user", _convert_content(m.get("content")))
        elif role == "assistant":
            blocks = _convert_content(m.get("content"))
            for call in m.get("tool_calls") or []:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": fn.get("arguments")}
                blocks.append({"type": "tool_use", "id": call.get("id"), "name": fn.get("name"), "input": args})
            _append(messages, "assistant", blocks)
        elif role == "tool":
            _append(messages, "user", [{
                "type":        "tool_result",
                "tool_use_id": m.get("tool_call_id"),
                "content":     _text(m.get("content")),
            }])

    req: dict = {
        "model":      spec.upstream_model,
        "messages":   messages,
        "max_tokens": body.get("max_completion_tokens") or body.get("max_tokens") or DEFAULT_MAX_TOKENS,
    }
    if system_parts:
        req["system"] = "\n\n".join(p for p in system_parts if p)
    if stream:
        req["stream"] = True

    for key in ("temperature", "top_p"):
        if body.get(key) is not None and key not in spec.drop_params:
            req[key] = body[key]

    stop = body.get("stop")
    if stop:
        req["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)

    if body.get("tools"):
        req["tools"] = [
            {
                "name":         t["function"]["name"],
                "description":  t["function"].get("description", ""),
                "input_schema": t["function"].get("parameters") or {"type": "object", "properties": {}},
            }
            for t in body["tools"] if t.get("type") == "function"
        ]
        # Modele 5.x odrzucają wymuszone tool_choice (any/tool) — mapujemy na auto
        choice = body.get("tool_choice")
        req["tool_choice"] = {"type": "none"} if choice == "none" else {"type": "auto"}

    if isinstance(body.get("user"), str):
        req["metadata"] = {"user_id": body["user"][:256]}

    return req


# ─── Odpowiedź ────────────────────────────────────────────────────────────

def usage_from_anthropic(u: dict | None) -> Usage:
    u = u or {}
    return Usage(
        input_tokens=u.get("input_tokens") or 0,
        output_tokens=u.get("output_tokens") or 0,
        cached_tokens=u.get("cache_read_input_tokens") or 0,
        cache_write_tokens=u.get("cache_creation_input_tokens") or 0,
    )


def openai_usage(usage: Usage) -> dict:
    prompt = usage.input_tokens + usage.cached_tokens + usage.cache_write_tokens
    return {
        "prompt_tokens":         prompt,
        "completion_tokens":     usage.output_tokens,
        "total_tokens":          prompt + usage.output_tokens,
        "prompt_tokens_details": {"cached_tokens": usage.cached_tokens},
    }


def to_openai_response(data: dict, model_name: str) -> tuple[dict, Usage]:
    text_parts: list[str] = []
    tool_calls: list[dict] = []
    for block in data.get("content", []):
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id":       block.get("id"),
                "type":     "function",
                "function": {"name": block.get("name"), "arguments": json.dumps(block.get("input", {}))},
            })
        # bloki thinking pomijamy — klient OpenAI ich nie zna

    message: dict = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls

    usage = usage_from_anthropic(data.get("usage"))
    return {
        "id":      f"chatcmpl-{data.get('id', '')}",
        "object":  "chat.completion",
        "created": int(time.time()),
        "model":   model_name,
        "choices": [{
            "index":         0,
            "message":       message,
            "finish_reason": FINISH_REASONS.get(data.get("stop_reason"), "stop"),
        }],
        "usage": openai_usage(usage),
    }, usage


# ─── Provider ─────────────────────────────────────────────────────────────

class AnthropicProvider:
    def __init__(self, client: httpx.AsyncClient, base_url: str, version: str):
        self.client   = client
        self.base_url = base_url.rstrip("/")
        self.version  = version

    def _request(self, api_key: str, body: dict) -> httpx.Request:
        return self.client.build_request(
            "POST",
            f"{self.base_url}/messages",
            headers={
                "x-api-key":         api_key,
                "anthropic-version": self.version,
                "content-type":      "application/json",
            },
            json=body,
        )

    async def complete(self, spec: ModelSpec, api_key: str, body: dict) -> CompletionResult:
        resp = await self.client.send(self._request(api_key, to_anthropic_request(body, spec, stream=False)))
        rl = parse_anthropic(resp.headers)
        await raise_for_upstream(resp, rl)
        out, usage = to_openai_response(resp.json(), spec.name)
        return CompletionResult(body=out, usage=usage, ratelimit=rl)

    async def stream(self, spec: ModelSpec, api_key: str, body: dict) -> StreamHandle:
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        resp = await self.client.send(
            self._request(api_key, to_anthropic_request(body, spec, stream=True)), stream=True,
        )
        rl = parse_anthropic(resp.headers)
        await raise_for_upstream(resp, rl)

        handle = StreamHandle(response=resp, ratelimit=rl, chunks=None)  # type: ignore[arg-type]
        handle.chunks = translate_stream(resp.aiter_lines(), handle, spec.name, include_usage)
        return handle


async def translate_stream(
    lines:         AsyncIterator[str],
    handle:        StreamHandle,
    model_name:    str,
    include_usage: bool,
) -> AsyncIterator[bytes]:
    chunk_id = "chatcmpl-gw"
    created  = int(time.time())
    # indeks bloku Anthropic → indeks tool_call OpenAI
    tool_index: dict[int, int] = {}

    def chunk(delta: dict, finish: str | None = None) -> bytes:
        return sse({
            "id": chunk_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        })

    async for line in lines:
        if not line.startswith("data:"):
            continue
        try:
            ev = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        kind = ev.get("type")

        if kind == "message_start":
            msg = ev.get("message", {})
            chunk_id = f"chatcmpl-{msg.get('id', 'gw')}"
            handle.usage = usage_from_anthropic(msg.get("usage"))
            yield chunk({"role": "assistant", "content": ""})

        elif kind == "content_block_start":
            block = ev.get("content_block", {})
            if block.get("type") == "tool_use":
                idx = len(tool_index)
                tool_index[ev.get("index", 0)] = idx
                yield chunk({"tool_calls": [{
                    "index": idx, "id": block.get("id"), "type": "function",
                    "function": {"name": block.get("name"), "arguments": ""},
                }]})

        elif kind == "content_block_delta":
            delta = ev.get("delta", {})
            if delta.get("type") == "text_delta":
                yield chunk({"content": delta.get("text", "")})
            elif delta.get("type") == "input_json_delta" and ev.get("index") in tool_index:
                yield chunk({"tool_calls": [{
                    "index": tool_index[ev["index"]],
                    "function": {"arguments": delta.get("partial_json", "")},
                }]})

        elif kind == "message_delta":
            u = ev.get("usage") or {}
            if "output_tokens" in u:
                handle.usage.output_tokens = u["output_tokens"]
            stop = (ev.get("delta") or {}).get("stop_reason")
            if stop:
                yield chunk({}, FINISH_REASONS.get(stop, "stop"))

        elif kind == "error":
            err = ev.get("error", {})
            yield sse({"error": {"message": err.get("message", "upstream error"), "type": err.get("type")}})
            break

    if include_usage:
        yield sse({
            "id": chunk_id, "object": "chat.completion.chunk", "created": created, "model": model_name,
            "choices": [], "usage": openai_usage(handle.usage),
        })
    yield sse("[DONE]")

"""Atrapa API OpenAI i Anthropic do testów e2e (uvicorn tests.fake_upstream:app --port 9999)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()
FAILING: set[str] = set()
CALLS: list[str] = []


@app.post("/control")
async def control(request: Request):
    body = await request.json()
    FAILING.clear()
    FAILING.update(body.get("fail", []))
    return {"failing": sorted(FAILING), "calls": CALLS}


def _oa_headers():
    return {
        "x-ratelimit-limit-tokens": "200000", "x-ratelimit-remaining-tokens": "199000",
        "x-ratelimit-reset-tokens": "6m0s", "x-ratelimit-limit-requests": "500",
        "x-ratelimit-remaining-requests": "499", "x-ratelimit-reset-requests": "120ms",
    }


def _an_headers():
    reset = (datetime.now(timezone.utc) + timedelta(seconds=45)).isoformat().replace("+00:00", "Z")
    return {
        "anthropic-ratelimit-tokens-limit": "400000", "anthropic-ratelimit-tokens-remaining": "390000",
        "anthropic-ratelimit-tokens-reset": reset, "anthropic-ratelimit-requests-limit": "50",
        "anthropic-ratelimit-requests-remaining": "49", "anthropic-ratelimit-requests-reset": reset,
    }


@app.post("/openai/v1/chat/completions")
async def openai_chat(request: Request):
    body = await request.json()
    CALLS.append(body["model"])
    if body["model"] in FAILING:
        return JSONResponse({"error": {"message": "Rate limit reached"}}, 429, headers={"x-ratelimit-remaining-requests": "0", "x-ratelimit-reset-requests": "30s"})
    usage = {"prompt_tokens": 1200, "completion_tokens": 30, "total_tokens": 1230, "prompt_tokens_details": {"cached_tokens": 200}}
    if body.get("stream"):
        async def gen():
            for word in ["Hello", " from", " openai"]:
                yield "data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "model": body["model"],
                                              "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}]}) + "\n\n"
            yield "data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "model": body["model"],
                                          "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}) + "\n\n"
            if (body.get("stream_options") or {}).get("include_usage"):
                yield "data: " + json.dumps({"id": "c1", "object": "chat.completion.chunk", "model": body["model"], "choices": [], "usage": usage}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(gen(), media_type="text/event-stream", headers=_oa_headers())
    return JSONResponse({
        "id": "c1", "object": "chat.completion", "created": 0, "model": body["model"],
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from openai"}, "finish_reason": "stop"}],
        "usage": usage,
    }, headers=_oa_headers())


@app.post("/anthropic/v1/messages")
async def anthropic_messages(request: Request):
    body = await request.json()
    CALLS.append(body["model"])
    assert request.headers.get("x-api-key") and request.headers.get("anthropic-version")
    assert "temperature" not in body, "5.x models reject temperature"
    if body["model"] in FAILING:
        return JSONResponse({"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}}, 429)
    usage = {"input_tokens": 900, "output_tokens": 40, "cache_read_input_tokens": 100, "cache_creation_input_tokens": 0}
    if body.get("stream"):
        def ev(e):
            return f"event: {e['type']}\ndata: {json.dumps(e)}\n\n"
        async def gen():
            yield ev({"type": "message_start", "message": {"id": "msg_1", "usage": {**usage, "output_tokens": 1}}})
            yield ev({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            for word in ["Hello", " from", " claude"]:
                yield ev({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": word}})
            yield ev({"type": "content_block_stop", "index": 0})
            yield ev({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 40}})
            yield ev({"type": "message_stop"})
        return StreamingResponse(gen(), media_type="text/event-stream", headers=_an_headers())
    return JSONResponse({
        "id": "msg_1", "type": "message", "role": "assistant", "model": body["model"], "stop_reason": "end_turn",
        "content": [{"type": "text", "text": "Hello from claude"}], "usage": usage,
    }, headers=_an_headers())

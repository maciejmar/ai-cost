import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import catalog
from app.ledger import calculate_cost
from app.limits import period_bounds
from app.providers.anthropic import to_anthropic_request, to_openai_response, translate_stream
from app.providers.base import StreamHandle, Usage
from app.providers.openai_compat import build_body, usage_from_openai
from app.providers.ratelimit_headers import parse_anthropic, parse_duration, parse_openai


def user(text):
    return [{"role": "user", "content": text}]


# ─── Routing ──────────────────────────────────────────────────────────────

def test_simple_prompt_routes_cheap():
    plan = catalog.resolve_plan(model=None, strategy="auto", messages=user("Extract the email address as JSON: Jan, jan@x.pl"))
    assert plan.strategy == "cheap"
    assert plan.candidates[0].name == "claude-haiku-5-5"


def test_complex_prompt_routes_smart():
    prompt = ("Analyze the architecture below step by step, compare trade-offs and design a migration strategy. "
              "Explain why.\n```python\nclass A: pass\n```")
    plan = catalog.resolve_plan(model="auto", strategy="auto", messages=user(prompt))
    assert plan.strategy == "smart", plan.reasons
    assert plan.candidates[0].name == "claude-opus-5-5"


def test_polish_keywords_count():
    score, _ = catalog.score_complexity(user("Przeanalizuj krok po kroku i zaprojektuj strategię migracji"))
    assert score >= 0.5


def test_explicit_strategy_header():
    plan = catalog.resolve_plan(model=None, strategy="fast", messages=user("hi"))
    assert plan.strategy == "fast" and plan.complexity is None


def test_explicit_model_uses_equivalents_as_fallback():
    plan = catalog.resolve_plan(model="gpt-4o", strategy="auto", messages=user("hi"))
    assert [c.name for c in plan.candidates] == ["gpt-4o", "claude-sonnet-5-5", "gpt-4.1"]


def test_soft_limit_forces_cheap_even_for_explicit_model():
    plan = catalog.resolve_plan(model="claude-opus-5-5", strategy="smart", messages=user("hi"), force_strategy="cheap")
    assert plan.strategy == "cheap"


def test_legacy_litellm_alias():
    plan = catalog.resolve_plan(model="claude-sonnet-4", strategy="auto", messages=user("hi"))
    assert plan.candidates[0].name == "claude-sonnet-5-5" and plan.requested == "claude-sonnet-4"


def test_unknown_model_raises():
    with pytest.raises(KeyError):
        catalog.resolve_plan(model="gpt-99", strategy="auto", messages=user("hi"))


# ─── Nagłówki rate-limit ──────────────────────────────────────────────────

def test_parse_duration():
    assert parse_duration("6m0s") == timedelta(minutes=6)
    assert parse_duration("1h2m3.5s") == timedelta(hours=1, minutes=2, seconds=3.5)
    assert parse_duration("20ms") == timedelta(milliseconds=20)
    assert parse_duration("") is None


def test_parse_openai_headers():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    snap = parse_openai({
        "x-ratelimit-limit-tokens": "30000", "x-ratelimit-remaining-tokens": "29000",
        "x-ratelimit-reset-tokens": "2s", "x-ratelimit-limit-requests": "500",
        "x-ratelimit-remaining-requests": "499", "x-ratelimit-reset-requests": "120ms",
    }, now)
    assert snap.tokens_remaining == 29000
    assert snap.tokens_reset_at == now + timedelta(seconds=2)
    assert snap.requests_reset_at == now + timedelta(milliseconds=120)


def test_parse_anthropic_headers():
    snap = parse_anthropic({
        "anthropic-ratelimit-tokens-limit": "400000", "anthropic-ratelimit-tokens-remaining": "0",
        "anthropic-ratelimit-tokens-reset": "2026-10-20T12:00:30Z",
        "anthropic-ratelimit-requests-limit": "50", "anthropic-ratelimit-requests-remaining": "49",
        "anthropic-ratelimit-requests-reset": "2026-10-20T12:00:01Z",
    })
    assert snap.tokens_remaining == 0
    assert snap.tokens_reset_at == datetime(2026, 10, 20, 12, 0, 30, tzinfo=timezone.utc)


# ─── Tłumaczenie Anthropic ────────────────────────────────────────────────

SPEC = catalog.get_catalog().models["claude-sonnet-5-5"]


def test_anthropic_request_translation():
    body = {
        "model": "claude-sonnet-5-5", "temperature": 0.2, "stop": "END",
        "messages": [
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": [
                {"type": "text", "text": "What is in this image?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ]},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\": 1}"}},
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "result"},
        ],
        "tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}],
        "tool_choice": "required",
    }
    req = to_anthropic_request(body, SPEC, stream=False)
    assert req["system"] == "Be terse."
    assert "temperature" not in req                          # drop_params dla 5.x
    assert req["max_tokens"] == 16000
    assert req["stop_sequences"] == ["END"]
    assert req["messages"][0]["content"][1]["source"] == {"type": "base64", "media_type": "image/png", "data": "AAAA"}
    assert req["messages"][1]["content"][0] == {"type": "tool_use", "id": "call_1", "name": "lookup", "input": {"q": 1}}
    assert req["messages"][2]["content"][0]["type"] == "tool_result"
    assert req["tool_choice"] == {"type": "auto"}            # wymuszone → auto


def test_anthropic_response_translation():
    out, usage = to_openai_response({
        "id": "msg_1", "stop_reason": "tool_use",
        "content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "tu_1", "name": "lookup", "input": {"q": 1}},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50, "cache_creation_input_tokens": 10},
    }, "claude-sonnet-5-5")
    choice = out["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["content"] == "Checking."
    assert json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"]) == {"q": 1}
    assert out["usage"]["prompt_tokens"] == 160
    assert usage == Usage(100, 20, 50, 10)


async def _lines(events):
    for e in events:
        yield f"event: {e['type']}"
        yield f"data: {json.dumps(e)}"
        yield ""


@pytest.mark.asyncio
async def test_anthropic_stream_translation():
    events = [
        {"type": "message_start", "message": {"id": "msg_9", "usage": {"input_tokens": 12, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu", "name": "f"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"a\":"}},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 7}},
        {"type": "message_stop"},
    ]
    handle = StreamHandle(response=None, ratelimit=None, chunks=None)  # type: ignore[arg-type]
    out = [c async for c in translate_stream(_lines(events), handle, "claude-sonnet-5-5", include_usage=True)]
    payloads = [c.decode()[6:].strip() for c in out]
    assert payloads[-1] == "[DONE]"
    chunks = [json.loads(p) for p in payloads[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content") or "" for c in chunks if c["choices"])
    assert text == "Hello"
    tool = [c for c in chunks if c["choices"] and "tool_calls" in c["choices"][0]["delta"]]
    assert tool[0]["choices"][0]["delta"]["tool_calls"][0]["id"] == "tu"
    assert any(c["choices"] and c["choices"][0]["finish_reason"] == "tool_calls" for c in chunks)
    assert chunks[-1]["usage"]["completion_tokens"] == 7
    assert handle.usage.input_tokens == 12 and handle.usage.output_tokens == 7


# ─── OpenAI / koszty / okresy ─────────────────────────────────────────────

def test_openai_body_forces_usage_in_stream():
    spec = catalog.get_catalog().models["gpt-4o"]
    out = build_body({"model": "auto", "messages": [], "stream": True}, spec, stream=True)
    assert out["model"] == "gpt-4o" and out["stream_options"]["include_usage"] is True


def test_openai_usage_splits_cached():
    u = usage_from_openai({"prompt_tokens": 1000, "completion_tokens": 10, "prompt_tokens_details": {"cached_tokens": 600}})
    assert u == Usage(input_tokens=400, output_tokens=10, cached_tokens=600)


def test_cost_calculation():
    price = {"input_per_mtok": 2, "output_per_mtok": 10, "cached_input_per_mtok": Decimal("0.2"), "cache_write_per_mtok": Decimal("2.5")}
    cost = calculate_cost(price, Usage(1_000_000, 100_000, 500_000, 0))
    assert cost == Decimal("3.1")
    assert calculate_cost(None, Usage(10, 10)) == 0


def test_period_bounds():
    now = datetime(2026, 10, 21, 15, 0, tzinfo=timezone.utc)  # środa
    assert period_bounds("day", now) == ("2026-10-21", datetime(2026, 10, 22, tzinfo=timezone.utc))
    key, reset = period_bounds("week", now)
    assert key == "2026-W43" and reset == datetime(2026, 10, 26, tzinfo=timezone.utc)
    assert period_bounds("month", now) == ("2026-10", datetime(2026, 11, 1, tzinfo=timezone.utc))

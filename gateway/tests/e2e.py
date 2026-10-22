"""
Scenariusz e2e na działającej bramce (+ fake_upstream). Uruchom:  python tests/e2e.py http://localhost:8090
Używa oficjalnego SDK openai jako klienta — sprawdza zgodność "podmień tylko base_url".
"""
from __future__ import annotations

import sys
import uuid

import httpx
from openai import OpenAI, RateLimitError

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8090"
FAKE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:9999"


def check(cond, msg):
    print(("  ok   " if cond else "  FAIL ") + msg)
    if not cond:
        sys.exit(1)


ui = httpx.Client(base_url=BASE)
email = f"admin-{uuid.uuid4().hex[:6]}@example.com"
r = ui.post("/api/auth/register", json={"email": email, "password": "correct-horse-battery"})
check(r.status_code == 201, f"register → {r.status_code} role={r.json().get('role')}")
role = r.json()["role"]

for provider, key in (("anthropic", "sk-ant-test-1234567890"), ("openai", "sk-test-1234567890")):
    r = ui.put(f"/api/credentials/{provider}", json={"api_key": key})
    check(r.status_code == 200 and "…" in r.json()["key_hint"], f"store {provider} credential (hint {r.json()['key_hint']})")
check(ui.put("/api/windows/anthropic", json={"token_limit": 1_000_000, "window_seconds": 10800}).status_code == 200,
      "custom 3h anthropic window")

app = ui.post("/api/apps", json={"app_name": "Content-Agent-01", "token_budget_limit": 100_000}).json()
key = ui.post(f"/api/apps/{app['id']}/keys").json()["key"]
check(key.startswith("agx_"), "app key generated")

client = OpenAI(base_url=f"{BASE}/v1", api_key=key, default_headers={"X-App-ID": "Content-Agent-01"})

# 1. Prosty prompt → auto → cheap → haiku
raw = client.chat.completions.with_raw_response.create(
    model="auto", messages=[{"role": "user", "content": "Extract the email as JSON: jan@x.pl"}], temperature=0.3,
)
resp = raw.parse()
check(raw.headers["x-gateway-model"] == "claude-haiku-5-5", f"auto/simple → {raw.headers['x-gateway-model']} (complexity {raw.headers.get('x-gateway-complexity')})")
check(resp.choices[0].message.content == "Hello from claude", "anthropic response translated to OpenAI format")
check(resp.usage.prompt_tokens == 1000 and resp.usage.completion_tokens == 40, "usage mapped")
check(float(raw.headers["x-gateway-cost-usd"]) > 0, f"cost header {raw.headers['x-gateway-cost-usd']}")

# 2. Strategia smart przez nagłówek
raw = client.chat.completions.with_raw_response.create(
    model="auto", messages=[{"role": "user", "content": "hi"}], extra_headers={"X-Gateway-Strategy": "smart"},
)
check(raw.headers["x-gateway-model"] == "claude-opus-5-5", "X-Gateway-Strategy: smart → opus")

# 3. Streaming (Anthropic → OpenAI SSE)
stream = client.chat.completions.create(model="claude-sonnet-5-5", messages=[{"role": "user", "content": "hi"}],
                                        stream=True, stream_options={"include_usage": True})
text, usage = "", None
for chunk in stream:
    if chunk.choices:
        text += chunk.choices[0].delta.content or ""
    if chunk.usage:
        usage = chunk.usage
check(text == "Hello from claude" and usage and usage.completion_tokens == 40, f"anthropic stream → '{text}', usage={usage and usage.total_tokens}")

# 4. Fallback: haiku zwraca 429 → gpt-4o-mini
httpx.post(f"{FAKE}/control", json={"fail": ["claude-haiku-5-5"]})
raw = client.chat.completions.with_raw_response.create(
    model="auto", messages=[{"role": "user", "content": "hi"}], extra_headers={"X-Gateway-Strategy": "cheap"},
)
check(raw.headers["x-gateway-model"] == "gpt-4o-mini" and raw.headers["x-gateway-fallbacks"] == "1",
      f"429 on haiku → fallback {raw.headers['x-gateway-model']}")

# 5. Po 429 provider jest w kwarantannie — następne zapytanie od razu idzie do OpenAI (bez nowego wywołania haiku)
before = httpx.post(f"{FAKE}/control", json={"fail": []}).json()["calls"].count("claude-haiku-5-5")
raw = client.chat.completions.with_raw_response.create(
    model="auto", messages=[{"role": "user", "content": "hi"}], extra_headers={"X-Gateway-Strategy": "cheap"},
)
after = httpx.post(f"{FAKE}/control", json={"fail": []}).json()["calls"].count("claude-haiku-5-5")
check(raw.headers["x-gateway-model"] == "gpt-4o-mini" and before == after, "throttled provider skipped until reset")

# 6. OpenAI streaming passthrough
text = "".join((c.choices[0].delta.content or "") for c in client.chat.completions.create(
    model="gpt-4o", messages=[{"role": "user", "content": "hi"}], stream=True) if c.choices)
check(text == "Hello from openai", "openai stream passthrough")

# 7. Błędy nagłówków
bad = httpx.post(f"{BASE}/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                 json={"model": "auto", "messages": [{"role": "user", "content": "x"}]})
check(bad.status_code == 400 and bad.json()["error"]["code"] == "missing_app_id", "missing X-App-ID → 400")
bad = httpx.post(f"{BASE}/v1/chat/completions", headers={"Authorization": f"Bearer {key}", "X-App-ID": "other"},
                 json={"model": "auto", "messages": [{"role": "user", "content": "x"}]})
check(bad.status_code == 403, "wrong X-App-ID → 403")

# 8. Dashboard
ov = ui.get("/api/stats/overview").json()
an = next(w for w in ov["windows"] if w["provider"] == "anthropic")
check(an["upstream"]["tokens_remaining"] is not None, f"anthropic upstream window tracked (remaining {an['upstream']['tokens_remaining']})")
check(an["subscription"]["used"] > 0 and an["subscription"]["resets_at"], f"subscription window used={an['subscription']['used']}")
check(ov["today"]["requests"] >= 6, f"ledger today: {ov['today']}")
costs = ui.get("/api/stats/costs?granularity=day&days=7").json()
check(costs["rows"] and costs["rows"][0]["app_name"] == "Content-Agent-01", f"cost ledger rows: {costs['rows']}")
apps = ui.get("/api/apps").json()
check(apps[0]["usage"]["used"] > 0, f"app quota usage {apps[0]['usage']['used']}/{apps[0]['usage']['limit']}")

# 9. Twardy limit aplikacji
ui.put(f"/api/apps/{app['id']}", json={"app_name": "Content-Agent-01", "token_budget_limit": 10})
try:
    client.chat.completions.create(model="auto", messages=[{"role": "user", "content": "hi"}])
    check(False, "hard quota should block")
except RateLimitError as e:
    check("exhausted" in str(e), "hard quota → 429 app_quota_exceeded")

# 10. Podgląd routingu i uprawnienia admina
pv = ui.post("/api/routing/preview", json={"prompt": "Zaprojektuj architekturę i przeanalizuj trade-offy krok po kroku"}).json()
check(pv["strategy"] in ("smart", "balanced"), f"routing preview → {pv['strategy']} ({pv['complexity']})")
status = ui.put("/api/pricing/gpt-4o", json={"provider_name": "openai", "input_per_mtok": 2.5, "output_per_mtok": 10,
                                            "cached_input_per_mtok": 1.25}).status_code
check(status == (200 if role == "admin" else 403), f"pricing edit as {role} → {status}")

print("\nE2E: all checks passed")

# AIGateway-X

Bramka AI dla Company AI OS: jeden OpenAI-kompatybilny endpoint dla wszystkich agentów i aplikacji,
z routingiem modeli, fallbackiem, limitami tokenów i ledgerem kosztów per aplikacja.
Dashboard: [`../gateway-ui`](../gateway-ui) (Next.js).

```
agent ──(OpenAI SDK, base_url=bramka, Bearer agx_…, X-App-ID)──▶ gateway :8090
                                                                   │ routing.yml (tiery + fallback)
                                                                   ├─▶ api.anthropic.com  (tłumaczenie ⇄ OpenAI)
                                                                   ├─▶ api.openai.com     (1:1)
                                                                   └─▶ LiteLLM/Ollama GPU (1:1)
Postgres: użytkownicy, klucze (Fernet), aplikacje, cennik, gw_token_logs, okna limitów
Redis:    liczniki kwot aplikacji, TPM, okna subskrypcji, snapshot nagłówków rate-limit, cost:* (CostGate)
```

## Uruchomienie

```bash
make gateway-keys            # wklej GATEWAY_JWT_SECRET i GATEWAY_ENCRYPTION_KEY do .env.agents
make gateway                 # gateway :8090 + dashboard :3100 (profil `gateway`, startuje też z `agents`)
```

Pierwsze zarejestrowane konto zostaje adminem. Kolejne rejestracje działają tylko przy `GATEWAY_ALLOW_SIGNUP=true`.
Produkcja: https://ai-cost.webaby.io (serwer 95.158.64.196, vhost [`nginx/ai-cost.webaby.io.conf`](../nginx/ai-cost.webaby.io.conf)).
Wdrożenia robi GitHub Actions — patrz [`deploy/README.md`](../deploy/README.md).

## Użycie z agenta

```python
from openai import OpenAI

client = OpenAI(base_url="http://gateway:8090/v1", api_key="agx_…",
                default_headers={"X-App-ID": "Content-Agent-01"})
client.chat.completions.create(
    model="auto",                                  # albo model z katalogu, np. "claude-sonnet-5-5"
    messages=[{"role": "user", "content": "…"}],
    extra_headers={"X-Gateway-Strategy": "cheap"}, # cheap | smart | fast | auto (domyślna z aplikacji)
)
```

`BaseAgent.call_llm()` robi to automatycznie, gdy ustawione są `GATEWAY_URL` i `GATEWAY_APP_KEY`.
Nazwa aplikacji w bramce musi wtedy być równa `AGENT_NAME`. Stare nazwy modeli z LiteLLM
(`claude-sonnet-4` …) są mapowane przez `aliases` w `routing.yml`.

Nagłówki odpowiedzi: `X-Gateway-Model`, `X-Gateway-Provider`, `X-Gateway-Strategy`,
`X-Gateway-Complexity` (dla `auto`), `X-Gateway-Fallbacks`, `X-Gateway-Cost-USD` (bez streamingu),
`X-Gateway-Quota-Warning` (po przekroczeniu miękkiego progu).

## Jak to działa

| Mechanizm | Zachowanie |
|---|---|
| Routing | `routing.yml`: strategia → tier → uporządkowana lista modeli. `auto` liczy heurystyczną złożoność promptu (długość, słowa kluczowe PL/EN, kod, tools) bez dodatkowego wywołania LLM. |
| Fallback | 429 / 5xx / 401 / timeout → następny kandydat. 400/413/422 zwracane od razu (inny provider też by odrzucił). Provider bez klucza albo z wyczerpanym oknem jest pomijany. |
| Limity providera | Nagłówki `x-ratelimit-*` (OpenAI) i `anthropic-ratelimit-*` zapisywane per użytkownik. `remaining = 0` → provider pomijany do resetu. 429 bez nagłówków → 30 s kwarantanny. |
| Okno subskrypcji | Własny limit, np. 1M tokenów / 3h, ustawiany per provider. Okno startuje przy pierwszym użyciu. |
| Kwoty aplikacji | Twardy limit tokenów na dzień/tydzień/miesiąc (429), miękki próg % (wymusza tier `soft_limit_strategy`) i TPM. |
| Ledger | Każde zapytanie (też błędy i przerwane strumienie) trafia do `gw_token_logs` z kosztem z `gw_model_pricing`. Wydatki zwiększają też liczniki `cost:daily:*` / `cost:monthly:*`, więc budżety `shared/cost_gate.py` je widzą. |

Uwagi do tłumaczenia Anthropic: modele 5.x odrzucają `temperature`/`top_p` (usuwane przez `drop_params`)
oraz wymuszone `tool_choice` (`required`/konkretne narzędzie → `auto`). Bloki `thinking` są pomijane.

## Testy

```bash
cd gateway && python -m pytest -q                      # testy jednostkowe (routing, nagłówki, tłumaczenie, koszty)

# e2e: Postgres + Redis + atrapa OpenAI/Anthropic, klient = oficjalny SDK openai
uvicorn tests.fake_upstream:app --port 9999 &
OPENAI_BASE_URL=http://localhost:9999/openai/v1 ANTHROPIC_BASE_URL=http://localhost:9999/anthropic/v1 \
  DATABASE_URL=… REDIS_URL=… GATEWAY_JWT_SECRET=… GATEWAY_ENCRYPTION_KEY=… GATEWAY_COOKIE_SECURE=false \
  uvicorn app.main:app --port 8090 &
pip install openai && python tests/e2e.py http://localhost:8090
```

Cennik w `database/gateway.sql` to stan na 2026-10. Zmiany robi admin w dashboardzie (zakładka Cennik).

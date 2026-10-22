-- AIGateway-X — schemat bramki AI (proxy, limity, ledger kosztów)
-- Idempotentny: wykonywany przez usługę gateway przy każdym starcie,
-- więc działa także na istniejącej bazie (init.sql odpala się tylko raz).

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── UŻYTKOWNICY ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gw_users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── KLUCZE UPSTREAM (zaszyfrowane Fernet) ────────────────────────────────

CREATE TABLE IF NOT EXISTS gw_provider_credentials (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES gw_users(id) ON DELETE CASCADE,
    provider_name       TEXT NOT NULL CHECK (provider_name IN ('openai', 'anthropic')),
    encrypted_api_key   TEXT NOT NULL,
    key_hint            TEXT NOT NULL,          -- np. "sk-ant-…a1b2" do wyświetlania
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, provider_name)
);

-- ─── APLIKACJE (agenci korzystający z bramki) ─────────────────────────────

CREATE TABLE IF NOT EXISTS gw_applications (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES gw_users(id) ON DELETE CASCADE,
    app_name            TEXT NOT NULL,          -- wartość nagłówka X-App-ID
    token_budget_limit  BIGINT,                 -- twardy limit tokenów na okres (NULL = brak)
    soft_limit_pct      INT NOT NULL DEFAULT 80 CHECK (soft_limit_pct BETWEEN 1 AND 100),
    budget_period       TEXT NOT NULL DEFAULT 'month' CHECK (budget_period IN ('day', 'week', 'month')),
    tpm_limit           INT,                    -- tokeny / minutę (NULL = brak)
    default_strategy    TEXT NOT NULL DEFAULT 'auto' CHECK (default_strategy IN ('auto', 'cheap', 'smart', 'fast')),
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, app_name)
);

-- Klucze aplikacji: przechowujemy tylko SHA-256, pełny klucz widać raz przy tworzeniu
CREATE TABLE IF NOT EXISTS gw_app_keys (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    app_id          UUID NOT NULL REFERENCES gw_applications(id) ON DELETE CASCADE,
    key_hash        TEXT NOT NULL UNIQUE,
    key_prefix      TEXT NOT NULL,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    last_used_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── CENNIK ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gw_model_pricing (
    model                   TEXT PRIMARY KEY,
    provider_name           TEXT NOT NULL,
    input_per_mtok          NUMERIC(12, 4) NOT NULL,
    output_per_mtok         NUMERIC(12, 4) NOT NULL,
    cached_input_per_mtok   NUMERIC(12, 4) NOT NULL DEFAULT 0,
    cache_write_per_mtok    NUMERIC(12, 4) NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Ceny USD / 1M tokenów (stan: 2026-10). Edytowalne w dashboardzie (admin).
INSERT INTO gw_model_pricing (model, provider_name, input_per_mtok, output_per_mtok, cached_input_per_mtok, cache_write_per_mtok) VALUES
    ('claude-opus-5-5',   'anthropic', 4.00,  20.00, 0.20,  5.00),
    ('claude-sonnet-5-5', 'anthropic', 2.00,  10.00, 0.20,  2.50),
    ('claude-haiku-5-5',  'anthropic', 0.10,   0.50, 0.01,  0.125),
    ('gpt-4.1',           'openai',    2.00,   8.00, 0.50,  0),
    ('gpt-4.1-mini',      'openai',    0.40,   1.60, 0.10,  0),
    ('gpt-4o',            'openai',    2.50,  10.00, 1.25,  0),
    ('gpt-4o-mini',       'openai',    0.15,   0.60, 0.075, 0),
    ('ollama-mistral',    'litellm',   0,      0,    0,     0),
    ('ollama-llama3-70b', 'litellm',   0,      0,    0,     0)
ON CONFLICT (model) DO NOTHING;

-- ─── LEDGER ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS gw_token_logs (
    id                  BIGSERIAL PRIMARY KEY,
    app_id              UUID NOT NULL REFERENCES gw_applications(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES gw_users(id) ON DELETE CASCADE,
    provider_name       TEXT NOT NULL,
    model_used          TEXT NOT NULL,
    requested_model     TEXT,
    strategy            TEXT,
    input_tokens        INT NOT NULL DEFAULT 0,     -- bez tokenów z cache
    output_tokens       INT NOT NULL DEFAULT 0,
    cached_tokens       INT NOT NULL DEFAULT 0,     -- odczyt z cache
    cache_write_tokens  INT NOT NULL DEFAULT 0,
    calculated_cost     NUMERIC(14, 8) NOT NULL DEFAULT 0,   -- USD
    latency_ms          INT,
    status              TEXT NOT NULL,              -- success | error
    fallback_count      INT NOT NULL DEFAULT 0,
    error               TEXT,
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gw_logs_user_ts ON gw_token_logs(user_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_gw_logs_app_ts  ON gw_token_logs(app_id, timestamp DESC);

-- ─── OKNA LIMITÓW ─────────────────────────────────────────────────────────
-- Jeden wiersz na (użytkownik, provider). Łączy:
--   * własne okno subskrypcji (np. 1M tokenów / 3h) — token_limit + window_seconds
--   * ostatni snapshot nagłówków rate-limit od providera (upstream_*)

CREATE TABLE IF NOT EXISTS gw_rate_limit_windows (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                     UUID NOT NULL REFERENCES gw_users(id) ON DELETE CASCADE,
    provider_name               TEXT NOT NULL,
    token_limit                 BIGINT,
    window_seconds              INT,
    current_token_count         BIGINT NOT NULL DEFAULT 0,
    window_reset_at             TIMESTAMPTZ,
    upstream_tokens_limit       BIGINT,
    upstream_tokens_remaining   BIGINT,
    upstream_tokens_reset_at    TIMESTAMPTZ,
    upstream_requests_limit     BIGINT,
    upstream_requests_remaining BIGINT,
    upstream_requests_reset_at  TIMESTAMPTZ,
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, provider_name)
);

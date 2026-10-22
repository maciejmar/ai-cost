-- Company AI OS — Schemat bazy danych
-- Uruchamiany automatycznie przez PostgreSQL przy pierwszym starcie

-- Rozszerzenia
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── AGENTY ───────────────────────────────────────────────────────────────

CREATE TYPE agent_status AS ENUM ('idle', 'working', 'waiting', 'failed', 'stopped');
CREATE TYPE agent_type AS ENUM (
    'mastermind', 'dev_mastermind', 'infra_mastermind', 'marketing_mastermind',
    'spec', 'repo', 'dev', 'qa', 'fix', 'security', 'devops', 'smoke',
    'cost', 'self_improvement', 'marketing_script', 'marketing_voice',
    'marketing_visual', 'marketing_video', 'marketing_distribution',
    'whatsapp_webhook', 'dashboard'
);

CREATE TABLE agents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    type        agent_type NOT NULL,
    status      agent_status NOT NULL DEFAULT 'idle',
    current_action TEXT,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agents_status ON agents(status);

-- ─── ZADANIA ──────────────────────────────────────────────────────────────

CREATE TYPE task_status AS ENUM (
    'queued', 'in_progress', 'completed', 'failed', 'escalated', 'cancelled'
);

CREATE TABLE tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    correlation_id  UUID NOT NULL DEFAULT uuid_generate_v4(),
    agent_id        UUID REFERENCES agents(id),
    goal            TEXT NOT NULL,
    status          task_status NOT NULL DEFAULT 'queued',
    cost_estimated  NUMERIC(10, 4),
    cost_actual     NUMERIC(10, 4) DEFAULT 0,
    fix_attempts    INT NOT NULL DEFAULT 0,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    result          JSONB,
    error_details   TEXT
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_correlation ON tasks(correlation_id);
CREATE INDEX idx_tasks_created ON tasks(created_at DESC);

-- ─── WYWOŁANIA LLM ────────────────────────────────────────────────────────

CREATE TABLE llm_calls (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID REFERENCES agents(id),
    task_id         UUID REFERENCES tasks(id),
    model           TEXT NOT NULL,
    provider        TEXT NOT NULL,      -- anthropic, openai, ollama
    input_tokens    INT NOT NULL DEFAULT 0,
    output_tokens   INT NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10, 6) NOT NULL DEFAULT 0,
    duration_ms     INT,
    status          TEXT NOT NULL,      -- success, error, cached
    langfuse_trace_id TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_calls_agent ON llm_calls(agent_id);
CREATE INDEX idx_llm_calls_created ON llm_calls(created_at DESC);
CREATE INDEX idx_llm_calls_model ON llm_calls(model, created_at DESC);

-- ─── ZATWIERDZENIA KOSZTÓW ────────────────────────────────────────────────

CREATE TYPE approval_status AS ENUM ('pending', 'approved', 'rejected', 'timeout');

CREATE TABLE cost_approvals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    approval_id     TEXT NOT NULL UNIQUE,   -- krótki ID wysyłany przez WhatsApp
    agent_name      TEXT NOT NULL,
    model           TEXT NOT NULL,
    estimated_cost  NUMERIC(10, 4) NOT NULL,
    context         TEXT,
    status          approval_status NOT NULL DEFAULT 'pending',
    decided_by      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at      TIMESTAMPTZ
);

CREATE INDEX idx_approvals_status ON cost_approvals(status, created_at DESC);

-- ─── EVENTY (audit log) ───────────────────────────────────────────────────

CREATE TABLE events_log (
    id          BIGSERIAL PRIMARY KEY,
    event_id    UUID NOT NULL,
    event_type  TEXT NOT NULL,
    publisher   TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    correlation_id UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_type ON events_log(event_type, created_at DESC);
CREATE INDEX idx_events_created ON events_log(created_at DESC);
CREATE INDEX idx_events_correlation ON events_log(correlation_id);

-- Immutable audit log — brak UPDATE/DELETE na events_log
CREATE RULE events_log_no_update AS ON UPDATE TO events_log DO INSTEAD NOTHING;
CREATE RULE events_log_no_delete AS ON DELETE TO events_log DO INSTEAD NOTHING;

-- ─── WIDOKI KOSZTÓW ───────────────────────────────────────────────────────

CREATE VIEW cost_daily AS
SELECT
    DATE(created_at) AS day,
    agent_id,
    a.name AS agent_name,
    model,
    COUNT(*) AS num_calls,
    SUM(input_tokens) AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    SUM(cost_usd) AS total_cost_usd
FROM llm_calls lc
JOIN agents a ON lc.agent_id = a.id
GROUP BY DATE(created_at), agent_id, a.name, model;

CREATE VIEW cost_monthly AS
SELECT
    DATE_TRUNC('month', created_at) AS month,
    a.name AS agent_name,
    SUM(cost_usd) AS total_cost_usd,
    COUNT(*) AS num_calls
FROM llm_calls lc
JOIN agents a ON lc.agent_id = a.id
GROUP BY DATE_TRUNC('month', created_at), a.name;

-- ─── TRIGGERY AUTO-UPDATE ─────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── DANE INICJALNE ───────────────────────────────────────────────────────

INSERT INTO agents (name, type) VALUES
    ('mastermind',              'mastermind'),
    ('spec-agent',              'spec'),
    ('repo-agent',              'repo'),
    ('dev-agent',               'dev'),
    ('qa-agent',                'qa'),
    ('fix-agent',               'fix'),
    ('security-agent',          'security'),
    ('devops-agent',            'devops'),
    ('smoke-agent',             'smoke'),
    ('cost-agent',              'cost'),
    ('self-improvement-agent',  'self_improvement'),
    ('marketing-mastermind',    'marketing_mastermind'),
    ('whatsapp-webhook',        'whatsapp_webhook'),
    ('dashboard-backend',       'dashboard')
ON CONFLICT (name) DO NOTHING;

-- 001_initial_schema.sql
-- Prompt Manager database schema

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Prompts ──────────────────────────────────────────────────────────────────

CREATE TABLE prompts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    description     TEXT,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    metadata        JSONB NOT NULL DEFAULT '{}',
    current_version INT NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_prompts_slug ON prompts (slug);
CREATE INDEX idx_prompts_tags ON prompts USING GIN (tags);

-- ── Prompt Versions ──────────────────────────────────────────────────────────

CREATE TABLE prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    version         INT NOT NULL,
    body            TEXT NOT NULL,
    model_hint      TEXT,
    template_vars   TEXT[] NOT NULL DEFAULT '{}',
    content_hash    TEXT NOT NULL,
    parent_version  INT,
    source          TEXT NOT NULL DEFAULT 'manual',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (prompt_id, version),
    UNIQUE (prompt_id, content_hash)
);

CREATE INDEX idx_versions_prompt ON prompt_versions (prompt_id, version DESC);

-- ── Experiments ──────────────────────────────────────────────────────────────

CREATE TABLE experiments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',
    sticky          BOOLEAN NOT NULL DEFAULT TRUE,
    auto_optimize   BOOLEAN NOT NULL DEFAULT FALSE,
    min_sample_size INT NOT NULL DEFAULT 100,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_experiments_prompt_status ON experiments (prompt_id, status);

-- ── Experiment Arms ──────────────────────────────────────────────────────────

CREATE TABLE experiment_arms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id   UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    version_id      UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
    weight          DOUBLE PRECISION NOT NULL,
    label           TEXT
);

CREATE INDEX idx_arms_experiment ON experiment_arms (experiment_id);

-- ── Metric Events ────────────────────────────────────────────────────────────

CREATE TABLE metric_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    version_id      UUID NOT NULL REFERENCES prompt_versions(id) ON DELETE CASCADE,
    experiment_id   UUID REFERENCES experiments(id) ON DELETE SET NULL,
    arm_id          UUID REFERENCES experiment_arms(id) ON DELETE SET NULL,
    session_id      TEXT,
    metric_name     TEXT NOT NULL,
    metric_value    DOUBLE PRECISION NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_metrics_prompt_name ON metric_events (prompt_id, metric_name);
CREATE INDEX idx_metrics_version ON metric_events (version_id);
CREATE INDEX idx_metrics_experiment ON metric_events (experiment_id) WHERE experiment_id IS NOT NULL;
CREATE INDEX idx_metrics_created ON metric_events (created_at DESC);

-- ── Optimization Runs ────────────────────────────────────────────────────────

CREATE TABLE optimization_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id) ON DELETE CASCADE,
    status          TEXT NOT NULL DEFAULT 'pending',
    objective       TEXT,
    input_version   INT NOT NULL,
    output_version  INT,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_optim_prompt ON optimization_runs (prompt_id, status);

-- ── Session Assignments (sticky experiment routing) ──────────────────────────

CREATE TABLE session_assignments (
    experiment_id   UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    session_id      TEXT NOT NULL,
    arm_id          UUID NOT NULL REFERENCES experiment_arms(id) ON DELETE CASCADE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (experiment_id, session_id)
);

# Prompt Manager Library — Deep Design Brainstorm

---

## 1. API Design

### REST API (Primary)

The REST API should feel familiar to anyone who has used Stripe or LaunchDarkly. Resource-oriented, predictable, paginated.

```
# Prompts
POST   /v1/prompts                     # Create prompt
GET    /v1/prompts                     # List prompts (paginated, filterable)
GET    /v1/prompts/:slug               # Get prompt (latest version by default)
PATCH  /v1/prompts/:slug               # Update metadata (name, tags, description)
DELETE /v1/prompts/:slug               # Soft-delete (archive)

# Versions
POST   /v1/prompts/:slug/versions      # Create new version
GET    /v1/prompts/:slug/versions      # List versions
GET    /v1/prompts/:slug/versions/:v   # Get specific version
POST   /v1/prompts/:slug/versions/:v/promote  # Promote to "latest"
POST   /v1/prompts/:slug/versions/:v/rollback # Rollback (creates new version pointing to old content)

# Experiments
POST   /v1/prompts/:slug/experiments   # Create experiment
GET    /v1/prompts/:slug/experiments   # List experiments
GET    /v1/experiments/:id             # Get experiment details
PATCH  /v1/experiments/:id             # Update weights, pause, resume
POST   /v1/experiments/:id/conclude    # End experiment, promote winner
DELETE /v1/experiments/:id             # Archive experiment

# Metrics
POST   /v1/metrics                     # Ingest metric signal (batch-friendly)
GET    /v1/prompts/:slug/metrics       # Aggregated metrics for a prompt
GET    /v1/experiments/:id/metrics     # Per-variant metrics for experiment

# Optimization
POST   /v1/prompts/:slug/optimize      # Trigger manual optimization
GET    /v1/optimization-runs           # List optimization history
GET    /v1/optimization-runs/:id       # Get details of a run

# Resolve (the hot path — what the client SDK calls)
GET    /v1/resolve/:slug               # Returns the prompt text for this caller
  ?session_id=...                      # For sticky routing
  ?context={"key":"val"}               # For template interpolation
  ?experiment=...                      # Force a specific experiment
  ?version=...                         # Force a specific version (override)

# Health & Admin
GET    /healthz
GET    /v1/config                      # Current server config (non-sensitive)
POST   /v1/config/llm                  # Update LLM provider credentials
```

### Why REST over gRPC

For a developer-tools library, REST is the right primary choice. The audience is application developers who want to curl endpoints, debug in browser dev tools, and integrate with any language. gRPC adds complexity for marginal latency gains on what are fundamentally low-QPS management calls.

The one exception is the `/v1/resolve` endpoint — this is the hot path. For this, consider offering both REST and a lightweight WebSocket/SSE channel for clients that want to subscribe to prompt changes in real time (push model rather than poll).

### MCP Tools

MCP (Model Context Protocol) exposure lets AI agents interact with the prompt manager directly. The tools should map to the most useful operations:

```
Tool: get_prompt         — Resolve a prompt by slug (with optional version/experiment)
Tool: list_prompts       — List available prompts with metadata
Tool: create_prompt      — Create a new prompt
Tool: update_prompt      — Create a new version of an existing prompt
Tool: get_experiment     — Get experiment status and metrics
Tool: adjust_experiment  — Modify experiment weights
Tool: run_optimization   — Trigger LLM optimization for a prompt
Tool: report_metric      — Send a quality/performance signal
```

The MCP server should be a separate entrypoint that can be enabled/disabled via config. It reuses the same service layer as the HTTP API.

---

## 2. Data Model

### Core Entities

```
┌─────────────┐       ┌──────────────────┐
│   prompts    │──1:N──│  prompt_versions  │
└─────────────┘       └──────────────────┘
       │                       │
      1:N                     N:M
       │                       │
       ▼                       ▼
┌─────────────┐       ┌──────────────────┐
│ experiments  │──1:N──│ experiment_arms   │
└─────────────┘       └──────────────────┘
       │
      1:N
       │
       ▼
┌──────────────────┐
│ metric_events     │
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ optimization_runs │
└──────────────────┘
```

### Table Designs

```sql
-- The prompt is the top-level entity. Identified by a human-readable slug.
CREATE TABLE prompts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT NOT NULL UNIQUE,       -- e.g. "welcome-email", "summarize-article"
    name            TEXT NOT NULL,
    description     TEXT,
    tags            TEXT[] DEFAULT '{}',
    metadata        JSONB DEFAULT '{}',         -- Arbitrary user data
    current_version INT NOT NULL DEFAULT 1,     -- Points to the "latest" version number
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each version is immutable once created. You never edit a version — you create a new one.
CREATE TABLE prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id),
    version         INT NOT NULL,               -- Monotonically increasing per prompt
    body            TEXT NOT NULL,               -- The actual prompt template
    model_hint      TEXT,                        -- Suggested model (e.g. "claude-sonnet-4-20250514")
    template_vars   TEXT[] DEFAULT '{}',         -- Declared variables like ["name", "context"]
    content_hash    TEXT NOT NULL,               -- SHA-256 of body, for dedup
    parent_version  INT,                         -- Which version this was derived from
    source          TEXT DEFAULT 'manual',       -- 'manual' | 'optimization' | 'rollback' | 'import'
    created_by      TEXT,                        -- User or system identifier
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(prompt_id, version)
);

-- An experiment splits traffic between multiple versions of the same prompt.
CREATE TABLE experiments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id),
    name            TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',  -- 'draft' | 'running' | 'paused' | 'concluded'
    sticky          BOOLEAN DEFAULT true,           -- Whether session_id pins to an arm
    auto_optimize   BOOLEAN DEFAULT false,          -- Let the optimizer adjust weights
    min_sample_size INT DEFAULT 100,                -- Per arm, before optimizer can act
    started_at      TIMESTAMPTZ,
    concluded_at    TIMESTAMPTZ,
    winner_arm_id   UUID,                           -- Set when concluded
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Each arm in an experiment points to a version and has a weight.
CREATE TABLE experiment_arms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id   UUID NOT NULL REFERENCES experiments(id),
    version_id      UUID NOT NULL REFERENCES prompt_versions(id),
    weight          REAL NOT NULL CHECK (weight >= 0 AND weight <= 100),
    label           TEXT,                           -- e.g. "control", "variant-a"
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Raw metric events. Append-only, high-volume.
CREATE TABLE metric_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id),
    version_id      UUID NOT NULL REFERENCES prompt_versions(id),
    experiment_id   UUID REFERENCES experiments(id),
    arm_id          UUID REFERENCES experiment_arms(id),
    session_id      TEXT,                           -- Caller-provided correlation ID
    metric_name     TEXT NOT NULL,                  -- e.g. "quality", "latency_ms", "thumbs_up"
    metric_value    DOUBLE PRECISION NOT NULL,      -- Numeric value
    metadata        JSONB DEFAULT '{}',             -- Extra context
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Tracks every optimization attempt.
CREATE TABLE optimization_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id),
    experiment_id   UUID REFERENCES experiments(id),
    trigger         TEXT NOT NULL,                  -- 'manual' | 'scheduled' | 'metric_threshold'
    llm_provider    TEXT NOT NULL,
    llm_model       TEXT NOT NULL,
    input_version   INT NOT NULL,
    output_version  INT,
    input_metrics   JSONB NOT NULL,
    llm_reasoning   TEXT,
    proposed_body   TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending', -- 'pending' | 'accepted' | 'rejected' | 'auto_deployed'
    reviewed_by     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sticky session assignments for experiments.
CREATE TABLE session_assignments (
    session_id      TEXT NOT NULL,
    experiment_id   UUID NOT NULL REFERENCES experiments(id),
    arm_id          UUID NOT NULL REFERENCES experiment_arms(id),
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, experiment_id)
);
```

### Key Design Decisions

- **Slugs, not IDs, as the public interface.** Developers think in names. `resolve("welcome-email")` is better than `resolve("550e8400-...")`.
- **Versions are immutable.** This is critical. You can always reproduce what was served at any point in time.
- **`content_hash` enables dedup.** If someone creates a "new version" with identical content, detect it and point to the existing one.
- **`source` on versions tracks lineage.** You can always tell whether a version came from a human, the optimizer, a rollback, or an import.
- **Soft deletes via `archived_at`.** Prompts are never truly deleted — they may be referenced by historical metrics.

---

## 3. Experiment Engine

### Routing Algorithm

The resolve endpoint is the heart of the system. Decision tree:

```
resolve(slug, session_id?, version?, experiment?)
  │
  ├── version specified? → Return that exact version. Done.
  │
  ├── experiment specified? → Use that experiment's routing.
  │
  ├── Active experiment on this prompt?
  │     ├── YES, and session_id provided, and experiment is sticky?
  │     │     ├── Session already assigned? → Return assigned arm's version.
  │     │     └── Not assigned? → Weighted random → Persist assignment → Return.
  │     │
  │     ├── YES, but no session_id or not sticky?
  │     │     └── Weighted random → Return.
  │     │
  │     └── Multiple active experiments? → Use the one with highest priority.
  │
  └── No experiment? → Return current_version (the "latest promoted" version).
```

### Weighted Random Selection

```python
import random

def select_arm(arms: list[Arm]) -> Arm:
    total = sum(arm.weight for arm in arms)
    remainder = 100.0 - total

    roll = random.uniform(0, 100)

    if roll < remainder:
        return None  # Serve default/control

    cumulative = remainder
    for arm in arms:
        cumulative += arm.weight
        if roll < cumulative:
            return arm

    return arms[-1]  # Floating point safety
```

The insight: **the sum of weights being less than 100 is a feature, not a bug.** The remaining percentage serves the default prompt. This lets you run an experiment at 10% traffic without disrupting 90% of users.

### Sticky Sessions

Sticky sessions use the `session_assignments` table. Essential for:
- Users who interact with the same prompt multiple times in a session (chatbots)
- Metrics that need to be attributed to a specific variant
- Avoiding jarring UX of seeing different prompt behaviors mid-conversation

### Multi-Armed Bandit Mode

When `auto_optimize` is true on an experiment, the system shifts from pure A/B testing to Thompson Sampling or Epsilon-Greedy:

```
Every N metric events (configurable):
  1. Compute per-arm performance (mean metric value, confidence interval)
  2. If an arm is statistically worse (p < 0.05), reduce its weight
  3. Redistribute weight to better-performing arms
  4. Log the weight change as an optimization event
```

This is distinct from the LLM optimization loop (which changes prompt *content*). The bandit adjusts *traffic distribution* among existing variants.

---

## 4. Optimization Loop

### Feedback Signal Types

| Signal Type | Example | How It Is Used |
|---|---|---|
| **Explicit** | thumbs_up/down, 1-5 rating | Direct quality signal |
| **Implicit** | latency_ms, token_count, retry_count | Efficiency signal |
| **Derived** | LLM-as-judge score, regex match rate | Automated quality signal |

### Composite Score

```python
composite = (
    weights["quality"] * normalize(avg_quality_score) +
    weights["efficiency"] * normalize(1 / avg_latency) +
    weights["success_rate"] * normalize(success_count / total_count)
)
```

### Regression Prevention — Guard Rails

1. **Shadow Testing.** Optimized prompt is never deployed directly. Added as a new arm at low weight (5%). Only promoted after demonstrating improvement over `min_sample_size` invocations.

2. **Rollback Trigger.** If new version's composite score drops below control's by configurable threshold, arm is auto-paused and weight redistributed.

3. **Human-in-the-Loop Gate.** By default, optimization runs produce `pending` entries requiring human review. Only with explicit `auto_deploy: true` does the system act autonomously.

4. **Optimization Budget.** Configurable limit on optimization runs per prompt per time window. Prevents runaway loops.

5. **Content Diff Review.** Large diffs (high edit distance) flagged for human review even in auto mode.

6. **Monotonic Version History.** Every change is a new version. Nothing is ever lost.

---

## 5. Client SDK Design

### Python Client

```python
from prompt_manager import PromptClient

client = PromptClient(
    url="http://localhost:8420",
    api_key="pm_live_...",
    cache_ttl=60,
    fallback_dir="./prompts_fallback",
    timeout=2.0,
)

# Simple — get the current prompt
prompt = await client.get("welcome-email")

# With template rendering
rendered = await client.render("welcome-email", {"name": "Alice"})

# With experiment routing
prompt = await client.get("welcome-email", session_id="user_123")

# Report a metric
await client.report_metric(
    slug="welcome-email",
    session_id="user_123",
    metrics={"quality": 0.9, "thumbs_up": 1}
)
```

### Caching Strategy (Three-Layer)

1. **In-memory LRU** — hot path, sub-ms. TTL-based expiration.
2. **Local file fallback** — cold start, disaster recovery. App never crashes because prompt manager is down.
3. **ETag-based revalidation** — server returns 304 if nothing changed, saving bandwidth.

### Client-Side Routing (Advanced)

For high-throughput apps, the client can download experiment config and do routing locally:

```python
client = PromptClient(
    url="http://localhost:8420",
    local_routing=True,
    sync_interval=30,
)
```

---

## 6. Technology Stack

| Component | Choice | Rationale |
|---|---|---|
| Language | **Python (asyncio)** | Target audience is ML/AI teams |
| Web framework | **FastAPI** | Async, auto-generated OpenAPI docs |
| PostgreSQL driver | **asyncpg** | Fastest async PG driver for Python |
| LLM integration | **litellm** (or custom abstraction) | Single interface to all providers |
| MCP | **mcp** (Anthropic SDK) | Official MCP Python SDK |
| Config | **Pydantic Settings** | Env vars + validation in one |
| Client SDK | **httpx** | Modern async HTTP client |

### Installation

```bash
pip install prompt-manager[client]          # Just the client
pip install prompt-manager[client,metric]   # Client + metric reporting
pip install prompt-manager[api]             # Full server
pip install prompt-manager[all]             # Everything
```

---

## 7. Edge Cases

- **Server restart**: Client SDK serves from cache/fallback. No impact.
- **Version rollback**: Creates a new version with same content (preserves audit trail).
- **Experiment conflicts**: Only one `running` experiment per prompt at a time.
- **Template variable mismatch**: Optimizer output validated against original vars.
- **Metric storms**: Rate limiting + batch ingestion via `COPY`.
- **Clock skew**: Server-assigned `created_at` used for aggregation.

---

## 8. Innovative Ideas

1. **Prompt Diff View** — Store and expose diffs between versions with LLM reasoning.
2. **Prompt Lineage Graph** — DAG of prompt evolution (like git history).
3. **Canary Deployments** — Auto-create 5% canary experiments for new versions.
4. **Collaborative Optimization** — Multiple LLMs propose improvements, a judge picks the best.
5. **Semantic Versioning** — Detect nature of change (patch/minor/major) based on edit distance.
6. **Contextual Routing** — Route different input types to different prompt versions (contextual bandits).
7. **Prompt Composition** — `{{@slug}}` syntax to reference and compose other prompts.
8. **Time-Travel Queries** — `?as_of=2025-01-15T00:00:00Z` to resolve historical prompts.

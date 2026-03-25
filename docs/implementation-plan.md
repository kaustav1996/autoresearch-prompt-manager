# Prompt Manager Library — Implementation Plan

## 1. Project Structure (Monorepo Layout)

```
autoresearch-prompt-manager/
├── pyproject.toml                    # Root: workspace definition
├── alembic.ini                       # Alembic config
├── .env.example
├── docker-compose.yml                # PostgreSQL + service for local dev
│
├── src/
│   └── prompt_manager/
│       ├── __init__.py               # Shared version, constants
│       │
│       ├── core/                     # Shared kernel (no extra deps)
│       │   ├── __init__.py
│       │   ├── models.py             # Pydantic domain models
│       │   ├── schemas.py            # Request/response schemas (Pydantic v2)
│       │   ├── enums.py              # Status enums, LLM provider enum
│       │   ├── exceptions.py         # Domain exceptions
│       │   └── config.py             # Settings via pydantic-settings
│       │
│       ├── api/                      # prompt_manager[api]
│       │   ├── __init__.py
│       │   ├── app.py                # FastAPI app factory
│       │   ├── deps.py               # Dependency injection
│       │   ├── main.py               # Entrypoint: uvicorn runner
│       │   ├── routers/
│       │   │   ├── __init__.py
│       │   │   ├── prompts.py        # /prompts CRUD
│       │   │   ├── versions.py       # /prompts/{id}/versions
│       │   │   ├── experiments.py    # /experiments CRUD + routing config
│       │   │   ├── metrics.py        # /metrics ingest + query
│       │   │   └── optimize.py       # /optimize trigger + status
│       │   ├── db/
│       │   │   ├── __init__.py
│       │   │   ├── engine.py         # asyncpg pool creation
│       │   │   ├── repository.py     # Base repository
│       │   │   ├── prompts_repo.py
│       │   │   ├── versions_repo.py
│       │   │   ├── experiments_repo.py
│       │   │   └── metrics_repo.py
│       │   ├── services/
│       │   │   ├── __init__.py
│       │   │   ├── prompt_service.py
│       │   │   ├── experiment_service.py
│       │   │   ├── metric_service.py
│       │   │   └── optimization_service.py
│       │   └── mcp/
│       │       ├── __init__.py
│       │       └── server.py         # MCP tool definitions
│       │
│       ├── client/                   # prompt_manager[client]
│       │   ├── __init__.py
│       │   ├── client.py             # PromptManagerClient class
│       │   ├── cache.py              # Optional local TTL cache
│       │   └── exceptions.py
│       │
│       ├── metric/                   # prompt_manager[metric]
│       │   ├── __init__.py
│       │   ├── collector.py          # MetricCollector class
│       │   ├── reporter.py           # Batched async metric sender
│       │   └── decorators.py         # @track_metric decorator
│       │
│       └── llm/                      # LLM abstraction (shared by api)
│           ├── __init__.py
│           ├── base.py               # Abstract LLMProvider
│           ├── factory.py            # Provider factory from config
│           ├── providers/
│           │   ├── __init__.py
│           │   ├── anthropic.py      # Claude
│           │   ├── openai.py         # OpenAI + OpenRouter
│           │   ├── groq.py
│           │   ├── gemini.py
│           │   ├── bedrock.py
│           │   └── custom.py         # Generic OpenAI-compatible
│           └── prompt_improver.py    # LLM-powered optimization logic
│
├── migrations/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_models.py
│   │   ├── test_experiment_routing.py
│   │   ├── test_prompt_improver.py
│   │   └── test_client.py
│   ├── integration/
│   │   ├── test_api_prompts.py
│   │   ├── test_api_experiments.py
│   │   ├── test_api_metrics.py
│   │   └── test_optimization_loop.py
│   └── e2e/
│       └── test_full_workflow.py
│
├── examples/
│   ├── basic_usage.py
│   └── experiment_setup.py
│
├── config/
│   └── default.toml
│
└── scripts/
    ├── dev_setup.sh
    └── run_migrations.sh
```

### Package Boundaries via `pyproject.toml` Extras

```toml
[project]
name = "prompt-manager"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]

[project.optional-dependencies]
api = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "mcp>=1.0",
    "httpx>=0.27",
]
client = [
    "httpx>=0.27",
]
metric = [
    "httpx>=0.27",
]
llm = [
    "anthropic>=0.40",
    "openai>=1.30",
    "google-genai>=0.5",
    "boto3>=1.34",
]
all = ["prompt-manager[api,client,metric,llm]"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
    "testcontainers[postgres]>=4.0",
    "ruff>=0.4",
    "mypy>=1.10",
]
```

---

## 2. Database Schema Design

All tables use UUID primary keys and UTC timestamps.

### Table: `prompts`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK, default `gen_random_uuid()` |
| `slug` | `TEXT` | NOT NULL, UNIQUE |
| `name` | `TEXT` | NOT NULL |
| `description` | `TEXT` | nullable |
| `tags` | `TEXT[]` | default `'{}'` |
| `metadata` | `JSONB` | default `'{}'` |
| `current_version` | `INT` | NOT NULL, default 1 |
| `archived_at` | `TIMESTAMPTZ` | nullable |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, default `now()` |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, default `now()` |

### Table: `prompt_versions`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK |
| `prompt_id` | `UUID` | FK -> `prompts.id` ON DELETE CASCADE |
| `version` | `INTEGER` | NOT NULL |
| `body` | `TEXT` | NOT NULL |
| `model_hint` | `TEXT` | nullable |
| `template_vars` | `TEXT[]` | default `'{}'` |
| `content_hash` | `TEXT` | NOT NULL (SHA-256 of body) |
| `parent_version` | `INT` | nullable |
| `source` | `TEXT` | default `'manual'` |
| `created_by` | `TEXT` | nullable |
| `created_at` | `TIMESTAMPTZ` | NOT NULL |

Constraints: `UNIQUE(prompt_id, version)`.

### Table: `experiments`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK |
| `prompt_id` | `UUID` | FK -> `prompts.id` ON DELETE CASCADE |
| `name` | `TEXT` | NOT NULL |
| `status` | `TEXT` | `'draft'`, `'running'`, `'paused'`, `'concluded'` |
| `sticky` | `BOOLEAN` | default `true` |
| `auto_optimize` | `BOOLEAN` | default `false` |
| `min_sample_size` | `INT` | default 100 |
| `started_at` | `TIMESTAMPTZ` | nullable |
| `concluded_at` | `TIMESTAMPTZ` | nullable |
| `winner_arm_id` | `UUID` | nullable |
| `created_at` | `TIMESTAMPTZ` | |
| `updated_at` | `TIMESTAMPTZ` | |

Constraint: Partial unique index on `(prompt_id) WHERE status = 'running'` — at most one running experiment per prompt.

### Table: `experiment_arms`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK |
| `experiment_id` | `UUID` | FK -> `experiments.id` ON DELETE CASCADE |
| `version_id` | `UUID` | FK -> `prompt_versions.id` |
| `weight` | `REAL` | NOT NULL, CHECK `weight >= 0 AND weight <= 100` |
| `label` | `TEXT` | nullable |
| `created_at` | `TIMESTAMPTZ` | |

### Table: `metric_events`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK |
| `prompt_id` | `UUID` | FK -> `prompts.id` |
| `version_id` | `UUID` | FK -> `prompt_versions.id` |
| `experiment_id` | `UUID` | nullable FK |
| `arm_id` | `UUID` | nullable FK |
| `session_id` | `TEXT` | nullable |
| `metric_name` | `TEXT` | NOT NULL |
| `metric_value` | `DOUBLE PRECISION` | NOT NULL |
| `metadata` | `JSONB` | default `'{}'` |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, default `now()` |

### Table: `optimization_runs`

| Column | Type | Constraints |
|--------|------|-------------|
| `id` | `UUID` | PK |
| `prompt_id` | `UUID` | FK |
| `experiment_id` | `UUID` | nullable FK |
| `trigger` | `TEXT` | `'manual'`, `'scheduled'`, `'metric_threshold'` |
| `status` | `TEXT` | `'pending'`, `'running'`, `'completed'`, `'failed'` |
| `llm_provider` | `TEXT` | |
| `llm_model` | `TEXT` | |
| `input_version` | `INT` | |
| `output_version` | `INT` | nullable |
| `input_metrics` | `JSONB` | |
| `proposed_body` | `TEXT` | |
| `llm_reasoning` | `TEXT` | nullable |
| `status` | `TEXT` | default `'pending'` |
| `created_at` | `TIMESTAMPTZ` | |
| `completed_at` | `TIMESTAMPTZ` | nullable |

### Table: `session_assignments`

| Column | Type | Constraints |
|--------|------|-------------|
| `session_id` | `TEXT` | PK (composite) |
| `experiment_id` | `UUID` | PK (composite), FK |
| `arm_id` | `UUID` | FK |
| `assigned_at` | `TIMESTAMPTZ` | |

### Key Indexes

```sql
CREATE INDEX idx_prompts_slug ON prompts(slug) WHERE archived_at IS NULL;
CREATE UNIQUE INDEX idx_versions_prompt_version ON prompt_versions(prompt_id, version);
CREATE INDEX idx_experiments_prompt_status ON experiments(prompt_id, status) WHERE status = 'running';
CREATE INDEX idx_metrics_prompt_version ON metric_events(prompt_id, version_id, created_at);
CREATE INDEX idx_metrics_experiment_arm ON metric_events(experiment_id, arm_id, created_at);
CREATE INDEX idx_session_assignments_lookup ON session_assignments(session_id, experiment_id);
```

---

## 3. API Design

Base path: `/api/v1`

### Prompts

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/prompts` | Create prompt (auto-creates version 1) |
| `GET` | `/prompts` | List prompts (paginated, filterable by tag) |
| `GET` | `/prompts/{slug}` | Get prompt metadata |
| `PATCH` | `/prompts/{slug}` | Update prompt metadata |
| `DELETE` | `/prompts/{slug}` | Soft-delete (archive) |

### Versions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/prompts/{slug}/versions` | Create new version (auto-increments) |
| `GET` | `/prompts/{slug}/versions` | List all versions |
| `GET` | `/prompts/{slug}/versions/latest` | Get latest active version |
| `GET` | `/prompts/{slug}/versions/{v}` | Get specific version |

### Resolve (Client-facing, experiment-aware)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/resolve/{slug}` | Returns prompt content. Experiment-aware routing. Optional `?version=N`, `?session_id=...` |

### Experiments

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/experiments` | Create experiment with arms |
| `GET` | `/experiments` | List experiments |
| `GET` | `/experiments/{id}` | Get experiment detail with arms + metrics |
| `PATCH` | `/experiments/{id}` | Update status/weights |
| `POST` | `/experiments/{id}/conclude` | End experiment, promote winner |

### Metrics

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/metrics` | Ingest single metric signal |
| `POST` | `/metrics/batch` | Ingest batch |
| `GET` | `/metrics/summary` | Aggregated metrics |

### Optimization

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/optimize/{slug}` | Trigger optimization run |
| `GET` | `/optimize/{run_id}` | Get run status + result |
| `POST` | `/optimize/{run_id}/apply` | Apply suggested changes |

---

## 4. Core Modules and Responsibilities

| Module | Responsibility |
|--------|---------------|
| `core/models.py` | Pure domain models, no DB dependency |
| `core/config.py` | `PromptManagerSettings` via pydantic-settings |
| `api/db/engine.py` | asyncpg connection pool management |
| `api/db/*_repo.py` | Raw SQL for each aggregate, returns domain models |
| `api/services/*` | Business logic, invariant enforcement, LLM calls |
| `api/routers/*` | Thin FastAPI routers |
| `llm/base.py` | `LLMProvider` ABC with `async complete()` |
| `llm/prompt_improver.py` | Meta-prompt construction, LLM response parsing |

---

## 5. Experiment Routing Algorithm

```python
def resolve_prompt(slug, version=None, session_id=None):
    prompt = lookup_by_slug(slug)

    # Pinned version bypasses experiments
    if version:
        return get_version(prompt.id, version)

    # Check for running experiment
    experiment = get_running_experiment(prompt.id)
    if not experiment:
        return get_latest_version(prompt.id)

    # Sticky session check
    if session_id and experiment.sticky:
        assignment = get_session_assignment(session_id, experiment.id)
        if assignment:
            return get_version_by_id(assignment.version_id)

    # Weighted random selection
    arms = get_experiment_arms(experiment.id)
    total_weight = sum(arm.weight for arm in arms)
    roll = random.uniform(0, 100)

    if roll >= total_weight:
        # Remainder serves default
        selected_version = get_latest_version(prompt.id)
    else:
        cumulative = 0
        for arm in arms:
            cumulative += arm.weight
            if roll < cumulative:
                selected_version = get_version_by_id(arm.version_id)
                break

    # Persist sticky assignment
    if session_id and experiment.sticky:
        save_session_assignment(session_id, experiment.id, arm.id)

    return selected_version
```

---

## 6. Optimization Loop Architecture

```
Trigger (manual / scheduled / threshold)
    │
    ▼
Collect Metrics (aggregate last N hours per version)
    │
    ▼
Build Meta-Prompt (current versions + metrics + constraints)
    │
    ▼
Call LLM (configured provider via llm/factory.py)
    │
    ▼
Store Result (optimization_runs, status='pending')
    │
    ▼
Apply on Request (POST /optimize/{run_id}/apply)
    ├── Creates new prompt_version
    └── Optionally updates experiment arm weights
```

### Guard Rails

- Shadow test new prompts at low weight (5%) before full promotion
- Rollback if composite score drops below threshold
- Human-in-the-loop by default (auto_deploy opt-in)
- Optimization budget (max runs per prompt per time window)
- Template variable validation (reject if vars are missing)

---

## 7. LLM Provider Abstraction

```python
class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: dict | None = None,
    ) -> str: ...

def create_provider(config: LLMProviderConfig) -> LLMProvider:
    match config.provider:
        case "anthropic": return AnthropicProvider(config)
        case "openai":    return OpenAIProvider(config)
        case "groq":      return GroqProvider(config)
        case "gemini":    return GeminiProvider(config)
        case "bedrock":   return BedrockProvider(config)
        case "openrouter": return OpenAIProvider(config)  # Compatible
        case "custom":    return CustomProvider(config)    # OpenAI-compatible
```

---

## 8. Client SDK Architecture

```python
class PromptManagerClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        cache_ttl: float | None = None,
        api_key: str | None = None,
    ): ...

    async def resolve(
        self,
        prompt_name: str,
        version: int | None = None,
        session_id: str | None = None,
        variables: dict[str, str] | None = None,
    ) -> ResolvedPrompt: ...

    async def get_prompt(self, slug: str) -> PromptResponse: ...
    async def list_prompts(self, tags: list[str] | None = None) -> list[PromptResponse]: ...
    async def close(self) -> None: ...
```

`ResolvedPrompt` includes `.render(**kwargs)` for template variable substitution.

---

## 9. MCP Integration

```python
from mcp.server import Server

server = Server("prompt-manager")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="list_prompts", ...),
        Tool(name="resolve_prompt", ...),
        Tool(name="create_prompt", ...),
        Tool(name="create_version", ...),
        Tool(name="create_experiment", ...),
        Tool(name="get_experiment_results", ...),
        Tool(name="optimize_prompt", ...),
        Tool(name="apply_optimization", ...),
    ]
```

MCP server runs alongside FastAPI, sharing the same service layer.

---

## 10. Configuration System

```python
class PromptManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env")

    # Database
    database_url: str = "postgresql://localhost:5432/prompt_manager"
    db_pool_min: int = 2
    db_pool_max: int = 10

    # Server
    host: str = "0.0.0.0"
    port: int = 8910

    # LLM
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str | None = None
    llm_api_base: str | None = None
    llm_region: str | None = None

    # Optimization
    optimization_auto_enabled: bool = False
    optimization_interval_minutes: int = 60

    # MCP
    mcp_enabled: bool = True
    mcp_transport: Literal["stdio", "sse"] = "stdio"
```

All values configurable via `PM_`-prefixed environment variables.

---

## 11. Testing Strategy

### Unit Tests
- Domain model validation, schema serialization
- Weighted routing with known seeds
- Mock LLM provider for prompt improver
- Mock httpx for client SDK

### Integration Tests
- Full CRUD via httpx.AsyncClient against FastAPI test app
- Real PostgreSQL via `testcontainers[postgres]`
- Experiment lifecycle + distribution verification
- Metric ingestion + aggregation

### E2E Tests
- Complete workflow: create prompt -> versions -> experiment -> metrics -> optimize -> apply

---

## 12. Phase-by-Phase Implementation Order

### Phase 1: Foundation (Days 1-3)
- `pyproject.toml`, `core/` package (models, schemas, config, exceptions)
- `docker-compose.yml` with PostgreSQL
- Alembic setup + `001_initial_schema.py` migration
- `api/db/engine.py` (asyncpg pool)

### Phase 2: Prompt CRUD + Versioning (Days 3-5)
- Repositories: `prompts_repo.py`, `versions_repo.py`
- Service: `prompt_service.py`
- Routers: `prompts.py`, `versions.py`
- FastAPI app factory + entrypoint
- Integration tests

### Phase 3: Experiment Routing (Days 5-7)
- Repository: `experiments_repo.py`
- Service: `experiment_service.py` with weighted routing
- Router: `experiments.py`
- Resolve endpoint: `GET /resolve/{slug}`
- Unit + integration tests

### Phase 4: Client SDK (Days 7-8)
- `client/client.py` with `PromptManagerClient`
- Cache + template rendering
- Unit + integration tests

### Phase 5: Metrics Collection (Days 8-10)
- Repository: `metrics_repo.py`
- Service: `metric_service.py`
- Router: `metrics.py`
- `metric/collector.py`, `metric/reporter.py`
- Tests

### Phase 6: LLM Abstraction + Optimizer (Days 10-13)
- `llm/base.py`, all providers
- `llm/prompt_improver.py`
- `optimization_service.py`
- Router: `optimize.py`
- Tests with mocked LLM

### Phase 7: MCP Integration (Days 13-14)
- `api/mcp/server.py` with all tool definitions
- Wire into FastAPI lifecycle

### Phase 8: Polish (Days 14-16)
- Structured logging
- OpenAPI docs
- E2E tests
- Examples, scripts, CI config

### Dependency Graph

```
Phase 1 (Foundation)
  ├── Phase 2 (Prompt CRUD)
  │     ├── Phase 3 (Experiments)
  │     │     └── Phase 4 (Client SDK)
  │     └── Phase 5 (Metrics)
  │           └── Phase 6 (LLM + Optimization)
  │                 └── Phase 7 (MCP)
  └── Phase 8 (Polish) — depends on all above
```

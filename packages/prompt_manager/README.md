# Prompt Manager

Versioned prompt CRUD, A/B experiments, metric collection, and LLM-driven optimization API.

## Install

```bash
# Just the client SDK (for services that fetch prompts)
pip install prompt-manager[client]

# Full API server
pip install prompt-manager[api]

# Client + metric reporting
pip install prompt-manager[client,metric]

# Everything
pip install prompt-manager[all]
```

## Quick start

### Start the API

```bash
PM_DATABASE_URL=postgresql://user:pass@localhost:5432/prompts \
  prompt-manager serve
```

### Use the client SDK

```python
from prompt_manager.client import PromptManagerClient

client = PromptManagerClient(base_url="http://localhost:8910")

# Resolve a prompt (returns latest version, experiment-aware)
prompt = await client.resolve("welcome-email", session_id="user-123")
print(prompt.body)       # "Hi {name}, welcome to {company}!"
print(prompt.version)    # 2

# Report a quality metric
await client.report_metric("welcome-email", str(prompt.version_id), "quality", 8.5)
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/prompts` | Create prompt (auto-creates v1) |
| GET | `/prompts` | List all prompts |
| GET | `/prompts/{slug}` | Get prompt by slug |
| POST | `/prompts/{slug}/versions` | Create new version |
| GET | `/prompts/{slug}/versions` | List versions |
| **GET** | **`/resolve/{slug}`** | **Resolve prompt (experiment-aware)** |
| POST | `/experiments` | Create A/B experiment |
| PATCH | `/experiments/{id}/status` | Start/pause/conclude |
| POST | `/metrics` | Report metric signal |
| GET | `/metrics/aggregate` | Aggregated metrics per version |
| POST | `/optimize` | Trigger LLM optimization |
| GET | `/health` | Health check |

## Key features

- **Slug-based addressing** -- `resolve("welcome-email")` not UUIDs
- **Immutable versions** -- append-only, SHA-256 dedup, full audit trail
- **Experiment routing** -- MurmurHash3 deterministic + Thompson Sampling (auto_optimize)
- **Sticky sessions** -- same user always sees same variant
- **Metric collection** -- quality signals per version, batch ingestion
- **MCP server** -- expose all tools via Model Context Protocol
- **CLI** -- `prompt-manager serve`, `prompt-manager migrate`, `prompt-manager health`

## Database

Requires PostgreSQL 14+. Migrations run automatically on startup.

```bash
# Docker
docker compose up -d

# Or point to existing Postgres
PM_DATABASE_URL=postgresql://user:pass@host:5432/dbname prompt-manager migrate
```

## Configuration

All settings via `PM_`-prefixed environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PM_DATABASE_URL` | `postgresql://localhost:5432/prompt_manager` | PostgreSQL DSN |
| `PM_HOST` | `0.0.0.0` | Bind host |
| `PM_PORT` | `8910` | Bind port |
| `PM_LLM_PROVIDER` | `anthropic` | LLM for optimization |
| `PM_LLM_MODEL` | `claude-sonnet-4-20250514` | Model ID |
| `PM_LLM_API_KEY` | -- | API key |

## Part of autoresearch-prompt-manager

```
autoresearch-prompt-manager  (this package -- API, client, metrics)
  -> autoresearcher-shonku   (optimization agents)
  -> shonku                  (agent framework)
  -> agno                    (runtime -- https://agno.com)
```

LLM-driven optimization is powered by [agno](https://agno.com) and [AgentOS](https://docs.agno.com/agent-os/introduction).

## Contributing

1. Fork [autoresearch-prompt-manager](https://github.com/kaustav1996/autoresearch-prompt-manager)
2. `cd packages/prompt_manager && pip install -e '.[dev,api,client,metric]'`
3. Make changes, `pytest`, `ruff check src/`
4. Integration tests: `PM_DATABASE_URL=... python3 -m pytest tests/integration/`
5. Submit a PR

## License

MIT

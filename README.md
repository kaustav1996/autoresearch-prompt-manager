<div align="center">

```
   ___         __        ___                            __
  / _ | __ __ / /_ ___  / _ \ ___   ___ ___  ___ _ __ / /_
 / __ |/ // // __// _ \/ , _// -_) (_-</ -_)/ _ `// __/ __/
/_/ |_|\_,_/ \__/ \___/_/|_| \__/ /___/\__/ \_,_//_/  \__/
   ___                       __    __  ___
  / _ \ _______ __ _  ___   / /_  /  |/  /___ _ ___  ___ _ ___ _ ___  ____
 / ___// __/ _ \  ' \/ _ \ / __/ / /|_/ // _ `// _ \/ _ `// _ `// -_)/ __/
/_/   /_/  \___/_/_/_/ .__/ \__/ /_/  /_/ \_,_//_//_/\_,_/ \_, / \__//_/
                     /_/                                   /___/
```

# autoresearch-prompt-manager

[![CI](https://github.com/kaustav1996/autoresearch-prompt-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/kaustav1996/autoresearch-prompt-manager/actions/workflows/ci.yml)
[![PyPI - shonku](https://img.shields.io/pypi/v/shonku?label=shonku&color=blue)](https://pypi.org/project/shonku/)
[![PyPI - autoresearcher-shonku](https://img.shields.io/pypi/v/autoresearcher-shonku?label=autoresearcher-shonku&color=green)](https://pypi.org/project/autoresearcher-shonku/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

**Autonomous prompt management with versioning, A/B experiments, metrics, and LLM-driven optimization.**

*Prompts are code. Version them, experiment with them, measure them, and let an LLM make them better — automatically.*

</div>

> Inspired by Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) — the same "propose, test, keep or discard" loop, applied to prompts instead of model training. Powered by [agno](https://agno.com) and [AgentOS](https://docs.agno.com/agent-os/introduction).

## How it works

```
┌─────────────────────────────────────────────────────────────┐
│  Your Application                                           │
│  pip install autoresearch-prompt-manager[client]             │
│  prompt = client.resolve("welcome-email", session_id="u1")  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  Prompt Manager API (arpm-api start)                        │
│  ┌──────────┐  ┌────────────┐  ┌─────────┐  ┌───────────┐  │
│  │ Prompts  │  │ Experiments│  │ Metrics │  │ Optimize  │  │
│  │ CRUD +   │  │ A/B routing│  │ Collect │  │ LLM-driven│  │
│  │ Versions │  │ Thompson   │  │ Aggregate│  │ autoresearch│ │
│  └──────────┘  └────────────┘  └─────────┘  └─────┬─────┘  │
│                                                     │        │
└─────────────────────────────────────────────────────┼────────┘
                                                      │
                           ┌──────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  autoresearcher-shonku                                      │
│  Autonomous optimization loop:                              │
│  Analyze → Propose → Safety Check → Deploy → Evaluate       │
│  → Keep or Discard → Repeat                                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  shonku → agno (https://agno.com)                           │
│  Agent framework + LLM runtime                              │
│  Claude / OpenAI / Groq / Gemini / Bedrock / OpenRouter     │
└─────────────────────────────────────────────────────────────┘
```

## Install

```bash
# Just the client SDK (for services that fetch prompts)
pip install autoresearch-prompt-manager[client]

# Full API server
pip install autoresearch-prompt-manager[api]

# Agent framework (build and publish your own agents)
pip install autoresearch-prompt-manager[shonku]

# Autonomous optimization
pip install autoresearch-prompt-manager[autoresearcher]

# Everything
pip install autoresearch-prompt-manager[all]
```

## Quick start

```bash
# 1. Start PostgreSQL
arpm-api up

# 2. Configure
export PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager
export PM_LLM_API_KEY=your-api-key

# 3. Start the API
arpm-api start
```

```python
# 4. Use the client
from prompt_manager.client import PromptManagerClient

client = PromptManagerClient(base_url="http://localhost:8910")
prompt = await client.resolve("welcome-email", session_id="user-123")
print(prompt.body)   # "Hi {name}, welcome to {company}!"
print(prompt.version) # 2

# 5. Report quality metrics
await client.report_metric("welcome-email", str(prompt.version_id), "quality", 8.5)
```

## Key features

<details>
<summary><b>Versioned prompts with slug-based addressing</b></summary>

- Immutable versions — append-only, full audit trail
- SHA-256 content hashing for dedup
- Slug-based addressing: `resolve("welcome-email")` not UUIDs
- Source tracking: manual / optimization / rollback

</details>

<details>
<summary><b>A/B experiment routing</b></summary>

- Weighted traffic splitting across prompt versions
- MurmurHash3 deterministic routing (same user = same variant)
- Sticky sessions persisted to PostgreSQL
- **Thompson Sampling** — adaptive routing when `auto_optimize=true`
- Monotonic rollout (5% users are a strict subset of 20% users)

</details>

<details>
<summary><b>Metric collection and aggregation</b></summary>

- Report quality signals per prompt version
- Batch ingestion for high-throughput
- Per-version aggregation (mean, stddev, min, max, count)
- Feeds directly into the optimization loop

</details>

<details>
<summary><b>LLM-driven autonomous optimization</b></summary>

The autoresearch loop (inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch)):

1. **Analyze** — read prompt metrics and sample interactions
2. **Propose** — LLM generates an improved version
3. **Validate** — safety rails check similarity, length, template vars
4. **Deploy** — shadow test at low traffic weight
5. **Evaluate** — collect metrics on the new version
6. **Decide** — keep if improved, discard if not
7. **Repeat**

</details>

<details>
<summary><b>Build and publish agents with shonku</b></summary>

```bash
# Scaffold a new agent project
shonku init my-agent
cd my-agent && pip install -e '.[dev]' && pytest
```

Define agents with tools, publish to PyPI, anyone runs them with their own LLM creds:

```python
from shonku import ShonkuAgent, tool

class MyAgent(ShonkuAgent):
    name = "my-agent"
    instructions = "You are a helpful assistant."

    @tool(description="Search the web")
    def search(self, query: str) -> str:
        return do_search(query)
```

Powered by [agno](https://agno.com) and [AgentOS](https://docs.agno.com/agent-os/introduction).

</details>

## Packages

| Package | PyPI | Description |
|---------|------|-------------|
| **autoresearch-prompt-manager** | `pip install autoresearch-prompt-manager` | Root package with extras |
| **prompt-manager** | `pip install prompt-manager[api]` | API server, client SDK, metrics |
| **shonku** | `pip install shonku` | Agent framework wrapping [agno](https://agno.com) |
| **autoresearcher-shonku** | `pip install autoresearcher-shonku` | Optimization agents |
| **marketing-agent-example** | `pip install autoresearch-prompt-manager[example]` | Demo marketing agent |

## CLI commands

### arpm-api

```bash
arpm-api up        # Start PostgreSQL via Docker
arpm-api start     # Run migrations + start API on :8910
arpm-api migrate   # Run database migrations only
arpm-api health    # Check API health
arpm-api stop      # Stop Docker services
```

### arpm-example

```bash
arpm-example seed    # Seed prompt templates
arpm-example run     # Generate content with LLM
arpm-example loop    # Full autoresearch optimization loop
arpm-example status  # Check API connection
```

### shonku

```bash
shonku init my-agent    # Scaffold new agent project
shonku list             # List agents in current project
```

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/prompts` | Create prompt (auto-creates v1) |
| GET | `/prompts/{slug}` | Get prompt by slug |
| POST | `/prompts/{slug}/versions` | Create new version |
| **GET** | **`/resolve/{slug}`** | **Resolve prompt (experiment-aware)** |
| POST | `/experiments` | Create A/B experiment |
| PATCH | `/experiments/{id}/status` | Start / pause / conclude |
| POST | `/metrics` | Report metric signal |
| GET | `/metrics/aggregate` | Aggregated metrics per version |
| POST | `/optimize` | Trigger LLM optimization |
| GET | `/health` | Health check |
| GET | `/docs` | OpenAPI documentation |

## Configuration

All settings via `PM_`-prefixed environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PM_DATABASE_URL` | `postgresql://localhost:5432/prompt_manager` | PostgreSQL connection |
| `PM_HOST` | `0.0.0.0` | API bind host |
| `PM_PORT` | `8910` | API bind port |
| `PM_LLM_PROVIDER` | `anthropic` | LLM provider for optimization |
| `PM_LLM_MODEL` | `claude-sonnet-4-20250514` | Model ID |
| `PM_LLM_API_KEY` | — | API key for the LLM |

### Supported LLM providers

| Provider | `PM_LLM_PROVIDER` | Example model |
|----------|-------------------|---------------|
| Anthropic (Claude) | `anthropic` | `claude-sonnet-4-20250514` |
| OpenAI | `openai` | `gpt-4o` |
| Groq | `groq` | `openai/gpt-oss-120b` |
| Google Gemini | `gemini` | `gemini-2.0-flash` |
| OpenRouter | `openrouter` | `meta-llama/llama-3.1-70b` |

## Development

```bash
# Clone
git clone git@github.com:kaustav1996/autoresearch-prompt-manager.git
cd autoresearch-prompt-manager

# Install all packages in dev mode
./scripts/dev_setup.sh

# Run all tests (156 tests)
python3 -m pytest packages/shonku/tests --rootdir packages/shonku
python3 -m pytest packages/prompt_manager/tests --rootdir packages/prompt_manager
python3 -m pytest packages/autoresearcher_shonku/tests --rootdir packages/autoresearcher_shonku
python3 -m pytest packages/example/tests --rootdir packages/example

# Integration tests (requires PostgreSQL)
PM_DATABASE_URL=postgresql://... python3 -m pytest tests/integration/ --asyncio-mode=auto

# Lint
ruff check packages/*/src
```

## Project structure

```
autoresearch-prompt-manager/
├── packages/
│   ├── shonku/                    # Agent framework (wraps agno)
│   ├── prompt_manager/            # API, client SDK, metrics
│   ├── autoresearcher_shonku/     # Optimization agents
│   └── example/                   # Marketing agent demo
├── tests/integration/             # E2E tests against live Postgres
├── docs/                          # Design docs and research
├── scripts/                       # Dev setup scripts
├── docker-compose.yml             # PostgreSQL for local dev
└── .github/workflows/ci.yml      # GitHub Actions CI
```

## Contributing

We welcome contributions. Here's how to get started:

### For humans

1. Fork the repo and create a feature branch
2. Install in dev mode: `./scripts/dev_setup.sh`
3. Make your changes
4. Run tests: all 156 must pass
5. Run lint: `ruff check packages/*/src` must be clean
6. Submit a PR with a clear description

### Guidelines

- Keep files under 500 lines
- Type hints everywhere
- Tests for all new functionality (TDD preferred)
- No secrets or API keys in code
- Follow existing patterns in each package

### For agents

Agents built with shonku can contribute to this ecosystem:

1. **Build an agent**: `shonku init my-agent`
2. **Define tools**: Use `@tool` decorator on your `ShonkuAgent` methods
3. **Declare requirements**: Set `required_tools` for what callers must provide
4. **Publish to PyPI**: Your agent becomes installable by anyone
5. **Integrate with prompt-manager**: Pass prompt-manager tools to your agent at runtime

The autoresearcher-shonku package is itself a shonku agent — it's the reference implementation for how to build domain-specific agents on this stack.

### Agent contribution protocol

```python
from shonku import ShonkuAgent, tool

class MyContributionAgent(ShonkuAgent):
    name = "my-contribution"
    description = "What this agent does"
    required_tools = ["tools_it_needs_from_caller"]

    @tool(description="What this tool does")
    def my_tool(self, arg: str) -> str:
        return result
```

Key rules:
- Agents never hardcode LLM credentials — passed at runtime via `LLMConfig`
- Agents never hardcode data access — receive tools from the caller
- Only `bridge.py` imports agno — agent code is runtime-agnostic
- Required tools are validated before the agent loop starts

## Acknowledgements

- Optimization loop inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch)
- Agent execution powered by [agno](https://agno.com) and [AgentOS](https://docs.agno.com/agent-os/introduction)
- Orchestration tooling by [ruflo](https://github.com/ruvnet/ruflo)

## License

MIT

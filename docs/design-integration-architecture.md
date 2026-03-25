# Integration Architecture: The 4-Layer Stack

> Design document — research and design only, no code produced
> Date: 2026-03-25
> Status: Draft

---

## Table of Contents

1. [Overview](#1-overview)
2. [The 4-Layer Stack](#2-the-4-layer-stack)
3. [Dependency Graph and PyPI Package Structure](#3-dependency-graph-and-pypi-package-structure)
4. [Tool Flow Architecture](#4-tool-flow-architecture)
5. [LLM Credentials Flow](#5-llm-credentials-flow)
6. [Updated prompt-manager Architecture](#6-updated-prompt-manager-architecture)
7. [Sequence Diagram: Complete Optimization Run](#7-sequence-diagram-complete-optimization-run)
8. [Error Propagation Model](#8-error-propagation-model)
9. [Observability and Tracing](#9-observability-and-tracing)
10. [Configuration at Each Layer](#10-configuration-at-each-layer)
11. [Independent Usability of Each Package](#11-independent-usability-of-each-package)
12. [Migration Path from Current Design](#12-migration-path-from-current-design)

---

## 1. Overview

The system is decomposed into four independently installable Python packages forming a strict dependency chain. Each layer has a single responsibility and a well-defined contract with the layers above and below it.

```
┌─────────────────────────────────────────────────────────────────┐
│  prompt-manager [api/client/metric]                             │  APPLICATION
│  Owns domain: prompts, versions, experiments, metrics, DB       │
│  Defines tools for prompt CRUD, passes them DOWN                │
├─────────────────────────────────────────────────────────────────┤
│  autoresearcher-shonku                                          │  AGENT SPECIALIZATION
│  Implements the autoresearch optimization loop                  │
│  Receives external tools + adds its own analytical tools        │
├─────────────────────────────────────────────────────────────────┤
│  shonku                                                         │  AGENT FRAMEWORK
│  Agent builder, publisher, runner                               │
│  Manages tool combining, node execution model                   │
├─────────────────────────────────────────────────────────────────┤
│  agnosai                                                        │  RUNTIME
│  LLM-agnostic execution, provider abstraction                   │
│  Core agent loop, tool protocol, result reporting               │
└─────────────────────────────────────────────────────────────────┘
```

### Design Principles

1. **Tools flow downward** — upper layers define tools, lower layers execute them.
2. **Config flows downward** — LLM credentials originate at the application layer and pass through to the runtime.
3. **Errors flow upward** — failures at any layer are wrapped in typed exceptions and propagated up.
4. **Each layer is independently usable** — you can use `agnosai` without `shonku`, `shonku` without `autoresearcher-shonku`.
5. **Only agnosai touches LLM SDKs** — no other layer imports `anthropic`, `openai`, etc.

---

## 2. The 4-Layer Stack

### Layer 1: agnosai (Runtime)

**Package**: `pip install agnosai`
**Dependencies**: LLM provider SDKs (`anthropic`, `openai`, `google-genai`, `boto3`)
**Responsibility**: Execute a single agent loop — accept instructions + tools, call an LLM, execute tool calls, return results.

```python
# agnosai public API (conceptual)
from agnosai import Agent, LLMConfig, ToolDef, AgentResult, AgentError

class LLMConfig:
    provider: str          # "anthropic", "openai", "groq", "gemini", "bedrock"
    model: str             # "claude-sonnet-4-20250514", "gpt-4o", etc.
    api_key: str
    api_base: str | None
    temperature: float
    max_tokens: int

class ToolDef:
    name: str
    description: str
    parameters: dict       # JSON Schema
    handler: Callable      # async (params) -> result

class AgentResult:
    output: str
    tool_calls: list[ToolCallRecord]
    usage: TokenUsage
    steps: int

class Agent:
    @staticmethod
    async def run(
        instructions: str,
        tools: list[ToolDef],
        llm_config: LLMConfig,
        max_steps: int = 50,
        on_tool_call: Callable | None = None,    # observability hook
        on_step: Callable | None = None,          # observability hook
    ) -> AgentResult: ...
```

**Key characteristics**:
- Zero opinion about what agents do — it is purely an execution engine.
- Handles the LLM call loop: send messages -> get response -> if tool call, execute tool, append result -> repeat until LLM returns final text or max_steps reached.
- Provider abstraction lives here: the `LLMConfig.provider` field determines which SDK client to instantiate.
- Defines the canonical `ToolDef` protocol that all layers use.

### Layer 2: shonku (Agent Framework)

**Package**: `pip install shonku`
**Dependencies**: `agnosai>=0.1`
**Responsibility**: Agent composition, packaging, and multi-step orchestration. Provides a higher-level agent builder on top of agnosai's raw execution loop.

```python
# shonku public API (conceptual)
from shonku import Agent, AgentConfig, Node, Pipeline

class AgentConfig:
    name: str
    version: str
    instructions: str
    tools: list[ToolDef]
    llm_config: LLMConfig
    max_steps: int
    metadata: dict

class Agent:
    def __init__(self, config: AgentConfig): ...

    def add_tools(self, tools: list[ToolDef]) -> None:
        """Merge external tools into the agent's tool set."""

    async def run(self, context: dict | None = None) -> AgentResult:
        """Execute the agent via agnosai."""

class Node:
    """A unit of work in a pipeline — wraps an Agent or a function."""

class Pipeline:
    """Chain multiple Nodes in sequence or parallel."""
```

**Key characteristics**:
- `Agent` is a configurable wrapper that composes tools from multiple sources, merges them, and delegates execution to `agnosai.Agent.run()`.
- `Pipeline` and `Node` enable multi-step workflows (e.g., analyze -> propose -> validate -> deploy).
- Agent packaging: a shonku agent can be published to PyPI as a standalone package with `[project.entry-points."shonku.agents"]`.
- Tool merging: `agent.add_tools(external_tools)` combines tools from different sources with namespace deduplication.

### Layer 3: autoresearcher-shonku (Agent Specialization)

**Package**: `pip install autoresearcher-shonku`
**Dependencies**: `shonku>=0.1`
**Responsibility**: Implements the autoresearch optimization loop as a specialized shonku agent. Defines analytical tools (trend analysis, variable validation, safety checks) but does NOT own any data.

```python
# autoresearcher-shonku public API (conceptual)
from autoresearcher_shonku import AutoResearcherAgent, AutoResearcherConfig

class AutoResearcherConfig:
    max_iterations: int = 10
    min_improvement_threshold: float = 0.01
    prefer_shorter_prompts: bool = True
    max_prompt_length: int = 4000
    strategies: list[str] = ["conservative", "ablation"]
    safety_checks_enabled: bool = True

class AutoResearcherAgent:
    @staticmethod
    async def run(
        llm_config: LLMConfig,
        tools: list[ToolDef],              # External tools (from prompt-manager)
        context: dict,                      # {"prompt_slug": "...", "metric": "..."}
        config: AutoResearcherConfig,
        on_iteration: Callable | None = None,   # Callback per optimization cycle
        on_tool_call: Callable | None = None,   # Passthrough to shonku/agnosai
    ) -> AutoResearcherResult: ...
```

**Key characteristics**:
- Receives external tools (prompt CRUD, metrics) from the calling application.
- Adds its own analytical tools that are internal to the optimization logic.
- Constructs the meta-prompt (instructions for the LLM on how to optimize prompts).
- Implements the keep/discard decision loop from the autoresearch pattern.
- Does NOT own a database, does NOT import any prompt-manager code.

### Layer 4: prompt-manager (Application)

**Package**: `pip install prompt-manager[api]`
**Dependencies**: `autoresearcher-shonku>=0.1`, `fastapi`, `asyncpg`, etc.
**Responsibility**: Domain owner. Defines prompt CRUD, versioning, experiments, metrics collection, and the database. Wraps its domain operations as tools and passes them to `autoresearcher-shonku`.

```python
# prompt-manager integration point (conceptual)
from autoresearcher_shonku import AutoResearcherAgent, AutoResearcherConfig
from agnosai import ToolDef, LLMConfig

class OptimizationService:
    async def optimize(self, prompt_id: UUID) -> OptimizationResult:
        tools = self._build_tools(prompt_id)
        llm_config = self._build_llm_config()

        result = await AutoResearcherAgent.run(
            llm_config=llm_config,
            tools=tools,
            context={
                "prompt_slug": self.prompt_slug,
                "metric": self.config.metric_name,
            },
            config=AutoResearcherConfig(
                max_iterations=self.config.max_iterations,
                min_improvement_threshold=self.config.improvement_threshold,
            ),
            on_tool_call=self._log_tool_call,
        )
        return self._process_result(result)
```

---

## 3. Dependency Graph and PyPI Package Structure

### Dependency Chain

```
agnosai                          0 deps (besides LLM SDKs)
  ^
  |
shonku                           depends on: agnosai>=0.1
  ^
  |
autoresearcher-shonku            depends on: shonku>=0.1
  ^
  |
prompt-manager[api]              depends on: autoresearcher-shonku>=0.1
```

Each package is independently versioned and published. A semver-breaking change in `agnosai` requires a new major version of `shonku`, and so on up the chain.

### Updated prompt-manager pyproject.toml

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
    "autoresearcher-shonku>=0.1",   # Pulls in shonku -> agnosai
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
# NOTE: The "llm" extra is REMOVED. LLM provider SDKs are now
# transitive dependencies via agnosai, pulled in through
# autoresearcher-shonku -> shonku -> agnosai.
all = ["prompt-manager[api,client,metric]"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-httpx>=0.30",
    "testcontainers[postgres]>=4.0",
    "ruff>=0.4",
    "mypy>=1.10",
]
```

### What Gets Removed from prompt-manager

The entire `src/prompt_manager/llm/` directory is **removed**:

```
REMOVED:
  src/prompt_manager/llm/
    ├── base.py               # Replaced by agnosai.LLMConfig + agnosai's provider abstraction
    ├── factory.py             # Replaced by agnosai's internal provider factory
    ├── providers/             # ALL providers replaced by agnosai
    │   ├── anthropic.py
    │   ├── openai.py
    │   ├── groq.py
    │   ├── gemini.py
    │   ├── bedrock.py
    │   └── custom.py
    └── prompt_improver.py     # Replaced by autoresearcher-shonku's meta-prompt logic
```

### autoresearcher-shonku pyproject.toml

```toml
[project]
name = "autoresearcher-shonku"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "shonku>=0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.entry-points."shonku.agents"]
autoresearcher = "autoresearcher_shonku:AutoResearcherAgent"
```

### shonku pyproject.toml

```toml
[project]
name = "shonku"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "agnosai>=0.1",
]
```

### agnosai pyproject.toml

```toml
[project]
name = "agnosai"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "pydantic>=2.0",
]

[project.optional-dependencies]
anthropic = ["anthropic>=0.40"]
openai = ["openai>=1.30"]
gemini = ["google-genai>=0.5"]
bedrock = ["boto3>=1.34"]
all = ["agnosai[anthropic,openai,gemini,bedrock]"]
```

---

## 4. Tool Flow Architecture

This is the most critical design decision. Tools are defined at the top (prompt-manager), merged in the middle (autoresearcher-shonku), passed through shonku, and presented to the LLM by agnosai.

### 4.1 Tool Definition at Each Layer

#### prompt-manager defines domain tools

These wrap database operations. Each tool is a `ToolDef` (defined by agnosai) with a handler that calls the repository/service layer.

```python
# In prompt-manager: optimization_service.py

from agnosai import ToolDef

class OptimizationService:
    def _build_tools(self, prompt_id: UUID) -> list[ToolDef]:
        return [
            ToolDef(
                name="read_prompt",
                description="Read the current prompt content and metadata by slug.",
                parameters={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string", "description": "The prompt slug"}
                    },
                    "required": ["slug"],
                },
                handler=self._handle_read_prompt,
            ),
            ToolDef(
                name="create_version",
                description=(
                    "Create a new version of a prompt. Returns the new version number. "
                    "The version is created with source='optimization'."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "content": {"type": "string", "description": "The new prompt body"},
                        "reasoning": {"type": "string", "description": "Why this change was made"},
                    },
                    "required": ["slug", "content"],
                },
                handler=self._handle_create_version,
            ),
            ToolDef(
                name="get_metrics",
                description=(
                    "Get aggregated metrics for a prompt version. Returns mean, p50, p95, "
                    "count, and trend direction for the specified metric."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt_id": {"type": "string", "format": "uuid"},
                        "version_id": {"type": "string", "format": "uuid"},
                        "metric_name": {"type": "string"},
                        "window_hours": {"type": "integer", "default": 24},
                    },
                    "required": ["prompt_id", "version_id", "metric_name"],
                },
                handler=self._handle_get_metrics,
            ),
            ToolDef(
                name="create_experiment",
                description=(
                    "Create an A/B experiment with the specified arms and weights. "
                    "Returns the experiment ID."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt_id": {"type": "string", "format": "uuid"},
                        "arms": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "version_id": {"type": "string", "format": "uuid"},
                                    "weight": {"type": "number"},
                                    "label": {"type": "string"},
                                },
                            },
                        },
                    },
                    "required": ["prompt_id", "arms"],
                },
                handler=self._handle_create_experiment,
            ),
            ToolDef(
                name="update_weights",
                description="Update the traffic weights for an experiment's arms.",
                parameters={
                    "type": "object",
                    "properties": {
                        "experiment_id": {"type": "string", "format": "uuid"},
                        "weights": {
                            "type": "object",
                            "description": "Map of arm_id -> new weight",
                            "additionalProperties": {"type": "number"},
                        },
                    },
                    "required": ["experiment_id", "weights"],
                },
                handler=self._handle_update_weights,
            ),
            ToolDef(
                name="conclude_experiment",
                description=(
                    "End an experiment and promote the winning arm to the default version. "
                    "Returns the final results."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "experiment_id": {"type": "string", "format": "uuid"},
                        "winner_arm_id": {"type": "string", "format": "uuid"},
                    },
                    "required": ["experiment_id", "winner_arm_id"],
                },
                handler=self._handle_conclude_experiment,
            ),
            ToolDef(
                name="get_sample_interactions",
                description=(
                    "Retrieve sample user interactions for a prompt — both high-performing "
                    "and low-performing examples. Useful for understanding what works and "
                    "what does not."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "prompt_id": {"type": "string", "format": "uuid"},
                        "n": {"type": "integer", "default": 10},
                        "sort_by": {
                            "type": "string",
                            "enum": ["best", "worst", "random"],
                            "default": "random",
                        },
                    },
                    "required": ["prompt_id"],
                },
                handler=self._handle_get_sample_interactions,
            ),
        ]
```

#### autoresearcher-shonku adds analytical tools

These are internal to the optimization logic. They do NOT touch the database — they operate on data returned by the external tools.

```python
# In autoresearcher-shonku: tools.py

AUTORESEARCHER_TOOLS = [
    ToolDef(
        name="analyze_trends",
        description=(
            "Analyze metric trends over time. Takes raw metric data and returns "
            "trend direction, rate of change, and statistical significance."
        ),
        parameters={
            "type": "object",
            "properties": {
                "metric_data": {"type": "array", "items": {"type": "object"}},
                "window_size": {"type": "integer", "default": 7},
            },
            "required": ["metric_data"],
        },
        handler=analyze_trends_handler,
    ),
    ToolDef(
        name="validate_template_vars",
        description=(
            "Validate that a proposed prompt body contains all required template "
            "variables. Returns a list of missing variables, if any."
        ),
        parameters={
            "type": "object",
            "properties": {
                "proposed_body": {"type": "string"},
                "required_vars": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["proposed_body", "required_vars"],
        },
        handler=validate_vars_handler,
    ),
    ToolDef(
        name="check_safety",
        description=(
            "Run safety checks on a proposed prompt. Checks for prompt injection "
            "vulnerabilities, harmful instructions, PII leakage patterns, and "
            "excessive length."
        ),
        parameters={
            "type": "object",
            "properties": {
                "proposed_body": {"type": "string"},
                "max_length": {"type": "integer"},
            },
            "required": ["proposed_body"],
        },
        handler=check_safety_handler,
    ),
    ToolDef(
        name="compute_composite_score",
        description=(
            "Compute a weighted composite score from multiple metrics. "
            "Used to compare prompt versions on a single scalar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "metrics": {
                    "type": "object",
                    "description": "Map of metric_name -> value",
                    "additionalProperties": {"type": "number"},
                },
                "weights": {
                    "type": "object",
                    "description": "Map of metric_name -> weight",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["metrics", "weights"],
        },
        handler=compute_composite_handler,
    ),
    ToolDef(
        name="compare_versions",
        description=(
            "Compare two prompt versions side by side. Returns a diff, character "
            "count comparison, and readability analysis."
        ),
        parameters={
            "type": "object",
            "properties": {
                "version_a_body": {"type": "string"},
                "version_b_body": {"type": "string"},
            },
            "required": ["version_a_body", "version_b_body"],
        },
        handler=compare_versions_handler,
    ),
]
```

### 4.2 Tool Merging and Passthrough

```
prompt-manager                    autoresearcher-shonku               shonku                    agnosai
─────────────                    ─────────────────────               ──────                    ───────

tools = [
  read_prompt,
  create_version,
  get_metrics,                   receives external_tools
  create_experiment,             ─────────────────────►
  update_weights,
  conclude_experiment,           all_tools = external_tools +
  get_sample_interactions,         [analyze_trends,
]                                   validate_template_vars,          receives all_tools
                                    check_safety,                    ──────────────►
                                    compute_composite_score,
                                    compare_versions]                agent.run(
                                                                       tools=all_tools,
                                 AutoResearcherAgent.run(               instructions=...,      passes all_tools
                                   tools=external_tools,                llm_config=...)        ──────────────►
                                   ...)
                                                                     delegates to              agnosai.Agent.run(
                                                                     agnosai.Agent.run()         tools=all_tools,
                                                                                                 llm_provider=...,
                                                                                                 instructions=...)

                                                                                              LLM sees ALL 12 tools:
                                                                                                read_prompt
                                                                                                create_version
                                                                                                get_metrics
                                                                                                create_experiment
                                                                                                update_weights
                                                                                                conclude_experiment
                                                                                                get_sample_interactions
                                                                                                analyze_trends
                                                                                                validate_template_vars
                                                                                                check_safety
                                                                                                compute_composite_score
                                                                                                compare_versions
```

### 4.3 Tool Execution Path

When the LLM decides to call `read_prompt`:

```
LLM output: {"tool": "read_prompt", "args": {"slug": "welcome-email"}}
    │
    ▼
agnosai receives tool call, finds matching ToolDef, calls handler
    │
    ▼
handler is a closure defined in prompt-manager's OptimizationService
    │
    ▼
handler calls self.prompt_repo.get_by_slug("welcome-email")
    │
    ▼
asyncpg executes SQL against PostgreSQL
    │
    ▼
Result flows back: DB row → domain model → JSON serialization → agnosai → LLM
```

The key insight: **agnosai does not know or care that the handler touches a database**. To agnosai, every tool is just an async callable that takes params and returns a string/dict.

### 4.4 Tool Namespace Conflict Resolution

If autoresearcher-shonku and the external tools both define a tool with the same name, shonku resolves this at merge time:

```python
# In shonku: Agent.add_tools()
def add_tools(self, tools: list[ToolDef], namespace: str | None = None) -> None:
    for tool in tools:
        key = f"{namespace}.{tool.name}" if namespace else tool.name
        if key in self._tool_registry:
            raise ToolConflictError(
                f"Tool '{key}' already registered. Use a namespace to disambiguate."
            )
        self._tool_registry[key] = tool
```

Convention: external tools are registered without a namespace (they are the "primary" tools). Internal tools can optionally use a namespace prefix like `autoresearch.analyze_trends` if conflicts arise. In practice, the tool names are distinct enough that namespacing is rarely needed.

---

## 5. LLM Credentials Flow

Credentials originate in prompt-manager's configuration and pass through each layer as an opaque config object. Only agnosai unpacks them to create an LLM client.

```
prompt-manager                                    agnosai
────────────                                      ───────
PM_LLM_PROVIDER=anthropic
PM_LLM_MODEL=claude-sonnet-4-20250514
PM_LLM_API_KEY=sk-ant-...
PM_LLM_API_BASE=https://...
PM_LLM_TEMPERATURE=0.7
         │
         ▼
PromptManagerSettings
  .llm_provider = "anthropic"
  .llm_model = "claude-sonnet-4-20250514"
  .llm_api_key = "sk-ant-..."
         │
         ▼
OptimizationService._build_llm_config()
         │
         ▼
LLMConfig(
    provider="anthropic",
    model="claude-sonnet-4-20250514",
    api_key="sk-ant-...",
    temperature=0.7,
    max_tokens=4096,
)
         │
         │  passed to AutoResearcherAgent.run(llm_config=...)
         ▼
autoresearcher-shonku
  (does not inspect llm_config — passes through)
         │
         │  passed to shonku.Agent(config=AgentConfig(llm_config=...))
         ▼
shonku
  (does not inspect llm_config — passes through)
         │
         │  passed to agnosai.Agent.run(llm_config=...)
         ▼
agnosai
  match llm_config.provider:
    case "anthropic":
      client = anthropic.AsyncAnthropic(
          api_key=llm_config.api_key
      )
    case "openai":
      client = openai.AsyncOpenAI(...)
    ...
```

### Security Considerations

- The `LLMConfig` object is the only place credentials live at runtime. It is never serialized to disk or logged.
- `LLMConfig.__repr__()` must redact the `api_key` field: `LLMConfig(provider='anthropic', model='claude-sonnet-4-20250514', api_key='sk-***')`.
- agnosai must not include API keys in error messages or traces.

---

## 6. Updated prompt-manager Architecture

### Before (Current Design)

```
src/prompt_manager/
├── llm/                          # ← OWNS LLM abstraction
│   ├── base.py                   #    Abstract LLMProvider
│   ├── factory.py                #    Provider factory
│   ├── providers/                #    6 provider implementations
│   └── prompt_improver.py        #    Meta-prompt + LLM call
└── api/services/
    └── optimization_service.py   # ← Calls LLM directly via prompt_improver
```

```python
# OLD: optimization_service.py
class OptimizationService:
    def __init__(self, prompt_repo, metric_repo, llm_provider):
        self.llm = llm_provider

    async def optimize(self, prompt_id: UUID) -> OptimizationRun:
        prompt = await self.prompt_repo.get(prompt_id)
        metrics = await self.metric_repo.aggregate(prompt_id)
        meta_prompt = build_meta_prompt(prompt, metrics)

        # Direct LLM call — tightly coupled
        result = await self.llm.complete(meta_prompt)

        new_version = parse_result(result)
        await self.version_repo.create(new_version)
        return OptimizationRun(status="completed", output_version=new_version.version)
```

### After (New Design)

```
src/prompt_manager/
├── llm/                          # ← DELETED entirely
└── api/services/
    └── optimization_service.py   # ← Delegates to autoresearcher-shonku
```

```python
# NEW: optimization_service.py
from agnosai import ToolDef, LLMConfig
from autoresearcher_shonku import AutoResearcherAgent, AutoResearcherConfig

class OptimizationService:
    def __init__(
        self,
        prompt_repo: PromptRepository,
        version_repo: VersionRepository,
        metric_repo: MetricRepository,
        experiment_repo: ExperimentRepository,
        settings: PromptManagerSettings,
    ):
        self.prompt_repo = prompt_repo
        self.version_repo = version_repo
        self.metric_repo = metric_repo
        self.experiment_repo = experiment_repo
        self.settings = settings

    async def optimize(self, prompt_slug: str) -> OptimizationRun:
        prompt = await self.prompt_repo.get_by_slug(prompt_slug)

        # 1. Build tools that wrap our DB operations
        tools = self._build_tools(prompt.id)

        # 2. Build LLM config from our settings
        llm_config = LLMConfig(
            provider=self.settings.llm_provider,
            model=self.settings.llm_model,
            api_key=self.settings.llm_api_key,
            api_base=self.settings.llm_api_base,
            temperature=0.7,
            max_tokens=4096,
        )

        # 3. Build autoresearcher config
        ar_config = AutoResearcherConfig(
            max_iterations=self.settings.optimization_max_iterations,
            min_improvement_threshold=self.settings.optimization_improvement_threshold,
            prefer_shorter_prompts=True,
            safety_checks_enabled=True,
        )

        # 4. Create optimization run record
        run = await self._create_run_record(prompt.id)

        # 5. Delegate to autoresearcher — no direct LLM calls
        try:
            result = await AutoResearcherAgent.run(
                llm_config=llm_config,
                tools=tools,
                context={
                    "prompt_slug": prompt_slug,
                    "prompt_id": str(prompt.id),
                    "metric": self.settings.optimization_metric_name,
                },
                config=ar_config,
                on_tool_call=self._log_tool_call,
            )
            await self._complete_run_record(run.id, result)
        except Exception as e:
            await self._fail_run_record(run.id, e)
            raise

        return run

    def _build_tools(self, prompt_id: UUID) -> list[ToolDef]:
        # (tool definitions as shown in Section 4.1)
        ...

    # --- Tool handlers (closures over repos) ---

    async def _handle_read_prompt(self, params: dict) -> dict:
        prompt = await self.prompt_repo.get_by_slug(params["slug"])
        latest = await self.version_repo.get_latest(prompt.id)
        return {
            "id": str(prompt.id),
            "slug": prompt.slug,
            "name": prompt.name,
            "current_version": prompt.current_version,
            "body": latest.body,
            "template_vars": latest.template_vars,
        }

    async def _handle_create_version(self, params: dict) -> dict:
        prompt = await self.prompt_repo.get_by_slug(params["slug"])
        version = await self.version_repo.create(
            prompt_id=prompt.id,
            body=params["content"],
            source="optimization",
        )
        return {
            "version_id": str(version.id),
            "version_number": version.version,
        }

    # ... (similar handlers for other tools)
```

### What Changes in the Dependency Injection

```python
# OLD: deps.py
def get_optimization_service(
    prompt_repo=Depends(get_prompt_repo),
    metric_repo=Depends(get_metric_repo),
    llm_provider=Depends(get_llm_provider),    # ← Had to create LLM provider
):
    return OptimizationService(prompt_repo, metric_repo, llm_provider)

# NEW: deps.py
def get_optimization_service(
    prompt_repo=Depends(get_prompt_repo),
    version_repo=Depends(get_version_repo),
    metric_repo=Depends(get_metric_repo),
    experiment_repo=Depends(get_experiment_repo),
    settings=Depends(get_settings),
):
    return OptimizationService(
        prompt_repo, version_repo, metric_repo, experiment_repo, settings
    )
    # No LLM provider needed — autoresearcher-shonku handles that via agnosai
```

---

## 7. Sequence Diagram: Complete Optimization Run

This traces a single optimization cycle end-to-end through all four layers.

```
User/Scheduler                prompt-manager          autoresearcher-shonku        shonku            agnosai              LLM
──────────────                ──────────────          ─────────────────────        ──────            ───────              ───
       │                             │                         │                      │                  │                  │
       │ POST /optimize/welcome-email│                         │                      │                  │                  │
       │────────────────────────────►│                         │                      │                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │ Build tools (7)         │                      │                  │                  │
       │                             │ Build LLMConfig         │                      │                  │                  │
       │                             │ Create optimization_run │                      │                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │ AutoResearcherAgent.run(│                      │                  │                  │
       │                             │   llm_config,           │                      │                  │                  │
       │                             │   tools=[7 tools],      │                      │                  │                  │
       │                             │   context={slug, metric}│                      │                  │                  │
       │                             │ )                        │                      │                  │                  │
       │                             │────────────────────────►│                      │                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │ Merge tools:          │                  │                  │
       │                             │                         │  7 external + 5 own   │                  │                  │
       │                             │                         │ = 12 tools             │                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │ Build meta-prompt     │                  │                  │
       │                             │                         │ (autoresearch          │                  │                  │
       │                             │                         │  instructions)         │                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │ shonku.Agent.run(     │                  │                  │
       │                             │                         │   tools=12,           │                  │                  │
       │                             │                         │   instructions=...,   │                  │                  │
       │                             │                         │   llm_config=...)     │                  │                  │
       │                             │                         │─────────────────────►│                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │                      │ agnosai.Agent.run│                  │
       │                             │                         │                      │   (tools=12,     │                  │
       │                             │                         │                      │    llm_config=..)│                  │
       │                             │                         │                      │─────────────────►│                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │                      │                  │ Create LLM client│
       │                             │                         │                      │                  │ (anthropic SDK)  │
       │                             │                         │                      │                  │                  │
       │                             │                         │          STEP 1: LLM decides to read current state        │
       │                             │                         │                      │                  │                  │
       │                             │                         │                      │                  │ messages + 12    │
       │                             │                         │                      │                  │ tool schemas     │
       │                             │                         │                      │                  │─────────────────►│
       │                             │                         │                      │                  │                  │
       │                             │                         │                      │                  │◄─────────────────│
       │                             │                         │                      │                  │ tool_call:       │
       │                             │                         │                      │                  │  read_prompt     │
       │                             │                         │                      │                  │  {slug:          │
       │                             │                         │                      │                  │   "welcome-email"}│
       │                             │                         │                      │                  │                  │
       │                             │                         │                      │                  │ Execute handler  │
       │                             │◄ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│ (closure calls   │
       │                             │  handler runs:          │                      │                  │  prompt_repo)    │
       │                             │  self.prompt_repo       │                      │                  │                  │
       │                             │    .get_by_slug(...)    │                      │                  │                  │
       │                             │─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│                  │
       │                             │                         │                      │                  │ Append result    │
       │                             │                         │                      │                  │ to messages      │
       │                             │                         │                      │                  │                  │
       │                             │                         │          STEP 2: LLM reads metrics                        │
       │                             │                         │                      │                  │─────────────────►│
       │                             │                         │                      │                  │◄─────────────────│
       │                             │                         │                      │                  │ tool_call:       │
       │                             │                         │                      │                  │  get_metrics     │
       │                             │◄ ─ ─ ─ handler executes─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ │                  │
       │                             │─ ─ ─ ─ result ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ►│                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │          STEP 3: LLM analyzes trends (internal tool)      │
       │                             │                         │                      │                  │─────────────────►│
       │                             │                         │                      │                  │◄─────────────────│
       │                             │                         │                      │                  │ tool_call:       │
       │                             │                         │◄ ─ ─ handler executes─ ─ ─ ─ ─ ─ ─ ─ ─│  analyze_trends  │
       │                             │                         │─ ─ ─ result ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │          STEP 4: LLM proposes new prompt                  │
       │                             │                         │                      │                  │─────────────────►│
       │                             │                         │                      │                  │◄─────────────────│
       │                             │                         │                      │                  │ tool_calls:      │
       │                             │                         │                      │                  │  validate_vars   │
       │                             │                         │                      │                  │  check_safety    │
       │                             │                         │                      │                  │                  │
       │                             │                         │          STEP 5: LLM creates version + experiment         │
       │                             │                         │                      │                  │─────────────────►│
       │                             │                         │                      │                  │◄─────────────────│
       │                             │                         │                      │                  │ tool_calls:      │
       │                             │                         │                      │                  │  create_version  │
       │                             │◄ ─ ─ ─ handler writes to DB ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│  create_experiment│
       │                             │─ ─ ─ ─ result ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─►│                  │
       │                             │                         │                      │                  │                  │
       │                             │                         │          STEP N: LLM returns final summary                │
       │                             │                         │                      │                  │─────────────────►│
       │                             │                         │                      │                  │◄─────────────────│
       │                             │                         │                      │                  │ final_text:      │
       │                             │                         │                      │                  │ "Optimization    │
       │                             │                         │                      │                  │  complete..."    │
       │                             │                         │                      │                  │                  │
       │                             │                         │                      │◄─────────────────│                  │
       │                             │                         │                      │ AgentResult      │                  │
       │                             │                         │◄─────────────────────│                  │                  │
       │                             │                         │ AgentResult           │                  │                  │
       │                             │◄────────────────────────│                      │                  │                  │
       │                             │ AutoResearcherResult    │                      │                  │                  │
       │                             │                         │                      │                  │                  │
       │                             │ Update optimization_run │                      │                  │                  │
       │                             │ status = 'completed'    │                      │                  │                  │
       │                             │                         │                      │                  │                  │
       │◄────────────────────────────│                         │                      │                  │                  │
       │ 200 OK {run_id, status}     │                         │                      │                  │                  │
```

---

## 8. Error Propagation Model

### 8.1 Error Types by Layer

```
agnosai errors:
├── LLMConnectionError          # Cannot reach the LLM API
├── LLMRateLimitError           # 429 from provider
├── LLMAuthenticationError      # Invalid API key
├── LLMTimeoutError             # Request timed out
├── LLMContentFilterError       # Content policy violation
├── MaxStepsExceededError       # Agent hit step limit without completing
└── ToolExecutionError          # A tool handler raised an exception
    └── .tool_name: str
    └── .original_error: Exception

shonku errors:
├── ToolConflictError           # Duplicate tool names at merge time
├── PipelineError               # A node in a pipeline failed
└── AgentConfigError            # Invalid agent configuration

autoresearcher-shonku errors:
├── OptimizationLoopError       # The optimization loop failed
│   └── .iteration: int
│   └── .cause: Exception
├── SafetyCheckFailedError      # Proposed prompt failed safety checks
└── NoImprovementFoundError     # All iterations exhausted without improvement

prompt-manager errors:
├── PromptNotFoundError         # slug does not exist
├── ExperimentConflictError     # Already a running experiment for this prompt
├── MetricQueryError            # DB error during metric aggregation
└── OptimizationServiceError    # Wrapper for autoresearcher failures
```

### 8.2 Propagation Rules

**Rule 1: Tool failures are caught by agnosai and reported to the LLM.**

When a tool handler raises an exception, agnosai does NOT terminate the agent loop. Instead, it converts the error into a tool result message that the LLM can see and react to:

```python
# Inside agnosai's execution loop
try:
    result = await tool.handler(params)
except Exception as e:
    result = {
        "error": True,
        "error_type": type(e).__name__,
        "error_message": str(e),
    }
    # This is appended to the conversation as the tool's response.
    # The LLM can then decide: retry, try a different approach, or give up.
```

This is critical because it allows the LLM to recover from transient failures (e.g., a DB timeout on `get_metrics` — the LLM can retry).

**Rule 2: LLM failures are retried by agnosai with exponential backoff.**

```python
# Inside agnosai
LLM_RETRY_CONFIG = {
    LLMRateLimitError: {"max_retries": 5, "base_delay": 1.0, "max_delay": 60.0},
    LLMTimeoutError: {"max_retries": 3, "base_delay": 2.0, "max_delay": 30.0},
    LLMConnectionError: {"max_retries": 3, "base_delay": 1.0, "max_delay": 15.0},
}
# LLMAuthenticationError and LLMContentFilterError are NOT retried — they fail immediately.
```

**Rule 3: Max steps exceeded is a clean exit, not a crash.**

If the agent hits `max_steps` without producing a final response, agnosai returns an `AgentResult` with `output=None` and `exceeded_max_steps=True`. autoresearcher-shonku interprets this as "the optimization attempt was inconclusive" and logs it accordingly.

**Rule 4: Unrecoverable errors propagate up as typed exceptions.**

```
DB error in read_prompt handler
    → ToolExecutionError (agnosai catches, reports to LLM)
    → LLM retries once
    → ToolExecutionError again
    → LLM says "I cannot proceed, the database is unavailable"
    → AgentResult with output describing the failure
    → autoresearcher-shonku wraps as OptimizationLoopError
    → prompt-manager catches, marks optimization_run as 'failed', returns 500
```

### 8.3 The Stuck Agent Problem

If the LLM enters an infinite loop (e.g., repeatedly calling the same tool), agnosai detects this via:

1. **Max steps**: Hard limit (default 50 steps). Terminates the loop.
2. **Repetition detection**: If the same tool is called with the same arguments 3 times consecutively, agnosai injects a system message: "You have called {tool_name} with identical arguments 3 times. Please try a different approach or conclude your work."
3. **Time budget**: Optional wall-clock timeout (e.g., 5 minutes). If exceeded, the agent is terminated with `AgentTimeoutError`.

---

## 9. Observability and Tracing

### 9.1 Structured Logging at Each Layer

Each layer emits structured log events with a shared `trace_id` that flows down from prompt-manager.

```python
# prompt-manager creates the trace_id
trace_id = str(uuid4())
result = await AutoResearcherAgent.run(
    ...,
    context={"trace_id": trace_id, ...},
)

# Each layer logs with the trace_id
# agnosai:
logger.info("tool_call", extra={
    "trace_id": context.get("trace_id"),
    "layer": "agnosai",
    "tool_name": "read_prompt",
    "step": 3,
    "duration_ms": 42,
})
```

### 9.2 The on_tool_call Callback

agnosai exposes an `on_tool_call` hook that fires every time a tool is called. This callback propagates up through all layers, enabling cross-layer observability.

```python
@dataclass
class ToolCallEvent:
    tool_name: str
    arguments: dict
    result: Any
    duration_ms: float
    step: int
    error: Exception | None

# prompt-manager provides the callback
async def log_tool_call(event: ToolCallEvent):
    # Log to structured logging
    logger.info("agent_tool_call", extra={
        "tool": event.tool_name,
        "step": event.step,
        "duration_ms": event.duration_ms,
        "error": str(event.error) if event.error else None,
    })

    # Optionally: write to optimization_runs.tool_call_log (JSONB column)
    await optimization_run_repo.append_tool_call(
        run_id=current_run_id,
        tool_call={
            "tool": event.tool_name,
            "args": event.arguments,
            "result_summary": summarize(event.result),
            "duration_ms": event.duration_ms,
            "step": event.step,
        },
    )
```

### 9.3 Full Trace of an Optimization Run

A single optimization run produces a trace like:

```json
{
  "trace_id": "abc-123",
  "run_id": "def-456",
  "prompt_slug": "welcome-email",
  "started_at": "2026-03-25T10:00:00Z",
  "completed_at": "2026-03-25T10:02:34Z",
  "total_steps": 12,
  "total_llm_calls": 6,
  "total_tokens": {"input": 8420, "output": 3150},
  "tool_calls": [
    {"step": 1, "tool": "read_prompt", "duration_ms": 12},
    {"step": 2, "tool": "get_metrics", "duration_ms": 45},
    {"step": 3, "tool": "get_sample_interactions", "duration_ms": 89},
    {"step": 4, "tool": "analyze_trends", "duration_ms": 3},
    {"step": 6, "tool": "validate_template_vars", "duration_ms": 1},
    {"step": 6, "tool": "check_safety", "duration_ms": 2},
    {"step": 8, "tool": "create_version", "duration_ms": 34},
    {"step": 9, "tool": "create_experiment", "duration_ms": 28},
    {"step": 11, "tool": "compute_composite_score", "duration_ms": 1}
  ],
  "result": {
    "new_version": 4,
    "experiment_id": "ghi-789",
    "strategy": "conservative",
    "reasoning": "Simplified the greeting section and added explicit success criteria..."
  }
}
```

### 9.4 Tracking "LLM in agnosai called read_prompt defined in prompt-manager"

The `ToolCallEvent` includes the tool name, which is sufficient to determine origin:

| Tool name | Defined in | Origin |
|-----------|------------|--------|
| `read_prompt` | prompt-manager | External (application domain) |
| `create_version` | prompt-manager | External (application domain) |
| `get_metrics` | prompt-manager | External (application domain) |
| `create_experiment` | prompt-manager | External (application domain) |
| `update_weights` | prompt-manager | External (application domain) |
| `conclude_experiment` | prompt-manager | External (application domain) |
| `get_sample_interactions` | prompt-manager | External (application domain) |
| `analyze_trends` | autoresearcher-shonku | Internal (optimization logic) |
| `validate_template_vars` | autoresearcher-shonku | Internal (optimization logic) |
| `check_safety` | autoresearcher-shonku | Internal (optimization logic) |
| `compute_composite_score` | autoresearcher-shonku | Internal (optimization logic) |
| `compare_versions` | autoresearcher-shonku | Internal (optimization logic) |

autoresearcher-shonku can optionally tag tools with an `origin` metadata field:

```python
ToolDef(
    name="analyze_trends",
    description="...",
    parameters={...},
    handler=analyze_trends_handler,
    metadata={"origin": "autoresearcher-shonku", "category": "analysis"},
)
```

prompt-manager does the same:

```python
ToolDef(
    name="read_prompt",
    ...,
    metadata={"origin": "prompt-manager", "category": "domain"},
)
```

The `on_tool_call` callback can then log the origin alongside the tool name.

---

## 10. Configuration at Each Layer

### Layer 1: agnosai

agnosai is configured entirely through `LLMConfig` passed at runtime. It has no global configuration, no config files, no environment variables of its own.

```python
# All config comes from the caller
agnosai.Agent.run(
    instructions="...",
    tools=[...],
    llm_config=LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="sk-ant-...",
        temperature=0.7,
        max_tokens=4096,
    ),
    max_steps=50,
)
```

### Layer 2: shonku

shonku's `AgentConfig` adds agent-level metadata but delegates LLM config downward.

```python
AgentConfig(
    name="my-agent",
    version="0.1.0",
    instructions="...",
    tools=[...],
    llm_config=LLMConfig(...),     # Passed through to agnosai
    max_steps=50,                   # Passed through to agnosai
    metadata={
        "published_by": "autoresearcher-shonku",
        "agent_type": "optimizer",
    },
)
```

### Layer 3: autoresearcher-shonku

`AutoResearcherConfig` controls the optimization loop behavior.

```python
AutoResearcherConfig(
    # Loop control
    max_iterations=10,                    # Max propose-evaluate-decide cycles
    min_improvement_threshold=0.01,       # 1% minimum improvement to keep

    # Prompt constraints
    prefer_shorter_prompts=True,
    max_prompt_length=4000,

    # Strategy
    strategies=["conservative", "ablation", "synthesis"],

    # Safety
    safety_checks_enabled=True,
    max_edit_distance_ratio=0.5,          # Don't change more than 50% of the prompt

    # Evaluation
    min_sample_size=100,                  # Samples per arm before deciding
    significance_threshold=0.05,          # p-value threshold
)
```

### Layer 4: prompt-manager

prompt-manager's settings are the root configuration. All other layers' configs are derived from here.

```python
class PromptManagerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PM_", env_file=".env")

    # Database
    database_url: str = "postgresql://localhost:5432/prompt_manager"

    # Server
    host: str = "0.0.0.0"
    port: int = 8910

    # LLM (passed to agnosai via autoresearcher-shonku)
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str | None = None
    llm_api_base: str | None = None

    # Optimization (maps to AutoResearcherConfig)
    optimization_auto_enabled: bool = False
    optimization_max_iterations: int = 10
    optimization_improvement_threshold: float = 0.01
    optimization_metric_name: str = "quality_score"
    optimization_min_sample_size: int = 100
    optimization_strategies: list[str] = ["conservative", "ablation"]

    # MCP
    mcp_enabled: bool = True
```

### Config Mapping Summary

```
PM_LLM_PROVIDER          ──► LLMConfig.provider          ──► agnosai
PM_LLM_MODEL             ──► LLMConfig.model              ──► agnosai
PM_LLM_API_KEY           ──► LLMConfig.api_key            ──► agnosai
PM_OPTIMIZATION_MAX_ITERATIONS ──► AutoResearcherConfig.max_iterations
PM_OPTIMIZATION_IMPROVEMENT_THRESHOLD ──► AutoResearcherConfig.min_improvement_threshold
PM_OPTIMIZATION_METRIC_NAME ──► context["metric"]
PM_OPTIMIZATION_MIN_SAMPLE_SIZE ──► AutoResearcherConfig.min_sample_size
```

---

## 11. Independent Usability of Each Package

### agnosai standalone

Use agnosai directly for any LLM agent task — no shonku or autoresearcher needed.

```python
from agnosai import Agent, LLMConfig, ToolDef

async def main():
    result = await Agent.run(
        instructions="You are a helpful coding assistant.",
        tools=[
            ToolDef(
                name="read_file",
                description="Read a file from disk.",
                parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                handler=lambda params: open(params["path"]).read(),
            ),
        ],
        llm_config=LLMConfig(
            provider="openai",
            model="gpt-4o",
            api_key="sk-...",
        ),
    )
    print(result.output)
```

### shonku standalone

Use shonku to build and publish reusable agents — no autoresearcher or prompt-manager needed.

```python
from shonku import Agent, AgentConfig
from agnosai import LLMConfig, ToolDef

config = AgentConfig(
    name="code-reviewer",
    version="1.0.0",
    instructions="Review the provided code for bugs and improvements.",
    tools=[
        ToolDef(name="read_file", ...),
        ToolDef(name="write_review", ...),
    ],
    llm_config=LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514", api_key="..."),
)

agent = Agent(config)
result = await agent.run(context={"file_path": "main.py"})
```

### autoresearcher-shonku standalone

Use autoresearcher-shonku with any data source — not just prompt-manager. For example, optimizing email subject lines stored in a CSV:

```python
from autoresearcher_shonku import AutoResearcherAgent, AutoResearcherConfig
from agnosai import LLMConfig, ToolDef

# Define tools that read/write to a CSV instead of a database
tools = [
    ToolDef(name="read_prompt", handler=read_from_csv, ...),
    ToolDef(name="create_version", handler=append_to_csv, ...),
    ToolDef(name="get_metrics", handler=read_metrics_from_csv, ...),
    # ... other tools
]

result = await AutoResearcherAgent.run(
    llm_config=LLMConfig(provider="anthropic", model="claude-sonnet-4-20250514", api_key="..."),
    tools=tools,
    context={"prompt_slug": "subject-line-a", "metric": "open_rate"},
    config=AutoResearcherConfig(max_iterations=5),
)
```

This demonstrates the key design goal: autoresearcher-shonku defines the optimization *logic* but does not own the *data*. Any application can provide tools that connect to its own storage.

### prompt-manager without optimization

The `client` and `metric` extras work without `autoresearcher-shonku`:

```bash
pip install prompt-manager[client]   # No LLM deps, no agent deps
pip install prompt-manager[metric]   # No LLM deps, no agent deps
```

The API extra could also be installed without optimization by making autoresearcher-shonku an optional import:

```python
# In optimization_service.py
try:
    from autoresearcher_shonku import AutoResearcherAgent
    HAS_AUTORESEARCHER = True
except ImportError:
    HAS_AUTORESEARCHER = False

class OptimizationService:
    async def optimize(self, prompt_slug: str):
        if not HAS_AUTORESEARCHER:
            raise FeatureNotAvailableError(
                "Optimization requires the 'autoresearcher-shonku' package. "
                "Install with: pip install prompt-manager[api]"
            )
        ...
```

---

## 12. Migration Path from Current Design

### What Changes

| Component | Before | After |
|-----------|--------|-------|
| `src/prompt_manager/llm/` | 8 files, ~1200 lines | **Deleted** — replaced by agnosai |
| `llm/base.py` (LLMProvider ABC) | Owned by prompt-manager | Replaced by `agnosai.LLMConfig` |
| `llm/providers/*.py` | 6 provider implementations | Replaced by agnosai's internal providers |
| `llm/prompt_improver.py` | Meta-prompt + direct LLM call | Replaced by autoresearcher-shonku's agent |
| `optimization_service.py` | Calls LLM directly | Delegates to `AutoResearcherAgent.run()` |
| `pyproject.toml` `[llm]` extra | `anthropic`, `openai`, etc. | **Removed** — transitive via agnosai |
| `pyproject.toml` `[api]` extra | No agent deps | Adds `autoresearcher-shonku>=0.1` |
| `deps.py` | Injects `LLMProvider` | No longer injects LLM provider |

### What Stays the Same

| Component | Status |
|-----------|--------|
| `core/models.py`, `core/schemas.py` | Unchanged |
| `api/db/*_repo.py` | Unchanged |
| `api/routers/*` | Unchanged (except `optimize.py` response shape may evolve) |
| `api/services/prompt_service.py` | Unchanged |
| `api/services/experiment_service.py` | Unchanged |
| `api/services/metric_service.py` | Unchanged |
| `client/` package | Unchanged |
| `metric/` package | Unchanged |
| `api/mcp/server.py` | Unchanged — MCP tools still defined here |
| Database schema | Unchanged (may add `tool_call_log JSONB` to `optimization_runs`) |

### Migration Steps

1. **Implement agnosai** with the `LLMConfig`, `ToolDef`, `Agent`, and provider abstraction. Publish to PyPI.
2. **Implement shonku** with `AgentConfig`, `Agent` wrapper, tool merging, and `Pipeline`/`Node`. Publish to PyPI.
3. **Implement autoresearcher-shonku** with `AutoResearcherAgent`, `AutoResearcherConfig`, analytical tools, and the meta-prompt. Publish to PyPI.
4. **Refactor prompt-manager**:
   a. Delete `src/prompt_manager/llm/` entirely.
   b. Rewrite `optimization_service.py` to build tools and delegate to `AutoResearcherAgent.run()`.
   c. Update `pyproject.toml`: remove `[llm]` extra, add `autoresearcher-shonku` to `[api]`.
   d. Update `deps.py`: remove LLM provider injection.
   e. Update tests: mock `AutoResearcherAgent.run()` instead of mocking LLM providers.
5. **Add observability**: Add `tool_call_log` JSONB column to `optimization_runs`, wire up `on_tool_call` callback.

### Risk Mitigation

- **Risk**: agnosai is not yet published — prompt-manager cannot install it.
  **Mitigation**: Use path dependencies during development: `agnosai = {path = "../agnosai"}`. Switch to PyPI versions once published.

- **Risk**: Breaking changes in agnosai's `ToolDef` protocol.
  **Mitigation**: Pin exact versions in development. Use semver strictly. The `ToolDef` protocol should be frozen early and changed only via deprecation cycles.

- **Risk**: Performance regression from the extra layers of indirection.
  **Mitigation**: The overhead is negligible — it is async function calls, not HTTP. The LLM call (seconds) dwarfs the overhead of passing through 4 layers (microseconds).

---

## Appendix A: The Meta-Prompt (autoresearcher-shonku)

autoresearcher-shonku constructs the instructions passed to the LLM. This is the "brain" of the optimization loop.

```
You are an autonomous prompt optimizer. Your goal is to improve the prompt
identified by slug "{prompt_slug}" by optimizing the metric "{metric}".

## Available Tools

You have access to tools for reading prompts, creating versions, managing
experiments, reading metrics, and analyzing data. Use them freely.

## Process

1. OBSERVE: Read the current prompt and its recent metrics.
2. ANALYZE: Use analyze_trends and get_sample_interactions to understand
   what is working and what is not.
3. PROPOSE: Write an improved prompt version. Before creating it:
   - Use validate_template_vars to ensure all required variables are present.
   - Use check_safety to verify the prompt is safe.
   - Use compare_versions to review your changes.
4. DEPLOY: Use create_version to save the new prompt, then create_experiment
   to set up a shadow test at low weight (5-10%).
5. EVALUATE: Use get_metrics to check if the new version improves the metric.
   Use compute_composite_score for multi-metric comparison.
6. DECIDE: If improved, use update_weights to increase traffic. If not,
   use conclude_experiment to end the test.

## Constraints

- Prefer shorter prompts that achieve the same results.
- Do not remove required template variables.
- Do not add prompt injection vulnerabilities.
- Maximum prompt length: {max_prompt_length} characters.
- Minimum improvement threshold: {min_improvement_threshold}.

## Important

You are autonomous. Do not ask for permission. Use the tools, make decisions
based on the data, and report your findings when done.
```

---

## Appendix B: Database Schema Addition

One new column on the existing `optimization_runs` table:

```sql
ALTER TABLE optimization_runs
    ADD COLUMN tool_call_log JSONB DEFAULT '[]',
    ADD COLUMN agent_steps INTEGER,
    ADD COLUMN agent_tokens_input INTEGER,
    ADD COLUMN agent_tokens_output INTEGER;
```

This captures the full tool call trace for each optimization run, enabling post-hoc analysis of agent behavior.

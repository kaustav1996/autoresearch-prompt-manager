# agnosai — LLM-Agnostic Agent Runtime: Design Document

**Date**: 2026-03-25
**Status**: Design only — no code produced
**Layer**: Foundation (layer 4 of 4)

---

## Table of Contents

1. [Position in the Stack](#1-position-in-the-stack)
2. [Design Philosophy](#2-design-philosophy)
3. [Package Structure](#3-package-structure)
4. [Core Protocols and Classes](#4-core-protocols-and-classes)
5. [Agent Execution Loop](#5-agent-execution-loop)
6. [Tool Protocol](#6-tool-protocol)
7. [LLM Provider Interface](#7-llm-provider-interface)
8. [Node Execution Model](#8-node-execution-model)
9. [Agent Lifecycle and Hooks](#9-agent-lifecycle-and-hooks)
10. [Result Types](#10-result-types)
11. [Agent Composition](#11-agent-composition)
12. [Credential Management](#12-credential-management)
13. [PyPI Publishability](#13-pypi-publishability)
14. [Example Usage](#14-example-usage)
15. [Open Questions](#15-open-questions)

---

## 1. Position in the Stack

```
prompt-manager          — prompt versioning, A/B testing, metrics
    ↓ depends on
autoresearcher-shonku   — research automation, paper finding, synthesis
    ↓ depends on
shonku                  — domain-specific agent behaviors and tool sets
    ↓ depends on
agnosai                 — generic agent runtime (THIS LAYER)
```

agnosai knows **nothing** about prompts, research, optimization, or any domain. It is a pure execution runtime: give it tools, give it a goal, give it an LLM connection, and it runs the observe-think-act loop until the goal is achieved or a limit is hit.

Everything above agnosai is a consumer that assembles tools and instructions and calls down into it.

---

## 2. Design Philosophy

1. **Protocol over inheritance** — Use Python `Protocol` classes (structural subtyping) wherever possible. Concrete base classes only where shared implementation is genuinely needed.
2. **Tools are passed in, never hardcoded** — agnosai is an executor, not an application. The caller decides what the agent can do.
3. **Zero domain knowledge** — agnosai must never import from shonku, autoresearcher-shonku, or prompt-manager.
4. **Minimal dependencies** — Core requires only `pydantic>=2.0` and the standard library. Provider adapters are optional extras.
5. **Async-first, sync-compatible** — The core loop is async. A synchronous `run_sync()` wrapper is provided for simple use cases.
6. **Streaming as a first-class concept** — Intermediate observations, tool calls, and partial results are yielded via `AsyncIterator`, not just returned at the end.

---

## 3. Package Structure

```
agnosai/
├── pyproject.toml
├── src/
│   └── agnosai/
│       ├── __init__.py              # Public API re-exports
│       ├── py.typed                 # PEP 561 marker
│       │
│       ├── core/
│       │   ├── __init__.py
│       │   ├── agent.py             # Agent class — the central runtime
│       │   ├── loop.py              # AgentLoop — the execution engine
│       │   ├── types.py             # AgentResult, StepResult, shared types
│       │   └── errors.py            # AgnosaiError hierarchy
│       │
│       ├── tool/
│       │   ├── __init__.py
│       │   ├── protocol.py          # Tool protocol and ToolResult
│       │   ├── registry.py          # ToolRegistry — validation and lookup
│       │   ├── decorator.py         # @tool decorator for defining tools
│       │   └── schema.py            # JSON Schema generation from type hints
│       │
│       ├── llm/
│       │   ├── __init__.py
│       │   ├── protocol.py          # LLMProvider protocol
│       │   ├── types.py             # Message, LLMResponse, ToolCallRequest
│       │   ├── creds.py             # LLMCredentials — typed credential container
│       │   └── providers/
│       │       ├── __init__.py
│       │       ├── anthropic.py     # Claude adapter
│       │       ├── openai.py        # OpenAI + OpenRouter adapter
│       │       ├── groq.py          # Groq adapter
│       │       ├── gemini.py        # Google Gemini adapter
│       │       ├── bedrock.py       # AWS Bedrock adapter
│       │       └── openai_compat.py # Generic OpenAI-compatible endpoint
│       │
│       ├── node/
│       │   ├── __init__.py
│       │   ├── protocol.py          # Node protocol
│       │   ├── runner.py            # NodeRunner — execute a node
│       │   └── manifest.py          # NodeManifest — declarative node config
│       │
│       ├── hooks/
│       │   ├── __init__.py
│       │   └── protocol.py          # Lifecycle hook protocol
│       │
│       └── _internal/
│           ├── __init__.py
│           └── util.py              # Shared internal utilities
│
├── tests/
│   ├── unit/
│   └── integration/
│
└── examples/
    ├── hello_agent.py
    ├── multi_tool_agent.py
    └── agent_as_tool.py
```

**Optional extras** (in `pyproject.toml`):

```toml
[project.optional-dependencies]
anthropic = ["anthropic>=0.40"]
openai = ["openai>=1.50"]
groq = ["groq>=0.12"]
gemini = ["google-genai>=1.0"]
bedrock = ["boto3>=1.35"]
all = ["agnosai[anthropic,openai,groq,gemini,bedrock]"]
```

---

## 4. Core Protocols and Classes

### 4.1 Tool Protocol

```python
# agnosai/tool/protocol.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

class ToolResultStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"

@dataclass(frozen=True, slots=True)
class ToolResult:
    """The outcome of a single tool invocation."""
    status: ToolResultStatus
    data: Any = None           # Arbitrary return payload on success
    error: str | None = None   # Human-readable error message on failure

    @classmethod
    def ok(cls, data: Any = None) -> ToolResult:
        return cls(status=ToolResultStatus.SUCCESS, data=data)

    @classmethod
    def err(cls, error: str) -> ToolResult:
        return cls(status=ToolResultStatus.ERROR, error=error)

@dataclass(frozen=True, slots=True)
class ToolSpec:
    """The static description of a tool — everything the LLM needs to decide
    whether and how to call it."""
    name: str
    description: str
    parameters_schema: dict[str, Any]   # JSON Schema object
    returns_schema: dict[str, Any] | None = None

@runtime_checkable
class Tool(Protocol):
    """A tool is anything that has a spec and can be called."""
    @property
    def spec(self) -> ToolSpec: ...

    async def __call__(self, **kwargs: Any) -> ToolResult: ...
```

### 4.2 LLM Provider Protocol

```python
# agnosai/llm/protocol.py

from __future__ import annotations
from typing import AsyncIterator, Protocol, runtime_checkable

from agnosai.llm.types import (
    LLMResponse,
    Message,
    StreamChunk,
    ToolCallRequest,
)
from agnosai.tool.protocol import ToolSpec

@runtime_checkable
class LLMProvider(Protocol):
    """Abstract LLM connection. Implementations live in agnosai/llm/providers/."""

    async def complete(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
    ) -> LLMResponse:
        """Send messages + tool definitions, receive a response that may
        contain text, tool call requests, or both."""
        ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        *,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        stop_sequences: list[str] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming variant. Yields chunks as they arrive."""
        ...
```

### 4.3 LLM Types

```python
# agnosai/llm/types.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class Role(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"

@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str
    name: str | None = None         # For tool-result messages
    tool_call_id: str | None = None # Correlates tool result to its request

@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    """The LLM is asking the runtime to execute a tool."""
    id: str                         # Provider-assigned call ID
    tool_name: str
    arguments: dict[str, Any]

@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized response from any provider."""
    content: str | None = None
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    stop_reason: str | None = None  # "end_turn", "tool_use", "max_tokens"
    usage: TokenUsage | None = None

@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int

@dataclass(frozen=True, slots=True)
class StreamChunk:
    """A single chunk from a streaming response."""
    delta_content: str | None = None
    tool_call: ToolCallRequest | None = None  # Emitted when complete
    stop_reason: str | None = None
    usage: TokenUsage | None = None           # Emitted on final chunk
```

### 4.4 Agent and AgentResult

```python
# agnosai/core/types.py

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class AgentStatus(Enum):
    SUCCESS = "success"
    ERROR = "error"
    MAX_STEPS = "max_steps"
    TIMEOUT = "timeout"

@dataclass(frozen=True, slots=True)
class StepResult:
    """One iteration of the agent loop."""
    step_number: int
    llm_response: LLMResponse
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    duration_ms: float = 0.0

@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """Record of a tool invocation within a step."""
    tool_name: str
    arguments: dict[str, Any]
    result: ToolResult
    duration_ms: float = 0.0

@dataclass(frozen=True, slots=True)
class AgentResult:
    """The final output of an agent run."""
    status: AgentStatus
    output: Any                                 # The agent's final answer/data
    steps: list[StepResult] = field(default_factory=list)
    total_tokens: TokenUsage | None = None
    total_duration_ms: float = 0.0
    error: str | None = None
```

### 4.5 Agent Class

```python
# agnosai/core/agent.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from agnosai.core.types import AgentResult, StepResult
from agnosai.hooks.protocol import AgentHooks
from agnosai.llm.protocol import LLMProvider
from agnosai.tool.protocol import Tool

@dataclass
class AgentConfig:
    max_steps: int = 30
    timeout_seconds: float = 300.0
    temperature: float = 0.0
    max_tokens_per_step: int = 4096

class Agent:
    """The central runtime. Stateless between runs — all state lives inside
    a single `run()` invocation."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        config: AgentConfig | None = None,
        hooks: AgentHooks | None = None,
    ) -> None:
        self._llm = llm
        self._config = config or AgentConfig()
        self._hooks = hooks

    async def run(
        self,
        instructions: str,
        tools: list[Tool],
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Execute the agent loop to completion and return the final result."""
        ...

    async def run_stream(
        self,
        instructions: str,
        tools: list[Tool],
        *,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[StepResult | AgentResult]:
        """Execute the agent loop, yielding each step as it completes.
        The final item yielded is always an AgentResult."""
        ...

    def run_sync(
        self,
        instructions: str,
        tools: list[Tool],
        *,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Synchronous convenience wrapper. Creates an event loop if needed."""
        ...
```

---

## 5. Agent Execution Loop

The loop lives in `agnosai/core/loop.py` and is called by `Agent.run()`. This is the heart of the framework.

### 5.1 Loop Pseudocode

```
function agent_loop(llm, instructions, tools, config, hooks):
    messages = [Message(role=SYSTEM, content=instructions)]

    if context is provided:
        messages.append(Message(role=USER, content=serialize(context)))

    messages.append(Message(role=USER, content="Begin."))

    hooks.on_start(instructions, tools)
    steps = []
    total_usage = TokenUsage(0, 0)

    for step_number in 1..config.max_steps:
        # 1. THINK — ask the LLM what to do next
        response = await llm.complete(
            messages,
            tools=[t.spec for t in tools],
            temperature=config.temperature,
            max_tokens=config.max_tokens_per_step,
        )
        total_usage += response.usage

        # 2. CHECK — did the LLM decide to finish?
        if response.stop_reason == "end_turn" and not response.tool_calls:
            hooks.on_complete(response.content)
            return AgentResult(
                status=SUCCESS,
                output=response.content,
                steps=steps,
                total_tokens=total_usage,
            )

        # 3. ACT — execute requested tool calls
        tool_records = []
        for call in response.tool_calls:
            tool = lookup(tools, call.tool_name)
            hooks.on_tool_call(tool, call.arguments)

            result = await tool(**call.arguments)

            tool_records.append(ToolCallRecord(
                tool_name=call.tool_name,
                arguments=call.arguments,
                result=result,
            ))

            # 4. OBSERVE — feed the tool result back as a message
            messages.append(Message(
                role=TOOL,
                content=serialize(result),
                name=call.tool_name,
                tool_call_id=call.id,
            ))

        step = StepResult(step_number, response, tool_records)
        steps.append(step)
        hooks.on_step(step)

        # Also append the assistant's own message to maintain conversation
        messages.append(Message(role=ASSISTANT, content=response.content,
                                tool_calls=response.tool_calls))

    # Exhausted max_steps
    return AgentResult(status=MAX_STEPS, output=None, steps=steps,
                       total_tokens=total_usage)
```

### 5.2 Message History Construction

The conversation fed to the LLM grows with each step:

```
[SYSTEM]    instructions
[USER]      context (optional)
[USER]      "Begin."
[ASSISTANT] (thinks + requests tool calls)         ← step 1
[TOOL]      result of tool call 1a
[TOOL]      result of tool call 1b
[ASSISTANT] (thinks + requests more tool calls)    ← step 2
[TOOL]      result of tool call 2a
[ASSISTANT] "Here is the final answer: ..."        ← terminal
```

### 5.3 Parallel Tool Execution

When the LLM requests multiple tool calls in a single response (common with Claude and GPT-4), agnosai executes them concurrently:

```python
async def _execute_tool_calls(
    self,
    calls: list[ToolCallRequest],
    tools: dict[str, Tool],
) -> list[ToolCallRecord]:
    async def _run_one(call: ToolCallRequest) -> ToolCallRecord:
        tool = tools[call.tool_name]
        start = time.monotonic()
        try:
            result = await tool(**call.arguments)
        except Exception as e:
            result = ToolResult.err(str(e))
        elapsed = (time.monotonic() - start) * 1000
        return ToolCallRecord(call.tool_name, call.arguments, result, elapsed)

    records = await asyncio.gather(*[_run_one(c) for c in calls])
    return list(records)
```

### 5.4 Timeout Enforcement

The entire `run()` is wrapped in `asyncio.wait_for(coro, timeout=config.timeout_seconds)`. If the timeout fires, the loop captures all steps so far and returns `AgentResult(status=TIMEOUT)`.

---

## 6. Tool Protocol

### 6.1 Defining Tools

Tools can be created three ways:

**A. The `@tool` decorator** (recommended for simple tools):

```python
from agnosai import tool, ToolResult

@tool(
    name="search_web",
    description="Search the web for information.",
)
async def search_web(query: str, max_results: int = 5) -> ToolResult:
    results = await some_search_api(query, max_results)
    return ToolResult.ok(results)
```

The decorator inspects the function signature and type hints to auto-generate the `parameters_schema` (JSON Schema). Pydantic models are supported for complex parameter types.

**B. Implementing the Tool protocol directly**:

```python
class DatabaseQuery:
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="query_db",
            description="Run a read-only SQL query.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "The SQL query"},
                },
                "required": ["sql"],
            },
        )

    async def __call__(self, sql: str) -> ToolResult:
        rows = await self.conn.fetch(sql)
        return ToolResult.ok([dict(r) for r in rows])
```

**C. From a Pydantic model** (for schema-first design):

```python
from pydantic import BaseModel, Field
from agnosai import tool_from_model

class FileReadParams(BaseModel):
    path: str = Field(description="Absolute file path")
    encoding: str = Field(default="utf-8", description="File encoding")

read_file_tool = tool_from_model(
    name="read_file",
    description="Read a file from disk.",
    model=FileReadParams,
    handler=_read_file_handler,
)
```

### 6.2 Tool Flow: Caller to Agent to LLM

```
Caller (e.g. shonku)          agnosai.Agent              LLM Provider
─────────────────────          ───────────                ────────────
defines tools as list[Tool]
        │
        ├── run(instructions,
        │       tools=[t1,t2,t3])
        │                      extracts [t.spec for t in tools]
        │                              │
        │                              ├── complete(messages,
        │                              │           tools=[spec1,spec2,spec3])
        │                              │                    │
        │                              │          Provider adapter translates
        │                              │          ToolSpec → provider-native format
        │                              │          (Anthropic tool_use, OpenAI functions, etc.)
        │                              │                    │
        │                              │          LLM returns tool_calls
        │                              │                    │
        │                              ├── executes tool callables
        │                              │   (calls t.__call__(**args))
        │                              │
        │                              ├── feeds ToolResult back as message
        │                              │
        │                      repeats until done
        │
        ├── receives AgentResult
```

### 6.3 Tool Wrapping and Filtering

Higher layers can transform tools before passing them down. This is how shonku or autoresearcher-shonku can add guardrails, rate limits, or logging without agnosai knowing:

```python
from agnosai import Tool, ToolSpec, ToolResult

class RateLimitedTool:
    """Wraps any Tool with a rate limit."""
    def __init__(self, inner: Tool, max_per_minute: int):
        self._inner = inner
        self._limiter = RateLimiter(max_per_minute)

    @property
    def spec(self) -> ToolSpec:
        return self._inner.spec  # Same spec — LLM sees the same tool

    async def __call__(self, **kwargs) -> ToolResult:
        await self._limiter.acquire()
        return await self._inner(**kwargs)
```

### 6.4 ToolRegistry

The `ToolRegistry` validates tools at registration time (unique names, valid schemas) and provides O(1) lookup by name during execution:

```python
class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools: dict[str, Tool] = {}
        for t in tools:
            if t.spec.name in self._tools:
                raise DuplicateToolError(t.spec.name)
            self._tools[t.spec.name] = t

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolNotFoundError(name)

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self._tools.values()]
```

---

## 7. LLM Provider Interface

### 7.1 Credential Management

```python
# agnosai/llm/creds.py

from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class LLMCredentials:
    """Typed credential container. The caller constructs this; agnosai
    never reads environment variables directly."""
    api_key: str
    base_url: str | None = None     # For custom endpoints / OpenRouter
    region: str | None = None       # For Bedrock
    project_id: str | None = None   # For Vertex AI
    organization: str | None = None # For OpenAI org scoping
```

**Key principle**: agnosai never reads `os.environ`. The caller (shonku, a CLI wrapper, etc.) is responsible for sourcing credentials and passing them in. This makes agnosai fully testable and avoids hidden global state.

### 7.2 Provider Factory

```python
# agnosai/llm/factory.py

from agnosai.llm.creds import LLMCredentials
from agnosai.llm.protocol import LLMProvider

def create_provider(
    provider: str,         # "anthropic", "openai", "groq", "gemini", "bedrock", "openai_compat"
    model: str,            # "claude-sonnet-4-20250514", "gpt-4o", etc.
    credentials: LLMCredentials,
) -> LLMProvider:
    """Factory that returns the appropriate provider adapter."""
    ...
```

### 7.3 Provider Adapter Internals

Each adapter translates between agnosai's normalized types and the provider's native SDK. Example outline for the Anthropic adapter:

```python
# agnosai/llm/providers/anthropic.py

class AnthropicProvider:
    def __init__(self, model: str, credentials: LLMCredentials) -> None:
        import anthropic  # Lazy import — only loaded if this provider is used
        self._client = anthropic.AsyncAnthropic(api_key=credentials.api_key)
        self._model = model

    async def complete(self, messages, tools=None, **kwargs) -> LLMResponse:
        # 1. Convert list[Message] → Anthropic message format
        # 2. Convert list[ToolSpec] → Anthropic tool definitions
        # 3. Call self._client.messages.create(...)
        # 4. Normalize response → LLMResponse
        ...

    async def stream(self, messages, tools=None, **kwargs):
        # Similar, but yields StreamChunk from the async stream
        ...
```

### 7.4 Tool Calling Translation

Each provider has a different wire format for tool definitions and tool call responses. The adapter layer handles this. The mapping:

| agnosai concept | Anthropic | OpenAI | Gemini |
|-----------------|-----------|--------|--------|
| `ToolSpec.name` | `tool.name` | `function.name` | `function_declaration.name` |
| `ToolSpec.parameters_schema` | `tool.input_schema` | `function.parameters` | `function_declaration.parameters` |
| `ToolCallRequest` | `tool_use` content block | `tool_calls[].function` | `function_call` |
| Tool result message | `tool_result` role | `tool` role with `tool_call_id` | `function_response` |

---

## 8. Node Execution Model

A **Node** is a packaged, self-contained agent configuration. It declares what it needs (tools, LLM access, config) and what it produces. This is the unit of distribution and composition.

### 8.1 NodeManifest

```python
# agnosai/node/manifest.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True, slots=True)
class NodeManifest:
    """Declarative description of a node — what it is and what it needs."""
    name: str
    version: str
    description: str
    instructions: str                         # The system prompt / goal
    required_tools: list[str] = field(default_factory=list)  # Tool names this node expects
    config_schema: dict[str, Any] | None = None              # JSON Schema for node-specific config
    output_schema: dict[str, Any] | None = None              # JSON Schema for the result
```

### 8.2 Node Protocol

```python
# agnosai/node/protocol.py

from typing import Protocol, runtime_checkable

@runtime_checkable
class Node(Protocol):
    @property
    def manifest(self) -> NodeManifest: ...

    async def run(
        self,
        llm: LLMProvider,
        tools: list[Tool],
        *,
        config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult: ...
```

### 8.3 NodeRunner

```python
# agnosai/node/runner.py

class NodeRunner:
    """Convenience class that wires up a Node with an LLM and tools, then runs it."""

    async def run(
        self,
        node: Node,
        llm: LLMProvider,
        tools: list[Tool],
        *,
        config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> AgentResult:
        # 1. Validate that all node.manifest.required_tools are present in tools
        # 2. Validate config against node.manifest.config_schema if present
        # 3. Call node.run(llm, tools, config=config, context=context)
        # 4. Validate output against node.manifest.output_schema if present
        # 5. Return AgentResult
        ...
```

---

## 9. Agent Lifecycle and Hooks

### 9.1 Hook Protocol

```python
# agnosai/hooks/protocol.py

from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class AgentHooks(Protocol):
    async def on_start(
        self, instructions: str, tools: list[ToolSpec]
    ) -> None: ...

    async def on_step(self, step: StepResult) -> None: ...

    async def on_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> None: ...

    async def on_tool_result(
        self, tool_name: str, result: ToolResult
    ) -> None: ...

    async def on_complete(self, result: AgentResult) -> None: ...

    async def on_error(self, error: Exception) -> None: ...
```

### 9.2 Default No-Op Hooks

```python
class NoOpHooks:
    """Default implementation — all hooks are no-ops."""
    async def on_start(self, instructions, tools): pass
    async def on_step(self, step): pass
    async def on_tool_call(self, tool_name, arguments): pass
    async def on_tool_result(self, tool_name, result): pass
    async def on_complete(self, result): pass
    async def on_error(self, error): pass
```

### 9.3 Composing Hooks

Multiple hook implementations can be combined:

```python
class CompositeHooks:
    def __init__(self, *hooks: AgentHooks) -> None:
        self._hooks = hooks

    async def on_start(self, instructions, tools):
        for h in self._hooks:
            await h.on_start(instructions, tools)

    # ... same pattern for all methods
```

This allows a caller to attach logging hooks, tracing hooks, and metrics hooks simultaneously without them knowing about each other.

---

## 10. Result Types

### 10.1 Structured Output

When the caller needs structured output (not just free-text), they encode the requirement in the instructions:

```
"Analyze the data and return your result as JSON matching this schema: {schema}"
```

agnosai itself does not enforce output schemas — that is the LLM's job given the instructions. However, the **Node** layer (Section 8) provides optional validation via `output_schema` in the manifest.

### 10.2 AgentResult Serialization

`AgentResult` is a plain dataclass. It can be serialized to JSON via Pydantic or `dataclasses.asdict()`. This is important for the PyPI publishability story — results must be serializable to cross process boundaries.

```python
import json
from dataclasses import asdict

result = await agent.run(instructions, tools)
print(json.dumps(asdict(result), default=str))
```

---

## 11. Agent Composition

An agent can call another agent as a tool. This is how complex multi-agent systems are built on top of agnosai.

### 11.1 Agent-as-Tool Wrapper

```python
# Example: wrapping an agent as a tool for another agent

from agnosai import Agent, tool, ToolResult, ToolSpec

def agent_as_tool(
    name: str,
    description: str,
    inner_agent: Agent,
    inner_instructions: str,
    inner_tools: list[Tool],
) -> Tool:
    """Wrap an Agent as a Tool that another Agent can call."""

    @tool(
        name=name,
        description=description,
    )
    async def _tool(task: str) -> ToolResult:
        result = await inner_agent.run(
            instructions=inner_instructions,
            tools=inner_tools,
            context={"task": task},
        )
        if result.status == AgentStatus.SUCCESS:
            return ToolResult.ok(result.output)
        else:
            return ToolResult.err(result.error or f"Agent failed: {result.status}")

    return _tool
```

### 11.2 Composition Pattern

```
Orchestrator Agent
├── tools: [search_tool, calculator_tool, researcher_agent_tool]
│                                           │
│                                    Researcher Agent (wrapped as tool)
│                                    ├── tools: [web_search, read_paper]
│                                    └── LLM: can be DIFFERENT provider/model
```

Each composed agent can use a different LLM provider and model. The orchestrator agent does not know or care — it just calls a tool and gets a result.

### 11.3 Credential Isolation

When composing agents, each inner agent receives its own LLM credentials. The outer agent never has access to the inner agent's credentials, and vice versa. This is enforced by construction — credentials are passed at agent instantiation time, not at tool-call time.

---

## 12. Credential Management

### 12.1 Flow

```
User / CLI / Environment
    │
    ├── reads API keys from env, config file, vault, etc.
    │
    ├── constructs LLMCredentials(api_key="sk-...")
    │
    ├── calls create_provider("anthropic", "claude-sonnet-4-20250514", creds)
    │
    ├── passes LLMProvider to Agent(llm=provider)
    │
    └── agnosai never touches env vars or files
```

### 12.2 Security Constraints

- `LLMCredentials` is frozen and slotted — cannot be mutated after creation.
- `LLMCredentials.__repr__` redacts the API key: `LLMCredentials(api_key="sk-...abc", ...)`.
- agnosai never logs credential values. The hooks protocol receives tool names and arguments, never LLM credentials.
- Credentials are never serialized into `AgentResult` or step logs.

---

## 13. PyPI Publishability

### 13.1 The Goal

Anyone can build an agent on agnosai, publish it to PyPI, and users can run it with their own LLM credentials:

```bash
pip install paper-reviewer-agent
```

```python
from paper_reviewer import PaperReviewerNode
from agnosai import create_provider, LLMCredentials, NodeRunner

llm = create_provider(
    "anthropic",
    "claude-sonnet-4-20250514",
    LLMCredentials(api_key="sk-..."),
)

node = PaperReviewerNode()
runner = NodeRunner()
result = await runner.run(node, llm, tools=[])
```

### 13.2 Package Convention

A publishable agent package should:

1. Depend on `agnosai` (the runtime).
2. Export a `Node` implementation (or multiple).
3. Declare required tools in its `NodeManifest`.
4. Provide a CLI entry point (optional) that reads creds from env and runs the node.

Example `pyproject.toml` for a published agent:

```toml
[project]
name = "paper-reviewer-agent"
version = "0.1.0"
dependencies = ["agnosai>=0.1.0"]

[project.scripts]
paper-reviewer = "paper_reviewer.cli:main"

[project.entry-points."agnosai.nodes"]
paper_reviewer = "paper_reviewer:PaperReviewerNode"
```

The `agnosai.nodes` entry point group allows discovery: frameworks or orchestrators can scan installed packages and find all available nodes.

### 13.3 Tool Dependency Declaration

A node declares the tools it requires by name. The caller is responsible for providing implementations. This keeps the node decoupled from specific tool implementations:

```python
class PaperReviewerNode:
    @property
    def manifest(self) -> NodeManifest:
        return NodeManifest(
            name="paper-reviewer",
            version="0.1.0",
            description="Reviews academic papers for methodology and clarity.",
            instructions="You are a paper reviewer...",
            required_tools=["read_pdf", "search_references"],
            output_schema={
                "type": "object",
                "properties": {
                    "score": {"type": "number"},
                    "review": {"type": "string"},
                },
                "required": ["score", "review"],
            },
        )
```

---

## 14. Example Usage

### 14.1 Minimal Agent

```python
import asyncio
from agnosai import Agent, AgentConfig, create_provider, LLMCredentials, tool, ToolResult

@tool(name="add", description="Add two numbers.")
async def add(a: float, b: float) -> ToolResult:
    return ToolResult.ok(a + b)

@tool(name="multiply", description="Multiply two numbers.")
async def multiply(a: float, b: float) -> ToolResult:
    return ToolResult.ok(a * b)

async def main():
    llm = create_provider(
        "anthropic",
        "claude-sonnet-4-20250514",
        LLMCredentials(api_key="sk-ant-..."),
    )

    agent = Agent(llm, config=AgentConfig(max_steps=10))

    result = await agent.run(
        instructions="You are a calculator. Use the tools to compute (3 + 5) * 12.",
        tools=[add, multiply],
    )

    print(result.status)   # AgentStatus.SUCCESS
    print(result.output)   # "96" or similar
    print(len(result.steps))  # 2 (one for add, one for multiply)

asyncio.run(main())
```

### 14.2 Streaming

```python
async def main():
    agent = Agent(llm)

    async for event in agent.run_stream(
        instructions="Research and summarize recent advances in CRISPR.",
        tools=[web_search, read_page],
    ):
        if isinstance(event, StepResult):
            print(f"Step {event.step_number}: called {[tc.tool_name for tc in event.tool_calls]}")
        elif isinstance(event, AgentResult):
            print(f"Done: {event.status}")
            print(event.output)
```

### 14.3 Agent Composition

```python
from agnosai import Agent, agent_as_tool, create_provider, LLMCredentials

# Inner agent: a researcher
researcher_llm = create_provider("groq", "llama-3.3-70b", LLMCredentials(api_key="gsk-..."))
researcher = Agent(researcher_llm)

researcher_tool = agent_as_tool(
    name="research",
    description="Delegate a research sub-task to a specialist researcher agent.",
    inner_agent=researcher,
    inner_instructions="You are a research specialist. Find and summarize information.",
    inner_tools=[web_search],
)

# Outer agent: an orchestrator
orchestrator_llm = create_provider("anthropic", "claude-sonnet-4-20250514", LLMCredentials(api_key="sk-..."))
orchestrator = Agent(orchestrator_llm)

result = await orchestrator.run(
    instructions="Write a report on quantum computing advances in 2025.",
    tools=[researcher_tool, write_file],
)
```

### 14.4 With Hooks

```python
import logging

class LoggingHooks:
    def __init__(self):
        self.logger = logging.getLogger("agnosai")

    async def on_start(self, instructions, tools):
        self.logger.info(f"Agent starting with {len(tools)} tools")

    async def on_step(self, step):
        self.logger.info(f"Step {step.step_number}: {len(step.tool_calls)} tool calls")

    async def on_tool_call(self, tool_name, arguments):
        self.logger.debug(f"Calling {tool_name}({arguments})")

    async def on_tool_result(self, tool_name, result):
        self.logger.debug(f"{tool_name} → {result.status}")

    async def on_complete(self, result):
        self.logger.info(f"Agent finished: {result.status}")

    async def on_error(self, error):
        self.logger.error(f"Agent error: {error}")

agent = Agent(llm, hooks=LoggingHooks())
```

### 14.5 Using a Published Node

```python
from agnosai import create_provider, LLMCredentials, NodeRunner
from paper_reviewer import PaperReviewerNode

llm = create_provider("openai", "gpt-4o", LLMCredentials(api_key="sk-..."))

# The node declares it needs "read_pdf" and "search_references" tools
# The caller provides implementations
from my_tools import read_pdf_tool, search_references_tool

runner = NodeRunner()
result = await runner.run(
    node=PaperReviewerNode(),
    llm=llm,
    tools=[read_pdf_tool, search_references_tool],
    context={"paper_url": "https://arxiv.org/abs/2301.00001"},
)

print(result.output)  # {"score": 7.5, "review": "The methodology is sound..."}
```

---

## 15. Open Questions

1. **Memory / state persistence across runs**: Should agnosai provide a persistence protocol (e.g., a key-value store tool that the caller injects), or should that be entirely the caller's responsibility? Current design says: caller's responsibility. agnosai is stateless between `run()` calls.

2. **Message history truncation**: Long-running agents will exceed context windows. Should agnosai provide a built-in summarization/truncation strategy, or should the caller handle this via a custom `LLMProvider` wrapper? Leaning toward: provide a `MessageStrategy` protocol that defaults to "keep all" but can be overridden.

3. **Structured output enforcement**: Should agnosai support a `response_format` parameter that gets passed through to the LLM provider for native JSON mode? This would make structured output more reliable than instruction-only approaches. Likely yes — add an optional `response_format` to `AgentConfig`.

4. **Error recovery**: When a tool call fails, the current design feeds the error back to the LLM as a message and lets it decide what to do. Should there be configurable retry policies at the tool level (e.g., retry transient errors N times before reporting to the LLM)?

5. **Cost budgets**: Should `AgentConfig` support a `max_cost_usd` field that terminates the loop when estimated cost exceeds the budget? This requires token-to-cost mapping per provider/model. Could be a hook responsibility instead.

6. **Multi-modal support**: Should `Message` support image/audio content blocks, or should that be deferred to a future version? The design should at least not preclude it — `Message.content` could become `str | list[ContentBlock]`.

7. **Observability format**: Should agnosai emit OpenTelemetry spans natively, or should that be a hook implementation concern? Leaning toward: provide an optional `OpenTelemetryHooks` implementation that users can opt into, keeping the core dependency-free.

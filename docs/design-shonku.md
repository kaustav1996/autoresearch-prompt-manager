# Shonku -- Design Document

> Status: Research and design only -- no code produced
> Date: 2026-03-25
> Layer: 2 of 4 in the agent stack (`prompt-manager -> autoresearcher-shonku -> shonku -> agnosai`)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Position in the Stack](#2-position-in-the-stack)
3. [Package Structure](#3-package-structure)
4. [Agent Base Class and Decorator API](#4-agent-base-class-and-decorator-api)
5. [Tool Passing Protocol](#5-tool-passing-protocol)
6. [Node Execution Lifecycle](#6-node-execution-lifecycle)
7. [Configuration System](#7-configuration-system)
8. [How Shonku Wraps Agnosai](#8-how-shonku-wraps-agnosai)
9. [PyPI Publishing Mechanism](#9-pypi-publishing-mechanism)
10. [Agent Discovery and Registry](#10-agent-discovery-and-registry)
11. [End-to-End Example: Building and Using an Agent](#11-end-to-end-example-building-and-using-an-agent)
12. [Error Handling and Observability](#12-error-handling-and-observability)
13. [Security Considerations](#13-security-considerations)
14. [Open Questions](#14-open-questions)

---

## 1. Overview

Shonku is a framework for **building, publishing, and running AI agents as reusable nodes**. It wraps agnosai (the low-level agent execution engine) and provides:

- A **declarative API** for defining agents (class + decorator)
- A **tool passing protocol** that chains tools from the consuming library through shonku down to agnosai
- A **packaging mechanism** that turns agents into installable PyPI packages
- A **node execution model** where anyone installs an agent, passes their own LLM credentials, and runs it

Shonku does not contain LLM credentials, model-specific logic, or application-specific tools. It is the plumbing layer that makes agents portable and composable.

### What Shonku Is Not

- **Not an LLM provider abstraction.** That is agnosai's job.
- **Not an application.** That is prompt-manager's or autoresearcher-shonku's job.
- **Not a workflow engine.** Shonku runs a single agent as a node. Orchestration of multiple agents is a concern of the layer above.

---

## 2. Position in the Stack

```
Layer 4 (Application):  prompt-manager
                         Owns domain tools (read_prompt, get_metrics, update_experiment)
                         Instantiates and runs agents from layer 3
                              |
                              | passes tools + context + llm_config
                              v
Layer 3 (Domain Agent):  autoresearcher-shonku
                         A shonku agent published to PyPI
                         Defines its own tools (analyze_metrics, propose_improvement)
                         Defines its system prompt and behavior
                              |
                              | merges own tools + received tools
                              v
Layer 2 (Framework):     shonku
                         Validates tool schemas, merges tool sets
                         Manages agent lifecycle (init -> run -> teardown)
                         Translates agent definition into agnosai calls
                              |
                              | passes merged tools + config
                              v
Layer 1 (Engine):        agnosai
                         Executes the agent loop (LLM call -> tool call -> repeat)
                         Handles LLM provider abstraction
                         Manages conversation state and tool execution
```

### Data Flow (detailed)

```
prompt-manager calls AutoResearcherAgent.run(
    llm_config={...},
    tools=[read_prompt, write_prompt, get_metrics, update_experiment],
    context={"prompt_id": "welcome-email", "metric_name": "quality"},
)

    shonku receives this call and:
    1. Instantiates AutoResearcherAgent
    2. Collects agent's own tools: [analyze_metrics, propose_improvement, format_report]
    3. Validates external tools against agent's declared requirements
    4. Merges: own_tools + external_tools -> unified tool set
    5. Builds agnosai configuration
    6. Calls agnosai.run(system_prompt, tools, llm_config, context)

        agnosai executes:
        1. Sends system prompt + tools to LLM
        2. LLM decides to call get_metrics (an external tool from prompt-manager)
        3. agnosai dispatches: shonku routes to external tool handler
        4. Result returned to LLM
        5. LLM decides to call analyze_metrics (agent's own tool)
        6. agnosai dispatches: shonku routes to agent method
        7. Loop continues until done
```

---

## 3. Package Structure

```
shonku/
├── pyproject.toml
├── src/
│   └── shonku/
│       ├── __init__.py              # Public API exports
│       ├── agent.py                 # Agent base class
│       ├── decorators.py            # @agent, @tool decorators
│       ├── tool.py                  # ToolSpec, ToolSet, ExternalTool
│       ├── runner.py                # Node execution engine
│       ├── config.py                # LLMConfig, AgentConfig, RunConfig
│       ├── schema.py                # Agent manifest schema (for publishing)
│       ├── validation.py            # Tool requirement validation
│       ├── bridge.py                # Agnosai bridge (translates shonku -> agnosai)
│       ├── result.py                # AgentResult, StepLog
│       ├── errors.py                # ShonkuError hierarchy
│       ├── registry.py              # Agent discovery (optional)
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── main.py              # CLI entrypoint
│       │   ├── build.py             # `shonku build` command
│       │   ├── run.py               # `shonku run` command
│       │   └── inspect_cmd.py       # `shonku inspect` command
│       └── packaging/
│           ├── __init__.py
│           ├── builder.py           # Generates pyproject.toml + package files
│           └── templates/           # Jinja templates for package scaffolding
│               ├── pyproject.toml.j2
│               └── __init__.py.j2
├── tests/
│   ├── test_agent.py
│   ├── test_tool_merging.py
│   ├── test_runner.py
│   ├── test_validation.py
│   └── test_packaging.py
└── examples/
    ├── hello_agent/                 # Minimal agent example
    └── tool_passing/                # Demonstrates external tool injection
```

### Dependencies

```toml
[project]
name = "shonku"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "agnosai>=0.1.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
cli = [
    "click>=8.0",
    "jinja2>=3.0",
    "rich>=13.0",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[project.scripts]
shonku = "shonku.cli.main:cli"
```

---

## 4. Agent Base Class and Decorator API

### 4.1 The `Agent` Base Class

```python
# shonku/agent.py

from __future__ import annotations
import inspect
from typing import Any, ClassVar
from pydantic import BaseModel, Field

from shonku.tool import ToolSpec, ToolSet
from shonku.config import LLMConfig, RunConfig
from shonku.result import AgentResult


class AgentManifest(BaseModel):
    """Metadata that describes an agent for publishing and discovery."""
    name: str
    description: str
    version: str
    author: str | None = None
    license: str | None = None
    tags: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    optional_tools: list[str] = Field(default_factory=list)
    expected_context: dict[str, str] = Field(default_factory=dict)
    # expected_context maps key name -> description
    # e.g. {"prompt_id": "The slug of the prompt to optimize"}


class Agent:
    """
    Base class for all shonku agents.

    Subclass this and use the @agent decorator to define an agent.
    The @tool decorator marks methods as agent-owned tools.
    """

    # Set by the @agent decorator
    __manifest__: ClassVar[AgentManifest]

    # Override in subclass
    system_prompt: ClassVar[str] = "You are a helpful assistant."

    def __init__(self, context: dict[str, Any] | None = None):
        self.context = context or {}
        self._own_tools: ToolSet | None = None

    def get_own_tools(self) -> ToolSet:
        """Collect all methods decorated with @tool on this agent."""
        if self._own_tools is not None:
            return self._own_tools

        tools = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if hasattr(method, "__tool_spec__"):
                spec: ToolSpec = method.__tool_spec__
                # Bind the method as the handler
                spec = spec.with_handler(method)
                tools.append(spec)

        self._own_tools = ToolSet(tools=tools, source=f"agent:{self.__manifest__.name}")
        return self._own_tools

    async def on_init(self) -> None:
        """Hook called after agent instantiation, before the loop starts.
        Override to perform setup (load data, validate context, etc.)."""
        pass

    async def on_step(self, step_number: int, tool_name: str, tool_result: Any) -> None:
        """Hook called after each tool invocation. Override for logging/monitoring."""
        pass

    async def on_complete(self, result: AgentResult) -> None:
        """Hook called when the agent loop finishes. Override for cleanup."""
        pass

    @classmethod
    async def run(
        cls,
        llm_config: dict[str, Any] | LLMConfig,
        tools: list[Any] | None = None,
        context: dict[str, Any] | None = None,
        config: dict[str, Any] | RunConfig | None = None,
    ) -> AgentResult:
        """
        Primary entry point. Called by the consuming library.

        Args:
            llm_config: LLM provider credentials and model selection.
            tools: External tools to inject (from the consuming library).
            context: Arbitrary data the agent needs (prompt_id, metric_name, etc.).
            config: Execution config (max_steps, timeout, verbosity).

        Returns:
            AgentResult with the final output, step log, and metadata.
        """
        from shonku.runner import NodeRunner

        runner = NodeRunner(
            agent_cls=cls,
            llm_config=LLMConfig.from_input(llm_config) if isinstance(llm_config, dict) else llm_config,
            external_tools=tools or [],
            context=context or {},
            config=RunConfig.from_input(config) if isinstance(config, dict) else (config or RunConfig()),
        )
        return await runner.execute()
```

### 4.2 The `@agent` Decorator

```python
# shonku/decorators.py

from __future__ import annotations
import functools
import inspect
from typing import Any, Callable, get_type_hints

from shonku.agent import Agent, AgentManifest
from shonku.tool import ToolSpec, ToolParameter


def agent(
    name: str,
    description: str,
    version: str,
    author: str | None = None,
    license: str | None = None,
    tags: list[str] | None = None,
    required_tools: list[str] | None = None,
    optional_tools: list[str] | None = None,
    expected_context: dict[str, str] | None = None,
):
    """
    Class decorator that registers an Agent subclass with its manifest.

    Usage:
        @agent(name="my-agent", description="Does X", version="0.1.0")
        class MyAgent(Agent):
            system_prompt = "..."
    """
    def decorator(cls):
        if not issubclass(cls, Agent):
            raise TypeError(f"@agent can only decorate Agent subclasses, got {cls.__name__}")

        cls.__manifest__ = AgentManifest(
            name=name,
            description=description,
            version=version,
            author=author,
            license=license,
            tags=tags or [],
            required_tools=required_tools or [],
            optional_tools=optional_tools or [],
            expected_context=expected_context or {},
        )
        return cls

    return decorator


def tool(
    func: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
):
    """
    Method decorator that marks an agent method as a tool.

    Extracts parameter schema from type hints and docstring.

    Usage:
        @tool
        async def analyze_metrics(self, prompt_id: str, window_hours: int = 24) -> str:
            '''Analyze recent metrics for a prompt.

            Args:
                prompt_id: The prompt slug to analyze.
                window_hours: How far back to look.
            '''
            ...

        @tool(name="custom_name", description="Override description")
        async def my_tool(self, x: int) -> str:
            ...
    """
    def decorator(fn):
        tool_name = name or fn.__name__
        tool_desc = description or _extract_docstring_summary(fn)
        parameters = _extract_parameters(fn)

        spec = ToolSpec(
            name=tool_name,
            description=tool_desc or f"Tool: {tool_name}",
            parameters=parameters,
            handler=None,  # Will be bound when get_own_tools() is called
            is_async=inspect.iscoroutinefunction(fn),
        )
        fn.__tool_spec__ = spec
        return fn

    if func is not None:
        # Used as @tool without arguments
        return decorator(func)
    return decorator


def _extract_docstring_summary(fn: Callable) -> str | None:
    """Extract the first line of the docstring as tool description."""
    doc = fn.__doc__
    if not doc:
        return None
    return doc.strip().split("\n")[0].strip()


def _extract_parameters(fn: Callable) -> list[ToolParameter]:
    """Extract tool parameters from type hints, skipping 'self'."""
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    params = []

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        if param_name == "return":
            continue

        param_type = hints.get(param_name, str)
        has_default = param.default is not inspect.Parameter.empty

        params.append(ToolParameter(
            name=param_name,
            type=_python_type_to_json_schema_type(param_type),
            required=not has_default,
            default=param.default if has_default else None,
            description=_extract_param_description(fn, param_name),
        ))

    return params


def _python_type_to_json_schema_type(t: type) -> str:
    """Map Python types to JSON Schema type strings."""
    mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }
    return mapping.get(t, "string")


def _extract_param_description(fn: Callable, param_name: str) -> str | None:
    """Parse Google-style docstring Args section to find param description."""
    doc = fn.__doc__
    if not doc:
        return None
    # Simplified parser: look for "param_name:" in Args section
    in_args = False
    for line in doc.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            if stripped.startswith(f"{param_name}:"):
                return stripped.split(":", 1)[1].strip()
            if stripped and not stripped.startswith(" ") and ":" not in stripped:
                in_args = False
    return None
```

---

## 5. Tool Passing Protocol

This is the most critical part of shonku's design. Tools flow downward through the stack, merging at each layer.

### 5.1 Core Types

```python
# shonku/tool.py

from __future__ import annotations
from typing import Any, Callable, Awaitable
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """Schema for a single tool parameter."""
    name: str
    type: str  # JSON Schema type: "string", "integer", "number", "boolean", "array", "object"
    required: bool = True
    default: Any | None = None
    description: str | None = None


class ToolSpec(BaseModel):
    """
    Canonical representation of a tool, regardless of where it came from.

    This is the lingua franca between layers. External tools (from prompt-manager),
    agent-owned tools (defined via @tool), and agnosai tools all get normalized
    to ToolSpec before merging.
    """
    name: str
    description: str
    parameters: list[ToolParameter] = Field(default_factory=list)
    handler: Any | None = None  # Callable -- the actual function to invoke
    is_async: bool = True
    source: str | None = None   # "agent:my-agent", "external:prompt-manager", etc.

    class Config:
        arbitrary_types_allowed = True

    def with_handler(self, handler: Callable) -> ToolSpec:
        """Return a copy with the handler bound."""
        return self.model_copy(update={"handler": handler})

    def to_agnosai_schema(self) -> dict[str, Any]:
        """Convert to the format agnosai expects for tool registration."""
        properties = {}
        required = []
        for p in self.parameters:
            properties[p.name] = {"type": p.type}
            if p.description:
                properties[p.name]["description"] = p.description
            if p.default is not None:
                properties[p.name]["default"] = p.default
            if p.required:
                required.append(p.name)

        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class ToolSet:
    """
    An ordered collection of ToolSpecs with conflict detection.
    """

    def __init__(self, tools: list[ToolSpec] | None = None, source: str | None = None):
        self._tools: dict[str, ToolSpec] = {}
        self.source = source
        if tools:
            for t in tools:
                self.add(t)

    def add(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            existing = self._tools[tool.name]
            raise ToolConflictError(
                f"Tool '{tool.name}' already registered "
                f"(existing source: {existing.source}, "
                f"conflicting source: {tool.source or self.source})"
            )
        tool_with_source = tool if tool.source else tool.model_copy(
            update={"source": self.source}
        )
        self._tools[tool.name] = tool_with_source

    def merge(self, other: ToolSet) -> ToolSet:
        """
        Merge two ToolSets. Raises ToolConflictError on name collision.

        This is the core operation of tool passing. When shonku merges
        agent-owned tools with external tools, it calls this method.
        """
        merged = ToolSet()
        for t in self._tools.values():
            merged.add(t)
        for t in other._tools.values():
            merged.add(t)
        return merged

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def to_agnosai_schemas(self) -> list[dict[str, Any]]:
        return [t.to_agnosai_schema() for t in self._tools.values()]

    def __len__(self) -> int:
        return len(self._tools)


class ToolConflictError(Exception):
    """Raised when two tools share the same name during merge."""
    pass
```

### 5.2 External Tool Adapter

External tools (from prompt-manager or any consuming library) can be passed in multiple formats. Shonku normalizes them all to `ToolSpec`.

```python
# shonku/tool.py (continued)

def normalize_external_tools(tools: list[Any]) -> ToolSet:
    """
    Accept tools in multiple formats and normalize to ToolSet.

    Supported input formats:
    1. ToolSpec instances (already normalized)
    2. Decorated callables (with __tool_spec__)
    3. Dictionaries with {name, description, parameters, handler}
    4. Plain async functions (name and params inferred from signature)
    """
    tool_set = ToolSet(source="external")

    for t in tools:
        if isinstance(t, ToolSpec):
            tool_set.add(t)
        elif hasattr(t, "__tool_spec__"):
            spec: ToolSpec = t.__tool_spec__
            spec = spec.with_handler(t)
            tool_set.add(spec)
        elif isinstance(t, dict):
            tool_set.add(_dict_to_tool_spec(t))
        elif callable(t):
            tool_set.add(_callable_to_tool_spec(t))
        else:
            raise TypeError(
                f"Cannot normalize tool of type {type(t).__name__}. "
                f"Expected ToolSpec, decorated callable, dict, or async function."
            )

    return tool_set


def _callable_to_tool_spec(fn: Callable) -> ToolSpec:
    """Infer ToolSpec from a plain function's signature and docstring."""
    import inspect
    from shonku.decorators import _extract_parameters, _extract_docstring_summary

    return ToolSpec(
        name=fn.__name__,
        description=_extract_docstring_summary(fn) or f"Tool: {fn.__name__}",
        parameters=_extract_parameters(fn),
        handler=fn,
        is_async=inspect.iscoroutinefunction(fn),
        source="external",
    )


def _dict_to_tool_spec(d: dict) -> ToolSpec:
    """Convert a dictionary tool definition to ToolSpec."""
    params = []
    if "parameters" in d:
        raw_params = d["parameters"]
        if isinstance(raw_params, dict) and "properties" in raw_params:
            # JSON Schema format
            required = raw_params.get("required", [])
            for pname, pschema in raw_params["properties"].items():
                params.append(ToolParameter(
                    name=pname,
                    type=pschema.get("type", "string"),
                    required=pname in required,
                    description=pschema.get("description"),
                    default=pschema.get("default"),
                ))
        elif isinstance(raw_params, list):
            params = [ToolParameter(**p) if isinstance(p, dict) else p for p in raw_params]

    return ToolSpec(
        name=d["name"],
        description=d.get("description", f"Tool: {d['name']}"),
        parameters=params,
        handler=d.get("handler"),
        is_async=d.get("is_async", True),
        source="external",
    )
```

### 5.3 The Merge Operation (Full Chain Example)

```python
# This is what happens inside the runner when a prompt-manager calls
# AutoResearcherAgent.run(tools=[read_prompt, get_metrics, ...])

# Step 1: Agent's own tools (defined via @tool on the class)
agent_instance = AutoResearcherAgent(context=context)
own_tools = agent_instance.get_own_tools()
# own_tools contains: analyze_metrics, propose_improvement, format_report
# source: "agent:autoresearcher"

# Step 2: External tools (passed by prompt-manager)
external_tools = normalize_external_tools(tools)
# external_tools contains: read_prompt, write_prompt, get_metrics, update_experiment
# source: "external"

# Step 3: Merge (conflict detection happens here)
merged_tools = own_tools.merge(external_tools)
# merged_tools contains ALL 7 tools
# If any name collision: ToolConflictError raised immediately

# Step 4: Pass to agnosai
agnosai_schemas = merged_tools.to_agnosai_schemas()
# agnosai gets a flat list of tool definitions, agnostic to their origin

# Step 5: When agnosai needs to invoke a tool:
tool_name = "get_metrics"  # LLM chose this
spec = merged_tools.get(tool_name)
result = await spec.handler(prompt_id="welcome-email", window_hours=24)
# The handler is the original function from prompt-manager
# Shonku just routes the call -- it does not wrap or transform arguments
```

### 5.4 Tool Requirement Validation

```python
# shonku/validation.py

from shonku.agent import Agent
from shonku.tool import ToolSet


class ToolValidationError(Exception):
    pass


def validate_tool_requirements(agent_cls: type[Agent], external_tools: ToolSet) -> None:
    """
    Check that all tools declared as 'required_tools' in the agent manifest
    are present in the external tool set.

    This runs BEFORE the agent loop starts. Fail fast if the caller
    forgot to pass a required tool.
    """
    manifest = agent_cls.__manifest__
    external_names = set(external_tools.names())

    missing = []
    for required_name in manifest.required_tools:
        if required_name not in external_names:
            missing.append(required_name)

    if missing:
        raise ToolValidationError(
            f"Agent '{manifest.name}' requires the following tools that were not provided: "
            f"{missing}. "
            f"The caller must pass these tools via the 'tools' parameter."
        )

    # Warn about optional tools (log, do not raise)
    for optional_name in manifest.optional_tools:
        if optional_name not in external_names:
            import warnings
            warnings.warn(
                f"Agent '{manifest.name}' declares optional tool '{optional_name}' "
                f"which was not provided. The agent will function without it "
                f"but some capabilities may be reduced.",
                UserWarning,
                stacklevel=2,
            )
```

---

## 6. Node Execution Lifecycle

### 6.1 The NodeRunner

```python
# shonku/runner.py

from __future__ import annotations
import time
from typing import Any

from shonku.agent import Agent
from shonku.config import LLMConfig, RunConfig
from shonku.tool import ToolSet, normalize_external_tools
from shonku.validation import validate_tool_requirements
from shonku.bridge import AgnosAIBridge
from shonku.result import AgentResult, StepLog


class NodeRunner:
    """
    Orchestrates the full lifecycle of running an agent as a node.

    Lifecycle:
        1. VALIDATE  -- check tool requirements, config
        2. INIT      -- instantiate agent, call on_init()
        3. MERGE     -- combine own tools + external tools
        4. BRIDGE    -- translate to agnosai configuration
        5. EXECUTE   -- run agnosai loop
        6. COMPLETE  -- call on_complete(), return result
    """

    def __init__(
        self,
        agent_cls: type[Agent],
        llm_config: LLMConfig,
        external_tools: list[Any],
        context: dict[str, Any],
        config: RunConfig,
    ):
        self.agent_cls = agent_cls
        self.llm_config = llm_config
        self.raw_external_tools = external_tools
        self.context = context
        self.config = config

    async def execute(self) -> AgentResult:
        start_time = time.monotonic()
        steps: list[StepLog] = []

        # Phase 1: VALIDATE
        external_tool_set = normalize_external_tools(self.raw_external_tools)
        validate_tool_requirements(self.agent_cls, external_tool_set)

        # Phase 2: INIT
        agent = self.agent_cls(context=self.context)
        await agent.on_init()

        # Phase 3: MERGE
        own_tools = agent.get_own_tools()
        merged_tools = own_tools.merge(external_tool_set)

        # Phase 4: BRIDGE
        bridge = AgnosAIBridge(
            system_prompt=agent.system_prompt,
            tools=merged_tools,
            llm_config=self.llm_config,
            run_config=self.config,
            context=self.context,
        )

        # Phase 5: EXECUTE
        def on_step(step_num: int, tool_name: str, tool_args: dict, tool_result: Any):
            log = StepLog(
                step=step_num,
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=str(tool_result)[:1000],  # Truncate for logging
                timestamp=time.monotonic() - start_time,
            )
            steps.append(log)

        bridge.on_step_callback = on_step

        try:
            final_output = await bridge.run()
        except Exception as e:
            result = AgentResult(
                success=False,
                output=None,
                error=str(e),
                steps=steps,
                elapsed_seconds=time.monotonic() - start_time,
                agent_name=self.agent_cls.__manifest__.name,
            )
            await agent.on_complete(result)
            raise

        # Phase 6: COMPLETE
        result = AgentResult(
            success=True,
            output=final_output,
            error=None,
            steps=steps,
            elapsed_seconds=time.monotonic() - start_time,
            agent_name=self.agent_cls.__manifest__.name,
        )
        await agent.on_complete(result)
        return result
```

### 6.2 Lifecycle Diagram

```
Caller calls Agent.run(llm_config, tools, context, config)
    |
    v
[1. VALIDATE]
    - normalize_external_tools() converts all tools to ToolSpec
    - validate_tool_requirements() checks required tools are present
    - validate LLMConfig (provider, model, api_key all present)
    |
    v
[2. INIT]
    - agent = AgentClass(context=context)
    - await agent.on_init()
    - Agent can load data, validate context, prepare state
    |
    v
[3. MERGE]
    - own_tools = agent.get_own_tools()     # from @tool methods
    - merged = own_tools.merge(external)    # ToolConflictError if collision
    |
    v
[4. BRIDGE]
    - Translate system_prompt + merged_tools + config -> agnosai format
    - Create agnosai session/runner
    |
    v
[5. EXECUTE]
    - agnosai runs the loop:
        LLM receives: system_prompt + all tools + context
        LLM chooses a tool -> agnosai calls it via merged_tools handler
        Result fed back to LLM
        Repeat until: LLM says done, or max_steps, or timeout
    - on_step callback fires after each tool call
    |
    v
[6. COMPLETE]
    - await agent.on_complete(result)
    - Return AgentResult to caller
```

---

## 7. Configuration System

```python
# shonku/config.py

from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """
    LLM credentials and model selection.

    Always provided at RUNTIME by the caller. Never baked into
    the agent package. This is a core design principle: agents
    are credential-free artifacts.
    """
    provider: str  # "anthropic", "openai", "groq", "bedrock", etc.
    api_key: str | None = None
    api_base: str | None = None  # For custom/self-hosted endpoints
    model: str  # "claude-sonnet-4-20250514", "gpt-4o", etc.
    temperature: float = 0.7
    max_tokens: int = 4096

    # Provider-specific extras (e.g., region for Bedrock)
    extras: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_input(cls, d: dict[str, Any]) -> LLMConfig:
        return cls(**d)


class RunConfig(BaseModel):
    """Execution parameters for a single agent run."""
    max_steps: int = 50
    timeout_seconds: float = 300.0  # 5 minutes default
    verbose: bool = False

    # Tool permissions (optional allowlist/blocklist)
    allowed_tools: list[str] | None = None   # None = all allowed
    blocked_tools: list[str] | None = None   # None = none blocked

    # Retry behavior
    max_retries_per_tool: int = 2
    retry_delay_seconds: float = 1.0

    @classmethod
    def from_input(cls, d: dict[str, Any] | None) -> RunConfig:
        if d is None:
            return cls()
        return cls(**d)


class AgentConfig(BaseModel):
    """
    Static agent configuration that can be overridden at runtime.

    Defined in the agent class, but the caller can override fields
    via RunConfig or context.
    """
    max_steps: int | None = None  # None = use RunConfig default
    model_preferences: list[str] = Field(default_factory=list)
    # e.g. ["claude-sonnet-4-20250514", "gpt-4o"] -- preferred models in order
    # If the caller provides a model not in this list, it still works
    # This is advisory, not enforced
```

---

## 8. How Shonku Wraps Agnosai

The bridge module translates shonku's high-level abstractions into agnosai's lower-level API.

```python
# shonku/bridge.py

from __future__ import annotations
from typing import Any, Callable

from shonku.config import LLMConfig, RunConfig
from shonku.tool import ToolSet, ToolSpec


class AgnosAIBridge:
    """
    Translates shonku's agent model into agnosai API calls.

    This is the ONLY module that imports agnosai directly.
    All other shonku modules are agnosai-agnostic, which means
    the engine could theoretically be swapped.
    """

    def __init__(
        self,
        system_prompt: str,
        tools: ToolSet,
        llm_config: LLMConfig,
        run_config: RunConfig,
        context: dict[str, Any],
    ):
        self.system_prompt = system_prompt
        self.tools = tools
        self.llm_config = llm_config
        self.run_config = run_config
        self.context = context
        self.on_step_callback: Callable | None = None

    def _build_system_prompt(self) -> str:
        """
        Augment the agent's system prompt with context.

        The context dict is injected as a structured block so the LLM
        knows what it is working with.
        """
        parts = [self.system_prompt]

        if self.context:
            context_block = "\n\n## Current Context\n"
            for key, value in self.context.items():
                context_block += f"- **{key}**: {value}\n"
            parts.append(context_block)

        return "\n".join(parts)

    def _build_tool_dispatcher(self) -> Callable:
        """
        Build a function that agnosai calls when the LLM invokes a tool.

        agnosai calls: dispatcher(tool_name, **kwargs) -> result
        We look up the handler in merged_tools and invoke it.
        """
        tools = self.tools
        step_counter = [0]
        callback = self.on_step_callback

        async def dispatch(tool_name: str, **kwargs: Any) -> Any:
            spec = tools.get(tool_name)
            if spec is None:
                return f"Error: Unknown tool '{tool_name}'"

            if spec.handler is None:
                return f"Error: Tool '{tool_name}' has no handler"

            # Invoke the handler
            if spec.is_async:
                result = await spec.handler(**kwargs)
            else:
                result = spec.handler(**kwargs)

            # Fire step callback
            step_counter[0] += 1
            if callback:
                callback(step_counter[0], tool_name, kwargs, result)

            return result

        return dispatch

    async def run(self) -> Any:
        """
        Execute the agent loop via agnosai.

        This method contains the actual agnosai import and API calls.
        The exact API shape depends on agnosai's design, but the
        contract is:

            agnosai.run(
                system_prompt: str,
                tools: list[dict],           # JSON Schema tool definitions
                tool_handler: Callable,      # dispatches tool calls
                llm_config: dict,            # provider + creds + model
                max_steps: int,
                timeout: float,
            ) -> str                         # final LLM output
        """
        import agnosai

        system_prompt = self._build_system_prompt()
        tool_schemas = self.tools.to_agnosai_schemas()
        dispatcher = self._build_tool_dispatcher()

        result = await agnosai.run(
            system_prompt=system_prompt,
            tools=tool_schemas,
            tool_handler=dispatcher,
            llm_config={
                "provider": self.llm_config.provider,
                "api_key": self.llm_config.api_key,
                "api_base": self.llm_config.api_base,
                "model": self.llm_config.model,
                "temperature": self.llm_config.temperature,
                "max_tokens": self.llm_config.max_tokens,
                **self.llm_config.extras,
            },
            max_steps=self.run_config.max_steps,
            timeout=self.run_config.timeout_seconds,
        )

        return result
```

### Key Design Decision: Single Import Boundary

Only `bridge.py` imports agnosai. This provides:

1. **Testability** -- All other modules can be tested without agnosai installed. Mock the bridge.
2. **Replaceability** -- If agnosai's API changes, only one file needs updating.
3. **Clarity** -- The translation layer is explicit and contained.

---

## 9. PyPI Publishing Mechanism

### 9.1 How `shonku build` Works

```
Developer has:
    my_agent/
    ├── agent.py          # Contains @agent class with @tool methods
    └── helpers.py        # Optional supporting code

Developer runs:
    shonku build ./my_agent

Shonku does:
    1. Imports the agent module, finds the @agent-decorated class
    2. Reads __manifest__ (name, version, description, required_tools, etc.)
    3. Generates a PyPI-publishable package:

    dist/
    └── autoresearcher_shonku-0.1.0/
        ├── pyproject.toml           # Generated from manifest
        ├── src/
        │   └── autoresearcher_shonku/
        │       ├── __init__.py      # Re-exports the Agent class
        │       ├── agent.py         # The original agent code (copied)
        │       ├── helpers.py       # Supporting code (copied)
        │       └── manifest.json    # Serialized AgentManifest
        └── README.md               # Auto-generated from description
```

### 9.2 Generated `pyproject.toml`

```toml
# Generated by shonku build
[project]
name = "autoresearcher-shonku"
version = "0.1.0"
description = "An agent that autonomously optimizes prompts using the autoresearch pattern."
requires-python = ">=3.11"
dependencies = [
    "shonku>=0.1.0",
]

[project.entry-points."shonku.agents"]
autoresearcher = "autoresearcher_shonku:AutoResearcherAgent"

# Entry point allows shonku to discover installed agents
```

### 9.3 The `shonku.agents` Entry Point

Published agents register themselves via Python entry points. This enables discovery:

```python
# shonku/registry.py

from importlib.metadata import entry_points
from shonku.agent import Agent


def discover_installed_agents() -> dict[str, type[Agent]]:
    """
    Find all shonku agents installed in the current environment.

    Uses the 'shonku.agents' entry point group.
    """
    agents = {}
    eps = entry_points(group="shonku.agents")
    for ep in eps:
        try:
            agent_cls = ep.load()
            if isinstance(agent_cls, type) and issubclass(agent_cls, Agent):
                agents[ep.name] = agent_cls
        except Exception:
            pass  # Skip broken packages
    return agents


def get_agent(name: str) -> type[Agent] | None:
    """Look up a specific installed agent by name."""
    agents = discover_installed_agents()
    return agents.get(name)
```

### 9.4 CLI Commands

```
shonku build <path>
    Reads agent source, generates PyPI package in ./dist/
    Validates: must have exactly one @agent class, all @tool methods must be async,
    manifest must be complete.

shonku inspect <path-or-package-name>
    Shows agent manifest: name, version, tools, required_tools, expected_context.
    Works on both source directories and installed packages.

shonku run <package-name> --llm-config config.json --context '{"key": "val"}'
    Quick way to run an installed agent from the command line.
    Mainly for testing. Production use is via the Python API.

shonku list
    Lists all shonku agents installed in the current environment.
```

---

## 10. Agent Discovery and Registry

### 10.1 Local Discovery (via entry points)

As described in section 9.3, agents installed via pip are automatically discoverable through Python's entry point mechanism. No central server required.

### 10.2 Manifest Introspection

```python
# Any installed agent exposes its manifest:

from autoresearcher_shonku import AutoResearcherAgent

manifest = AutoResearcherAgent.__manifest__
print(manifest.name)            # "autoresearcher"
print(manifest.required_tools)  # ["read_prompt", "write_prompt", "get_metrics", ...]
print(manifest.expected_context) # {"prompt_id": "The prompt slug to optimize", ...}
```

This allows the consuming library to programmatically check compatibility before attempting to run the agent.

### 10.3 Optional Remote Registry (Future)

A future extension could provide a central registry (similar to PyPI but for agent metadata):

```
POST /agents                     # Publish agent metadata
GET  /agents                     # Search agents by tags, capabilities
GET  /agents/{name}              # Get agent details
GET  /agents/{name}/manifest     # Get full manifest
```

This is out of scope for the initial version. The entry point mechanism plus PyPI itself is sufficient.

---

## 11. End-to-End Example: Building and Using an Agent

### 11.1 Building the Agent (developer writes this)

```python
# File: autoresearcher_shonku/agent.py

from shonku import Agent, agent, tool


@agent(
    name="autoresearcher",
    description="Autonomously optimizes prompts using the autoresearch pattern. "
                "Analyzes metrics, proposes improvements, and manages the keep/discard loop.",
    version="0.1.0",
    author="Autoresearch Team",
    tags=["optimization", "prompts", "autoresearch"],
    required_tools=["read_prompt", "write_prompt", "get_metrics"],
    optional_tools=["update_experiment", "get_experiment_results"],
    expected_context={
        "prompt_id": "The slug of the prompt to optimize",
        "metric_name": "Primary metric to optimize (e.g., 'quality')",
        "optimization_budget": "Max number of iterations (default: 10)",
    },
)
class AutoResearcherAgent(Agent):
    system_prompt = """You are an autonomous prompt optimization agent.

Your job is to improve a prompt by analyzing its performance metrics,
proposing changes, and testing those changes against the baseline.

You follow the autoresearch pattern:
1. OBSERVE: Read the current prompt and its metrics.
2. PROPOSE: Generate an improved version with clear reasoning.
3. DEPLOY: Write the new version as a candidate.
4. EVALUATE: Check metrics after deployment.
5. DECIDE: Keep if improved, discard if not.

You have access to tools for reading prompts, writing new versions,
and checking metrics. Use them methodically.

IMPORTANT: Never make changes without first reading the current state.
Always explain your reasoning before proposing a change."""

    async def on_init(self) -> None:
        """Validate that we have the context we need."""
        if "prompt_id" not in self.context:
            raise ValueError("AutoResearcherAgent requires 'prompt_id' in context")
        self.iteration = 0
        self.max_iterations = int(self.context.get("optimization_budget", 10))

    @tool
    async def analyze_metrics(self, metrics_json: str) -> str:
        """Analyze raw metrics and produce a structured summary.

        Args:
            metrics_json: JSON string of metric data from get_metrics.
        """
        import json
        metrics = json.loads(metrics_json)

        summary_parts = []
        for metric_name, values in metrics.items():
            if isinstance(values, list) and len(values) > 0:
                avg = sum(values) / len(values)
                summary_parts.append(
                    f"- {metric_name}: avg={avg:.3f}, n={len(values)}, "
                    f"min={min(values):.3f}, max={max(values):.3f}"
                )

        return "Metric Analysis:\n" + "\n".join(summary_parts) if summary_parts else "No metrics available."

    @tool
    async def format_improvement_proposal(
        self, current_prompt: str, proposed_prompt: str, reasoning: str
    ) -> str:
        """Format a prompt improvement proposal for logging.

        Args:
            current_prompt: The current prompt text.
            proposed_prompt: The proposed improved prompt text.
            reasoning: Why this change should improve the metric.
        """
        return (
            f"## Improvement Proposal (iteration {self.iteration})\n\n"
            f"### Reasoning\n{reasoning}\n\n"
            f"### Current ({len(current_prompt)} chars)\n```\n{current_prompt[:500]}\n```\n\n"
            f"### Proposed ({len(proposed_prompt)} chars)\n```\n{proposed_prompt[:500]}\n```"
        )

    @tool
    async def should_continue(self) -> str:
        """Check whether the optimization loop should continue.

        Returns 'continue' or 'stop' with reasoning.
        """
        self.iteration += 1
        if self.iteration >= self.max_iterations:
            return f"stop: reached maximum iterations ({self.max_iterations})"
        return f"continue: iteration {self.iteration}/{self.max_iterations}"
```

### 11.2 Publishing the Agent

```bash
# Developer builds the package
shonku build ./autoresearcher_shonku/

# Developer publishes to PyPI
cd dist/autoresearcher-shonku-0.1.0/
python -m build
twine upload dist/*
```

### 11.3 Using the Agent (consumer writes this)

```python
# File: prompt_manager/optimization/runner.py
# This lives in the prompt-manager codebase (layer 4)

from autoresearcher_shonku import AutoResearcherAgent
from prompt_manager.tools import read_prompt, write_prompt, get_metrics, update_experiment


async def run_optimization(prompt_id: str, metric_name: str, llm_api_key: str):
    """
    Run the autoresearcher agent to optimize a prompt.

    The prompt-manager passes its own tools to the agent.
    The agent uses those tools (plus its own) to do its work.
    """
    result = await AutoResearcherAgent.run(
        llm_config={
            "provider": "anthropic",
            "api_key": llm_api_key,
            "model": "claude-sonnet-4-20250514",
            "temperature": 0.7,
        },
        tools=[
            read_prompt,        # prompt-manager's tool
            write_prompt,       # prompt-manager's tool
            get_metrics,        # prompt-manager's tool
            update_experiment,  # prompt-manager's tool
        ],
        context={
            "prompt_id": prompt_id,
            "metric_name": metric_name,
            "optimization_budget": "5",
        },
        config={
            "max_steps": 30,
            "timeout_seconds": 600,
        },
    )

    if result.success:
        print(f"Optimization completed in {result.elapsed_seconds:.1f}s")
        print(f"Steps taken: {len(result.steps)}")
        print(f"Output: {result.output}")
    else:
        print(f"Optimization failed: {result.error}")

    return result
```

### 11.4 What the Prompt-Manager Tools Look Like

```python
# File: prompt_manager/tools.py
# These are plain async functions that shonku will auto-detect via signature

async def read_prompt(slug: str, version: int | None = None) -> str:
    """Read the current prompt text by slug.

    Args:
        slug: The prompt identifier.
        version: Optional specific version number. Returns latest if omitted.
    """
    # Actual implementation calls prompt_manager's service layer
    ...

async def write_prompt(slug: str, body: str, source: str = "optimization") -> str:
    """Write a new version of a prompt.

    Args:
        slug: The prompt identifier.
        body: The new prompt text.
        source: How this version was created.
    """
    ...

async def get_metrics(
    slug: str, metric_name: str, window_hours: int = 24
) -> str:
    """Get aggregated metrics for a prompt.

    Args:
        slug: The prompt identifier.
        metric_name: Which metric to retrieve (e.g., 'quality').
        window_hours: How far back to look.
    """
    ...

async def update_experiment(
    experiment_id: str, arm_label: str, new_weight: float
) -> str:
    """Update an experiment arm's weight.

    Args:
        experiment_id: The experiment UUID.
        arm_label: Which arm to update.
        new_weight: The new weight (0-100).
    """
    ...
```

---

## 12. Error Handling and Observability

### 12.1 Error Hierarchy

```python
# shonku/errors.py

class ShonkuError(Exception):
    """Base exception for all shonku errors."""
    pass

class ToolConflictError(ShonkuError):
    """Two tools share the same name during merge."""
    pass

class ToolValidationError(ShonkuError):
    """Required tools are missing."""
    pass

class AgentInitError(ShonkuError):
    """Agent's on_init() failed."""
    pass

class ToolExecutionError(ShonkuError):
    """A tool raised an exception during execution."""
    def __init__(self, tool_name: str, original_error: Exception):
        self.tool_name = tool_name
        self.original_error = original_error
        super().__init__(f"Tool '{tool_name}' failed: {original_error}")

class AgentTimeoutError(ShonkuError):
    """Agent exceeded its timeout."""
    pass

class BridgeError(ShonkuError):
    """Agnosai interaction failed."""
    pass
```

### 12.2 Result and Step Logging

```python
# shonku/result.py

from __future__ import annotations
from pydantic import BaseModel, Field


class StepLog(BaseModel):
    """Record of a single tool invocation during agent execution."""
    step: int
    tool_name: str
    tool_args: dict
    tool_result: str  # Truncated to prevent memory bloat
    timestamp: float  # Seconds since run start


class AgentResult(BaseModel):
    """The complete output of an agent run."""
    success: bool
    output: str | None            # Final LLM output (the answer/conclusion)
    error: str | None             # Error message if success=False
    steps: list[StepLog] = Field(default_factory=list)
    elapsed_seconds: float
    agent_name: str

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def tools_used(self) -> list[str]:
        """Unique tool names that were called, in order of first use."""
        seen = set()
        ordered = []
        for s in self.steps:
            if s.tool_name not in seen:
                seen.add(s.tool_name)
                ordered.append(s.tool_name)
        return ordered

    def summary(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        return (
            f"[{status}] Agent '{self.agent_name}' completed in {self.elapsed_seconds:.1f}s "
            f"({self.step_count} steps, tools used: {', '.join(self.tools_used)})"
        )
```

---

## 13. Security Considerations

### 13.1 Credential Isolation

- **LLM credentials are NEVER stored in the agent package.** They are passed at runtime via `llm_config`.
- Agent packages published to PyPI contain zero secrets.
- `shonku build` validates that no environment variables or string literals resembling API keys appear in agent source code (basic heuristic scan).

### 13.2 Tool Sandboxing (Future)

The current design trusts all tools. Future work could add:

- **Tool permission scoping**: agent declares which operations it needs (read, write, delete) and shonku enforces at the tool dispatch layer.
- **Execution sandboxing**: tools run in a restricted context that limits filesystem/network access.
- `RunConfig.allowed_tools` and `RunConfig.blocked_tools` provide basic allowlist/blocklist capability today.

### 13.3 Supply Chain

Published agents are Python packages -- the same supply chain risks as any PyPI package apply. Users should:

- Pin versions in requirements.
- Audit agent source code (it is plain Python, fully readable).
- Use `shonku inspect <package>` to review the manifest before running.

---

## 14. Open Questions

1. **Agnosai API shape.** The bridge module assumes a specific agnosai API (`agnosai.run(system_prompt, tools, tool_handler, llm_config, ...)`). The actual API depends on agnosai's design, which is being defined in a parallel document. The bridge is the natural seam to absorb API differences.

2. **Streaming.** Should shonku support streaming the agent's intermediate outputs back to the caller? This would require a callback/async-generator pattern rather than a simple `await run()`.

3. **Multi-agent composition.** The current design is one-agent-per-node. If a shonku agent needs to call another shonku agent, how should that work? Options:
   - Agent-as-tool: expose another agent as a tool in the tool set.
   - Runner composition: the parent agent's `on_step` calls another runner.
   - Leave this to the orchestration layer above (prompt-manager).

4. **State persistence across runs.** Currently each `run()` is stateless. For the autoresearch loop (which runs many iterations), should shonku provide a state store, or should the agent manage its own state via tools (read/write to the prompt-manager)?

5. **Tool schema versioning.** If prompt-manager changes a tool's signature between versions, how does an older published agent handle the mismatch? Options:
   - Semantic versioning on tool schemas.
   - Runtime parameter validation with helpful error messages.
   - Required tools declare minimum parameter sets, ignore extras.

6. **Namespacing for tool conflicts.** The current design raises `ToolConflictError` on name collision. An alternative is automatic namespacing (`agent:analyze_metrics` vs `external:analyze_metrics`), but this complicates the LLM's tool selection. The current approach (fail loudly, force unique names) is simpler.

# shonku

## What it is

shonku is a framework for building AI agents that other people can install and run. Not agents that live inside your application. Agents that are distributed as Python packages on PyPI, with their own versioning, their own dependencies, and their own release cycle.

The name comes from Professor Shonku, a fictional scientist-inventor created by Satyajit Ray. Like the character, the framework is about building things that work independently, that can be composed with other things, and that carry their own tools.

## The pattern

An agent in shonku has three things:

1. **Instructions** that tell the LLM what to do
2. **Built-in tools** that the agent defines itself (with `@tool`)
3. **Required tools** that the caller must provide at runtime

The third point is the important one. A weather agent does not hardcode a weather API. It declares `required_tools = ["get_weather"]` and the caller passes the actual implementation. A code review agent does not hardcode GitHub access. It declares `required_tools = ["get_diff", "post_comment"]` and the caller provides them.

This inversion means the same agent works in different environments. Your code review agent works with GitHub, GitLab, or Bitbucket. The agent does not care. It calls `get_diff` and gets a diff.

## How it works with agno

shonku wraps [agno](https://agno.com), the open-source agent framework. agno handles the hard parts: LLM provider abstraction, tool calling, message formatting, streaming, retries. shonku adds the packaging layer on top.

There is exactly one file in shonku that imports agno: `bridge.py`. Every other file is agno-free. This is deliberate. If you want to swap agno for a different runtime, you rewrite one file. Your agent definitions, your tool decorators, your test suite, your CLI, none of it changes.

The bridge translates:
- `LLMConfig(provider="groq", model="openai/gpt-oss-120b")` becomes `Groq(id="openai/gpt-oss-120b")`
- `ToolSpec(name="search", callable=my_func)` becomes a plain callable that agno can invoke
- `AgentResult(content=..., tool_calls_made=...)` gets assembled from agno's `RunOutput`

## Scaffolding

```bash
shonku init my-agent
```

This creates:

```
my-agent/
  src/my_agent/agent.py      <- ShonkuAgent subclass with @tool
  tests/test_agent.py        <- passing tests
  pyproject.toml              <- pip installable, PyPI ready
  README.md                   <- documentation
```

The tests pass out of the box. The package is publishable to PyPI without modification. You edit the agent, add your tools, run the tests, publish.

## Tool merging

When a shonku agent runs, two sets of tools merge:

1. The agent's own `@tool`-decorated methods
2. External tools passed by the caller via `tools=[...]`

The `ToolSet` class handles this merge. It checks for name collisions (raises `ToolConflictError` if two tools share a name) and validates that all `required_tools` are present (raises `MissingToolError` if not).

The merged set is flattened to a list of callables and handed to agno as `Agent(tools=[...])`. The LLM sees all tools, agent-defined and external, in a single flat namespace.

## The philosophy

An agent should be a pure function of its inputs. Give it instructions, give it tools, give it an LLM connection, and it produces output. No hidden state. No ambient configuration. No environment variables read behind your back.

This makes agents testable (mock the tools, mock the LLM, assert the output), composable (one agent's output becomes another agent's input), and distributable (publish to PyPI, anyone runs it with their own credentials).

The world does not need more agent platforms. It needs agent packages.

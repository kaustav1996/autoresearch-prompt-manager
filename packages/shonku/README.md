# shonku

Build, publish, and run AI agents as PyPI packages.

shonku is a declarative agent framework that wraps [agno](https://docs.agno.com). Define agents with built-in tools, accept external tools at runtime, and publish them as installable packages.

## Install

```bash
pip install shonku
```

## Scaffold a new agent project

```bash
shonku init my-agent
cd my-agent
pip install -e '.[dev]'
pytest
```

This creates a ready-to-go project:

```
my-agent/
  src/my_agent/agent.py    <- your agent (ShonkuAgent subclass)
  tests/test_agent.py      <- tests (passing out of the box)
  pyproject.toml            <- package config (pip installable)
  README.md
```

Edit `agent.py`, add tools, publish to PyPI. Anyone can then `pip install my-agent` and run your agent with their own LLM creds.

## Quick start

```python
from shonku import ShonkuAgent, tool, LLMConfig

class MyAgent(ShonkuAgent):
    name = "my-agent"
    instructions = "You are a helpful assistant."
    required_tools = ["search"]  # caller must provide this

    @tool(description="Calculate a math expression")
    def calculate(self, expression: str) -> str:
        return str(eval(expression))

# Run with external tools + LLM creds passed at runtime
agent = MyAgent()
result = await agent.run(
    input="What is 42 * 17?",
    llm_config=LLMConfig(provider="groq", model="llama-3.3-70b-versatile", api_key="..."),
    tools=[search_tool],  # external tool passed by caller
)
print(result.content)
```

## Key concepts

- **`ShonkuAgent`** -- subclass to define agents with `@tool`-decorated methods
- **Tool merging** -- agent's own tools + caller-provided tools merge at runtime
- **Required tools** -- declare what tools callers must provide
- **`LLMConfig`** -- LLM credentials passed at runtime, never stored in the agent
- **Only `bridge.py` imports agno** -- swap the runtime without touching agent code

## Publish agents as PyPI packages

```python
# myagent/agent.py
from shonku import ShonkuAgent, tool

class WeatherAgent(ShonkuAgent):
    name = "weather-agent"
    instructions = "Look up weather using the tools provided."
    required_tools = ["get_weather"]

    @tool(description="Format temperature")
    def format_temp(self, celsius: str) -> str:
        return f"{celsius}C / {float(celsius) * 9/5 + 32:.0f}F"
```

```bash
pip install myagent  # anyone can install it
```

```python
# consumer code
from myagent import WeatherAgent

result = await WeatherAgent().run(
    input="Weather in Tokyo?",
    llm_config=my_config,
    tools=[my_weather_api_tool],
)
```

## Supported LLM providers

| Provider | Config |
|----------|--------|
| Anthropic (Claude) | `provider="anthropic"` |
| OpenAI | `provider="openai"` |
| Groq | `provider="groq"` |
| Google Gemini | `provider="gemini"` |
| OpenRouter | `provider="openrouter"` |

## Part of autoresearch-prompt-manager

shonku is the agent framework layer in the [autoresearch-prompt-manager](https://github.com/kaustav1996/autoresearch-prompt-manager) stack:

```
autoresearch-prompt-manager  (prompt CRUD, experiments, metrics)
  -> autoresearcher-shonku   (optimization agents)
  -> shonku                  (this package -- agent framework)
  -> agno                    (runtime)
```

Install via the parent package: `pip install autoresearch-prompt-manager[shonku]`

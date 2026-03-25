# Shonku

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
    instructions = "You are a helpful assistant. Use tools when needed."
    required_tools = ["search"]  # caller must provide this

    @tool(description="Calculate a math expression")
    def calculate(self, expression: str) -> str:
        return str(eval(expression))

# Caller provides the external tool
def search(query: str) -> str:
    return f"Results for: {query}"

# Run with external tools + LLM creds passed at runtime
agent = MyAgent()
result = await agent.run(
    input="Search for Python frameworks, then calculate 42 * 17",
    llm_config=LLMConfig(provider="groq", model="openai/gpt-oss-120b", api_key="..."),
    tools=[ToolSpec(name="search", description="Search the web", callable=search)],
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

### 1. Scaffold

```bash
shonku init my-weather-agent
cd my-weather-agent
```

### 2. Build your agent

```python
# src/my_weather_agent/agent.py
from shonku import ShonkuAgent, tool

class WeatherAgent(ShonkuAgent):
    name = "weather-agent"
    instructions = "Look up weather using the tools provided."
    required_tools = ["get_weather"]

    @tool(description="Format temperature")
    def format_temp(self, celsius: str) -> str:
        return f"{celsius}C / {float(celsius) * 9/5 + 32:.0f}F"
```

### 3. Test locally

```bash
pip install -e ".[dev]"
pytest
```

### 4. Set up GitHub + PyPI

Create a GitHub repo and add your PyPI API token:

1. **Get a PyPI token**: https://pypi.org/manage/account/token/
2. **Add to GitHub**: Repo Settings > Secrets > Actions > `PYPI_API_TOKEN`
3. **Create environment**: Repo Settings > Environments > create `pypi`

`shonku init` creates `.github/workflows/release.yml` automatically. It runs tests on every push and publishes to PyPI on tags.

### 5. Push and publish

```bash
git init && git add -A && git commit -m "Initial commit"
git remote add origin git@github.com:you/my-weather-agent.git
git push -u origin main

# Publish to PyPI
git tag v0.1.0 && git push --tags
```

### 6. Anyone can now use it

```bash
pip install my-weather-agent
```

```python
from my_weather_agent import WeatherAgent
from shonku import LLMConfig
from shonku.types import ToolSpec

def get_weather(city: str) -> str:
    return f"22C, sunny in {city}"

result = await WeatherAgent().run(
    input="Weather in Tokyo?",
    llm_config=LLMConfig(provider="groq", model="openai/gpt-oss-120b", api_key="..."),
    tools=[ToolSpec(name="get_weather", description="Get weather", callable=get_weather)],
)
```

## Configuration

LLM credentials are passed at runtime via `LLMConfig`, never stored in the agent:

```python
from shonku import LLMConfig

llm_config = LLMConfig(
    provider="groq",              # or: anthropic, openai, gemini, openrouter
    model="openai/gpt-oss-120b",  # model ID for the provider
    api_key="your-api-key",       # API key
)
```

When used with autoresearch-prompt-manager, these map to environment variables:

| Env var | LLMConfig field | Example |
|---------|----------------|---------|
| `PM_LLM_PROVIDER` | `provider` | `groq` |
| `PM_LLM_MODEL` | `model` | `openai/gpt-oss-120b` |
| `PM_LLM_API_KEY` | `api_key` | `gsk_...` |

## Supported LLM providers

All providers supported by [agno](https://docs.agno.com) work out of the box:

| Provider | `provider=` | Example model |
|----------|-------------|---------------|
| Anthropic (Claude) | `anthropic` | `claude-sonnet-4-20250514` |
| OpenAI | `openai` | `gpt-4o` |
| Groq | `groq` | `openai/gpt-oss-120b` |
| Google Gemini | `gemini` | `gemini-2.0-flash` |
| OpenRouter | `openrouter` | `meta-llama/llama-3.1-70b` |

## Built on agno

shonku is a thin, opinionated layer on top of [agno](https://docs.agno.com) (the open-source agent framework by [Agno](https://agno.com)). agno provides the production-grade agent runtime, LLM provider integrations, and [AgentOS](https://docs.agno.com/agent-os/introduction) for deploying agents at scale. shonku adds:

- Declarative agent definitions with `@tool` decorators
- Runtime tool injection (caller passes tools, agent doesn't hardcode them)
- Required tool validation
- `shonku init` scaffolding for publishable PyPI packages
- A single-file bridge (`bridge.py`) so agent code never imports agno directly

If you need the full agent runtime directly, use agno: `pip install agno`

## Part of autoresearch-prompt-manager

shonku is the agent framework layer in the [autoresearch-prompt-manager](https://github.com/kaustav1996/autoresearch-prompt-manager) stack:

```
autoresearch-prompt-manager  (prompt CRUD, experiments, metrics)
  -> autoresearcher-shonku   (optimization agents)
  -> shonku                  (this package -- agent framework)
  -> agno                    (runtime -- https://agno.com)
```

Install via the parent package: `pip install autoresearch-prompt-manager[shonku]`

## Contributing

### For humans

1. Fork and clone [autoresearch-prompt-manager](https://github.com/kaustav1996/autoresearch-prompt-manager)
2. `cd packages/shonku && pip install -e '.[dev]'`
3. Make changes, run `pytest`, run `ruff check src/`
4. Submit a PR

### For agents

Build agents with shonku and publish them as PyPI packages:

1. `shonku init my-agent` — scaffold a project
2. Edit `src/my_agent/agent.py` — add `@tool` methods, set `required_tools`
3. `pip install -e '.[dev]' && pytest` — verify
4. Publish to PyPI — anyone can `pip install` and run your agent

Key rules for agent authors:
- Never hardcode LLM creds — always passed via `LLMConfig` at runtime
- Never hardcode data access — receive tools from the caller
- Declare `required_tools` so callers know what to provide
- Keep agent code agno-free — only `bridge.py` imports agno

## License

MIT

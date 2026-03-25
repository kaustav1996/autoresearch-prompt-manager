# Getting Started

## Prerequisites

- Python 3.10+
- Docker (for PostgreSQL)
- An LLM API key (Groq, Anthropic, OpenAI, or any supported provider)

## Install

```bash
pip install autoresearch-prompt-manager[all]
```

Or install only what you need:

```bash
pip install autoresearch-prompt-manager[client]    # just the SDK
pip install autoresearch-prompt-manager[api]        # API server
pip install shonku                                   # agent framework
```

## Configure

Create a `.env` file or export environment variables:

```bash
# Required
export PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager

# For optimization (pick your provider)
export PM_LLM_PROVIDER=groq
export PM_LLM_MODEL=openai/gpt-oss-120b
export PM_LLM_API_KEY=gsk_your_key_here
```

### Supported providers

| Provider | `PM_LLM_PROVIDER` | Example `PM_LLM_MODEL` |
|----------|-------------------|------------------------|
| Groq | `groq` | `openai/gpt-oss-120b`, `llama-3.3-70b-versatile` |
| Anthropic | `anthropic` | `claude-sonnet-4-20250514` |
| OpenAI | `openai` | `gpt-4o` |
| Google | `gemini` | `gemini-2.0-flash` |
| OpenRouter | `openrouter` | `meta-llama/llama-3.1-70b` |

## Start

```bash
# Start PostgreSQL
arpm-api up

# Start the API (runs migrations automatically)
arpm-api start
```

The API is now running on `http://localhost:8910`. Visit `http://localhost:8910/docs` for the interactive OpenAPI documentation.

## Try the example

```bash
# Seed marketing prompt templates
arpm-example seed

# Generate content with the LLM
arpm-example run "Write a welcome email for Alice joining TechCorp"

# Run the full autoresearch optimization loop
arpm-example loop

# Check status
arpm-example status
```

## Use the client SDK

```python
from prompt_manager.client import PromptManagerClient

async def main():
    client = PromptManagerClient(base_url="http://localhost:8910")

    # Resolve a prompt (experiment-aware)
    prompt = await client.resolve("welcome-email", session_id="user-123")
    print(prompt.body)
    print(prompt.version)

    # Report quality
    await client.report_metric(
        "welcome-email", str(prompt.version_id), "quality", 8.5
    )

    await client.close()
```

## Build your own agent

```bash
# Scaffold
shonku init my-agent
cd my-agent
pip install -e '.[dev]'
pytest

# Edit src/my_agent/agent.py
# Publish to PyPI when ready
```

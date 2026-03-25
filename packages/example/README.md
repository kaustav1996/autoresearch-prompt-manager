# Marketing Content Agent Example

A marketing content agent whose prompts get better over time. Built on the full [Autoresearch Prompt Manager](https://github.com/kaustav1996/autoresearch-prompt-manager) stack, powered by [agno](https://agno.com).

## Install

```bash
pip install autoresearch-prompt-manager[example]
```

## Configure

```bash
export PM_LLM_PROVIDER=groq              # or: anthropic, openai, gemini, openrouter
export PM_LLM_MODEL=openai/gpt-oss-120b  # or: claude-sonnet-4-20250514, gpt-4o, etc.
export PM_LLM_API_KEY=your-api-key       # required
export PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager
```

| Env Var | Default | Description |
|---------|---------|-------------|
| `PM_LLM_PROVIDER` | `groq` | LLM provider |
| `PM_LLM_MODEL` | `openai/gpt-oss-120b` | Model ID |
| `PM_LLM_API_KEY` / `GROQ_API_KEY` | -- | API key (required) |
| `PM_API_URL` | `http://localhost:8910` | Prompt Manager API URL |
| `PM_DATABASE_URL` | `postgresql://...` | PostgreSQL connection |

## Quick start

```bash
# Start the API
arpm-api up       # Start PostgreSQL
arpm-api start    # Run migrations + start API on :8910

# Seed prompt templates
arpm-example seed

# Generate content
arpm-example run "Write a welcome email for Alice joining TechCorp"

# Run the full autoresearch optimization loop
arpm-example loop

# Check status
arpm-example status
```

## Commands

| Command | What it does |
|---------|-------------|
| `arpm-example seed` | Seed 4 marketing prompt templates into the API |
| `arpm-example run "task"` | Generate content using an LLM with the best prompt version |
| `arpm-example loop` | Run the full autoresearch optimization loop (multi-version experiment + autoresearcher) |
| `arpm-example status` | Check API connection, prompt count, LLM config |

## What it demonstrates

1. **Prompt resolution** -- the agent calls `arpm-example run` and gets the best template via experiment-aware routing
2. **A/B experiment routing** -- MurmurHash3 deterministic routing, same user always gets the same variant
3. **Quality metrics** -- the agent self-evaluates and reports scores back to the API
4. **Autonomous optimization** -- autoresearcher-shonku analyses metrics, proposes improved versions, deploys experiments with adjusted weights

## The full loop (`arpm-example loop`)

This runs 6 steps:

**Step 1.** Create a prompt with 2 versions (formal vs casual)

**Step 2.** Create an A/B experiment with 50/50 routing

**Step 3.** Run the marketing agent 4 times. Each session gets routed to a different version. The agent generates content, rates it, reports the metric.

**Step 4.** Check metrics per version:
```
v1 (formal): mean=6.00
v2 (casual): mean=6.50
```

**Step 5.** Autoresearcher runs. It reads the metrics, reads the prompts, proposes v3 (combining the best of both), validates safety, and deploys a new experiment:

| Version | Style | Weight |
|---------|-------|--------|
| v1 | Formal | 30% |
| v2 | Casual | 30% |
| v3 | Optimized | 40% |

**Step 6.** Verify all 3 versions are now receiving traffic.

## How tools flow

```
arpm-example (this package)
  │
  │ defines tools that wrap the prompt-manager API:
  │   resolve_prompt  → GET /resolve/{slug}
  │   report_metric   → POST /metrics
  │
  └─→ MarketingContentAgent (shonku agent)
        │
        │ agent's built-in tool:
        │   rate_content  → heuristic quality scorer
        │
        └─→ agno → LLM (Groq gpt-oss-120b)
```

For the optimization loop, the autoresearcher gets 6 additional tools (get_prompt, get_metrics, create_version, create_experiment, conclude_experiment, get_sample_interactions) that also wrap the API.

The autoresearcher has **no built-in knowledge** of your prompts. It learns everything through tool calls.

## Seed prompts

| Slug | Type | Tags |
|------|------|------|
| `welcome-email` | Email | email, onboarding |
| `social-post` | Social | social, engagement |
| `ad-copy` | Ad | ad, conversion |
| `product-description` | Product | product, ecommerce |

## Contributing

```bash
# Clone the repo
git clone git@github.com:kaustav1996/autoresearch-prompt-manager.git
cd autoresearch-prompt-manager/packages/example
pip install -e ".[dev]"
pytest
```

## License

MIT

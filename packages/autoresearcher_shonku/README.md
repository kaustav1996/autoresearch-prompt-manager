# Autoresearcher Shonku

Autonomous prompt optimization agents built on [shonku](https://github.com/kaustav1996/autoresearch-prompt-manager/tree/main/packages/shonku).

Implements Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) pattern for prompts: propose an improvement, shadow-test it, measure, keep or discard, repeat.

## Install

```bash
pip install autoresearcher-shonku
```

## How it works

```
1. ANALYZE   -- read prompt metrics and sample interactions
2. PROPOSE   -- LLM generates an improved prompt version
3. VALIDATE  -- safety rails check (similarity, length, template vars)
4. DEPLOY    -- create experiment at low traffic weight
5. EVALUATE  -- collect metrics on the new version
6. DECIDE    -- keep if improved, discard if not
7. REPEAT
```

## Agents

| Agent | Role |
|-------|------|
| `PromptAnalyzerAgent` | Analyzes metrics to identify weaknesses |
| `PromptOptimizerAgent` | Proposes improved prompt versions |
| `ExperimentManagerAgent` | Manages A/B experiment lifecycle |
| `AutoResearcherAgent` | Orchestrates the full loop |

## Usage

The autoresearcher does NOT own your data. You pass tools that wrap your storage. This works with any backend, not just autoresearch-prompt-manager.

### Example: optimize email subject lines stored in a CSV

```python
import csv
from autoresearcher_shonku import AutoResearcherAgent
from shonku import LLMConfig
from shonku.types import ToolSpec

# Your data lives wherever you want. Wrap access as tools.
subjects = {"welcome": {"body": "Welcome to our service", "version": 1}}
metrics = [{"quality": 5.2}, {"quality": 4.8}, {"quality": 6.0}]

def get_prompt(slug: str) -> str:
    import json
    s = subjects.get(slug, {})
    return json.dumps({"slug": slug, **s})

def get_metrics(prompt_id: str, version_id: str, metric_name: str = "quality") -> str:
    import json
    vals = [m.get(metric_name, 0) for m in metrics]
    return json.dumps({"count": len(vals), "mean": sum(vals)/len(vals)})

def get_sample_interactions(prompt_id: str, limit: str = "3") -> str:
    return '[{"feedback": "too generic"}, {"feedback": "boring"}]'

def create_version(slug: str, content: str) -> str:
    import json
    subjects[slug] = {"body": content, "version": subjects.get(slug, {}).get("version", 0) + 1}
    return json.dumps({"version": subjects[slug]["version"]})

def create_experiment(prompt_id: str, baseline_version_id: str, new_version_id: str, weight: str = "10") -> str:
    return '{"experiment_id": "exp-1", "status": "running"}'

def conclude_experiment(experiment_id: str) -> str:
    return '{"status": "concluded"}'

tools = [
    ToolSpec(name="get_prompt", description="Get prompt by slug", callable=get_prompt),
    ToolSpec(name="get_metrics", description="Get metrics", callable=get_metrics),
    ToolSpec(name="get_sample_interactions", description="Get samples", callable=get_sample_interactions),
    ToolSpec(name="create_version", description="Create new version", callable=create_version),
    ToolSpec(name="create_experiment", description="Create experiment", callable=create_experiment),
    ToolSpec(name="conclude_experiment", description="Conclude experiment", callable=conclude_experiment),
]

agent = AutoResearcherAgent()
result = await agent.run(
    input="Optimize 'welcome' subject line. Quality is 5.3/10, target 7.0+.",
    llm_config=LLMConfig(provider="groq", model="openai/gpt-oss-120b", api_key="..."),
    tools=tools,
)
print(subjects["welcome"]["body"])  # improved version
```

### With autoresearch-prompt-manager

When used with the full prompt-manager stack, the tools wrap the API instead of local data:

```bash
arpm-api up && arpm-api start   # start the API
arpm-example loop                # run the optimization loop
```
```

## Safety rails

The `AutoResearcherAgent` includes a built-in `check_safety_rails` tool that validates:

- Similarity to original (>= 30%)
- Non-empty content (> 10 chars)
- Within iteration budget
- Reasonable length (30%-300% of original)

## Configuration

### LLM settings

The autoresearcher receives LLM config at runtime. When used with autoresearch-prompt-manager, set:

```bash
export PM_LLM_PROVIDER=groq              # or: anthropic, openai, gemini, openrouter
export PM_LLM_MODEL=openai/gpt-oss-120b  # model ID
export PM_LLM_API_KEY=your-api-key       # provider API key
```

### Optimization settings

```python
from autoresearcher_shonku import AutoResearcherConfig

config = AutoResearcherConfig(
    max_iterations=10,
    improvement_threshold=0.01,
    max_edit_distance=0.5,
    canary_weight=5.0,
    rollback_on_regression=True,
)
```

## Acknowledgements

- Optimization loop inspired by Karpathy's [autoresearch](https://github.com/karpathy/autoresearch)
- Agent execution powered by [agno](https://agno.com) and [AgentOS](https://docs.agno.com/agent-os/introduction)

## Part of autoresearch-prompt-manager

```
autoresearch-prompt-manager  (prompt CRUD, experiments, metrics)
  -> autoresearcher-shonku   (this package -- optimization agents)
  -> shonku                  (agent framework)
  -> agno                    (runtime -- https://agno.com)
```

Install via the parent package: `pip install autoresearch-prompt-manager[autoresearcher]`

## Contributing

1. Fork [autoresearch-prompt-manager](https://github.com/kaustav1996/autoresearch-prompt-manager)
2. `cd packages/autoresearcher_shonku && pip install -e '.[dev]'`
3. Make changes, `pytest`, `ruff check src/`
4. Submit a PR

To add new optimization strategies, create a new agent in `agents/` following the `ShonkuAgent` pattern.

## License

MIT

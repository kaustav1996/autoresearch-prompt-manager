# autoresearcher-shonku

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

The autoresearcher does NOT own your data. You pass tools that wrap your storage:

```python
from autoresearcher_shonku import AutoResearcherAgent
from shonku import LLMConfig
from shonku.types import ToolSpec

# Your tools (wrap your API/DB)
tools = [
    ToolSpec(name="get_prompt", description="...", callable=my_get_prompt),
    ToolSpec(name="get_metrics", description="...", callable=my_get_metrics),
    ToolSpec(name="create_version", description="...", callable=my_create_version),
    ToolSpec(name="create_experiment", description="...", callable=my_create_experiment),
    ToolSpec(name="conclude_experiment", description="...", callable=my_conclude),
    ToolSpec(name="get_sample_interactions", description="...", callable=my_samples),
]

agent = AutoResearcherAgent()
result = await agent.run(
    input="Optimize prompt 'welcome-email'. Quality is 5.2/10, target 7.0+.",
    llm_config=LLMConfig(provider="groq", model="openai/gpt-oss-120b", api_key="..."),
    tools=tools,
)
```

## Safety rails

The `AutoResearcherAgent` includes a built-in `check_safety_rails` tool that validates:

- Similarity to original (>= 30%)
- Non-empty content (> 10 chars)
- Within iteration budget
- Reasonable length (30%-300% of original)

## Configuration

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

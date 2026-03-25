# Marketing Content Agent Example

A demo showing how the full prompt-manager stack works together to build a marketing content agent whose prompts **get better over time**.

## Architecture

```
+--------------------------+
|   marketing-agent        |  <-- this example
|   (ShonkuAgent)          |
+----------+---------------+
           |
           | resolve_prompt / report_metric
           v
+----------+---------------+
|   prompt-manager         |  API + client SDK
|   (FastAPI + PostgreSQL) |
+----------+---------------+
           |
           | analyse metrics, propose improvements
           v
+----------+---------------+
|   autoresearcher-shonku  |  autonomous prompt optimiser
|   (ShonkuAgent)          |
+----------+---------------+
           |
           | agent primitives
           v
+----------+---------------+
|   shonku                 |  declarative agent framework
|   (wraps agno)           |
+--------------------------+
```

## What it demonstrates

1. **Prompt resolution** -- the agent asks prompt-manager for the best template for a given content type.
2. **Experiment-aware routing** -- if an A/B experiment is running, prompt-manager routes to the right variant based on `session_id` using MurmurHash3 deterministic hashing.
3. **Quality metrics** -- after generating content the agent self-evaluates quality and reports the score back to prompt-manager.
4. **Autonomous optimisation** -- autoresearcher-shonku analyses collected metrics, proposes improved prompt versions, validates safety, deploys a new experiment, and adjusts routing weights.

## Setup

### 1. Start PostgreSQL

```bash
# From the repo root
docker compose up -d
```

### 2. Start the prompt-manager API

```bash
PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager \
  python -m prompt_manager.api.main
```

The API starts on `http://localhost:8910` by default.

### 3. Install this example

```bash
cd packages/example
pip install -e ".[dev]"
```

## Running

### Basic demo (generate content)

```bash
python -m marketing_agent.main
```

Seeds four prompt templates and generates content for each.

### Full loop demo (experiment + optimisation)

```bash
python -m marketing_agent.demo_full_loop
```

This runs the complete autoresearch loop end-to-end. See below for details.

## Full Loop Demo: What Happens

The `demo_full_loop.py` script runs 6 steps that demonstrate the entire system:

### Step 1: Create prompt with 2 versions

Two versions of a welcome email are created:

| Version | Style | Content |
|---------|-------|---------|
| v1 | Formal | "Dear {name}, We are pleased to inform you..." |
| v2 | Casual | "Hey {name}! We're SO excited you're here..." |

### Step 2: Create A/B experiment (50/50 routing)

An experiment is created with two arms:
- **formal** arm (v1): 50% of traffic
- **casual** arm (v2): 50% of traffic

Routing is deterministic per `session_id` using MurmurHash3 -- the same user always sees the same version.

### Step 3: Marketing agent runs 4 times

The marketing agent runs with different session IDs. Each run:

1. Calls `resolve_prompt("welcome-demo", session_id=...)` -- prompt-manager routes to v1 or v2 based on the experiment
2. The LLM (gpt-oss-120b on Groq) generates personalised content from the template
3. Calls `rate_content(content, "email")` -- agent's built-in quality scorer
4. Calls `report_metric(slug, version_id, "quality_score", score)` -- metric saved to PostgreSQL

Example output:
```
demo-user-0 → v2 (casual), quality: 6.5
demo-user-1 → v2 (casual), quality: 6.5
demo-user-2 → v1 (formal), quality: 6.0
demo-user-3 → v1 (formal), quality: 6.0
```

### Step 4: Check metrics per version

Metrics are aggregated from PostgreSQL:
```
v1 (formal): count=2, mean=6.00
v2 (casual): count=2, mean=6.50
```

Both versions score mediocre. The casual version is slightly better.

### Step 5: Autoresearcher proposes v3 and adjusts routing

This is where the autoresearch loop runs. The `AutoResearcherAgent` (from autoresearcher-shonku) is given tools that wrap the prompt-manager API:

```python
tools = [get_prompt, get_metrics, get_sample_interactions,
         create_version, create_experiment, conclude_experiment]
```

The autoresearcher has **no built-in knowledge** of your prompts. It learns everything through tool calls:

1. `get_prompt("welcome-demo")` -- reads current prompt text
2. `get_metrics(prompt_id, ...)` -- sees v1=6.0, v2=6.5
3. `get_sample_interactions(prompt_id)` -- sees both version texts
4. **LLM proposes v3** -- combines formal professionalism with casual warmth
5. `create_version("welcome-demo", "Hello {name}, Welcome to {company}! We're delighted...")` -- saves to DB
6. `check_safety_rails(original, proposed, ...)` -- validates (similarity=0.376, all checks pass)
7. `conclude_experiment(old_exp_id)` -- stops the old 50/50 experiment
8. `create_experiment(...)` -- creates new experiment with **adjusted weights**:

| Version | Style | Weight |
|---------|-------|--------|
| v1 | Formal | 30% |
| v2 | Casual | 30% |
| v3 | **Optimised (new)** | **40%** |

The optimised version gets the highest weight because it was designed to improve on both.

### Step 6: Verify new routing

Traffic now routes across all 3 versions:
```
verify-user-0 → v2
verify-user-1 → v3  ← new optimised version
verify-user-2 → v1
verify-user-3 → v1
verify-user-4 → v2
verify-user-5 → v2
```

All 3 versions receiving traffic. The system is now collecting metrics on v3 alongside v1 and v2.

## How tools flow through the stack

```
demo_full_loop.py (example layer)
  │
  │ defines 6 tool functions (closures over httpx client)
  │   get_prompt()           → GET /prompts/{slug}
  │   get_metrics()          → GET /metrics/aggregate
  │   get_sample_interactions() → GET /prompts/{slug}/versions
  │   create_version()       → POST /prompts/{slug}/versions
  │   create_experiment()    → POST /experiments
  │   conclude_experiment()  → PATCH /experiments/{id}/status
  │
  └─→ AutoResearcherAgent.run(tools=[...], input="Optimize...")
        │
        │ autoresearcher-shonku adds its own tool:
        │   check_safety_rails() (validates similarity, length, budget)
        │
        │ shonku merges: 6 external + 1 agent-owned = 7 tools
        │ shonku validates: all required_tools present
        │
        └─→ agno.Agent(tools=[7 callables], model=Groq("gpt-oss-120b"))
              │
              └─→ LLM decides which tools to call based on reasoning
```

The autoresearcher is **completely reusable** -- swap the tools and it optimises different things. The domain knowledge lives in the tools (which wrap the prompt-manager API), not in the agent.

## Seed prompts

The file `prompts/seed_prompts.json` contains four starter templates:

| Slug                 | Type    | Tags                |
|----------------------|---------|---------------------|
| `welcome-email`      | Email   | email, onboarding   |
| `social-post`        | Social  | social, engagement  |
| `ad-copy`            | Ad      | ad, conversion      |
| `product-description`| Product | product, ecommerce  |

Templates use `{{variable}}` placeholders that the agent fills in at generation time.

## Running tests

```bash
pytest
```

## Configuration

```bash
export PM_DATABASE_URL=postgresql://prompt_manager:prompt_manager@localhost:15432/prompt_manager
export PM_LLM_PROVIDER=groq              # or: anthropic, openai, gemini, openrouter
export PM_LLM_MODEL=openai/gpt-oss-120b  # or: claude-sonnet-4-20250514, gpt-4o, etc.
export PM_LLM_API_KEY=your-api-key       # required for optimization + content generation
```

| Env Var | Default | Description |
|---------|---------|-------------|
| `PM_DATABASE_URL` | `postgresql://localhost:5432/prompt_manager` | PostgreSQL connection |
| `PM_API_URL` | `http://localhost:8910` | Prompt Manager API URL |
| `PM_LLM_PROVIDER` | `groq` | LLM provider |
| `PM_LLM_MODEL` | `openai/gpt-oss-120b` | Model ID |
| `PM_LLM_API_KEY` / `GROQ_API_KEY` | -- | API key (required) |

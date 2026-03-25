# Autoresearch Pattern — Applied to Prompt Optimization

## Inspiration

This prompt manager's optimization loop is modeled after [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — a system where an AI agent autonomously experiments with ML training code, keeping what improves the metric and discarding what doesn't.

We apply the same pattern to **prompt engineering**: instead of a human tweaking prompts, an LLM autonomously iterates on prompts, measures outcomes, and keeps what works.

---

## The Analogy

| Autoresearch (ML Training) | Prompt Manager (Prompt Optimization) |
|---|---|
| `train.py` — the file the agent modifies | Prompt text — what the LLM optimizer modifies |
| `prepare.py` — fixed evaluation harness | `[metric]` package — fixed metric collection |
| `val_bpb` — the metric (lower is better) | Custom metric per prompt (configurable) |
| 5-minute training run | Experiment window (configurable duration or sample count) |
| `results.tsv` — experiment log | `optimization_runs` table |
| Git branch — keep/discard via commit/reset | Prompt versions — keep (new version) / discard (revert) |
| `program.md` — human controls the research org | Experiment config — human defines objectives, constraints |
| Agent runs autonomously overnight | Optimization loop runs autonomously until stopped |

---

## The Optimization Loop

```
LOOP FOREVER (until budget exhausted or manually stopped):

1. OBSERVE: Read current prompt state
   - Current best prompt version (the "baseline")
   - Recent metric signals (quality, latency, success rate, etc.)
   - Aggregated performance (mean, p50, p95, count per version)

2. PROPOSE: LLM generates an improvement
   - Feed the optimizer LLM:
     - Current prompt text
     - Metric summary
     - Sample interactions (good and bad)
     - Constraints (template vars, max length, tone)
   - LLM returns: improved prompt + reasoning

3. DEPLOY: Shadow test the proposal
   - Create new prompt version (source='optimization')
   - Add as experiment arm at low weight (e.g., 5%)
   - This is the "training run" — real traffic evaluates the prompt

4. EVALUATE: Wait for sufficient signal
   - Collect min_sample_size metric events for the new arm
   - Compute composite score vs. baseline

5. DECIDE: Keep or discard
   - IF improved → promote: increase weight, eventually make it the new default
   - IF equal → discard (simplicity criterion: don't add complexity for no gain)
   - IF worse → discard and revert
   - Log result to optimization_runs (equivalent to results.tsv)

6. ADVANCE: Update baseline and continue
   - New baseline = best performing version
   - Go to step 1
```

---

## Key Design Principles (from autoresearch)

### 1. Fixed Evaluation Metric
Just as autoresearch uses `val_bpb` as the single ground truth, each prompt defines its optimization metric. The metric collection (`[metric]` package) is the evaluation harness — it is NOT modified by the optimizer.

```python
# The metric is configured per prompt, not per experiment
prompt.optimization_config = {
    "metric_name": "quality_score",      # What to optimize
    "direction": "maximize",              # or "minimize" for latency
    "min_sample_size": 100,               # Per arm before deciding
    "composite_weights": {                # Optional multi-metric
        "quality": 0.7,
        "latency": 0.2,
        "success_rate": 0.1,
    }
}
```

### 2. Autonomous Operation
> "NEVER STOP: Once the experiment loop has begun, do NOT pause to ask the human... The human might be asleep."

The optimization loop, once started, runs autonomously:
- No human approval needed per iteration (opt-in via `auto_deploy: true`)
- Runs on a schedule (e.g., every 6 hours) or continuously
- Logs everything for human review later
- Only stops when: budget exhausted, manually stopped, or no more ideas

### 3. Keep/Discard Binary
Every optimization produces exactly one of:
- **keep**: New version becomes the baseline, branch advances
- **discard**: Revert to previous best, as if the experiment never happened
- **crash**: Log it, move on, try something different

There is no "maybe" — the metric decides.

### 4. Simplicity Criterion
> "A 0.001 improvement that adds 20 lines of hacky code? Probably not worth it."

Applied to prompts: If the optimizer produces a much longer/more complex prompt for marginal improvement, prefer the simpler version. The optimizer's meta-prompt should include this instruction:

```
When proposing improvements:
- Shorter prompts that perform equally are preferred
- Don't add unnecessary instructions for marginal gains
- Removing unhelpful parts of the prompt IS an improvement
- Clarity > complexity
```

### 5. Everything is Logged
Just as autoresearch logs every experiment to `results.tsv`, every optimization attempt is recorded:

```
optimization_runs table:
- What was tried (proposed_body)
- Why (llm_reasoning)
- What happened (metrics before/after)
- Decision (keep/discard/crash)
- Full lineage (parent_version → new_version)
```

This lets humans review the optimization history, understand what worked, and tune the process.

---

## The Three Roles

### The Human (program.md equivalent)
Configures the optimization:
- Defines what metric to optimize
- Sets constraints (template vars, max length, tone)
- Chooses the optimizer LLM (Claude, GPT-4, etc.)
- Sets the budget (max runs, time window)
- Decides auto_deploy vs. human review

### The Optimizer LLM (the agent)
Proposes prompt improvements:
- Analyzes metric data and sample interactions
- Generates improved prompt text
- Explains reasoning
- Respects constraints

### The Evaluation Harness ([metric] package)
Measures results:
- Collects signals from production traffic
- Aggregates metrics per version
- Computes composite scores
- Determines statistical significance

---

## Advanced: Multi-Agent Optimization

Autoresearch uses a single agent. We can go further with multiple optimizer agents:

### Collaborative Optimization
```python
# Multiple LLMs propose improvements in parallel
proposals = await asyncio.gather(
    optimize_with("claude-sonnet-4-20250514", prompt, metrics),
    optimize_with("gpt-4o", prompt, metrics),
    optimize_with("claude-opus-4-20250514", prompt, metrics),
)

# Judge picks the best proposal
winner = await judge_proposals(proposals, metrics, judge="claude-opus-4-20250514")
```

### Diverse Strategies
Different optimizer agents can use different strategies:
- **Conservative**: Small targeted edits to weak spots
- **Radical**: Major restructuring of the prompt
- **Ablation**: Try removing parts to find what's unnecessary
- **Synthesis**: Combine best elements from multiple versions

---

## Configuration Example

```yaml
optimization:
  # The autoresearch loop
  enabled: true
  mode: "autonomous"           # or "human-review"

  # LLM for optimization
  llm_provider: "anthropic"
  llm_model: "claude-sonnet-4-20250514"

  # Loop settings
  schedule: "continuous"       # or cron: "0 */6 * * *"
  min_events_between_runs: 500
  max_runs_per_day: 24

  # Evaluation
  min_sample_size: 100
  significance_threshold: 0.05
  improvement_threshold: 0.01  # Min 1% improvement to keep

  # Safety
  max_weight_for_new_version: 0.10   # Start at 10% traffic
  auto_promote_after_samples: 1000   # Promote to default after 1000 samples
  rollback_on_regression: true

  # Simplicity
  prefer_shorter_prompts: true
  max_prompt_length: 4000
```

---

## Implementation Priority

Based on the autoresearch pattern, the optimization loop should be built in this order:

1. **Metric collection** — The evaluation harness must exist first (like `prepare.py`)
2. **Experiment engine** — The keep/discard mechanism (like git branch management)
3. **Optimizer LLM** — The agent that proposes changes (like the agent modifying `train.py`)
4. **Autonomous loop** — The scheduler that ties it all together (like the "LOOP FOREVER")
5. **Logging/review** — The results tracking (like `results.tsv`)

This matches the implementation plan: Phase 5 (Metrics) → Phase 3 (Experiments) → Phase 6 (LLM Optimizer) → Phase 8 (Polish/Scheduling).

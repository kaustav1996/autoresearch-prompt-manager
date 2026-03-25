# Autoresearcher Shonku

## The autoresearch pattern

In early 2026, Andrej Karpathy published a small repository called [autoresearch](https://github.com/karpathy/autoresearch). The idea was disarmingly simple. Give an AI agent a training script. Let it modify the script, run a 5-minute training session, check the validation loss, and decide: keep the change or revert. Then repeat. A hundred times overnight while you sleep.

The results were surprisingly good. Not because the agent had better ideas than a human researcher. But because it could try a hundred ideas in the time a human would try three. And the feedback loop was tight. Propose, test, measure, decide. No meetings, no PRs, no design discussions. Just the metric.

autoresearcher-shonku applies this same loop to prompts.

## How the loop works

```
1. ANALYZE    Read the prompt. Read its metrics. Read sample interactions.
2. PROPOSE    The LLM generates an improved version.
3. VALIDATE   Safety rails check: similarity, template vars, length.
4. DEPLOY     Shadow test at 5% traffic.
5. EVALUATE   Collect metrics on the new version.
6. DECIDE     Keep if improved. Discard if not.
7. REPEAT
```

Each step corresponds to either a tool call (reading data, writing data) or an agent decision (what to change, whether to keep). The LLM sees the tools and decides which to call. The autoresearcher's instructions tell it the loop structure. The actual execution is the LLM reasoning through each step.

## The agents

autoresearcher-shonku defines four agents, all built on shonku:

**PromptAnalyzerAgent** reads metrics and sample interactions to identify what is working and what is not. It looks for patterns: which version scores higher, what kind of inputs produce low ratings, whether there is a trend over time.

**PromptOptimizerAgent** takes the analysis and proposes a concrete improvement. It writes the new prompt text, validates that template variables are preserved, and checks that the edit distance is within bounds.

**ExperimentManagerAgent** handles the experiment lifecycle. Create the experiment, configure arms with weights, start it, monitor it, conclude it.

**AutoResearcherAgent** is the orchestrator. It runs the loop, calling the other agents or their tools in sequence. It is the one that decides when to stop, when to escalate, and when a change is not worth the complexity.

## The self-improving part

Here is the thing that makes this recursive rather than linear.

The AutoResearcherAgent has instructions. Those instructions are a prompt. The prompt says things like "analyze the metrics, propose an improvement, check safety rails." The quality of those instructions affects the quality of the optimizations the agent produces.

If you track whether the experiments created by the autoresearcher are getting better or worse over time, you can feed that signal back into a meta-optimization loop. The system rewrites its own optimization instructions based on the outcomes of the experiments it creates.

The meta-prompt that says "propose an improvement" can itself be improved by the same propose-test-keep-discard loop. And the meta-meta-prompt... well, you see where this goes. In practice, two levels of recursion is probably enough. But the architecture does not prevent deeper nesting.

This feature is gated by configuration. It is not the default. Most users want the single-level loop: optimize my prompts. The recursive mode is for teams that want their optimization to get better at optimizing.

## Tools and the boundary of knowledge

autoresearcher-shonku knows nothing about your data. It does not import your database, your ORM, or your API. It receives tools from the caller:

| Tool | Who provides it | What it does |
|------|----------------|-------------|
| `get_prompt` | prompt-manager | Reads the current prompt text |
| `get_metrics` | prompt-manager | Reads aggregated quality scores |
| `get_sample_interactions` | prompt-manager | Reads recent inputs/outputs |
| `create_version` | prompt-manager | Writes a new prompt version |
| `create_experiment` | prompt-manager | Sets up an A/B test |
| `conclude_experiment` | prompt-manager | Ends an experiment |
| `check_safety_rails` | autoresearcher itself | Validates a proposal |

The first six tools are closures over the prompt-manager API. The last one is built into the agent. This split means the autoresearcher is reusable. Swap the tools and it optimizes prompts stored anywhere.

## Safety

Every proposed change passes through safety rails before deployment:

- **Similarity check**: The new prompt must be at least 30% similar to the original. This prevents catastrophic rewrites.
- **Template variable preservation**: Every `{variable}` in the original must exist in the proposal. Dropping a variable would break downstream callers.
- **Length bounds**: The proposal must be between 30% and 300% of the original length. Extreme compression or expansion is a red flag.
- **Iteration budget**: The loop has a maximum iteration count. When exhausted, it stops.
- **Non-empty check**: The proposal must contain meaningful text (>10 characters).

These rails are not optional. They run on every iteration, even in fully autonomous mode.

# Autoresearch Prompt Manager

## The problem it solves

Every team building with LLMs has a prompts problem. The prompts live in code as string constants, or in a shared Google Doc, or in someone's head. When you want to try a different wording, you edit the string, deploy, and cross your fingers. There is no version history. There is no way to compare two versions side by side against production traffic. There is no way to know if the change you made last week actually helped.

autoresearch-prompt-manager treats prompts the way good engineering treats source code.

## The approach

### Versioned prompts with slug addressing

Every prompt has a human-readable slug. `welcome-email`. `checkout-upsell`. `support-triage`. You resolve a prompt by its slug, and you get the latest version by default. Every version is immutable, append-only, with a SHA-256 content hash for dedup. You can always trace what was served and when.

```python
prompt = await client.resolve("welcome-email")
# Returns: body, version, template_vars, experiment info
```

### Experiment routing

You have two versions of your checkout prompt and you want to know which one converts better. Create an experiment, assign weights, and the system handles routing.

The routing is deterministic. The same `session_id` always gets the same variant, using MurmurHash3 hashing. This means your users do not see different prompts on page refresh. It also means your metrics are clean, because each user is consistently bucketed.

When `auto_optimize` is enabled, the system switches from fixed weights to Thompson Sampling. This is a multi-armed bandit algorithm that automatically shifts traffic toward the better-performing variant. No manual weight adjustment needed. The math handles exploration vs. exploitation.

### Metric collection

After your application uses a prompt to generate content, it reports a quality signal back to the API. This could be a user rating, a conversion event, a latency measurement, or an LLM-as-judge score. Metrics are stored per-version, per-experiment, and aggregated on demand.

```python
await client.report_metric("welcome-email", version_id, "quality", 8.5)
```

### The optimization loop

This is the part that makes it different from a key-value store with versioning.

When optimization is triggered (manually or on a schedule), the system delegates to autoresearcher-shonku. The autoresearcher reads the current prompt, reads the metrics, reads sample interactions, and asks an LLM to propose an improvement. The proposal goes through safety checks (similarity bounds, template variable preservation, length constraints). If it passes, it gets deployed as a new experiment arm at low traffic weight. If the metrics improve, it gets promoted. If not, discarded.

The loop runs autonomously. The human sets the objective and the constraints. The machine does the iteration.

## Architecture

```
Your Application
    ↓ resolve("welcome-email")
autoresearch-prompt-manager (FastAPI + PostgreSQL)
    ↓ when optimization triggered
autoresearcher-shonku (optimization agents)
    ↓ agent framework
shonku (declarative agents)
    ↓ runtime
agno (LLM execution)
```

Each layer is an independent PyPI package. You can use the prompt manager without the optimizer. You can use shonku without the prompt manager. The coupling is through tools passed at runtime, not through import dependencies.

## Patterns worth noting

**Tools as the integration layer.** The autoresearcher does not import the prompt manager. It receives tools (`get_prompt`, `get_metrics`, `create_version`) from the caller. This means the same autoresearcher can optimize prompts stored in PostgreSQL, in Redis, in a flat file, or in memory. The storage is behind the tool interface.

**Safety rails as first-class citizens.** The optimizer includes a built-in `check_safety_rails` tool that validates every proposal before deployment. Similarity to original (catch catastrophic rewrites). Template variable preservation (catch broken callers). Length bounds. Iteration budget. These are not afterthoughts. They are part of the agent's instruction set.

**Deterministic routing for clean experiments.** MurmurHash3 with per-experiment seeds means the routing is reproducible. Given the same session_id and experiment configuration, you always get the same arm. This eliminates a class of subtle bugs where routing randomness contaminates metric attribution.

# Design Document: autoresearcher-shonku

> Status: Design only -- no code produced
> Date: 2026-03-25

---

## Table of Contents

1. [Overview and Position in the Stack](#1-overview-and-position-in-the-stack)
2. [Package Structure](#2-package-structure)
3. [Agent Definitions](#3-agent-definitions)
4. [Tool Architecture](#4-tool-architecture)
5. [The Optimization Loop](#5-the-optimization-loop)
6. [Safety Rails](#6-safety-rails)
7. [Configuration System](#7-configuration-system)
8. [Tool Flow: prompt-manager to shonku to agnosai](#8-tool-flow-prompt-manager-to-shonku-to-agnosai)
9. [PyPI Packaging](#9-pypi-packaging)
10. [Integration Example](#10-integration-example)
11. [Data Models](#11-data-models)
12. [Error Handling and Resilience](#12-error-handling-and-resilience)
13. [Observability](#13-observability)
14. [Open Questions](#14-open-questions)

---

## 1. Overview and Position in the Stack

autoresearcher-shonku is the **third layer** in a 4-layer agent stack:

```
prompt-manager  (application -- owns data, APIs, CRUD, metrics)
       |
       v  passes tools down
autoresearcher-shonku  (agent package -- optimization logic, THIS DOCUMENT)
       |
       v  defines agents using
shonku  (agent framework -- agent lifecycle, discovery, node execution)
       |
       v  built on
agnosai  (base protocol -- tool declaration, instruction execution, result reporting)
```

### What autoresearcher-shonku IS

- A published PyPI package (`pip install autoresearcher-shonku`).
- A collection of four shonku-based agents that implement Karpathy's autoresearch loop for autonomous prompt optimization.
- A consumer of tools -- it expects prompt CRUD, metrics, and experiment tools to be injected by the caller (prompt-manager).
- A producer of its own tools for analysis, similarity checking, and safety validation.

### What autoresearcher-shonku is NOT

- It is NOT a web server. It has no HTTP endpoints.
- It does NOT own any data storage. No database, no ORM, no migrations.
- It does NOT implement LLM provider abstraction. It uses shonku's agent execution model, which delegates to agnosai for LLM interaction.
- It does NOT know about prompt-manager's internal schema. It operates entirely through the tool interface.

---

## 2. Package Structure

```
autoresearcher-shonku/
├── pyproject.toml
├── LICENSE
├── README.md
│
├── src/
│   └── autoresearcher_shonku/
│       ├── __init__.py                  # Package version, public API exports
│       ├── py.typed                     # PEP 561 marker
│       │
│       ├── agents/
│       │   ├── __init__.py              # Re-exports all agent classes
│       │   ├── analyzer.py              # PromptAnalyzerAgent
│       │   ├── optimizer.py             # PromptOptimizerAgent
│       │   ├── experiment_manager.py    # ExperimentManagerAgent
│       │   └── autoresearcher.py        # AutoResearcherAgent (orchestrator)
│       │
│       ├── tools/
│       │   ├── __init__.py              # Re-exports all tool definitions
│       │   ├── analysis.py              # analyze_metric_trends
│       │   ├── improvement.py           # generate_prompt_improvement
│       │   ├── validation.py            # validate_template_vars
│       │   ├── similarity.py            # compute_similarity
│       │   └── safety.py               # check_safety_rails
│       │
│       ├── config.py                    # AutoResearcherConfig + sub-configs
│       ├── models.py                    # Data models (input/output types)
│       ├── loop.py                      # The core optimization loop logic
│       ├── scoring.py                   # Composite scoring, comparison logic
│       └── exceptions.py               # Domain exceptions
│
├── tests/
│   ├── conftest.py                      # Shared fixtures, mock tool factories
│   ├── test_analyzer.py
│   ├── test_optimizer.py
│   ├── test_experiment_manager.py
│   ├── test_autoresearcher.py
│   ├── test_loop.py
│   ├── test_scoring.py
│   ├── test_safety.py
│   └── test_config.py
│
└── examples/
    ├── basic_run.py                     # Minimal example with mock tools
    └── prompt_manager_integration.py    # How prompt-manager calls this package
```

### File Responsibilities

| File | Responsibility | Approximate LOC |
|------|---------------|-----------------|
| `agents/analyzer.py` | Shonku agent definition for metric analysis | ~120 |
| `agents/optimizer.py` | Shonku agent definition for prompt improvement | ~150 |
| `agents/experiment_manager.py` | Shonku agent definition for experiment lifecycle | ~130 |
| `agents/autoresearcher.py` | Orchestrator agent composing the above three | ~200 |
| `tools/*.py` | Five own-tool implementations | ~80 each |
| `loop.py` | The stateful optimization loop controller | ~250 |
| `scoring.py` | Metric comparison, composite scoring, statistical tests | ~150 |
| `config.py` | Pydantic configuration models | ~100 |
| `models.py` | Typed data models for all inputs/outputs | ~200 |

Total estimated: ~1800 lines of Python (excluding tests).

---

## 3. Agent Definitions

Each agent is defined as a shonku agent -- a declarative structure that specifies the agent's identity, system prompt, required tools, own tools, and output schema. Shonku handles LLM execution; agnosai handles tool dispatch.

### 3.1 PromptAnalyzerAgent

**Purpose**: Examines metric data for a prompt and produces a structured analysis of what is working, what is not, and hypotheses for improvement.

```python
from shonku import Agent, ToolRequirement

class PromptAnalyzerAgent(Agent):
    name = "prompt-analyzer"
    description = "Analyzes prompt performance metrics to identify weaknesses and opportunities"

    # Tools this agent REQUIRES from the caller
    required_tools = [
        ToolRequirement(name="get_metrics", description="Fetch metric summary for a prompt version"),
        ToolRequirement(name="get_prompt_version", description="Fetch a specific prompt version"),
        ToolRequirement(name="get_sample_interactions", description="Fetch sample interactions for analysis"),
    ]

    # Tools this agent PROVIDES (defined in autoresearcher-shonku)
    own_tools = [
        "analyze_metric_trends",
    ]

    system_prompt = """You are a prompt performance analyst. Given metric data and sample
    interactions for a prompt, produce a structured analysis.

    Your analysis MUST include:
    1. Performance summary: key metrics and their trends
    2. Strengths: what the current prompt does well (with evidence)
    3. Weaknesses: specific failure modes observed in sample interactions
    4. Hypotheses: ranked list of what changes might improve the metric
    5. Confidence: how confident you are in each hypothesis (high/medium/low)

    Be specific. Reference actual metric values and actual interaction examples.
    Do NOT suggest changes -- only analyze. The optimizer agent handles proposals."""

    output_schema = "AnalysisReport"
```

**Input context** (passed at invocation):
- `prompt_slug`: which prompt to analyze
- `version_id`: which version is the current baseline
- `metric_window`: time range for metric aggregation
- `sample_count`: how many interactions to examine (default 20)

**Output**: `AnalysisReport` (see section 11 for schema)

### 3.2 PromptOptimizerAgent

**Purpose**: Given an analysis report and the current prompt text, proposes a concrete improved prompt with reasoning and risk assessment.

```python
class PromptOptimizerAgent(Agent):
    name = "prompt-optimizer"
    description = "Proposes improved prompt text based on analysis"

    required_tools = [
        ToolRequirement(name="get_prompt", description="Fetch current prompt"),
        ToolRequirement(name="get_metrics", description="Fetch metric summary"),
        ToolRequirement(name="get_sample_interactions", description="Fetch sample interactions"),
    ]

    own_tools = [
        "generate_prompt_improvement",
        "validate_template_vars",
        "compute_similarity",
    ]

    system_prompt = """You are a prompt engineer optimizer. Given an analysis of a prompt's
    performance and the current prompt text, propose a single improved version.

    Rules:
    - Make ONE focused change per proposal. Do not rewrite the entire prompt.
    - Preserve ALL template variables from the original ({{var_name}} placeholders).
    - Explain your reasoning: what specific weakness does this change address?
    - Assess risk: what could go wrong with this change?
    - ALWAYS use the validate_template_vars tool to verify your proposal preserves variables.
    - ALWAYS use the compute_similarity tool to check your edit distance is reasonable.
    - Prefer shorter prompts when quality is equal. Removing unnecessary instructions IS
      an improvement.
    - Do NOT add filler, hedging language, or redundant instructions."""

    output_schema = "OptimizationProposal"
```

**Input context**:
- `analysis`: the `AnalysisReport` from PromptAnalyzerAgent
- `current_prompt`: full text of the baseline prompt
- `constraints`: `OptimizationConstraints` (max length, required vars, tone, etc.)
- `history`: list of recent proposals and their outcomes (to avoid repeating failures)

**Output**: `OptimizationProposal` (see section 11)

### 3.3 ExperimentManagerAgent

**Purpose**: Manages the lifecycle of a shadow test -- creating the experiment, monitoring sample collection, and determining the outcome.

```python
class ExperimentManagerAgent(Agent):
    name = "experiment-manager"
    description = "Manages shadow test experiments for prompt optimization"

    required_tools = [
        ToolRequirement(name="create_prompt_version", description="Create a new prompt version"),
        ToolRequirement(name="create_experiment", description="Create an A/B experiment"),
        ToolRequirement(name="update_experiment_weights", description="Adjust traffic weights"),
        ToolRequirement(name="conclude_experiment", description="End experiment and record winner"),
        ToolRequirement(name="get_metrics", description="Fetch metric summary"),
    ]

    own_tools = [
        "check_safety_rails",
    ]

    system_prompt = """You manage A/B experiments for prompt optimization. Your responsibilities:

    1. Create new prompt versions from proposed text
    2. Set up experiments with appropriate canary weights
    3. Monitor experiments until sufficient samples are collected
    4. Determine winners based on metric comparison
    5. Conclude experiments (promote winner or discard challenger)

    You do NOT decide what prompt text to test -- that comes from the optimizer.
    You DO decide the experimental parameters: weights, sample thresholds, timing."""

    output_schema = "ExperimentOutcome"
```

**Input context**:
- `proposal`: the `OptimizationProposal` from PromptOptimizerAgent
- `baseline_version_id`: current baseline version
- `config`: experiment parameters from `AutoResearcherConfig`

**Output**: `ExperimentOutcome` (see section 11)

### 3.4 AutoResearcherAgent (Orchestrator)

**Purpose**: The top-level agent that composes the three sub-agents into a continuous optimization loop.

```python
class AutoResearcherAgent(Agent):
    name = "autoresearcher"
    description = "Orchestrates the full prompt optimization loop"

    required_tools = [
        # ALL tools from prompt-manager (superset of what sub-agents need)
        ToolRequirement(name="get_prompt"),
        ToolRequirement(name="get_prompt_version"),
        ToolRequirement(name="create_prompt_version"),
        ToolRequirement(name="get_metrics"),
        ToolRequirement(name="get_sample_interactions"),
        ToolRequirement(name="create_experiment"),
        ToolRequirement(name="update_experiment_weights"),
        ToolRequirement(name="conclude_experiment"),
    ]

    own_tools = [
        "analyze_metric_trends",
        "generate_prompt_improvement",
        "validate_template_vars",
        "compute_similarity",
        "check_safety_rails",
    ]

    # The orchestrator does not use a freeform LLM system prompt.
    # Its logic is procedural (implemented in loop.py).
    # It calls sub-agents via shonku's agent composition API.
    mode = "orchestrator"
```

The orchestrator is NOT a freeform LLM agent. It executes a deterministic control flow (the loop in section 5) and delegates the LLM-reasoning steps to the three sub-agents. This makes the loop predictable and auditable.

---

## 4. Tool Architecture

### 4.1 Required Tools (Injected by prompt-manager)

These tools are NOT implemented by autoresearcher-shonku. They are passed in by the caller via shonku's tool injection mechanism.

| Tool | Signature | Returns |
|------|-----------|---------|
| `get_prompt` | `(slug: str) -> Prompt` | Prompt metadata + current version number |
| `get_prompt_version` | `(slug: str, version: int) -> PromptVersion` | Full version including body text |
| `create_prompt_version` | `(slug: str, content: str, source: str = "optimization") -> PromptVersion` | Newly created version |
| `get_metrics` | `(prompt_id: str, version_id: str, metric_name: str \| None, window_minutes: int = 360) -> MetricSummary` | Aggregated metrics |
| `get_sample_interactions` | `(prompt_id: str, version_id: str, n: int = 20) -> list[Interaction]` | Recent interactions with inputs/outputs |
| `create_experiment` | `(prompt_id: str, arms: list[ExperimentArm]) -> Experiment` | Created experiment |
| `update_experiment_weights` | `(experiment_id: str, weights: dict[str, float]) -> Experiment` | Updated experiment |
| `conclude_experiment` | `(experiment_id: str, winner_arm_id: str \| None = None) -> Experiment` | Concluded experiment |

### 4.2 Own Tools (Defined by autoresearcher-shonku)

These tools are implemented within this package and registered with shonku.

#### `analyze_metric_trends`

```python
def analyze_metric_trends(
    metrics: list[MetricDataPoint],
    window_hours: int = 24,
    min_points: int = 10,
) -> TrendAnalysis:
    """Compute trend direction, velocity, and anomalies from raw metric data.

    Returns:
        TrendAnalysis with fields:
        - direction: "improving" | "degrading" | "stable"
        - slope: float (rate of change per hour)
        - volatility: float (coefficient of variation)
        - anomalies: list of data points that deviate >2 std from the mean
        - sufficient_data: bool (whether min_points threshold was met)
    """
```

Implementation: Linear regression over the time series. Volatility via coefficient of variation. Anomaly detection via z-score >2.0. Pure computation, no LLM call.

#### `generate_prompt_improvement`

```python
def generate_prompt_improvement(
    current_prompt: str,
    analysis: AnalysisReport,
    constraints: OptimizationConstraints,
    history: list[ProposalRecord],
) -> ImprovedPrompt:
    """Prepare the structured context that the PromptOptimizerAgent uses to generate
    an improved prompt.

    This tool does NOT call an LLM directly. It structures the input for the optimizer
    agent, applying constraints filtering and history deduplication.

    Returns:
        ImprovedPrompt with fields:
        - context_block: formatted string for the optimizer agent
        - excluded_strategies: list of strategies already tried and failed
        - constraint_summary: human-readable constraint description
    """
```

Implementation: Filters history to extract recently-failed strategies, formats the analysis report into a structured prompt context block, validates constraints are internally consistent.

#### `validate_template_vars`

```python
def validate_template_vars(
    original: str,
    proposed: str,
) -> ValidationResult:
    """Check that all template variables in the original prompt exist in the proposed prompt.

    Template variables are identified by the pattern {{variable_name}} or {variable_name}.
    Both Jinja2-style and Python format-string-style are detected.

    Returns:
        ValidationResult with fields:
        - valid: bool
        - original_vars: set[str]
        - proposed_vars: set[str]
        - missing_vars: set[str]  (in original but not proposed)
        - added_vars: set[str]    (in proposed but not original)
    """
```

Implementation: Regex extraction of `{{...}}` and `{...}` patterns from both strings. Set comparison. Pure computation.

#### `compute_similarity`

```python
def compute_similarity(
    original: str,
    proposed: str,
) -> float:
    """Compute normalized edit distance between two prompt texts.

    Uses Levenshtein distance normalized by the length of the longer string.
    Returns a float in [0.0, 1.0] where 1.0 means identical and 0.0 means
    completely different.

    Also computes structural similarity: whether section headers, bullet structures,
    and formatting are preserved.
    """
```

Implementation: Levenshtein distance (using `rapidfuzz` if available, falling back to a pure-Python implementation). Structural comparison via regex-extracted section markers.

#### `check_safety_rails`

```python
def check_safety_rails(
    optimization_history: list[OptimizationRecord],
    current_proposal: OptimizationProposal,
    config: AutoResearcherConfig,
) -> SafetyCheck:
    """Evaluate whether the current optimization state is safe to continue.

    Checks:
    1. Iteration count vs max_iterations
    2. Consecutive failures (>5 in a row triggers cooldown)
    3. Edit distance of proposal vs baseline (must be < max_edit_distance)
    4. Time since last optimization (must respect cooldown_minutes)
    5. Budget consumption (total LLM calls, estimated cost)
    6. Regression detection (have recent iterations made things worse?)

    Returns:
        SafetyCheck with fields:
        - safe: bool
        - violations: list[str]  (human-readable reasons if not safe)
        - recommendation: "continue" | "pause" | "stop" | "rollback"
    """
```

Implementation: Pure computation over the history records and config thresholds.

---

## 5. The Optimization Loop

The loop is implemented in `loop.py` as a class `OptimizationLoop` that the `AutoResearcherAgent` drives.

### 5.1 Full Loop Pseudocode

```python
class OptimizationLoop:
    def __init__(self, tools: ToolSet, config: AutoResearcherConfig):
        self.tools = tools
        self.config = config
        self.history: list[OptimizationRecord] = []

    async def run(self, prompt_slug: str) -> OptimizationResult:
        # --- SETUP ---
        prompt = await self.tools.get_prompt(prompt_slug)
        baseline = await self.tools.get_prompt_version(prompt_slug, prompt.current_version)
        baseline_metrics = await self.tools.get_metrics(
            prompt.id, baseline.id, metric_name=None,
            window_minutes=self.config.metric_window_minutes,
        )

        result = OptimizationResult(
            prompt_slug=prompt_slug,
            starting_version=baseline.version,
            starting_metrics=baseline_metrics,
            iterations=[],
        )

        # --- MAIN LOOP ---
        for iteration in range(self.config.max_iterations):

            # 0. SAFETY CHECK (pre-iteration)
            safety = check_safety_rails(self.history, None, self.config)
            if not safety.safe:
                result.stop_reason = f"safety: {safety.violations}"
                break

            # 1. COOLDOWN
            if self.history and self.config.cooldown_minutes > 0:
                elapsed = time_since_last(self.history)
                if elapsed < timedelta(minutes=self.config.cooldown_minutes):
                    await sleep_until_cooldown(self.config.cooldown_minutes - elapsed)

            # 2. ANALYZE
            analysis = await self._run_analyzer(prompt, baseline, baseline_metrics)

            # If analyzer finds no weaknesses, optimization has converged
            if analysis.no_actionable_weaknesses:
                result.stop_reason = "converged"
                break

            # 3. PROPOSE
            proposal = await self._run_optimizer(prompt, baseline, analysis)

            # 4. VALIDATE PROPOSAL
            # 4a. Template variable check
            var_check = validate_template_vars(baseline.body, proposal.content)
            if not var_check.valid:
                self._record_failure(iteration, "template_vars_missing", var_check)
                continue

            # 4b. Edit distance check
            similarity = compute_similarity(baseline.body, proposal.content)
            if similarity < (1.0 - self.config.max_edit_distance):
                self._record_failure(iteration, "edit_distance_exceeded", similarity)
                continue

            # 4c. Full safety check with proposal
            safety = check_safety_rails(self.history, proposal, self.config)
            if not safety.safe:
                self._record_failure(iteration, "safety_violation", safety.violations)
                if safety.recommendation == "rollback":
                    await self._rollback(prompt, result)
                    break
                continue

            # 5. DEPLOY SHADOW TEST
            experiment_outcome = await self._run_experiment(
                prompt, baseline, proposal,
            )

            # 6. RECORD AND DECIDE
            record = OptimizationRecord(
                iteration=iteration,
                baseline_version=baseline.version,
                proposed_content=proposal.content,
                reasoning=proposal.reasoning,
                risk_assessment=proposal.risk_assessment,
                experiment_id=experiment_outcome.experiment_id,
                baseline_metrics=baseline_metrics.to_dict(),
                new_metrics=experiment_outcome.new_metrics.to_dict(),
                decision=experiment_outcome.decision,
            )
            self.history.append(record)
            result.iterations.append(record)

            # 7. ADVANCE OR HOLD
            if experiment_outcome.decision == "keep":
                # New version becomes baseline
                baseline = experiment_outcome.new_version
                baseline_metrics = experiment_outcome.new_metrics
                result.current_version = baseline.version
            # If "discard", baseline remains unchanged. Loop continues.

        # --- FINALIZE ---
        result.ending_version = baseline.version
        result.ending_metrics = baseline_metrics
        result.total_iterations = len(result.iterations)
        return result
```

### 5.2 Sub-Agent Invocations

Each `_run_*` method delegates to a shonku sub-agent:

```python
async def _run_analyzer(self, prompt, baseline, metrics) -> AnalysisReport:
    """Invoke the PromptAnalyzerAgent via shonku."""
    return await self.shonku.run_agent(
        agent=PromptAnalyzerAgent,
        tools=self.tools.subset(["get_metrics", "get_prompt_version",
                                  "get_sample_interactions", "analyze_metric_trends"]),
        context={
            "prompt_slug": prompt.slug,
            "version_id": baseline.id,
            "metric_window": self.config.metric_window_minutes,
            "sample_count": self.config.analysis_sample_count,
        },
    )

async def _run_optimizer(self, prompt, baseline, analysis) -> OptimizationProposal:
    """Invoke the PromptOptimizerAgent via shonku."""
    return await self.shonku.run_agent(
        agent=PromptOptimizerAgent,
        tools=self.tools.subset(["get_prompt", "get_metrics", "get_sample_interactions",
                                  "generate_prompt_improvement", "validate_template_vars",
                                  "compute_similarity"]),
        context={
            "analysis": analysis,
            "current_prompt": baseline.body,
            "constraints": self.config.constraints,
            "history": self._recent_proposals(),
        },
    )

async def _run_experiment(self, prompt, baseline, proposal) -> ExperimentOutcome:
    """Invoke the ExperimentManagerAgent via shonku."""
    return await self.shonku.run_agent(
        agent=ExperimentManagerAgent,
        tools=self.tools.subset(["create_prompt_version", "create_experiment",
                                  "update_experiment_weights", "conclude_experiment",
                                  "get_metrics", "check_safety_rails"]),
        context={
            "proposal": proposal,
            "baseline_version_id": baseline.id,
            "prompt_id": prompt.id,
            "config": ExperimentConfig(
                canary_weight=self.config.canary_weight,
                min_sample_size=self.config.min_sample_size,
                promote_after_samples=self.config.promote_after_samples,
                improvement_threshold=self.config.improvement_threshold,
            ),
        },
    )
```

### 5.3 Experiment Lifecycle (Inside ExperimentManagerAgent)

The ExperimentManagerAgent follows this sub-loop when invoked:

```
1. Create new prompt version from proposal.content
2. Create experiment with two arms:
   - baseline: weight = (100 - canary_weight)
   - challenger: weight = canary_weight (default 5)
3. Poll for metrics at intervals until min_sample_size reached for BOTH arms
   - Poll interval: max(30 seconds, config.poll_interval)
   - Timeout: config.experiment_timeout_minutes (default 1440 = 24 hours)
4. Compute composite scores for both arms
5. Compare:
   - If challenger > baseline by improvement_threshold  -> decision = "keep"
   - If challenger <= baseline                          -> decision = "discard"
   - If challenger caused regression > rollback_threshold -> decision = "rollback"
6. Conclude the experiment via conclude_experiment tool
7. Return ExperimentOutcome
```

### 5.4 Wait-for-Signal Strategy

The "wait for sufficient samples" step is the most time-intensive part of the loop. The package supports two modes:

**Polling mode** (default): The experiment manager polls `get_metrics` at a configurable interval. This is suitable when the optimization loop runs as a long-lived process.

```python
async def wait_for_signal(self, experiment_id, min_samples, timeout_minutes):
    deadline = utcnow() + timedelta(minutes=timeout_minutes)
    while utcnow() < deadline:
        metrics = await self.tools.get_metrics(experiment_id=experiment_id)
        if all(arm.sample_count >= min_samples for arm in metrics.arms):
            return metrics
        await asyncio.sleep(self.config.poll_interval_seconds)
    raise ExperimentTimeoutError(experiment_id)
```

**Callback mode** (advanced): The caller provides a `wait_for_signal` callback that blocks until the experiment has sufficient data. This allows prompt-manager to use its own event system (webhooks, database triggers, etc.) instead of polling.

---

## 6. Safety Rails

Safety is enforced at three levels: pre-proposal, post-proposal, and post-experiment.

### 6.1 Pre-Proposal Rails

Checked before the optimizer agent runs each iteration.

| Rail | Condition | Action |
|------|-----------|--------|
| **Max iterations** | `iteration >= config.max_iterations` | Stop loop |
| **Consecutive failures** | `>= 5 consecutive discards or errors` | Pause for `cooldown_minutes * 3`, then resume |
| **Cooldown** | `time_since_last < cooldown_minutes` | Sleep until cooldown expires |
| **Budget limit** | `total_llm_calls > config.max_llm_calls` | Stop loop |

### 6.2 Post-Proposal Rails

Checked after the optimizer agent produces a proposal but before deploying.

| Rail | Condition | Action |
|------|-----------|--------|
| **Template variable integrity** | Missing variables in proposed prompt | Skip proposal, log, continue |
| **Edit distance** | `similarity < (1.0 - max_edit_distance)` | Skip proposal, log, continue |
| **Prompt length** | `len(proposed) > config.max_prompt_length` | Skip proposal, log, continue |
| **Banned patterns** | Proposed prompt contains patterns from `config.banned_patterns` | Skip proposal, log, continue |
| **Duplicate detection** | Proposed prompt identical to a recent proposal | Skip proposal, log, continue |

### 6.3 Post-Experiment Rails

Checked after experiment results are in.

| Rail | Condition | Action |
|------|-----------|--------|
| **Regression detection** | New version is significantly WORSE (> `rollback_threshold`) | Conclude experiment immediately, discard |
| **Metric anomaly** | Sudden spike/drop in baseline metrics during experiment | Pause experiment, alert, wait for stability |
| **Cascading failure** | 3 consecutive experiments show regression | Stop loop entirely, recommend human review |

### 6.4 Rollback Mechanism

When `rollback_on_regression` is enabled and a regression is detected:

1. Immediately conclude the active experiment (discard challenger).
2. If the baseline itself has degraded compared to the starting point of the optimization run, emit a `RollbackRequired` event.
3. The caller (prompt-manager) is responsible for acting on this event (e.g., reverting to the starting version).

autoresearcher-shonku does NOT directly modify the baseline outside of the experiment flow. It can only recommend rollback; the caller must execute it.

---

## 7. Configuration System

All configuration is via a single Pydantic model. The caller constructs it and passes it in.

```python
from pydantic import BaseModel, Field

class OptimizationConstraints(BaseModel):
    """Constraints on what the optimizer can do to the prompt."""
    max_prompt_length: int = 8000
    required_template_vars: list[str] = Field(default_factory=list)
    banned_patterns: list[str] = Field(default_factory=list)
    tone_guidance: str | None = None
    preserve_sections: list[str] = Field(default_factory=list)

class ExperimentConfig(BaseModel):
    """Controls for the experiment phase."""
    canary_weight: float = Field(default=5.0, ge=1.0, le=50.0)
    min_sample_size: int = Field(default=100, ge=10)
    promote_after_samples: int = Field(default=1000, ge=100)
    experiment_timeout_minutes: int = Field(default=1440, ge=10)
    poll_interval_seconds: int = Field(default=60, ge=10)

class AutoResearcherConfig(BaseModel):
    """Top-level configuration for the optimization loop."""

    # Loop control
    max_iterations: int = Field(default=100, ge=1)
    cooldown_minutes: int = Field(default=30, ge=0)
    metric_window_minutes: int = Field(default=360, ge=30)
    analysis_sample_count: int = Field(default=20, ge=5)

    # Thresholds
    improvement_threshold: float = Field(default=0.01, ge=0.0, le=1.0)
    rollback_threshold: float = Field(default=0.05, ge=0.0, le=1.0)
    max_edit_distance: float = Field(default=0.5, ge=0.0, le=1.0)

    # Safety
    max_consecutive_failures: int = Field(default=5, ge=1)
    max_llm_calls: int = Field(default=500, ge=1)
    rollback_on_regression: bool = True

    # Scoring
    simplicity_preference: bool = True
    simplicity_weight: float = Field(default=0.05, ge=0.0, le=0.5)
    composite_weights: dict[str, float] = Field(
        default_factory=lambda: {"quality": 0.7, "latency": 0.2, "success_rate": 0.1}
    )

    # Experiment sub-config
    experiment: ExperimentConfig = Field(default_factory=ExperimentConfig)

    # Constraints
    constraints: OptimizationConstraints = Field(default_factory=OptimizationConstraints)
```

### 7.1 Configuration Layering

The caller (prompt-manager) can provide configuration at multiple levels:

1. **Global defaults**: Built into `AutoResearcherConfig` field defaults.
2. **Per-prompt overrides**: Stored in prompt metadata, merged at invocation time.
3. **Per-run overrides**: Passed directly when triggering an optimization run.

Merge order: global < per-prompt < per-run (last wins).

```python
# In prompt-manager:
config = AutoResearcherConfig(
    **{**global_defaults, **prompt.optimization_config, **run_overrides}
)
```

---

## 8. Tool Flow: prompt-manager to shonku to agnosai

This section describes how tools flow through the stack.

### 8.1 The Full Tool Chain

```
prompt-manager (application layer)
  |
  |  1. Constructs tool implementations (functions that call its own services)
  |  2. Wraps them as agnosai Tool objects
  |  3. Passes tool list to AutoResearcherAgent.run()
  |
  v
autoresearcher-shonku (agent layer)
  |
  |  4. Validates all required_tools are present
  |  5. Adds its own tools (analyze_metric_trends, etc.)
  |  6. Composes the combined tool set
  |  7. When running sub-agents, passes a SUBSET of tools to each
  |
  v
shonku (framework layer)
  |
  |  8. Receives agent definition + tools
  |  9. Constructs the LLM message (system prompt + tool schemas)
  | 10. Runs the agent loop: LLM call -> tool dispatch -> LLM call -> ...
  |
  v
agnosai (protocol layer)
  |
  | 11. Serializes tool schemas to the LLM's expected format
  | 12. Dispatches tool calls to the registered implementations
  | 13. Returns tool results to the LLM
  | 14. Handles the run loop (message -> tool_use -> tool_result -> message)
```

### 8.2 Tool Wrapping at Each Layer

**prompt-manager creates tools:**

```python
from agnosai import Tool, ToolParameter

# prompt-manager wraps its service methods as agnosai Tools
get_prompt_tool = Tool(
    name="get_prompt",
    description="Fetch a prompt by slug",
    parameters=[
        ToolParameter(name="slug", type="string", required=True),
    ],
    handler=prompt_service.get_by_slug,  # actual implementation
)
```

**autoresearcher-shonku adds its own tools:**

```python
from agnosai import Tool, ToolParameter

analyze_trends_tool = Tool(
    name="analyze_metric_trends",
    description="Compute trend direction and anomalies from metric data",
    parameters=[
        ToolParameter(name="metrics", type="array", required=True),
        ToolParameter(name="window_hours", type="integer", required=False, default=24),
    ],
    handler=analyze_metric_trends,  # implementation in tools/analysis.py
)
```

**shonku receives the combined set:**

```python
# Inside AutoResearcherAgent.run():
all_tools = [
    *caller_tools,        # 8 tools from prompt-manager
    *own_tools,           # 5 tools from autoresearcher-shonku
]

# When running a sub-agent, pass only what it needs:
analyzer_tools = select_tools(all_tools, PromptAnalyzerAgent.required_tools +
                                          PromptAnalyzerAgent.own_tools)
```

### 8.3 Tool Validation

At startup, `AutoResearcherAgent.run()` validates that all required tools are present:

```python
def validate_tools(provided: list[Tool], required: list[ToolRequirement]) -> None:
    provided_names = {t.name for t in provided}
    required_names = {r.name for r in required}
    missing = required_names - provided_names
    if missing:
        raise MissingToolsError(
            f"AutoResearcherAgent requires tools not provided: {missing}"
        )
```

This fails fast with a clear error message rather than failing mid-loop when a tool is first invoked.

---

## 9. PyPI Packaging

### 9.1 pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "autoresearcher-shonku"
version = "0.1.0"
description = "Autonomous prompt optimization agents built on shonku"
readme = "README.md"
license = "MIT"
requires-python = ">=3.11"
authors = [
    { name = "autoresearch-prompt-manager team" },
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

dependencies = [
    "shonku>=0.1.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
fast-similarity = [
    "rapidfuzz>=3.0",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.4",
    "mypy>=1.10",
]

[project.urls]
Homepage = "https://github.com/your-org/autoresearcher-shonku"
Documentation = "https://github.com/your-org/autoresearcher-shonku/docs"
Issues = "https://github.com/your-org/autoresearcher-shonku/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/autoresearcher_shonku"]
```

### 9.2 Dependencies

| Dependency | Why | Version |
|-----------|-----|---------|
| `shonku` | Agent framework (also brings in `agnosai` transitively) | `>=0.1.0` |
| `pydantic` | Configuration and data models | `>=2.0` |
| `rapidfuzz` (optional) | Fast Levenshtein distance for `compute_similarity` | `>=3.0` |

Note: No LLM SDK dependency. autoresearcher-shonku does not call LLMs directly. shonku/agnosai handle LLM interaction.

### 9.3 Publishing

```bash
# Build
hatch build

# Test publish
hatch publish --repo test

# Production publish
hatch publish
```

The package follows standard Python packaging practices: src layout, PEP 561 type marker, hatchling build backend.

---

## 10. Integration Example

This is how prompt-manager uses autoresearcher-shonku.

### 10.1 prompt-manager's Optimization Service

```python
# src/prompt_manager/api/services/optimization_service.py

from autoresearcher_shonku import AutoResearcherAgent, AutoResearcherConfig
from autoresearcher_shonku.models import OptimizationResult
from agnosai import Tool, ToolParameter


class OptimizationService:
    """prompt-manager's service that bridges its data layer to autoresearcher-shonku."""

    def __init__(
        self,
        prompt_service: PromptService,
        experiment_service: ExperimentService,
        metric_service: MetricService,
    ):
        self.prompt_service = prompt_service
        self.experiment_service = experiment_service
        self.metric_service = metric_service

    def _build_tools(self) -> list[Tool]:
        """Wrap prompt-manager's service methods as agnosai Tools."""
        return [
            Tool(
                name="get_prompt",
                description="Fetch a prompt by slug",
                parameters=[ToolParameter(name="slug", type="string", required=True)],
                handler=self.prompt_service.get_by_slug,
            ),
            Tool(
                name="get_prompt_version",
                description="Fetch a specific prompt version",
                parameters=[
                    ToolParameter(name="slug", type="string", required=True),
                    ToolParameter(name="version", type="integer", required=True),
                ],
                handler=self.prompt_service.get_version,
            ),
            Tool(
                name="create_prompt_version",
                description="Create a new prompt version",
                parameters=[
                    ToolParameter(name="slug", type="string", required=True),
                    ToolParameter(name="content", type="string", required=True),
                    ToolParameter(name="source", type="string", required=False, default="optimization"),
                ],
                handler=self.prompt_service.create_version,
            ),
            Tool(
                name="get_metrics",
                description="Fetch aggregated metrics for a prompt version",
                parameters=[
                    ToolParameter(name="prompt_id", type="string", required=True),
                    ToolParameter(name="version_id", type="string", required=True),
                    ToolParameter(name="metric_name", type="string", required=False),
                    ToolParameter(name="window_minutes", type="integer", required=False, default=360),
                ],
                handler=self.metric_service.get_summary,
            ),
            Tool(
                name="get_sample_interactions",
                description="Fetch sample interactions for analysis",
                parameters=[
                    ToolParameter(name="prompt_id", type="string", required=True),
                    ToolParameter(name="version_id", type="string", required=True),
                    ToolParameter(name="n", type="integer", required=False, default=20),
                ],
                handler=self.metric_service.get_sample_interactions,
            ),
            Tool(
                name="create_experiment",
                description="Create an A/B experiment",
                parameters=[
                    ToolParameter(name="prompt_id", type="string", required=True),
                    ToolParameter(name="arms", type="array", required=True),
                ],
                handler=self.experiment_service.create,
            ),
            Tool(
                name="update_experiment_weights",
                description="Update experiment arm weights",
                parameters=[
                    ToolParameter(name="experiment_id", type="string", required=True),
                    ToolParameter(name="weights", type="object", required=True),
                ],
                handler=self.experiment_service.update_weights,
            ),
            Tool(
                name="conclude_experiment",
                description="Conclude an experiment",
                parameters=[
                    ToolParameter(name="experiment_id", type="string", required=True),
                    ToolParameter(name="winner_arm_id", type="string", required=False),
                ],
                handler=self.experiment_service.conclude,
            ),
        ]

    async def run_optimization(
        self,
        prompt_slug: str,
        config_overrides: dict | None = None,
    ) -> OptimizationResult:
        """Trigger an autonomous optimization run for a prompt."""

        # 1. Build config (global + per-prompt + overrides)
        prompt = await self.prompt_service.get_by_slug(prompt_slug)
        config = self._build_config(prompt, config_overrides)

        # 2. Build tools
        tools = self._build_tools()

        # 3. Run the autoresearcher
        agent = AutoResearcherAgent()
        result = await agent.run(tools=tools, config=config)

        # 4. Log the result
        await self._log_optimization_run(prompt, result)

        return result
```

### 10.2 Triggering from the API

```python
# src/prompt_manager/api/routers/optimize.py

@router.post("/optimize/{slug}")
async def trigger_optimization(
    slug: str,
    body: OptimizationRequest,
    optimization_service: OptimizationService = Depends(get_optimization_service),
):
    # Start optimization in background task
    task = asyncio.create_task(
        optimization_service.run_optimization(slug, body.config_overrides)
    )
    # Return immediately with a run ID for polling
    return {"run_id": task.get_name(), "status": "started"}
```

### 10.3 Minimal Usage (for testing or standalone)

```python
from autoresearcher_shonku import AutoResearcherAgent, AutoResearcherConfig

# Create mock tools for testing
tools = create_mock_tools(
    prompt_text="You are a helpful assistant. Answer the user's question.",
    metrics={"quality": 0.72, "latency": 1.2, "success_rate": 0.95},
)

config = AutoResearcherConfig(
    max_iterations=5,
    min_sample_size=50,
    improvement_threshold=0.02,
)

agent = AutoResearcherAgent()
result = await agent.run(tools=tools, config=config)

print(f"Started at version {result.starting_version}, ended at {result.ending_version}")
print(f"Iterations: {result.total_iterations}, Stop reason: {result.stop_reason}")
```

---

## 11. Data Models

All models use Pydantic v2 for serialization and validation.

### 11.1 Analysis Models

```python
class AnalysisReport(BaseModel):
    """Output of PromptAnalyzerAgent."""
    performance_summary: dict[str, float]
    trends: dict[str, TrendAnalysis]
    strengths: list[Finding]
    weaknesses: list[Finding]
    hypotheses: list[Hypothesis]
    no_actionable_weaknesses: bool
    raw_sample_count: int

class Finding(BaseModel):
    description: str
    evidence: str          # Specific metric value or interaction quote
    severity: str          # "high" | "medium" | "low"

class Hypothesis(BaseModel):
    description: str
    target_weakness: str
    expected_impact: str   # "high" | "medium" | "low"
    confidence: str        # "high" | "medium" | "low"
    strategy: str          # "edit" | "restructure" | "remove" | "add"

class TrendAnalysis(BaseModel):
    direction: str         # "improving" | "degrading" | "stable"
    slope: float
    volatility: float
    anomalies: list[dict]
    sufficient_data: bool
```

### 11.2 Proposal Models

```python
class OptimizationProposal(BaseModel):
    """Output of PromptOptimizerAgent."""
    content: str                    # The proposed new prompt text
    reasoning: str                  # Why this change should help
    target_hypothesis: str          # Which hypothesis from analysis this addresses
    risk_assessment: str            # What could go wrong
    expected_improvement: float     # Estimated metric improvement (0.0-1.0)
    edit_type: str                  # "targeted_edit" | "restructure" | "ablation" | "addition"
    similarity_score: float         # Result of compute_similarity
    template_vars_valid: bool       # Result of validate_template_vars

class OptimizationConstraints(BaseModel):
    max_prompt_length: int = 8000
    required_template_vars: list[str] = Field(default_factory=list)
    banned_patterns: list[str] = Field(default_factory=list)
    tone_guidance: str | None = None
    preserve_sections: list[str] = Field(default_factory=list)
```

### 11.3 Experiment Models

```python
class ExperimentOutcome(BaseModel):
    """Output of ExperimentManagerAgent."""
    experiment_id: str
    new_version: PromptVersionRef
    baseline_metrics: MetricSummary
    new_metrics: MetricSummary
    decision: str                   # "keep" | "discard" | "rollback"
    decision_reasoning: str
    sample_counts: dict[str, int]   # arm_id -> sample count
    duration_minutes: float

class PromptVersionRef(BaseModel):
    id: str
    version: int
    body: str

class MetricSummary(BaseModel):
    metric_values: dict[str, float]   # metric_name -> value
    composite_score: float
    sample_count: int
    window_minutes: int
```

### 11.4 Loop Result Models

```python
class OptimizationRecord(BaseModel):
    """One iteration of the optimization loop."""
    iteration: int
    baseline_version: int
    proposed_content: str
    reasoning: str
    risk_assessment: str
    experiment_id: str | None
    baseline_metrics: dict
    new_metrics: dict | None
    decision: str               # "keep" | "discard" | "skip" | "error"
    skip_reason: str | None
    timestamp: datetime

class OptimizationResult(BaseModel):
    """Final result of a complete optimization run."""
    prompt_slug: str
    starting_version: int
    ending_version: int
    starting_metrics: MetricSummary
    ending_metrics: MetricSummary
    iterations: list[OptimizationRecord]
    total_iterations: int
    stop_reason: str            # "max_iterations" | "converged" | "safety" | "budget" | "manual"
    duration_minutes: float

class SafetyCheck(BaseModel):
    safe: bool
    violations: list[str]
    recommendation: str         # "continue" | "pause" | "stop" | "rollback"

class ValidationResult(BaseModel):
    valid: bool
    original_vars: set[str]
    proposed_vars: set[str]
    missing_vars: set[str]
    added_vars: set[str]
```

---

## 12. Error Handling and Resilience

### 12.1 Exception Hierarchy

```python
class AutoResearcherError(Exception):
    """Base exception for all autoresearcher-shonku errors."""

class MissingToolsError(AutoResearcherError):
    """Required tools were not provided by the caller."""

class ConfigurationError(AutoResearcherError):
    """Invalid configuration."""

class ExperimentTimeoutError(AutoResearcherError):
    """Experiment did not collect enough samples within the timeout."""

class SafetyViolationError(AutoResearcherError):
    """A safety rail was triggered that requires stopping the loop."""

class AgentExecutionError(AutoResearcherError):
    """A sub-agent failed to produce valid output."""

class ToolExecutionError(AutoResearcherError):
    """A tool call failed."""
```

### 12.2 Resilience Patterns

**Sub-agent retry**: If a sub-agent call fails (LLM error, malformed output), retry up to 2 times with the same context. On the third failure, record as `decision="error"` and continue to the next iteration.

**Tool call retry**: If a tool call fails (network error, transient DB error), retry with exponential backoff (1s, 2s, 4s). After 3 failures, propagate as `ToolExecutionError`.

**Graceful degradation**: If `get_sample_interactions` fails, the analyzer can still run on metrics alone (degraded but functional). If `get_metrics` fails, the loop pauses and retries after cooldown.

**Crash recovery**: The `OptimizationResult` is periodically checkpointed (serialized to JSON). If the process crashes and restarts, the loop can resume from the last checkpoint rather than starting over.

---

## 13. Observability

### 13.1 Structured Logging

Every significant event emits a structured log entry:

```python
logger.info("optimization.iteration.start", extra={
    "prompt_slug": slug,
    "iteration": iteration,
    "baseline_version": baseline.version,
})

logger.info("optimization.proposal.generated", extra={
    "prompt_slug": slug,
    "iteration": iteration,
    "edit_type": proposal.edit_type,
    "similarity_score": proposal.similarity_score,
})

logger.info("optimization.decision", extra={
    "prompt_slug": slug,
    "iteration": iteration,
    "decision": outcome.decision,
    "baseline_score": baseline_metrics.composite_score,
    "new_score": outcome.new_metrics.composite_score,
    "improvement": improvement_pct,
})
```

### 13.2 Events

The loop emits typed events that the caller can subscribe to:

| Event | When | Payload |
|-------|------|---------|
| `optimization.started` | Loop begins | prompt_slug, config |
| `optimization.iteration.complete` | After each iteration | OptimizationRecord |
| `optimization.proposal.skipped` | Proposal fails validation | reason, proposal summary |
| `optimization.experiment.started` | New experiment created | experiment_id, arms |
| `optimization.decision.keep` | Challenger wins | version, improvement |
| `optimization.decision.discard` | Baseline wins | version, delta |
| `optimization.safety.triggered` | Safety rail fires | rail name, details |
| `optimization.completed` | Loop ends | OptimizationResult |
| `optimization.error` | Unrecoverable error | exception details |

The event system uses a simple callback pattern:

```python
agent = AutoResearcherAgent()
agent.on("optimization.decision.keep", lambda e: notify_slack(e))
agent.on("optimization.safety.triggered", lambda e: page_oncall(e))
result = await agent.run(tools=tools, config=config)
```

---

## 14. Open Questions

These are design decisions that should be resolved during implementation.

### 14.1 Orchestrator: Deterministic Loop vs. LLM-Driven Orchestrator

The current design uses a deterministic loop (coded in Python) that calls sub-agents at fixed points. An alternative is to make the AutoResearcherAgent itself an LLM agent that decides when to analyze, propose, and test.

**Recommendation**: Start with the deterministic loop. It is more predictable, auditable, and testable. The LLM-driven orchestrator can be explored as a future "autonomous mode" once the deterministic loop is proven.

### 14.2 Multi-Metric Scoring

The composite score formula (`quality * 0.7 + latency * 0.2 + success_rate * 0.1`) assumes all metrics are normalized to [0, 1]. How should normalization work for metrics with different scales (e.g., latency in milliseconds, quality as a 1-5 rating)?

**Recommendation**: Require the caller to provide a normalization function per metric, or use min-max normalization over the observed range within the experiment window.

### 14.3 Concurrent Proposals

Should the optimizer generate multiple proposals per iteration and test them in a multi-arm experiment? This increases experiment complexity but could find improvements faster.

**Recommendation**: Start with one proposal per iteration. Add multi-proposal as a configuration option in v0.2.

### 14.4 Cross-Prompt Learning

Can the analyzer learn from optimization runs on OTHER prompts? For example, if removing hedging language helped prompt A, it might help prompt B.

**Recommendation**: Out of scope for v0.1. Design the `ProposalRecord` schema to be query-friendly so that cross-prompt learning can be added later by injecting historical records into the optimizer's context.

### 14.5 shonku Agent Registration

How exactly does shonku discover and register agents? This depends on shonku's design (see `docs/design-shonku.md`). autoresearcher-shonku will need to conform to whatever registration mechanism shonku provides -- likely a Python entry point or explicit registration call.

**Provisional assumption**: shonku provides a `shonku.register_agent(AgentClass)` function and an `Agent` base class. This document's agent definitions use this assumed API.

### 14.6 LLM Model Selection

Which LLM model should the sub-agents use? Should it be configurable per agent (e.g., use a cheaper model for analysis, a stronger model for optimization)?

**Recommendation**: Add an optional `model` field to each agent definition. Default to whatever shonku's default model is. Allow per-agent overrides in `AutoResearcherConfig`.

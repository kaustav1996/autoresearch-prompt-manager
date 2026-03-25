# Research: Autoresearch Optimization Loop for Autonomous Prompt Improvement

> Research compiled: 2026-03-25
> Status: Research only -- no code produced

---

## Table of Contents

1. [The Autoresearch Methodology in Detail](#1-the-autoresearch-methodology-in-detail)
2. [LLM-as-Prompt-Engineer Research](#2-llm-as-prompt-engineer-research)
3. [Feedback Signals for Prompt Quality](#3-feedback-signals-for-prompt-quality)
4. [Autonomous Optimization Safety](#4-autonomous-optimization-safety)
5. [Collaborative/Ensemble Optimization](#5-collaborativeensemble-optimization)
6. [Scheduling and Triggering](#6-scheduling-and-triggering)
7. [Synthesis: Recommendations for Our Prompt Manager](#7-synthesis-recommendations-for-our-prompt-manager)

---

## 1. The Autoresearch Methodology in Detail

### 1.1 Background

[Karpathy's autoresearch](https://github.com/karpathy/autoresearch) is a 630-line Python tool released in March 2026 that lets an AI agent autonomously run ML experiments on a single GPU. The agent modifies training code (`train.py`), runs a fixed 5-minute training budget, evaluates the result against a single metric (`val_bpb` -- validation bits per byte), and decides to keep or discard the change. It repeats this loop indefinitely, producing roughly 12 experiments/hour or ~100 overnight.

The repo does **not** ship an agent. It is designed to be used with an external coding agent (Claude, Codex, etc.) that can edit files and run shell commands. The intelligence is in three files:

| File | Role | Mutable? |
|------|------|----------|
| `prepare.py` | Data loading, tokenizer, evaluation function | No -- immutable harness |
| `train.py` | Model architecture, optimizer, training loop | Yes -- the agent's canvas |
| `program.md` | Instructions, constraints, stopping criteria | No -- the "constitution" |

### 1.2 How the Keep/Discard Loop Works in Practice

The loop follows this exact sequence:

1. **Read state**: Agent examines current `train.py`, recent `results.tsv` entries, and its own prior reasoning.
2. **Form hypothesis**: Agent proposes a specific change (architecture tweak, hyperparameter, new technique).
3. **Implement**: Agent directly edits `train.py`.
4. **Run**: Training executes for exactly 5 minutes wall-clock time (excluding startup/compilation). If a run exceeds 10 minutes, it is killed and treated as a failure.
5. **Evaluate**: `grep "^val_bpb:\|^peak_vram_mb:" run.log` extracts the metric.
6. **Log**: Results appended to `results.tsv` as tab-separated: commit hash, val_bpb, memory_gb, status, description.
7. **Decide**:
   - If `val_bpb` improved (lower): **keep** -- the git commit stands, this becomes the new baseline.
   - If `val_bpb` is equal or worse: **discard** -- `git reset` wipes the change instantly.
   - If the run crashed: log as "crash", fix obvious bugs if possible, move on.
8. **Repeat**: Go to step 1. No human approval sought.

The binary nature of this decision is critical: there is no "maybe" state. The metric is the sole arbiter.

### 1.3 Why Fixed Evaluation Budgets Matter

The 5-minute fixed training budget serves several purposes:

- **Comparability**: Every experiment uses the same compute. A change that makes training faster does not get credited for extra training steps -- it gets credited for being a more efficient use of the same wall-clock time.
- **Throughput**: Fixed budgets enable predictable experiment throughput (~12/hour), which is essential for autonomous overnight operation.
- **Prevention of "longer is better" bias**: Without a fixed budget, the optimizer could trivially "improve" the metric by simply training longer. The fixed budget forces genuine algorithmic improvements.
- **Cost containment**: The total compute cost is bounded and predictable.

**Application to prompt optimization**: The equivalent of the fixed budget is a fixed sample size (e.g., 100 metric events per arm) or a fixed time window (e.g., 6 hours of traffic). This ensures that prompt variants are compared on equal footing.

### 1.4 How to Prevent the Optimizer from "Gaming" the Metric

This is Goodhart's Law applied to prompt optimization: "When a measure becomes a target, it ceases to be a good measure."

**Risks specific to prompt optimization**:
- Optimizing for "thumbs up" rate may produce sycophantic, agreeable-but-unhelpful responses.
- Optimizing for "low retry rate" may produce verbose responses that technically answer but are not concise.
- Optimizing for "LLM-as-judge score" may produce responses that game the judge's biases (verbosity bias, position bias).

**Mitigation strategies** (from autoresearch and the broader literature):

| Strategy | How It Works |
|----------|-------------|
| **Immutable evaluation harness** | In autoresearch, `prepare.py` cannot be modified. The optimizer cannot change how it is measured. In prompt optimization, the metric collection code and composite formula must be outside the optimizer's reach. |
| **Composite metrics** | Use a weighted combination of multiple signals (quality + latency + success rate). Gaming one dimension hurts another. |
| **Human audit sampling** | Periodically sample optimizer outputs for human review. Flag large metric jumps for inspection. |
| **Diversity of evaluation** | Use multiple LLM judges with different prompts. A prompt that games one judge is less likely to game all of them. |
| **Behavioral anchoring** | Constrain the optimizer: "The prompt must still address the user's question directly. Do not add filler." |
| **Edit distance bounds** | Limit how much the prompt can change per iteration. Prevents radical rewrites that exploit metric loopholes. |
| **Early stopping** | OpenAI research on RLHF found that optimizing a proxy reward too aggressively (beyond ~10 nats of KL divergence) causes the true objective to decrease. The analog: stop optimization when marginal gains become negligible. |

### 1.5 The Simplicity Criterion

From `program.md`:

> "All else being equal, simpler is better. A small improvement that adds ugly complexity is not worth it."

Applied to prompts:
- Shorter prompts that perform equally are preferred over longer ones.
- Removing unnecessary instructions IS an improvement (even if the metric stays flat).
- Adding 200 words to a prompt for a 0.5% metric gain is probably not worth it.
- The optimizer's meta-prompt should explicitly state: "If you can achieve the same result with fewer words, do so."

This prevents prompt bloat -- a common failure mode where optimizers keep appending instructions, making prompts increasingly unwieldy.

**Implementation**: Add a length penalty to the composite score, or use a lexicographic comparison: first compare metric score (must be at least as good), then prefer shorter prompts.

### 1.6 The "Optimizer Runs Out of Ideas" Problem

From `program.md`:

> "If you feel stuck, think harder, reference prior work, recombine near-misses, try radical changes -- don't exit or seek guidance."

In practice, autonomous optimizers hit plateaus. Strategies:

1. **Ablation mode**: Instead of adding, try removing parts of the prompt. Often reveals that sections are unnecessary.
2. **Radical restructuring**: Completely reorganize the prompt (e.g., switch from instruction-first to example-first format).
3. **Cross-pollination**: If multiple prompts exist in the system, borrow successful patterns from high-performing prompts in other domains.
4. **Temperature increase**: When stuck, use higher LLM temperature for proposals to increase diversity.
5. **Strategy rotation**: Cycle through different optimization strategies (conservative edits, radical rewrites, ablation, synthesis).
6. **Backtracking**: Revert to an earlier version (not the immediate predecessor) and try a different direction. Karpathy's `program.md` allows this but says to do it "very very sparingly."
7. **Graceful stop**: After N consecutive discards with no improvement, pause optimization and wait for new metric data or human input. This is the responsible alternative to generating increasingly desperate proposals.

---

## 2. LLM-as-Prompt-Engineer Research

### 2.1 APE: Automatic Prompt Engineer (Zhou et al., ICLR 2023)

**Paper**: ["Large Language Models Are Human-Level Prompt Engineers"](https://arxiv.org/abs/2211.01910)

**Core idea**: Treat the instruction/prompt as a "program" and search over a pool of candidate instructions proposed by an LLM to maximize a score function.

**How it works**:
1. Generate candidate instructions by prompting an LLM with input-output demonstrations: "What instruction could have produced these outputs from these inputs?"
2. Score each candidate on a held-out validation set.
3. Select the best-performing instruction.
4. Optionally refine via iterative resampling around the best candidate.

**Key results**: On 24 NLP tasks, APE-generated instructions outperformed human-written baselines on 19/24 tasks.

**Relevance to our system**: APE's generate-then-select approach maps directly to our optimization loop. The key insight is that LLMs are surprisingly good at generating diverse prompt candidates when given examples of good and bad outputs.

### 2.2 OPRO: Optimization by PROmpting (Google DeepMind, 2023)

**Paper**: ["Large Language Models as Optimizers"](https://arxiv.org/abs/2309.03409)

**Core idea**: Describe an optimization problem in natural language. In each step, the LLM sees previously generated solutions with their scores and generates new (hopefully better) solutions.

**How it works**:
1. Maintain a "trajectory" of (solution, score) pairs.
2. In each iteration, present the trajectory to the LLM in a meta-prompt.
3. The LLM proposes new solutions informed by what has worked and what hasn't.
4. Evaluate the new solutions, add to trajectory.
5. Repeat.

**Key results**: OPRO-optimized prompts outperformed human-designed prompts by up to 8% on GSM8K and up to 50% on Big-Bench Hard.

**Key design detail**: The trajectory acts as an in-context "memory" of optimization history. Solutions are sorted by score so the LLM can see the trend. This is directly analogous to our `optimization_runs` table -- the optimizer should see prior attempts and their outcomes.

**Relevance**: OPRO's trajectory-based approach should be adopted in our meta-prompt construction. When calling the optimizer LLM, include the last N optimization attempts with their metric results.

### 2.3 DSPy: Programming (Not Prompting) Language Models

**Repo**: [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy)

**Core idea**: Replace hand-written prompts with declarative "signatures" (input/output specs) and let compilers/optimizers automatically generate the actual prompt text, few-shot examples, and chain-of-thought reasoning.

**Key optimizers in DSPy**:

| Optimizer | Strategy |
|-----------|----------|
| **BootstrapFewShot** | Uses a teacher model to generate demonstrations. Validates them against a metric. Selects the best few-shot examples. |
| **MIPROv2** | Previews program code, data, and traces. Drafts many candidate instructions. Launches a Bayesian search over instruction + demonstration combinations. |
| **GEPA** | Reflects on program trajectories to identify what worked and what didn't. Proposes new prompts addressing gaps. Can leverage domain-specific textual feedback. |

**Key insight for our system**: DSPy's optimizers work because they have a clear feedback loop: metric -> propose -> evaluate -> select. The sophistication is in *how* proposals are generated (trajectory analysis, contrastive learning, Bayesian search), not in the loop structure itself. Our system should support pluggable optimization strategies.

**Model portability**: DSPy enables seamless model switching -- transitioning from GPT-4o to Llama requires only changing configuration and re-running optimization, not re-engineering prompts. This validates our multi-provider LLM abstraction.

### 2.4 PromptBreeder: Self-Referential Self-Improvement (Google DeepMind, 2023)

**Paper**: ["Promptbreeder: Self-Referential Self-Improvement Via Prompt Evolution"](https://arxiv.org/abs/2309.16797)

**Core idea**: Evolve a population of task-prompts using mutation operators, where the mutation operators themselves are also evolved. This is a two-level evolutionary system.

**How it works**:
1. Maintain a population of (task-prompt, mutation-prompt) pairs.
2. Use the mutation-prompt to mutate the task-prompt via the LLM.
3. Evaluate fitness on a training set.
4. Select the fittest pairs for the next generation.
5. Crucially: the mutation-prompts also evolve -- the system improves how it improves.

**Mutation operators**:
- **Direct mutation**: "Improve this prompt: [prompt]"
- **Estimation of Distribution (EDA)**: Generate a new prompt that captures the essence of the top-K prompts.
- **Hypermutation**: Mutate the mutation-prompt itself.
- **Lamarckian mutation**: Use a working-out from a task to improve the prompt.
- **Prompt crossover**: Combine elements from two prompts.

**Key result**: Outperformed Chain-of-Thought and Plan-and-Solve on arithmetic and commonsense reasoning benchmarks. The unintuitive prompt "SOLUTION" achieved 83.9% on a math benchmark in the zero-shot setting.

**Relevance**: PromptBreeder's population-based approach is a strong candidate for our ensemble optimization mode. Instead of a single optimizer proposing one change, maintain a population of prompt variants and evolve them. The self-referential aspect (evolving the meta-prompt) is ambitious but powerful for long-running optimization.

### 2.5 EvoPrompt: Evolutionary Algorithms for Prompt Optimization (ICLR 2024)

**Paper**: ["Connecting Large Language Models with Evolutionary Algorithms Yields Powerful Prompt Optimizers"](https://arxiv.org/abs/2309.08532)

**Core idea**: Apply classical evolutionary algorithms (Genetic Algorithm, Differential Evolution) to prompt optimization, using the LLM as the mutation/crossover operator.

**How it works**:
1. **Initialize**: Create a population of prompts (manually or LLM-generated).
2. **Evolve**: Apply EA operators (mutation, crossover) using LLM-powered templates.
3. **Evaluate**: Score each prompt on a dev set.
4. **Select**: GA keeps top-N; DE replaces old prompts if new ones are better.

**Key result**: Up to 25% improvement over human-engineered prompts on Big-Bench Hard.

**Two algorithm variants**:
- **GA (Genetic Algorithm)**: Maintains top-N prompts per generation. Crossover combines two parent prompts. Mutation introduces random variation.
- **DE (Differential Evolution)**: Uses the *difference* between two prompts to mutate a third. More targeted than GA.

**Relevance**: EvoPrompt's use of classical EA frameworks is cleaner than PromptBreeder and easier to implement. The DE approach is particularly interesting for production use -- it generates more focused mutations based on what distinguishes good prompts from bad ones.

### 2.6 TextGrad: Automatic Differentiation via Text (Stanford, Nature 2024)

**Paper**: ["TextGrad: Automatic 'Differentiation' via Text"](https://arxiv.org/abs/2406.07496)

**Core idea**: Backpropagate textual feedback (not numerical gradients) through compound AI systems. An LLM provides natural-language "gradients" -- critiques of what went wrong -- which are used to update prompts and other text-based components.

**How it works**:
1. Run the system on a test case.
2. Compute a "loss" (natural language critique from an LLM).
3. "Backpropagate" by asking the LLM: "Given this critique, how should the prompt be modified?"
4. Update the prompt based on the textual gradient.

**Key results**: Improved GPT-4o zero-shot accuracy on question answering from 51% to 55%. 20% relative gain on LeetCode-Hard solutions.

**Relevance**: TextGrad's approach of using natural-language feedback as the optimization signal aligns with our LLM-as-judge strategy. The "textual gradient" concept -- telling the optimizer *why* something failed, not just *that* it failed -- is a powerful pattern for our meta-prompt.

### 2.7 Meta-Prompt Patterns That Work

Research and practice converge on several effective meta-prompt patterns for instructing an LLM to improve a prompt:

**Pattern 1: Contrastive Analysis**
> "Here is the current prompt and examples of its outputs. Some outputs are good (scored > 0.8) and some are bad (scored < 0.5). Analyze what the prompt does well and where it falls short. Propose a revised prompt that addresses the weaknesses while preserving the strengths."

**Pattern 2: Trajectory-Informed (OPRO-style)**
> "Here are the last 5 optimization attempts and their metric scores: [list]. Notice the trend. Based on what worked and what didn't, propose a new version."

**Pattern 3: Ablation Request**
> "This prompt has N sections. Which sections are essential and which might be unnecessary? Propose a simplified version that removes non-essential parts."

**Pattern 4: Role-Based**
> "You are an expert prompt engineer. Your goal is to maximize [metric] while keeping the prompt concise. The current prompt scores [X]. Analyze it and propose improvements."

**Pattern 5: Constraint-Explicit**
> "Improve this prompt. Constraints: (1) Must preserve template variables {name}, {context}. (2) Must be shorter than the original. (3) Must maintain the same tone. (4) Do not add examples unless they clearly improve the metric."

The most effective approach combines these: provide the trajectory (OPRO), contrastive examples (good/bad outputs), explicit constraints, and the simplicity criterion.

---

## 3. Feedback Signals for Prompt Quality

### 3.1 Explicit Signals

| Signal | Description | Strengths | Weaknesses |
|--------|-------------|-----------|------------|
| Thumbs up/down | Binary user feedback | Clear, unambiguous | Very sparse (< 1% of interactions) |
| 1-5 star rating | Granular user feedback | More information per signal | Requires UI, still sparse |
| Text feedback | "This was wrong because..." | Rich signal | Hard to aggregate, very rare |
| Correction/edit | User corrects the output | Shows exactly what was wrong | Requires specialized UI |

**Key insight from research**: Explicit feedback is the gold standard but is extremely rare -- less than 1% of interactions yield direct feedback. Systems must not depend solely on explicit signals.

### 3.2 Implicit Signals

| Signal | Description | What It Indicates |
|--------|-------------|-------------------|
| Retry rate | User re-asks the same question | Dissatisfaction (high retry = bad) |
| Response length | Tokens in the LLM response | May indicate verbosity issues |
| Latency | Time to first token / total time | User experience quality |
| Session continuation | User keeps conversing | Engagement (continued = good) |
| Copy/paste rate | User copies the response | Usefulness (copied = good) |
| Task completion | User achieves their goal | Ultimate success metric |
| Abandonment rate | User leaves mid-conversation | Frustration (abandoned = bad) |

**Key insight**: Prolonged engagement (users continue to converse and don't quit) can serve as a proxy for satisfaction, per research on dialogue systems. However, this must be calibrated -- a user who keeps retrying is NOT engaged, they're frustrated.

### 3.3 LLM-as-Judge

Using another LLM to evaluate output quality. This is increasingly the standard approach for automated evaluation.

**Best practices from 2024-2025 research**:

1. **Ask for reasoning first, then score**: Forcing the LLM to explain its rating significantly improves alignment with human judgments. Do not ask for just a number.

2. **Use specific rubrics**: Vague criteria like "Is this good?" produce inconsistent scores. Provide detailed rubrics: "Score relevance (1-5) based on: Does the response address the user's specific question? Does it include relevant details?"

3. **Mitigate known biases**:
   - **Position bias**: LLM judges favor responses presented first. Randomize order.
   - **Verbosity bias**: Longer responses tend to score higher regardless of quality. Normalize for length.
   - **Self-enhancement bias**: GPT-4 rates GPT-4 outputs higher. Use a different model family as judge.
   - **Bandwagon bias**: If told "most people prefer A", the judge agrees. Don't include popularity signals.

4. **Ensemble judges**: Use multiple judge LLMs or multiple judge prompts and aggregate scores. Amazon's CollabEval framework uses a three-phase process: initial evaluation, multi-round discussion among agents, and final judgment with strategic consensus checking.

5. **Calibrate against human labels**: Even GPT-4-class judges achieve < 0.7 accuracy on alignment datasets. Always calibrate against a set of human-labeled examples.

6. **Adversarial robustness**: LLM judges are highly sensitive to adversarial attacks. An optimizer that knows the judge's prompt can game it. Keep judge prompts separate from the optimizer and rotate them.

### 3.4 Composite Metrics

Combining multiple signals into a single optimization target:

```
composite_score = (
    w_quality * normalize(quality_signal) +
    w_latency * normalize(1 / latency_ms) +
    w_success * normalize(success_rate) +
    w_brevity * normalize(1 / response_length) +
    w_retry   * normalize(1 / retry_rate)
)
```

**Design considerations**:

- **Normalization**: Each signal must be normalized to [0, 1] before weighting. Use min-max normalization with rolling windows (last 7 days) to handle distribution shifts.
- **Weight selection**: Start with equal weights, then adjust based on business priorities. Quality should usually dominate (0.5-0.7 weight).
- **Pareto optimality**: An improvement is only "real" if it improves at least one dimension without degrading any other significantly.
- **Confidence intervals**: Don't trust scores from small sample sizes. Require minimum N samples per arm before comparing.

### 3.5 Avoiding Goodhart's Law (Metric Gaming)

The fundamental risk: "When a measure becomes a target, it ceases to be a good measure."

**Concrete examples in prompt optimization**:
- Optimizing for "user satisfaction rating" produces sycophantic prompts that agree with everything.
- Optimizing for "low latency" produces prompts that generate short, unhelpful responses.
- Optimizing for "LLM-as-judge quality score" produces prompts that exploit the judge's verbosity bias.
- Optimizing for "task completion rate" produces prompts that define "completion" too loosely.

**Defenses**:

| Defense | Description |
|---------|-------------|
| **Multi-dimensional metrics** | Optimize a composite of 3-5 signals. Gaming one hurts another. |
| **Metric rotation** | Periodically change the exact judge prompt or weight distribution. |
| **Human audit** | Sample 5-10% of optimizer outputs for human review. Kill the loop if quality diverges from metric. |
| **Behavioral constraints** | Hard constraints in the meta-prompt: "The response must directly address the user's question." |
| **Diminishing returns threshold** | Stop optimizing when improvement per iteration drops below epsilon. OpenAI found ~10 nats of KL divergence is the practical limit before Goodhart effects dominate. |
| **Hold-out test set** | Evaluate on a separate set that the optimizer never sees metrics from. If hold-out performance diverges from optimization set, gaming is occurring. |

---

## 4. Autonomous Optimization Safety

### 4.1 Preventing Catastrophic Prompt Drift

Over many iterations, an autonomous optimizer can drift the prompt far from its original intent. A prompt that started as "Summarize this article in 3 bullet points" might drift to something unrecognizable after 50 optimization cycles.

**Mitigation strategies**:

1. **Semantic similarity bounds**: Compute embedding similarity between the current prompt and the original (version 1). If similarity drops below a threshold (e.g., cosine similarity < 0.7), halt optimization and require human review.

2. **Maximum edit distance per iteration**: Limit each optimization step to change at most X% of the prompt text (e.g., Levenshtein distance / prompt_length < 0.3). Prevents radical rewrites in a single step.

3. **Cumulative drift tracking**: Track total edit distance from version 1 across all iterations. Alert when cumulative drift exceeds a threshold.

4. **Intent anchoring**: Require the optimizer to preserve a set of "anchor phrases" or structural elements that define the prompt's core intent.

5. **Periodic regression testing**: Every N iterations, re-evaluate the current prompt against the original test cases (not just recent traffic). Ensures the prompt hasn't lost capabilities it originally had.

### 4.2 Rollback Mechanisms

The version history should support:

- **Immediate rollback**: Revert to the previous version (N-1). Equivalent to autoresearch's `git reset`.
- **Historical rollback**: Revert to any previous version. Useful when drift is detected late.
- **Automatic rollback triggers**:
  - Composite score drops below a threshold for more than M minutes.
  - Error rate exceeds X%.
  - Any single metric dimension degrades by more than Y%.
- **Rollback creates a new version**: Following our immutable versioning principle, a rollback creates version N+1 with the content of version K, preserving full audit trail.

### 4.3 Template Variable Preservation

A critical safety constraint: optimized prompts must preserve all template variables (e.g., `{name}`, `{context}`, `{{user_query}}`).

**Implementation**:
1. Before accepting an optimized prompt, extract all template variables from the original.
2. Verify every original variable appears in the proposed prompt.
3. Reject proposals that add new undefined variables or remove existing ones.
4. This check is a hard gate -- no override, even in fully autonomous mode.

### 4.4 Rate Limiting Optimization Runs

| Parameter | Recommended Default | Rationale |
|-----------|-------------------|-----------|
| Max runs per prompt per day | 24 | ~1 per hour, prevents runaway loops |
| Max runs per prompt per week | 100 | Budget ceiling |
| Min time between runs | 30 minutes | Allow metrics to accumulate |
| Min metric events per arm | 100 | Statistical significance |
| Max concurrent experiments | 1 per prompt | Avoid interference |
| Cool-down after N consecutive discards | 3 discards -> 2x cool-down period | Prevent thrashing when stuck |

### 4.5 Human Review Gates vs Fully Autonomous

Three operational modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Manual** | Optimizer proposes, human reviews and approves | High-stakes prompts (customer-facing, legal, medical) |
| **Semi-autonomous** | Auto-deploy if improvement > threshold AND edit distance < bound; else require human review | Most production prompts |
| **Fully autonomous** | Keep/discard loop runs without human intervention | Internal prompts, development, low-risk use cases |

**Recommendation**: Default to semi-autonomous. Fully autonomous should require explicit opt-in per prompt and should still have hard safety bounds (edit distance, semantic similarity, template variable preservation).

---

## 5. Collaborative/Ensemble Optimization

### 5.1 Multi-LLM Proposal Generation

Instead of a single optimizer LLM, use multiple LLMs to generate diverse proposals:

```
Proposals = parallel(
    claude-sonnet -> conservative_edit(prompt, metrics),
    gpt-4o -> radical_restructure(prompt, metrics),
    claude-opus -> ablation_analysis(prompt, metrics),
)
```

**Benefits**:
- **Diversity**: Different LLMs have different "priors" about what makes a good prompt. This explores the search space more broadly.
- **Robustness**: If one LLM's suggestions consistently underperform, the ensemble still has other sources.
- **Strategy diversity**: Each LLM can be given a different optimization strategy (conservative, radical, ablative).

### 5.2 LLM-as-Judge for Proposal Selection

Before expensive shadow testing, use an LLM judge to pre-filter proposals:

1. Generate N proposals from M models.
2. LLM judge evaluates each proposal on: coherence, adherence to constraints, likely improvement over baseline.
3. Top K proposals advance to shadow testing.
4. Shadow test results determine the final keep/discard decision.

This reduces the cost of shadow testing (which requires real traffic) by filtering out obviously bad proposals early.

**Amazon's CollabEval pattern**: Multiple judge agents evaluate proposals, discuss disagreements in multi-round deliberation, and reach consensus. This is more expensive but more robust than a single judge.

### 5.3 Evolutionary Approaches

Drawing from PromptBreeder and EvoPrompt:

**Population-Based Prompt Optimization**:

1. **Initialize**: Population of K prompt variants (current best + K-1 mutations).
2. **Evaluate**: Each variant gets a fraction of traffic. Collect metrics.
3. **Select**: Top 50% survive to next generation.
4. **Reproduce**:
   - **Mutation**: LLM modifies a surviving prompt.
   - **Crossover**: LLM combines elements from two surviving prompts.
5. **Repeat** for G generations.

**Crossover operator** (adapted from EvoPrompt's DE approach):
> "Here are two high-performing prompts (A and B) and one lower-performing prompt (C). Create a new prompt that takes the best elements of A and B while avoiding the weaknesses of C."

**When to use evolutionary approaches**:
- When the search space is large (many possible prompt structures).
- When you have enough traffic to support a population of variants.
- When single-point optimization has plateaued.

**When NOT to use**:
- Low-traffic prompts (not enough signal for a population).
- When the prompt is already near-optimal and only marginal gains are possible.
- When prompt constraints are very tight (few valid mutations exist).

### 5.4 Self-Referential Improvement

From PromptBreeder: evolving not just the task prompt, but also the meta-prompt that instructs the optimizer. This is a second-order optimization.

**Practical implementation**:
- Track which meta-prompt strategies produce the most "keeps" vs "discards".
- Over time, weight the system toward strategies that produce more improvements.
- This is the prompt optimization equivalent of "learning to learn."

**Caution**: Self-referential systems can be unstable. Changes to the meta-prompt affect all future optimization, amplifying errors. This should be a Phase 2 feature with careful monitoring.

---

## 6. Scheduling and Triggering

### 6.1 Continuous vs Scheduled Optimization

| Mode | Description | Pros | Cons |
|------|-------------|------|------|
| **Continuous** | Loop runs whenever sufficient new metrics arrive | Fastest convergence, always adapting | Higher compute cost, risk of thrashing |
| **Scheduled (cron)** | Run optimization at fixed intervals (e.g., every 6 hours) | Predictable cost, easy to monitor | May miss rapid quality drops |
| **Event-driven** | Triggered by specific events | Responsive, targeted | Requires event infrastructure |
| **Hybrid** | Scheduled baseline + event-driven overrides | Best of both worlds | Most complex to implement |

**Recommendation**: Start with scheduled (every 6-12 hours) with event-driven overrides. Continuous mode is for high-traffic prompts after the system is proven stable.

### 6.2 Metric Threshold Triggers

Trigger optimization when quality drops:

```yaml
triggers:
  - type: metric_threshold
    metric: composite_score
    condition: "< 0.7"           # Below quality floor
    window: "1h"                 # Over the last hour
    min_events: 50               # With at least 50 data points
    action: optimize

  - type: metric_delta
    metric: composite_score
    condition: "delta < -0.1"    # 10% drop from 24h average
    window: "1h"
    action: optimize_and_alert

  - type: error_rate
    condition: "> 0.05"          # More than 5% errors
    window: "30m"
    action: rollback_and_alert
```

### 6.3 Event-Driven Triggers

| Event | Trigger Action |
|-------|---------------|
| New prompt version deployed manually | Run evaluation against previous version |
| Model provider updated (e.g., GPT-4 -> GPT-4.5) | Re-optimize all prompts for new model |
| Traffic pattern change (volume spike or new user segment) | Re-evaluate metrics, potentially optimize |
| Upstream dependency change | Re-run regression tests |
| Metric anomaly detected | Alert + possible automatic optimization |

### 6.4 Budget Management

```yaml
budget:
  max_optimization_runs_per_day: 24
  max_optimization_runs_per_week: 100
  max_llm_cost_per_day_usd: 10.00
  max_llm_cost_per_week_usd: 50.00

  # Per-prompt limits
  per_prompt:
    max_runs_per_day: 6
    min_interval_minutes: 60
    max_consecutive_discards: 5   # Pause after 5 failures
    cool_down_after_discards: 360 # 6 hour cool-down
```

**Cost tracking**: Each optimization run should log its LLM token usage and cost. The budget manager should refuse to start new runs when limits are exceeded.

---

## 7. Synthesis: Recommendations for Our Prompt Manager

### 7.1 Phase 1: Core Loop (Minimum Viable Optimization)

Implement the autoresearch pattern directly:
- Single optimizer LLM proposes improvements.
- OPRO-style trajectory in the meta-prompt (show last N attempts and their results).
- Fixed sample size evaluation (min 100 events per arm).
- Binary keep/discard based on composite metric.
- Simplicity criterion (prefer shorter prompts at equal performance).
- Template variable preservation (hard gate).
- Scheduled mode (cron-based, every 6-12 hours).

### 7.2 Phase 2: Safety and Monitoring

- Semantic similarity bounds (cosine similarity > 0.7 from original).
- Edit distance limits per iteration (< 30% change).
- Automatic rollback on regression.
- Human review gate for large changes.
- Budget management and rate limiting.
- Hold-out evaluation set for Goodhart detection.

### 7.3 Phase 3: Ensemble and Evolution

- Multi-LLM proposal generation (diversity).
- LLM-as-judge pre-filtering before shadow testing.
- EvoPrompt-style evolutionary operators (mutation + crossover).
- Population-based optimization for high-traffic prompts.
- Strategy rotation (conservative, radical, ablation).

### 7.4 Phase 4: Self-Improvement

- Meta-prompt optimization (learn which strategies produce more keeps).
- Adaptive scheduling (optimize more frequently for high-traffic prompts).
- Cross-prompt learning (borrow patterns from successful optimizations).
- Self-referential improvement a la PromptBreeder (evolve the optimizer's own instructions).

### 7.5 Key Architecture Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Meta-prompt structure | OPRO trajectory + contrastive examples + explicit constraints | Best convergence from research |
| Default optimization strategy | Conservative single-point (not evolutionary) | Simpler, sufficient for most cases |
| Default evaluation | Composite metric (quality 0.6, latency 0.2, success 0.2) | Balanced, harder to game |
| Default mode | Semi-autonomous | Safe default, explicit opt-in for full autonomy |
| Default schedule | Every 6 hours | Balances responsiveness and cost |
| Minimum sample size | 100 events per arm | Statistical significance at p < 0.05 for moderate effect sizes |
| Maximum traffic for new variant | 10% | Limits blast radius of bad prompts |

---

## Sources

### Primary References
- [Karpathy autoresearch (GitHub)](https://github.com/karpathy/autoresearch)
- [Karpathy autoresearch program.md](https://github.com/karpathy/autoresearch/blob/master/program.md)
- [Andrej Karpathy's 630-line Python script ran 50 experiments overnight (The New Stack)](https://thenewstack.io/karpathy-autonomous-experiment-loop/)
- [Karpathy's Autoresearch for PMs: Complete Guide](https://www.news.aakashg.com/p/autoresearch-guide-for-pms)
- [autoresearch: Karpathy's Blueprint for Agents That Improve Themselves](https://www.mager.co/blog/2026-03-14-autoresearch-pattern/)
- [Scaling Karpathy's Autoresearch (SkyPilot Blog)](https://blog.skypilot.co/scaling-autoresearch/)

### Academic Papers
- [APE: Large Language Models Are Human-Level Prompt Engineers (Zhou et al., ICLR 2023)](https://arxiv.org/abs/2211.01910)
- [OPRO: Large Language Models as Optimizers (Yang et al., 2023)](https://arxiv.org/abs/2309.03409)
- [PromptBreeder: Self-Referential Self-Improvement Via Prompt Evolution (2023)](https://arxiv.org/abs/2309.16797)
- [EvoPrompt: Connecting LLMs with Evolutionary Algorithms (ICLR 2024)](https://arxiv.org/abs/2309.08532)
- [TextGrad: Automatic Differentiation via Text (Nature, 2024)](https://arxiv.org/abs/2406.07496)
- [Goodhart's Law in Reinforcement Learning (ICLR 2024)](https://openreview.net/forum?id=5o9G4XF1LI)
- [A Survey on LLM-as-a-Judge (2024)](https://arxiv.org/html/2411.15594v6)
- [Prompt Optimization with Human Feedback (2024)](https://arxiv.org/html/2405.17346v1)
- [Auto-Prompt Ensemble for LLM Judge (2025)](https://arxiv.org/abs/2510.06538)

### Frameworks and Tools
- [DSPy: Programming Language Models (Stanford NLP)](https://github.com/stanfordnlp/dspy)
- [DSPy Optimizers Documentation](https://dspy.ai/learn/optimization/optimizers/)
- [OPRO Official Implementation (Google DeepMind)](https://github.com/google-deepmind/opro)
- [TextGrad Framework](https://github.com/zou-group/textgrad)
- [EvoPrompt Official Implementation](https://github.com/beeevita/EvoPrompt)

### LLM-as-Judge and Evaluation
- [LLM-as-a-judge: Complete Guide (Evidently AI)](https://www.evidentlyai.com/llm-guide/llm-as-a-judge)
- [LLM-As-Judge: 7 Best Practices (Monte Carlo Data)](https://www.montecarlodata.com/blog-llm-as-judge/)
- [LLM-as-a-Judge (Langfuse)](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge)
- [LLM-as-a-Judge (Arize)](https://arize.com/llm-as-a-judge/)

### Meta-Prompting and Prompt Engineering
- [Meta-Prompting: LLMs Crafting Their Own Prompts (IntuitionLabs)](https://intuitionlabs.ai/articles/meta-prompting-llm-self-optimization)
- [Enhance Your Prompts with Meta Prompting (OpenAI Cookbook)](https://cookbook.openai.com/examples/enhance_your_prompts_with_meta_prompting)
- [Meta Prompting (Prompt Engineering Guide)](https://www.promptingguide.ai/techniques/meta-prompting)
- [Exploring Prompt Optimization (LangChain Blog)](https://blog.langchain.com/exploring-prompt-optimization/)

### Deployment and Safety
- [LLM Canary Prompting in Production: Shadow Tests, Drift Alarms, and Safe Rollouts](https://medium.com/@komalbaparmar007/llm-canary-prompting-in-production-shadow-tests-drift-alarms-and-safe-rollouts-7bdbd0e5f9d0)
- [When Prompt Deployment Goes Wrong: MLOps Lessons from ChatGPT's Sycophantic Rollback](https://leehanchung.github.io/blogs/2025/04/30/ai-ml-llm-llm-ops/)
- [A/B Testing Prompts: Complete Guide (DEV Community)](https://dev.to/kuldeep_paul/ab-testing-prompts-a-complete-guide-to-optimizing-llm-performance-1442)
- [Measuring Goodhart's Law (OpenAI)](https://openai.com/index/measuring-goodharts-law/)
- [GUARDRAILS.md Safety Protocol](https://guardrails.md/)
- [Safely Deploying ML Models: Four Controlled Strategies (MarkTechPost)](https://www.marktechpost.com/2026/03/21/safely-deploying-ml-models-to-production-four-controlled-strategies-a-b-canary-interleaved-shadow-testing/)

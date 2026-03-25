# Experiment / A/B Testing Engine — Research Document

## Table of Contents

1. [A/B Testing Frameworks and Their Algorithms](#1-ab-testing-frameworks-and-their-algorithms)
2. [Multi-Armed Bandit Algorithms for Prompt Selection](#2-multi-armed-bandit-algorithms-for-prompt-selection)
3. [Statistical Significance for Prompt Experiments](#3-statistical-significance-for-prompt-experiments)
4. [The Autoresearch Pattern Applied to Prompts](#4-the-autoresearch-pattern-applied-to-prompts)
5. [Sticky Sessions and Routing](#5-sticky-sessions-and-routing)
6. [Edge Cases](#6-edge-cases)
7. [Recommendations for This Project](#7-recommendations-for-this-project)

---

## 1. A/B Testing Frameworks and Their Algorithms

### 1.1 GrowthBook — Experiment Assignment

GrowthBook uses **deterministic hashing** for experiment assignment. The core idea: given a user identifier and an experiment key, a hash function produces a float in [0, 1), which maps to an experiment bucket.

**How it works:**

1. Concatenate: `hash_input = user_id + experiment_key`
2. Hash with FNV-32a (fast, well-distributed) or MurmurHash3
3. Convert hash to a float in [0, 1): `n = (hash_value % 10000) / 10000`
4. Walk through bucket ranges to find assignment:
   - Control: [0.0, 0.5)
   - Variant A: [0.5, 1.0)

**Key properties:**
- **Deterministic**: Same user + same experiment always gets the same variant. No database lookup needed.
- **Stateless**: No session_assignments table. The hash IS the assignment.
- **Cross-platform consistent**: Any client (Python, JS, Go) with the same hash algorithm produces the same result.
- **Namespace isolation**: GrowthBook uses "namespaces" — subdivisions of the [0, 1) range — to prevent cross-experiment interference. If experiment A uses [0.0, 0.5) and experiment B uses [0.5, 1.0), no user is in both.

**GrowthBook's assignment pseudocode:**

```
function getAssignment(userId, experimentKey, weights, namespace?):
    if namespace:
        n = hash(userId + "__" + namespace.id) % 1.0
        if n < namespace.start or n >= namespace.end:
            return null  # User not in this namespace range

    n = hash(userId + experimentKey) % 1.0

    cumulative = 0
    for i, weight in enumerate(weights):
        cumulative += weight
        if n < cumulative:
            return i

    return len(weights) - 1  # Fallback
```

**Relevance to prompt manager:** Our current design uses `random.uniform()` + stored `session_assignments`. GrowthBook's approach eliminates the storage requirement entirely for the assignment step. The trade-off: you cannot retroactively look up "which variant did session X see?" without replaying the hash. Our `session_assignments` table gives us that auditability, which matters for metric attribution.

### 1.2 Optimizely — Traffic Allocation

Optimizely uses a two-layer allocation model:

**Layer 1: Traffic Allocation (who enters the experiment)**
- A "traffic allocation" percentage determines what fraction of all users even participate. Example: 20% of users enter the experiment, 80% get the default.
- This is distinct from variant weights within the experiment.

**Layer 2: Variant Distribution (among participants)**
- Among the users who enter, weights determine which variant they see.
- Example: 50/50 split among two variants.

**Combined effect:** If traffic allocation is 20% and variant split is 50/50, each variant gets 10% of total traffic.

**Optimizely's bucketing algorithm:**
1. Hash `userId + experimentId` using MurmurHash3
2. Map to bucket number 0-9999 (10,000 buckets)
3. Check if bucket falls within experiment's traffic allocation range
4. If yes, map within-experiment bucket to variant

**Mutual exclusion groups:** Optimizely supports "mutual exclusion groups" where experiments share a traffic pool. If experiment A takes buckets 0-4999 and experiment B takes 5000-9999, they are guaranteed non-overlapping. This prevents a user from being in two experiments simultaneously.

**Relevance to prompt manager:** Our current schema has a partial unique index ensuring one running experiment per prompt. This is simpler than Optimizely's model but means we cannot run concurrent experiments on the same prompt. For phase 1 this is fine. For later phases, Optimizely's namespace/layer model is the pattern to follow.

### 1.3 LaunchDarkly — Percentage Rollouts

LaunchDarkly's percentage rollouts use a similar deterministic hashing approach but with an important addition: **gradual rollouts with consistent assignment**.

**How it works:**
1. Hash `contextKey + flagKey + salt` using SHA-1 (first 15 hex chars, converted to int, modulo 100000)
2. Result is a bucket number 0-99999
3. Rollout rules specify percentage thresholds: if bucket < threshold, user gets the new variant

**Progressive rollout pattern:**
```
Day 1:  threshold = 5000   (5% of traffic)
Day 3:  threshold = 20000  (20% of traffic)
Day 7:  threshold = 50000  (50% of traffic)
Day 14: threshold = 100000 (100% of traffic)
```

**Critical property:** Because assignment is hash-based, the users in the 5% group are a strict subset of the 20% group, which is a strict subset of the 50% group. Users never "switch sides" during a rollout increase. This is essential for canary deployments.

**LaunchDarkly also supports:**
- **Targeting rules**: Override assignment for specific users/segments
- **Prerequisites**: Flag A must be on before flag B activates
- **Experimentation on top of rollouts**: Measure impact at each rollout stage

**Relevance to prompt manager:** This is directly applicable to our canary deployment pattern (5% -> 20% -> 50% -> 100%). Using deterministic hashing means we can increase traffic to a new prompt version without disrupting existing users' assignments. Our current `random.uniform()` approach does NOT have this property — a user at 5% might get variant A, then at 20% might get the control. Switching to hash-based routing fixes this.

### 1.4 Deterministic Hashing vs. Random Assignment

| Property | Deterministic Hash | Random + Store |
|---|---|---|
| **Consistency** | Guaranteed by math | Guaranteed by database |
| **Storage** | None for assignment | Row per (session, experiment) |
| **Cross-platform** | Yes (same hash = same result) | Need shared DB |
| **Retroactive audit** | Replay hash | Query table |
| **Performance** | O(1) CPU, no I/O | O(1) DB lookup (indexed) |
| **Flexibility** | Cannot override individual users easily | Can update/delete rows |
| **Rollout consistency** | Users never switch sides | Existing rows preserved, new rolls are random |

**Recommended hash functions:**
- **MurmurHash3**: Fast, excellent distribution. Used by Optimizely, GrowthBook.
- **FNV-32a**: Simpler, slightly worse distribution, but adequate.
- **SHA-1/SHA-256**: Cryptographic strength unnecessary, slower, but universally available. LaunchDarkly uses SHA-1.

**For this project, the hybrid approach is best:**
- Use deterministic hashing (MurmurHash3 or SHA-256 truncated) as the primary assignment mechanism
- Store the assignment in `session_assignments` for auditability and metric attribution
- The hash determines the assignment; the table records it

---

## 2. Multi-Armed Bandit Algorithms for Prompt Selection

### 2.1 Thompson Sampling

**How it works:**
1. Model each arm's reward as a Beta distribution: `Beta(alpha, beta)` where alpha = successes + 1, beta = failures + 1
2. For each request, sample a random value from each arm's distribution
3. Route to the arm with the highest sampled value
4. Update that arm's alpha/beta based on the observed reward

**For continuous metrics (not just 0/1):**
Use a Normal-Inverse-Gamma distribution, or discretize the metric into success/failure using a threshold (e.g., quality_score > 0.7 = success).

**Advantages:**
- Naturally balances exploration and exploitation
- Adapts faster than fixed A/B tests — allocates more traffic to winning variants automatically
- Mathematically principled (Bayesian)
- Simple to implement (Beta distribution sampling is trivial)

**Disadvantages:**
- Non-deterministic: same user can get different variants on different requests (unless combined with hashing for the sampling seed)
- Harder to explain to stakeholders ("why is variant B getting 73.2% of traffic?")
- Requires per-request sampling (though this is fast)

**Implementation sketch:**
```
For each arm i:
    sample_i = random.betavariate(alpha_i, beta_i)
selected_arm = argmax(sample_i for all i)

# After observing reward:
if reward:
    alpha_selected += 1
else:
    beta_selected += 1
```

**When to use for prompts:** When you have many prompt variants (3+) and want to converge on the best one quickly without wasting traffic on clearly inferior variants. Best for high-traffic scenarios where you can afford the statistical complexity.

### 2.2 Epsilon-Greedy

**How it works:**
1. With probability epsilon, choose a random arm (explore)
2. With probability 1 - epsilon, choose the arm with the highest observed mean reward (exploit)

**Tuning epsilon:**
- `epsilon = 0.1` (10% exploration): Good default. Converges reasonably fast.
- `epsilon = 0.05` (5%): More conservative. Better when you are fairly confident in the current best.
- **Decaying epsilon**: Start at 0.2, decay to 0.01 over time. `epsilon = max(0.01, 0.2 * decay_factor^t)`. This is usually the best approach — explore heavily early, exploit later.

**Advantages:**
- Simplest to implement and understand
- Easy to explain: "90% of traffic goes to the best variant, 10% tries alternatives"
- Tunable with a single parameter

**Disadvantages:**
- Explores uniformly across all non-best arms, even clearly bad ones
- Does not account for uncertainty (a new arm with 1 observation is treated the same as one with 1000)
- Fixed epsilon wastes exploration budget on well-established experiments

**When to use for prompts:** Good starting point for prompt A/B testing. When you have 2-3 variants and moderate traffic. The simplicity is a major advantage for an initial implementation.

### 2.3 UCB (Upper Confidence Bound)

**How it works:**
1. For each arm, compute: `UCB_i = mean_reward_i + c * sqrt(ln(total_pulls) / pulls_i)`
2. Select the arm with the highest UCB value
3. The second term is the "exploration bonus" — arms with fewer observations get a larger bonus

**The parameter `c`:**
- `c = 1.0`: Standard UCB1 — theoretical guarantees
- `c = 2.0`: More exploration
- `c = 0.5`: More exploitation
- Typical range: 0.5 to 2.0

**Advantages:**
- Deterministic (no randomness in selection, given the same state)
- Theoretically optimal regret bounds (UCB1)
- Naturally explores under-sampled arms
- No tuning required for UCB1 (c is fixed at sqrt(2))

**Disadvantages:**
- Does not handle non-stationary rewards well (prompt quality might change as user behavior shifts)
- Can be slow to converge with many arms
- The exploration bonus can keep pulling clearly bad arms for too long

**When to use for prompts:** When you want a principled, deterministic algorithm and your metric is relatively stable. Good when you need reproducibility (same state -> same decision).

### 2.4 Bayesian Optimization

**For continuous prompt parameter tuning:**

Bayesian optimization is different from the above — it is for optimizing *continuous* parameters, not selecting among discrete arms. In the prompt context, this means tuning:
- Temperature
- Max tokens
- System prompt length
- Weight of different prompt components

**How it works:**
1. Define a search space (e.g., temperature in [0.0, 1.5])
2. Build a surrogate model (Gaussian Process) of the objective function
3. Use an acquisition function (Expected Improvement, UCB) to select the next point to evaluate
4. Evaluate the point (run the prompt with those parameters, collect metrics)
5. Update the surrogate model
6. Repeat

**Advantages:**
- Sample-efficient (finds good parameters in few evaluations)
- Handles continuous parameter spaces naturally
- Can optimize multiple parameters simultaneously

**Disadvantages:**
- High computational overhead per iteration (GP fitting)
- Requires careful definition of the search space
- Not suitable for discrete choices (use bandits instead)
- Each "evaluation" requires many prompt executions to get a reliable metric

**When to use for prompts:** When tuning model parameters (temperature, top_p) or prompt structure parameters (number of few-shot examples, prompt length budget). NOT for selecting between completely different prompt texts — use bandits for that.

### 2.5 Which Algorithm is Best for Prompt A/B Testing?

**Recommendation: Thompson Sampling, with Epsilon-Greedy as the fallback.**

Rationale:

| Factor | Thompson Sampling | Epsilon-Greedy | UCB | Bayesian Opt |
|---|---|---|---|---|
| **Number of variants** | 2-10: excellent | 2-3: good, 4+: wasteful | 2-5: good | N/A (continuous) |
| **Traffic volume** | Works at any volume | Needs moderate volume | Needs moderate volume | Needs many evaluations |
| **Non-stationary rewards** | Adapts naturally (recent data weights more via windowed updates) | Adapts if epsilon > 0 | Poor | Poor |
| **Implementation complexity** | Low (Beta sampling) | Very low | Low | High |
| **Convergence speed** | Fast | Moderate | Moderate | N/A |
| **Prompt-specific fit** | Excellent — LLM outputs are noisy, Bayesian approach handles uncertainty well | Good — simple and debuggable | Good for stable metrics | Good for parameter tuning only |

**Practical recommendation for this project:**

1. **Phase 1**: Fixed-weight A/B testing (what the implementation plan already describes). Weights are manually set or set by the autoresearch loop. This is the simplest and most debuggable.

2. **Phase 2**: Add epsilon-greedy as `auto_optimize` mode. When an experiment has `auto_optimize=true`, use epsilon-greedy with decaying epsilon to automatically shift traffic toward the better variant.

3. **Phase 3**: Thompson Sampling as the advanced `auto_optimize` mode. Store alpha/beta per arm (simple columns on `experiment_arms`), update on each metric event, sample during routing.

---

## 3. Statistical Significance for Prompt Experiments

### 3.1 Sample Size Requirements

**The core question: How many observations per variant before declaring a winner?**

For a two-sample z-test with:
- Significance level alpha = 0.05
- Power (1 - beta) = 0.80
- Minimum detectable effect (MDE) = the smallest improvement worth detecting

**Formula (per group):**

```
n = (Z_alpha/2 + Z_beta)^2 * 2 * sigma^2 / delta^2

Where:
  Z_alpha/2 = 1.96 (for alpha = 0.05, two-tailed)
  Z_beta    = 0.84 (for power = 0.80)
  sigma     = standard deviation of the metric
  delta     = minimum detectable effect
```

**Practical examples for prompt metrics:**

| Metric | Typical sigma | MDE | Required n per group |
|---|---|---|---|
| Quality score (0-1) | 0.25 | 0.05 | ~392 |
| Quality score (0-1) | 0.25 | 0.10 | ~98 |
| Thumbs up rate | 0.45 (binary) | 0.05 | ~1,270 |
| Latency (seconds) | 2.0 | 0.5 | ~252 |

**Key insight for prompt experiments:** LLM outputs are inherently noisy. The variance of quality metrics for prompts is typically high (sigma is large relative to the effect size you care about). This means you need MORE samples than you might expect. The default `min_sample_size = 100` in the implementation plan is reasonable for detecting a 10% relative improvement in a quality score, but may be too low for detecting 5% improvements.

**Recommendation:** Make `min_sample_size` configurable per experiment and provide a calculator that takes (sigma, MDE, power) and returns the required n. Expose this via the API so the prompt engineer can make an informed choice.

### 3.2 Sequential Testing

**Problem:** Fixed-sample testing requires deciding the sample size in advance and waiting until all samples are collected. This is wasteful — if one variant is clearly better after 50 samples, why wait for 500?

**Sequential Probability Ratio Test (SPRT):**
- After each observation, compute the likelihood ratio: `L = P(data | H1) / P(data | H0)`
- If L > upper boundary: reject H0, declare winner
- If L < lower boundary: accept H0, declare no difference
- If between: continue collecting

**Group Sequential Testing (GST):**
- Pre-specify interim analysis points (e.g., at 25%, 50%, 75%, 100% of planned sample size)
- At each interim analysis, apply an adjusted significance threshold (e.g., O'Brien-Fleming boundaries)
- Allows early stopping while controlling the overall Type I error rate

**Bayesian sequential approach (simplest for this project):**
- After each batch of observations, compute the posterior probability that variant A > variant B
- If P(A > B) > 0.95 (or whatever threshold), declare A the winner
- If P(A > B) < 0.05, declare B the winner
- Otherwise, continue

**Implementation sketch:**
```
# Bayesian comparison using Beta distributions
# Assume binary reward (success/failure)

alpha_A = successes_A + 1
beta_A  = failures_A + 1
alpha_B = successes_B + 1
beta_B  = failures_B + 1

# Monte Carlo estimate of P(A > B)
samples_A = np.random.beta(alpha_A, beta_A, size=10000)
samples_B = np.random.beta(alpha_B, beta_B, size=10000)
p_a_better = np.mean(samples_A > samples_B)

if p_a_better > 0.95:
    declare_winner("A")
elif p_a_better < 0.05:
    declare_winner("B")
else:
    continue_experiment()
```

**Recommendation for this project:** Use the Bayesian sequential approach. It is simple, intuitive ("there is a 97% probability that variant A is better"), and does not require pre-specifying a fixed sample size. It integrates naturally with Thompson Sampling — you are already modeling arm performance as Beta distributions.

### 3.3 Bayesian vs. Frequentist Approaches

| Aspect | Frequentist | Bayesian |
|---|---|---|
| **Question answered** | "What is the probability of seeing this data if H0 is true?" (p-value) | "What is the probability that A is better than B?" |
| **Intuition** | Counter-intuitive for most people | Natural: "93% chance A is better" |
| **Early stopping** | Inflates Type I error unless corrected (GST, alpha spending) | Safe to peek at any time — posterior is always valid |
| **Prior knowledge** | Not incorporated | Can encode prior beliefs (e.g., "new prompts are usually slightly worse") |
| **Sample size planning** | Required in advance | Optional — you can stop when confident enough |
| **Multiple comparisons** | Bonferroni, Holm, etc. | Hierarchical models handle this naturally |
| **Implementation** | scipy.stats.ttest_ind | Beta distribution sampling |

**For prompt experiments, Bayesian is the better fit because:**
1. Prompt engineers want to know "is this new prompt better?" not "can I reject the null hypothesis?"
2. Experiments should stop early when possible (LLM API calls cost money)
3. The autoresearch loop needs a continuous probability signal, not a binary p-value
4. Priors are useful — a newly proposed prompt should require strong evidence to displace an established one

### 3.4 Multiple Comparison Correction

**Problem:** When testing many variants simultaneously (or running many experiments over time), the chance of at least one false positive increases. With 20 independent experiments at alpha = 0.05, the expected false positive rate is 1 - (0.95)^20 = 64%.

**Frequentist corrections:**

- **Bonferroni**: Divide alpha by number of comparisons. Simple but very conservative. Alpha = 0.05 / 20 = 0.0025 per test.
- **Holm-Bonferroni**: Step-down procedure. Less conservative than Bonferroni while still controlling familywise error rate.
- **Benjamini-Hochberg (FDR)**: Controls the false discovery rate rather than familywise error. More powerful. If you expect 5% of your "discoveries" to be false, that is often acceptable.

**Bayesian approach:**
- Use a hierarchical model where all arm performances are drawn from a shared prior
- This naturally "shrinks" estimates toward the group mean, reducing the false discovery rate
- Arms with few observations are pulled more strongly toward the prior, preventing premature conclusions

**Practical recommendation for this project:**

For the typical use case (2-4 arms per experiment, 1 experiment per prompt at a time), multiple comparison correction is not critical. The risk is low.

For the autoresearch loop (many sequential experiments on the same prompt), use one of these approaches:
1. **Bayesian sequential testing with a strong prior** — new variants must show strong evidence to be promoted (P(new > baseline) > 0.95)
2. **Two-stage evaluation** — an initial screen at low traffic, then a confirmation experiment at higher traffic. The two-stage approach reduces false discovery without requiring formal correction.
3. **Track the "improvement rate"** — if the autoresearch loop is promoting variants that later regress, the improvement threshold is too low. Use this as a meta-signal to tighten criteria.

---

## 4. The Autoresearch Pattern Applied to Prompts

### 4.1 Karpathy's Autoresearch Core Loop

The autoresearch pattern (from Karpathy's `autoresearch` project) is:

```
LOOP:
  1. Agent reads current code (train.py)
  2. Agent reads current best metric (val_bpb from results.tsv)
  3. Agent proposes a code change + reasoning
  4. Change is applied, training run executes (5 minutes)
  5. New metric is measured
  6. IF improved: commit the change, update baseline
     ELSE: revert the change
  7. Log result to results.tsv
  8. Go to 1
```

**What makes it work:**
- The evaluation metric (`val_bpb`) is fixed and objective
- The agent never modifies the evaluation harness
- Every experiment is logged for human review
- Binary keep/discard — no "maybe"
- The loop runs autonomously (the human might be asleep)

### 4.2 Adaptation for Prompt Optimization

**Direct mapping:**

| Autoresearch | Prompt Manager |
|---|---|
| `train.py` (code being optimized) | Prompt body text |
| `prepare.py` (evaluation harness) | Metric collection pipeline |
| `val_bpb` (the metric) | Composite score (quality, latency, success rate) |
| 5-minute training run | Experiment window (N samples or T time) |
| `results.tsv` | `optimization_runs` table |
| Git commit (keep) | New prompt version (keep) |
| Git reset (discard) | Revert to previous version (discard) |
| `program.md` (research directions) | Optimization config (constraints, objectives) |

**The adapted loop:**

```
LOOP (until budget exhausted or manually stopped):

  1. OBSERVE
     - Read current best prompt version (baseline)
     - Aggregate recent metrics: mean, p50, p95, count per version
     - Sample recent interactions (good and bad examples)

  2. PROPOSE
     - Construct meta-prompt with:
       * Current prompt text
       * Metric summary
       * Sample interactions
       * Constraints (template vars must be preserved, max length, etc.)
       * Optimization history (what was tried before and what happened)
     - Call optimizer LLM
     - Parse response: new prompt text + reasoning

  3. SHADOW TEST
     - Create new prompt_version (source='optimization')
     - Create experiment with two arms:
       * Control (current baseline): weight = 95
       * Candidate (new version): weight = 5
     - Start experiment

  4. EVALUATE
     - Wait for min_sample_size metric events on the candidate arm
     - Compute composite score for both arms
     - Apply Bayesian comparison: P(candidate > control)

  5. DECIDE
     - IF P(candidate > control) > 0.95:
         → KEEP: Promote candidate to new baseline
         → Optionally ramp up: 5% → 20% → 50% → 100% (canary pattern)
     - IF P(candidate > control) < 0.05:
         → DISCARD: Conclude experiment, revert to control
     - IF 0.05 <= P(...) <= 0.95 AND samples < max_sample_size:
         → CONTINUE: Collect more data
     - IF 0.05 <= P(...) <= 0.95 AND samples >= max_sample_size:
         → DISCARD: Inconclusive = not worth the complexity

  6. LOG
     - Record everything in optimization_runs:
       * input_version, proposed_body, llm_reasoning
       * input_metrics, output_metrics
       * decision (keep/discard/inconclusive)
     - Advance baseline if kept
     - Go to step 1
```

### 4.3 Preventing Optimization Drift

**The risk:** An autonomous optimization loop can drift in undesirable directions. Each individual step might improve the target metric, but the cumulative effect could be:
- Prompt becomes manipulative (optimizes thumbs-up by being sycophantic)
- Prompt loses properties not captured by the metric (brand voice, accuracy on edge cases)
- Prompt grows unboundedly long (more instructions = marginally better metric)
- Prompt "overfits" to the test distribution (good on common inputs, bad on rare ones)

**Guard rails:**

1. **Metric guardrails (hard constraints):**
   ```
   guard_rails:
     max_latency_p95: 5000ms      # Candidate is auto-rejected if latency exceeds this
     min_success_rate: 0.95        # Must maintain 95% success rate
     max_prompt_length: 4000       # Absolute length limit
     min_prompt_length: 100        # Prevent degenerate prompts
     required_template_vars:       # These must appear in the prompt
       - "user_name"
       - "context"
   ```

2. **Semantic drift detection:**
   - Compute embedding similarity between the baseline prompt and the candidate
   - If similarity drops below threshold (e.g., cosine < 0.7), flag for human review
   - This catches cases where the optimizer fundamentally changes what the prompt does

3. **Regression testing on held-out examples:**
   - Maintain a curated set of (input, expected_output) pairs
   - Run the candidate prompt against these before deploying to production
   - Any regression on the held-out set blocks deployment

4. **Optimization budget:**
   ```
   budget:
     max_runs_per_day: 24
     max_consecutive_discards: 5   # If 5 in a row are discarded, pause and alert
     max_total_versions: 100       # Total versions before requiring human review
     cooldown_after_promotion: 1h  # Wait at least 1 hour after a promotion before next run
   ```

5. **Diversity requirement:**
   - Track edit distance between consecutive optimization attempts
   - If the optimizer is making the same type of change repeatedly, inject a "try something different" instruction
   - This prevents the optimizer from getting stuck in a local optimum

6. **Human review checkpoints:**
   - After every N promotions, require human review of the prompt lineage
   - Flag large diffs (edit distance > threshold) for review even in auto mode
   - Provide a "prompt evolution" view showing how the prompt changed over time

### 4.4 Canary Deployments for Prompts

Canary deployment is a staged rollout pattern that limits blast radius:

```
Stage 1: Shadow (0% real traffic)
  - Run candidate prompt alongside control on the same inputs
  - Compare outputs but only serve the control's output to users
  - Duration: until N shadow comparisons pass quality gate

Stage 2: Canary (5% traffic)
  - Route 5% of real traffic to the candidate
  - Monitor metrics closely with tight thresholds
  - Auto-rollback if any guard rail is violated
  - Duration: min_sample_size observations

Stage 3: Ramp (20% traffic)
  - If canary passes, increase to 20%
  - Same monitoring, slightly relaxed thresholds (more data, more confidence)
  - Duration: 2x min_sample_size

Stage 4: Broad (50% traffic)
  - If ramp passes, increase to 50%
  - This is now a proper A/B test with statistical power
  - Duration: until statistical significance

Stage 5: Full (100% traffic)
  - Candidate becomes the new baseline
  - Control is archived but never deleted
```

**Key implementation details:**

- **Each stage transition is an experiment weight update**, not a new experiment. The experiment persists across stages; only the arm weights change.
- **Using deterministic hashing (LaunchDarkly pattern)**, users in the 5% canary are a subset of the 20% ramp, which is a subset of the 50% broad. No user switches from candidate back to control during rollout.
- **Each stage has its own guard rails.** Early stages (canary) should be more sensitive to regressions because the sample size is small and you want to catch catastrophic failures fast. Later stages focus on statistical significance.
- **Auto-rollback at any stage:** If the candidate violates a guard rail, immediately revert to control (set candidate weight to 0) and conclude the experiment.

---

## 5. Sticky Sessions and Routing

### 5.1 Hash-Based Deterministic Routing

**Algorithm:**
```
assignment = hash(session_id + experiment_id) % 10000 / 10000.0

cumulative = 0
for arm in experiment.arms:
    cumulative += arm.weight / 100.0
    if assignment < cumulative:
        return arm
```

**Pros:**
- Stateless — no DB I/O for assignment
- Consistent — same session always gets the same arm
- Fast — CPU-only, sub-microsecond
- Scales horizontally — any server can compute the same result

**Cons:**
- Cannot retroactively look up assignments without replaying the hash
- Cannot override individual users without adding a targeting layer
- Weight changes cause some users to switch arms (unless using the LaunchDarkly-style monotonic rollout)

### 5.2 Stored Assignments

**Algorithm:**
```
# Check for existing assignment
row = SELECT arm_id FROM session_assignments
       WHERE session_id = ? AND experiment_id = ?

if row:
    return get_arm(row.arm_id)

# New assignment via weighted random
arm = weighted_random_select(experiment.arms)
INSERT INTO session_assignments (session_id, experiment_id, arm_id)
VALUES (?, ?, ?)

return arm
```

**Pros:**
- Full auditability — can query exactly what any session saw
- Supports individual overrides (UPDATE a specific row)
- Weight changes only affect new users (existing assignments are preserved)
- Can expire/delete assignments when experiments end

**Cons:**
- Requires DB I/O on first request per (session, experiment)
- Storage grows with users: O(sessions * experiments)
- Distributed systems need to handle race conditions (two requests for same session simultaneously)

### 5.3 Hybrid Approach (Recommended)

Use deterministic hashing as the primary mechanism, store assignments for auditability:

```
1. Compute: arm = hash_assign(session_id, experiment_id, arms)
2. Asynchronously: INSERT INTO session_assignments (session_id, experiment_id, arm_id)
   ON CONFLICT DO NOTHING  -- Idempotent
3. Return arm

On metric ingestion:
- Join against session_assignments to attribute metrics to arms
- If no assignment found, replay the hash to determine which arm it was
```

This gives you the speed of hashing with the auditability of stored assignments. The async write means the assignment never blocks the hot path.

### 5.4 Session Expiry

**Options:**

1. **Time-based TTL:** Delete session_assignments older than X days. Simple, but may cause a user to switch arms if they return after expiry.

2. **Experiment-scoped:** Session assignments are deleted when the experiment concludes. This is the cleanest approach — assignments have no meaning after the experiment ends.

3. **Rolling window:** Keep the last 30 days of assignments. Use a background job to prune old rows.

4. **No expiry:** Keep all assignments forever. Storage is cheap. This preserves the complete history for analytics.

**Recommendation:** Experiment-scoped cleanup. When an experiment is concluded, its session_assignments can be archived (moved to a cold table or deleted). Active experiments always have their assignments in the hot table.

### 5.5 Cross-Experiment Isolation

**Problem:** A user might be in multiple experiments across different prompts. Do experiments interfere with each other?

**Answer: No, if experiments are per-prompt.** The current design enforces one running experiment per prompt via a partial unique index. A user in experiment A (on prompt "welcome-email") and experiment B (on prompt "summary") are in completely independent contexts.

**If we ever support multiple experiments per prompt:** Use Optimizely's namespace/layer model:
- Divide the hash space [0, 1) into non-overlapping segments
- Each experiment owns a segment
- A user's hash determines which experiment they are in (or none)
- This guarantees a user is in at most one experiment per prompt

---

## 6. Edge Cases

### 6.1 Experiment Paused Mid-Flight

**Scenario:** An experiment with arms A (60%) and B (40%) is paused while there are active sessions.

**Behavior options:**

1. **Freeze assignment, serve control** (recommended): When status = 'paused', all requests get the current baseline version. Existing session_assignments are preserved. When resumed, the same assignments are reactivated.

2. **Freeze assignment, serve last assigned**: Continue serving whatever arm the user was in. This requires checking session_assignments even when paused.

3. **Reset everything**: Clear all assignments, start fresh when resumed. Loses data but is simplest.

**Metrics during pause:**
- Metric events during a pause should NOT be attributed to experiment arms
- If a metric arrives with an experiment_id for a paused experiment, store it but flag it with `experiment_status = 'paused'` or simply set `arm_id = NULL`
- This prevents the pause period from contaminating the experiment results

**Recommendation:** Option 1 (freeze assignment, serve control). It is the safest behavior — users get a known-good experience during the pause, and the experiment can resume cleanly.

### 6.2 Metrics for Discarded Experiment Versions

**Scenario:** An experiment concludes, variant B is declared the loser. But there are still metric events arriving for version B (delayed reporting, batch ingestion).

**Handling:**
- Accept all metric events regardless of experiment status. The `metric_events` table is append-only — never reject data.
- Tag late-arriving events with the experiment's concluded status when querying/aggregating.
- For dashboard display: show metrics up to the `concluded_at` timestamp by default, with an option to include post-conclusion data.
- For the autoresearch loop: only consider metrics collected while the experiment was `running`.

**Data retention for discarded versions:**
- Keep the `prompt_versions` row (immutable history)
- Keep all `metric_events` for the version (useful for post-hoc analysis)
- The version simply is not referenced as `current_version` — it exists in history but is not served

### 6.3 Concurrent Experiment Modifications (Optimistic Locking)

**Scenario:** Two administrators simultaneously try to update the same experiment's weights. Or the autoresearch loop tries to adjust weights while an admin is manually tweaking them.

**Solution: Optimistic locking with version counter.**

```sql
ALTER TABLE experiments ADD COLUMN lock_version INT NOT NULL DEFAULT 0;

-- Update with optimistic lock
UPDATE experiments
SET weights = $new_weights,
    lock_version = lock_version + 1,
    updated_at = now()
WHERE id = $experiment_id
  AND lock_version = $expected_version;

-- If rows_affected = 0, the experiment was modified by someone else
-- Retry: re-read, re-apply, re-update
```

**In the API layer:**
```
PATCH /experiments/{id}
Body: { weights: [...], lock_version: 3 }

Response:
  200 OK (if lock_version matched)
  409 Conflict (if lock_version stale, return current state for client to retry)
```

**For the autoresearch loop:** The optimization service should always read the experiment's current state before making changes, and use optimistic locking for the update. If it gets a 409, it re-reads and re-evaluates (the human's manual change might have already addressed the issue).

### 6.4 Weight Changes During Live Traffic

**Scenario:** An experiment is running with arms A (70%) and B (30%). An administrator changes it to A (50%) and B (50%).

**Impact depends on routing strategy:**

**Hash-based routing:**
- Some users who were in arm A (because their hash fell in [0.3, 0.5)) will now be in arm B
- Users whose hash is in [0.0, 0.3) remain in arm B
- Users whose hash is in [0.5, 1.0) remain in arm A
- This means a fraction of users "switch sides"

**Stored-assignment routing:**
- Existing users keep their current assignment (the row in session_assignments doesn't change)
- Only new users (no existing row) see the new weight distribution
- This is more stable but means the actual traffic split does not immediately reflect the new weights — it converges over time as new users arrive

**Hybrid approach (recommended):**
- When weights change, optionally clear session_assignments for the experiment: `DELETE FROM session_assignments WHERE experiment_id = ?`
- This forces all users to be re-assigned using the new weights
- Or, keep existing assignments and only apply new weights to new users (gradual convergence)
- Make this a configurable option: `reassign_on_weight_change: true/false`

**Metric impact:**
- Metric events before the weight change reflect the old distribution
- Metric events after reflect the new distribution
- For statistical analysis, treat weight changes as "epoch boundaries" — analyze within-epoch data separately or use a time-weighted analysis
- Store weight change events in an audit log for reference

---

## 7. Recommendations for This Project

### 7.1 Phase 1: Fixed-Weight A/B Testing (Current Plan)

Keep the current design from the implementation plan:
- Manual weight-based routing
- Stored session assignments for stickiness
- `min_sample_size` per experiment before concluding
- One running experiment per prompt

**Changes to consider:**
- Replace `random.uniform()` with deterministic hashing using MurmurHash3 or SHA-256. This gives consistent assignment without requiring a DB lookup, and enables the LaunchDarkly-style monotonic rollout for canary deployments.
- Store the assignment asynchronously for auditability (the hybrid approach from section 5.3).

### 7.2 Phase 2: Bayesian Sequential Testing

Add to the experiment evaluation:
- Model each arm's performance as a Beta distribution (for binary metrics) or Normal distribution (for continuous metrics)
- Implement the Bayesian sequential comparison from section 3.2
- Allow experiments to auto-conclude when P(winner > loser) exceeds a threshold (default 0.95)
- Expose this probability in the experiment detail API response

### 7.3 Phase 3: Thompson Sampling / Epsilon-Greedy

When `auto_optimize` is enabled on an experiment:
- Add `alpha` and `beta` columns to `experiment_arms` (initialized to 1, 1)
- On each metric event, update the corresponding arm's alpha/beta
- During routing (for non-sticky sessions), sample from each arm's Beta distribution and select the highest
- Log weight adjustments as experiment events for audit

Offer two modes:
- `epsilon_greedy`: Simpler, more predictable. Good default.
- `thompson_sampling`: Better convergence, more adaptive. Advanced option.

### 7.4 Phase 4: Full Autoresearch Loop

Implement the autoresearch optimization loop from section 4.2:
- Observe -> Propose -> Shadow Test -> Evaluate -> Decide -> Log
- Use canary deployment stages (5% -> 20% -> 50% -> 100%)
- Apply all guard rails from section 4.3
- Track optimization history in `optimization_runs`

### 7.5 Algorithm Selection Summary

| Use Case | Algorithm | Why |
|---|---|---|
| Manual A/B test (2 variants) | Fixed weights + Bayesian sequential testing | Simple, controllable, stops early |
| Manual A/B test (3+ variants) | Fixed weights + Bayesian comparison | Same, with pairwise comparisons |
| Auto-optimize (simple) | Epsilon-greedy (decaying) | Easy to implement and explain |
| Auto-optimize (advanced) | Thompson Sampling | Better convergence, handles uncertainty |
| Canary deployment | Deterministic hash + staged rollout | Consistent assignment, monotonic rollout |
| Parameter tuning (temp, tokens) | Bayesian optimization (future) | Sample-efficient for continuous params |
| Autoresearch loop | Thompson Sampling + canary stages | Full autonomous optimization |

### 7.6 Key Technical Decisions

1. **Hashing function**: Use MurmurHash3 (via `mmh3` Python package) or SHA-256 truncated to 4 bytes. MurmurHash3 is faster; SHA-256 is universally available without extra dependencies.

2. **Bayesian implementation**: Use `numpy.random.beta` for Thompson Sampling. No heavy dependencies required. For the sequential test, use Monte Carlo comparison (10,000 samples from each arm's Beta, count how often A > B).

3. **Metric windowing**: For non-stationary metrics (which prompt metrics often are), use a sliding window (e.g., last 7 days of data) for bandit updates rather than all-time data. This allows the system to adapt to changing user behavior.

4. **Concurrency model**: Bandit state (alpha/beta) updates should be atomic. Use PostgreSQL's `UPDATE experiment_arms SET alpha = alpha + 1 WHERE id = ?` for lock-free atomic updates.

5. **Fallback behavior**: If the experiment engine fails (DB down, hash error), always fall back to the current baseline version. Never fail the user's request because of an experiment failure.

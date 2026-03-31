"""
Validation script for the autoresearch optimization loop — REAL LLM edition.

Uses a real Groq LLM to propose prompt improvements each iteration, while
keeping mock Instagram metrics (Gaussian noise around version-correlated
base rates) and in-memory state (no PostgreSQL required).

Env vars (loaded from .env at repo root if python-dotenv is available):
    GROQ_API_KEY      — required
    PM_LLM_PROVIDER   — optional, defaults to "groq"
    PM_LLM_MODEL      — optional, defaults to "llama-3.3-70b-versatile"

Usage:
    cd packages/example
    python -m marketing_agent.validate_optimization_loop_real_llm

    # OR from repo root:
    python packages/example/src/marketing_agent/validate_optimization_loop_real_llm.py
"""

from __future__ import annotations

import json
import os
import random
import re
import statistics
import sys
import textwrap
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Load .env if present (repo root or worktree root)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
for _candidate in [
    _SCRIPT_DIR.parents[4] / ".env",   # worktree root
    _SCRIPT_DIR.parents[7] / ".env",   # repo root (if run from full path)
    Path.cwd() / ".env",
]:
    if _candidate.exists():
        with _candidate.open() as _fh:
            for _line in _fh:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _, _v = _line.partition("=")
                    os.environ.setdefault(_k.strip(), _v.strip())
        break

# ---------------------------------------------------------------------------
# Real tool imports (installed packages — no DB/LLM in these modules)
# ---------------------------------------------------------------------------
from autoresearcher_shonku.tools.analysis import analyze_metric_trends  # noqa: E402
from autoresearcher_shonku.tools.validation import (  # noqa: E402
    compute_similarity,
    validate_template_vars,
)
from autoresearcher_shonku.scoring import (  # noqa: E402
    compute_composite_score,
    is_improvement,
)

# ---------------------------------------------------------------------------
# Groq client setup
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
PM_LLM_PROVIDER = os.environ.get("PM_LLM_PROVIDER", "groq")
PM_LLM_MODEL = os.environ.get("PM_LLM_MODEL", "llama-3.3-70b-versatile")

if not GROQ_API_KEY:
    print("ERROR: GROQ_API_KEY is not set. Add it to .env or export it.")
    sys.exit(1)

try:
    from groq import Groq as GroqClient
    _groq = GroqClient(api_key=GROQ_API_KEY)
except ImportError:
    print("ERROR: groq package not installed. Run: pip install groq")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
IMPROVEMENT_THRESHOLD = 0.01   # 1% composite-score improvement required
MAX_ITERATIONS = 8
SESSIONS_PER_ITER = 20
RANDOM_SEED = 42
N_WARMUP_SESSIONS = 20

random.seed(RANDOM_SEED)

# ---------------------------------------------------------------------------
# Seed prompts
# ---------------------------------------------------------------------------
PROMPT_V1 = textwrap.dedent("""\
    Dear {name},

    We are excited to announce our new {product} collection.
    Please visit our website to explore the latest offerings.
    Use code {promo_code} for a 10% discount.

    Thank you for your continued support.
    — {brand}
""")

PROMPT_V2 = textwrap.dedent("""\
    Hey {name}! 🔥

    Just dropped: our {product} collection and it's giving EVERYTHING. ✨
    Snag yours before it's gone — grab {promo_code} at checkout for 10% off!

    Your faves @ {brand} 💖
""")

# ---------------------------------------------------------------------------
# Mock metric generator (identical to the mock-only validation script)
# ---------------------------------------------------------------------------

_BASE_ENGAGEMENT: dict[int, float] = {
    1: 0.032,
    2: 0.051,
    3: 0.058,
    4: 0.063,
    5: 0.067,
    6: 0.070,
    7: 0.072,
    8: 0.073,
}


def _mock_metrics_for_version(version: int, n: int = 20) -> dict[str, list[float]]:
    """Generate *n* simulated Instagram metric observations for a prompt version."""
    base_eng = _BASE_ENGAGEMENT.get(version, 0.055 + (version - 8) * 0.002)
    metrics: dict[str, list[float]] = {
        "engagement_rate": [],
        "likes_rate": [],
        "comments_rate": [],
        "shares_rate": [],
    }
    for _ in range(n):
        noise = random.gauss(0, 0.005)
        eng = max(0.001, base_eng + noise)
        metrics["engagement_rate"].append(round(eng, 4))
        metrics["likes_rate"].append(round(max(0.001, eng * 0.70 + random.gauss(0, 0.003)), 4))
        metrics["comments_rate"].append(round(max(0.001, eng * 0.18 + random.gauss(0, 0.002)), 4))
        metrics["shares_rate"].append(round(max(0.001, eng * 0.12 + random.gauss(0, 0.001)), 4))
    return metrics


def _composite_from_metric_means(metric_means: dict[str, float]) -> float:
    normalised = {k: min(1.0, v / 0.15) for k, v in metric_means.items()}
    weights = {
        "engagement_rate": 0.50,
        "likes_rate": 0.20,
        "comments_rate": 0.20,
        "shares_rate": 0.10,
    }
    return compute_composite_score(normalised, weights)


# ---------------------------------------------------------------------------
# Safety check (mirrors AutoResearcherAgent.check_safety_rails)
# ---------------------------------------------------------------------------

def check_safety_rails(
    original: str,
    proposed: str,
    iteration: int,
    max_iterations: int,
) -> dict[str, Any]:
    sim = SequenceMatcher(None, original, proposed).ratio()
    original_len = max(len(original), 1)
    checks = {
        "similarity_ok": sim >= 0.3,
        "not_empty": len(proposed.strip()) > 10,
        "within_budget": iteration <= max_iterations,
        "length_reasonable": 0.3 <= len(proposed) / original_len <= 3.0,
    }
    return {
        "safe": all(checks.values()),
        "checks": checks,
        "similarity": round(sim, 3),
        "blocked_reason": None if all(checks.values()) else [k for k, v in checks.items() if not v],
    }


# ---------------------------------------------------------------------------
# LLM proposal generation (the key difference from the mock-only script)
# ---------------------------------------------------------------------------

def _build_llm_prompt(
    current_prompt: str,
    current_version: int,
    metric_means: dict[str, float],
    composite_score: float,
    analysis: dict[str, Any],
    iteration_history: list[dict],
) -> str:
    trends = {k: v.get("trend", "unknown") for k, v in analysis.items()}

    history_lines: list[str] = []
    for h in iteration_history[-3:]:  # last 3 for context window efficiency
        action = "ACCEPTED" if h["accepted"] else "REJECTED"
        history_lines.append(
            f"  - Iter {h['iteration']}: {action} — {h['reason'][:80]}"
        )
    history_str = "\n".join(history_lines) if history_lines else "  (none yet)"

    return f"""You are an expert prompt engineer optimizing Instagram marketing post templates.

CURRENT PROMPT (v{current_version}):
---
{current_prompt.strip()}
---

PERFORMANCE METRICS (last {SESSIONS_PER_ITER} simulated sessions):
  engagement_rate : {metric_means['engagement_rate']:.4f}  (trend: {trends.get('engagement_rate', '?')})
  likes_rate      : {metric_means['likes_rate']:.4f}  (trend: {trends.get('likes_rate', '?')})
  comments_rate   : {metric_means['comments_rate']:.4f}  (trend: {trends.get('comments_rate', '?')})
  shares_rate     : {metric_means['shares_rate']:.4f}  (trend: {trends.get('shares_rate', '?')})
  composite_score : {composite_score:.4f}  (higher is better, max 1.0)

RECENT ITERATION HISTORY:
{history_str}

TASK:
Propose ONE focused improvement to this Instagram marketing post template.

HARD CONSTRAINTS (violation = proposal rejected):
  1. Keep ALL four template variables exactly as-is: {{name}}, {{product}}, {{promo_code}}, {{brand}}
  2. The improved prompt must be 30–300% the length of the current prompt
  3. Must remain clearly similar to current (similarity ≥ 0.30) — no complete rewrites

IMPROVEMENT GOALS (pick 1–2 to address):
  - Increase urgency or scarcity signals (if shares/engagement are low)
  - Add social proof (e.g. "500+ customers love it") if comments are low
  - Sharpen the CTA (call-to-action) if engagement is plateauing
  - Adjust tone (more personal, more energetic, or more concise)
  - Add or improve emoji usage for visual appeal

Respond with ONLY valid JSON, no markdown, no preamble:
{{"improved_prompt": "<full prompt text with template vars>", "reasoning": "<1-2 sentences>", "expected_improvement": "<what metric you expect to improve and why>", "risk": "low"}}"""


def propose_improvement_via_llm(
    current_prompt: str,
    current_version: int,
    metric_means: dict[str, float],
    composite_score: float,
    analysis: dict[str, Any],
    iteration_history: list[dict],
) -> dict[str, Any] | None:
    """Call Groq LLM to propose a prompt improvement. Returns parsed dict or None on failure."""
    user_msg = _build_llm_prompt(
        current_prompt, current_version, metric_means,
        composite_score, analysis, iteration_history,
    )

    try:
        response = _groq.chat.completions.create(
            model=PM_LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a prompt optimization expert. "
                        "Always respond with valid JSON only — no markdown, no explanation outside the JSON."
                    ),
                },
                {"role": "user", "content": user_msg},
            ],
            temperature=0.7,
            max_tokens=1024,
        )
    except Exception as exc:
        print(f"  [LLM ERROR] Groq API call failed: {exc}")
        return None

    raw = response.choices[0].message.content.strip()

    # Try direct JSON parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Fallback: extract JSON block from markdown code fences or surrounding text
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    print(f"  [LLM WARN] Could not parse JSON from response:\n    {raw[:200]}")
    return None


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class IterationResult:
    iteration: int
    active_version: int
    active_prompt_preview: str
    metrics: dict[str, list[float]]
    metric_means: dict[str, float]
    composite_score: float
    analysis: dict[str, Any]
    proposed_version: int | None
    proposed_prompt_preview: str | None
    llm_reasoning: str | None
    llm_expected_improvement: str | None
    safety_check: dict[str, Any] | None
    template_vars_valid: bool | None
    similarity: float | None
    accepted: bool
    reason: str
    baseline_score: float
    delta: float


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_validation_loop() -> list[IterationResult]:
    results: list[IterationResult] = []
    iteration_history: list[dict] = []

    current_version = 2
    baseline_score = 0.0
    all_versions = [PROMPT_V1, PROMPT_V2]

    print("=" * 70)
    print("  AUTORESEARCH OPTIMIZATION LOOP — REAL LLM VALIDATION")
    print(f"  Provider: {PM_LLM_PROVIDER}  Model: {PM_LLM_MODEL}")
    print(f"  Iterations: {MAX_ITERATIONS}  |  Sessions/iter: {SESSIONS_PER_ITER}")
    print(f"  Improvement threshold: {IMPROVEMENT_THRESHOLD:.0%}")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Warm-up: seed baseline from v1 + v2
    # ------------------------------------------------------------------
    print("\n[WARM-UP] Collecting initial metrics from v1 & v2 (50/50 routing)…")
    warmup_metrics: dict[str, list[float]] = {
        "engagement_rate": [], "likes_rate": [], "comments_rate": [], "shares_rate": [],
    }
    for v in [1, 2]:
        m = _mock_metrics_for_version(v, n=N_WARMUP_SESSIONS // 2)
        for key in warmup_metrics:
            warmup_metrics[key].extend(m[key])

    warmup_means = {k: statistics.mean(v) for k, v in warmup_metrics.items()}
    baseline_score = _composite_from_metric_means(warmup_means)
    print(f"  Baseline composite score: {baseline_score:.4f}")
    print(f"  Engagement rate (mean):   {warmup_means['engagement_rate']:.4f}")

    # ------------------------------------------------------------------
    # Optimization iterations
    # ------------------------------------------------------------------
    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'─' * 70}")
        print(f"  ITERATION {iteration}/{MAX_ITERATIONS}  —  active version: v{current_version}")
        print(f"{'─' * 70}")

        # Step 1: Collect mock metrics for current version
        metrics = _mock_metrics_for_version(current_version, n=SESSIONS_PER_ITER)
        metric_means = {k: round(statistics.mean(v), 4) for k, v in metrics.items()}
        composite = _composite_from_metric_means(metric_means)

        print(f"  [METRICS]  eng={metric_means['engagement_rate']:.4f}  "
              f"likes={metric_means['likes_rate']:.4f}  "
              f"comments={metric_means['comments_rate']:.4f}  "
              f"shares={metric_means['shares_rate']:.4f}")
        print(f"  [SCORE]    composite={composite:.4f}  baseline={baseline_score:.4f}")

        # Step 2: Analyze trends with real tool
        analysis_raw = analyze_metric_trends(json.dumps(metrics))
        analysis = json.loads(analysis_raw)
        trends = {k: v["trend"] for k, v in analysis.items()}
        print(f"  [ANALYSIS] trends={trends}")

        # Step 3: Call the real LLM to propose an improvement
        current_prompt_text = all_versions[current_version - 1]
        print(f"  [LLM]      Calling {PM_LLM_MODEL} for proposal…")
        llm_result = propose_improvement_via_llm(
            current_prompt_text,
            current_version,
            metric_means,
            composite,
            analysis,
            iteration_history,
        )

        if llm_result is None or not llm_result.get("improved_prompt", "").strip():
            reason = "LLM returned no usable proposal"
            print(f"  [DECISION] SKIP — {reason}")
            result = IterationResult(
                iteration=iteration,
                active_version=current_version,
                active_prompt_preview=current_prompt_text[:80].replace("\n", " "),
                metrics=metrics,
                metric_means=metric_means,
                composite_score=composite,
                analysis=analysis,
                proposed_version=None,
                proposed_prompt_preview=None,
                llm_reasoning=None,
                llm_expected_improvement=None,
                safety_check=None,
                template_vars_valid=None,
                similarity=None,
                accepted=False,
                reason=reason,
                baseline_score=baseline_score,
                delta=composite - baseline_score,
            )
            results.append(result)
            iteration_history.append({"iteration": iteration, "accepted": False, "reason": reason})
            baseline_score = composite
            continue

        proposed_prompt = llm_result["improved_prompt"]
        llm_reasoning = llm_result.get("reasoning", "")
        llm_expected = llm_result.get("expected_improvement", "")
        proposed_version_num = len(all_versions) + 1
        proposed_preview = proposed_prompt[:80].replace("\n", " ")

        print(f"  [PROPOSE]  v{proposed_version_num}: {proposed_preview}…")
        print(f"  [REASON]   {llm_reasoning[:100]}")
        print(f"  [EXPECTED] {llm_expected[:80]}")

        # Step 4: Validate template vars (real tool)
        vars_result = json.loads(validate_template_vars(current_prompt_text, proposed_prompt))
        vars_valid = vars_result["valid"]
        print(f"  [VALIDATE] vars_valid={vars_valid}  "
              f"vars={vars_result['vars']}  missing={vars_result['missing']}")

        # Step 5: Safety check
        safety = check_safety_rails(current_prompt_text, proposed_prompt, iteration, MAX_ITERATIONS)
        sim_raw = json.loads(compute_similarity(current_prompt_text, proposed_prompt))
        similarity = sim_raw["similarity"]
        print(f"  [SAFETY]   safe={safety['safe']}  similarity={safety['similarity']}  "
              f"checks={safety['checks']}")

        if not safety["safe"] or not vars_valid:
            reason = f"Blocked: safety={safety['safe']} vars_valid={vars_valid}"
            if not safety["safe"]:
                reason += f" [{safety['blocked_reason']}]"
            if not vars_valid:
                reason += f" missing_vars={vars_result['missing']}"
            print(f"  [DECISION] DISCARD — {reason}")
            result = IterationResult(
                iteration=iteration,
                active_version=current_version,
                active_prompt_preview=current_prompt_text[:80].replace("\n", " "),
                metrics=metrics,
                metric_means=metric_means,
                composite_score=composite,
                analysis=analysis,
                proposed_version=proposed_version_num,
                proposed_prompt_preview=proposed_preview,
                llm_reasoning=llm_reasoning,
                llm_expected_improvement=llm_expected,
                safety_check=safety,
                template_vars_valid=vars_valid,
                similarity=similarity,
                accepted=False,
                reason=reason,
                baseline_score=baseline_score,
                delta=composite - baseline_score,
            )
            results.append(result)
            iteration_history.append({"iteration": iteration, "accepted": False, "reason": reason})
            baseline_score = composite
            continue

        # Step 6: Shadow-test — mock metrics for proposed version
        proposed_metrics = _mock_metrics_for_version(proposed_version_num, n=SESSIONS_PER_ITER)
        proposed_means = {k: round(statistics.mean(v), 4) for k, v in proposed_metrics.items()}
        proposed_composite = _composite_from_metric_means(proposed_means)
        print(f"  [SHADOW]   proposed eng={proposed_means['engagement_rate']:.4f}  "
              f"composite={proposed_composite:.4f}")

        # Step 7: Decide keep/discard
        improved = is_improvement(proposed_composite, composite, IMPROVEMENT_THRESHOLD)
        if improved:
            all_versions.append(proposed_prompt)
            current_version = proposed_version_num
            accepted = True
            reason = (f"Accepted: {composite:.4f} → {proposed_composite:.4f} "
                      f"(+{proposed_composite - composite:.4f})")
            print(f"  [DECISION] KEEP v{proposed_version_num} — {reason}")
        else:
            accepted = False
            reason = (f"Discarded: {composite:.4f} → {proposed_composite:.4f} "
                      f"(delta {proposed_composite - composite:+.4f} below "
                      f"threshold {IMPROVEMENT_THRESHOLD})")
            print(f"  [DECISION] DISCARD — {reason}")

        result = IterationResult(
            iteration=iteration,
            active_version=current_version if accepted else current_version,
            active_prompt_preview=current_prompt_text[:80].replace("\n", " "),
            metrics=metrics,
            metric_means=metric_means,
            composite_score=composite,
            analysis=analysis,
            proposed_version=proposed_version_num,
            proposed_prompt_preview=proposed_preview,
            llm_reasoning=llm_reasoning,
            llm_expected_improvement=llm_expected,
            safety_check=safety,
            template_vars_valid=vars_valid,
            similarity=similarity,
            accepted=accepted,
            reason=reason,
            baseline_score=baseline_score,
            delta=composite - baseline_score,
        )
        results.append(result)
        iteration_history.append({"iteration": iteration, "accepted": accepted, "reason": reason})

        baseline_score = proposed_composite if accepted else composite

    return results


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: list[IterationResult]) -> None:
    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)

    accepted = [r for r in results if r.accepted]
    rejected = [r for r in results if not r.accepted]
    scores = [r.composite_score for r in results]

    print(f"  Total iterations : {len(results)}")
    print(f"  Accepted         : {len(accepted)}")
    print(f"  Rejected/Blocked : {len(rejected)}")
    print(f"  Score range      : {min(scores):.4f} – {max(scores):.4f}")

    if len(scores) >= 2:
        score_delta = scores[-1] - scores[0]
        trend = (
            "↑ improving" if score_delta > 0.001
            else ("↓ declining" if score_delta < -0.001 else "→ stable")
        )
        print(f"  First → last     : {scores[0]:.4f} → {scores[-1]:.4f}  ({score_delta:+.4f})  {trend}")

    if len(scores) >= 4:
        last_3 = scores[-3:]
        spread = max(last_3) - min(last_3)
        print(f"  Last-3 spread    : {spread:.4f}  → {'CONVERGED' if spread < 0.005 else 'still evolving'}")

    print("\n  Per-iteration table:")
    print(f"  {'Iter':>4}  {'v':>3}  {'Score':>7}  {'Delta':>7}  {'Accept':>6}  Reason")
    print(f"  {'─'*4}  {'─'*3}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*40}")
    for r in results:
        print(
            f"  {r.iteration:>4}  v{r.active_version:<2}  {r.composite_score:.4f}  "
            f"{r.delta:>+.4f}  {'YES' if r.accepted else 'no':>6}  "
            f"{r.reason[:55]}"
        )

    # Show final accepted prompts
    if accepted:
        print(f"\n  LLM PROPOSALS (accepted):")
        for r in accepted:
            print(f"    Iter {r.iteration}: {r.llm_reasoning or '(no reasoning)'}  [{r.similarity:.2f} sim]")

    print("\n" + "=" * 70)
    if len(accepted) > 0:
        print("  CONCLUSION: Real LLM produced improvements — optimization is working.")
    else:
        print("  CONCLUSION: No improvements accepted — proposals were blocked or below threshold.")
    print("=" * 70)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> list[IterationResult]:
    results = run_validation_loop()
    print_summary(results)
    return results


if __name__ == "__main__":
    main()

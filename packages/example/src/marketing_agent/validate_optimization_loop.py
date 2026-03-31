"""
Validation script for the autoresearch optimization loop.

Runs 8 iterations of the autonomous optimization loop with mock Instagram
marketing metrics. No PostgreSQL or LLM API required — uses real tool
implementations from autoresearcher_shonku (analysis, validation, safety,
scoring) and an in-memory state store.

Usage:
    cd packages/example
    python -m marketing_agent.validate_optimization_loop

    # OR from repo root:
    python packages/example/src/marketing_agent/validate_optimization_loop.py
"""

from __future__ import annotations

import json
import random
import statistics
import sys
import textwrap
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path setup so script can run from anywhere in the repo
# ---------------------------------------------------------------------------
_REPO = Path(__file__).resolve().parents[5]
for _pkg in ["autoresearcher_shonku", "prompt_manager", "shonku"]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# Real tool imports (pure-Python, no DB/LLM needed)
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
# In-memory state
# ---------------------------------------------------------------------------

IMPROVEMENT_THRESHOLD = 0.01   # 1% composite-score improvement required
MAX_ITERATIONS = 8
SESSIONS_PER_ITER = 20         # simulated users / sessions per iteration
RANDOM_SEED = 42
N_WARMUP_SESSIONS = 20         # initial sessions before first optimization run

random.seed(RANDOM_SEED)

# Instagram post versions -------------------------------------------------

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

# Deterministic improved versions (simulate what an LLM would propose)
PROMPT_IMPROVEMENTS = [
    # v3 — warm professional hybrid
    textwrap.dedent("""\
        Hi {name}! 👋

        Exciting news: our {product} collection just launched and we think
        you'll love it. Use {promo_code} at checkout for 10% off.

        Shop now before your size sells out!
        — {brand}
    """),
    # v4 — adds urgency + social proof
    textwrap.dedent("""\
        Hi {name}! 👋

        Our {product} collection is HERE — and 500+ customers already love it! 🌟
        Grab yours with {promo_code} for 10% off. Limited stock!

        — {brand}
    """),
    # v5 — question hook + CTA
    textwrap.dedent("""\
        {name}, looking for the perfect {product}? 👀

        We've got exactly what you need — and with {promo_code} you save 10%!
        Tap the link in bio to shop before it's gone.

        — {brand} ✨
    """),
    # v6 — refined question hook
    textwrap.dedent("""\
        Ready to elevate your {product} game, {name}? 🚀

        Our new drop is live with 500+ 5-star reviews. Use {promo_code} at checkout
        for 10% off — but hurry, stock is flying!

        Shop now → link in bio 🛍️
        — {brand}
    """),
    # v7 — trimmed, punchy
    textwrap.dedent("""\
        {name}, your {product} is waiting! ⚡

        New drop · 500+ fans · 10% off with {promo_code}
        Limited stock — link in bio 👆

        — {brand}
    """),
    # v8 — adds personalized opener
    textwrap.dedent("""\
        {name} — we picked this {product} with you in mind. 🎯

        Use {promo_code} for 10% off. 500+ happy customers can't be wrong!
        Tap link in bio while stock lasts. ⏳

        — {brand}
    """),
]

# ---------------------------------------------------------------------------
# Mock metric generator
# ---------------------------------------------------------------------------

# Base engagement rates per version (0–1 scale, 1 = 100%)
# Later versions are slightly better on average (provides learning signal)
_BASE_ENGAGEMENT: dict[int, float] = {
    1: 0.032,   # v1 formal — lower engagement
    2: 0.051,   # v2 casual — moderate
    3: 0.058,
    4: 0.063,
    5: 0.067,
    6: 0.070,
    7: 0.072,
    8: 0.073,
}


def _mock_metrics_for_version(version: int, n: int = 20) -> dict[str, list[float]]:
    """Generate n simulated Instagram metric observations for a prompt version.

    Metrics are in [0, 1] (normalised rates).
    """
    base_eng = _BASE_ENGAGEMENT.get(version, 0.055)
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
    """Compute a composite [0,1] score from normalised metric means."""
    # Normalise engagement_rate to [0,1] assuming max realistic IG rate ~15%
    normalised = {
        k: min(1.0, v / 0.15)
        for k, v in metric_means.items()
    }
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
    """Run the full optimization loop for MAX_ITERATIONS iterations.

    Returns a list of IterationResult objects (one per iteration).
    """
    results: list[IterationResult] = []

    # State
    current_version = 2          # start A/B: route 50/50 between v1 and v2
    baseline_score = 0.0
    all_versions = [PROMPT_V1, PROMPT_V2]  # index 0 = v1, index 1 = v2

    print("=" * 70)
    print("  AUTORESEARCH OPTIMIZATION LOOP — VALIDATION RUN")
    print(f"  Iterations: {MAX_ITERATIONS}  |  Sessions/iter: {SESSIONS_PER_ITER}")
    print(f"  Improvement threshold: {IMPROVEMENT_THRESHOLD:.0%}")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Warm-up: collect initial metrics from v1 and v2 to seed baseline
    # ------------------------------------------------------------------
    print("\n[WARM-UP] Collecting initial metrics from v1 & v2 (50/50 routing)…")
    warmup_metrics: dict[str, list[float]] = {
        "engagement_rate": [],
        "likes_rate": [],
        "comments_rate": [],
        "shares_rate": [],
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

        # Step 1: Collect metrics for current version
        metrics = _mock_metrics_for_version(current_version, n=SESSIONS_PER_ITER)
        metric_means = {k: round(statistics.mean(v), 4) for k, v in metrics.items()}
        composite = _composite_from_metric_means(metric_means)

        print(f"  [METRICS] engagement={metric_means['engagement_rate']:.4f}  "
              f"likes={metric_means['likes_rate']:.4f}  "
              f"comments={metric_means['comments_rate']:.4f}  "
              f"shares={metric_means['shares_rate']:.4f}")
        print(f"  [SCORE]   composite={composite:.4f}  baseline={baseline_score:.4f}")

        # Step 2: Analyze trends with real tool
        analysis_raw = analyze_metric_trends(json.dumps(metrics))
        analysis = json.loads(analysis_raw)
        trends = {k: v["trend"] for k, v in analysis.items()}
        print(f"  [ANALYSIS] trends={trends}")

        # Step 3: Propose next version (deterministic — simulates LLM output)
        proposal_idx = iteration - 1  # use next improvement template
        if proposal_idx >= len(PROMPT_IMPROVEMENTS):
            # No more improvements — stop proposing
            print("  [PROPOSE]  No more improvement templates — skipping proposal")
            results.append(IterationResult(
                iteration=iteration,
                active_version=current_version,
                active_prompt_preview=all_versions[current_version - 1][:80].replace("\n", " "),
                metrics=metrics,
                metric_means=metric_means,
                composite_score=composite,
                analysis=analysis,
                proposed_version=None,
                proposed_prompt_preview=None,
                safety_check=None,
                template_vars_valid=None,
                similarity=None,
                accepted=False,
                reason="No more improvement proposals available",
                baseline_score=baseline_score,
                delta=composite - baseline_score,
            ))
            baseline_score = composite
            continue

        proposed_prompt = PROMPT_IMPROVEMENTS[proposal_idx]
        proposed_version_num = len(all_versions) + 1
        proposed_preview = proposed_prompt[:80].replace("\n", " ")
        print(f"  [PROPOSE]  v{proposed_version_num}: {proposed_preview}…")

        # Step 4: Validate template vars (real tool)
        current_prompt_text = all_versions[current_version - 1]
        vars_result = json.loads(validate_template_vars(current_prompt_text, proposed_prompt))
        vars_valid = vars_result["valid"]
        print(f"  [VALIDATE] template_vars_valid={vars_valid}  "
              f"vars={vars_result['vars']}  missing={vars_result['missing']}")

        # Step 5: Safety check (mirrors AutoResearcherAgent.check_safety_rails)
        safety = check_safety_rails(
            current_prompt_text, proposed_prompt, iteration, MAX_ITERATIONS
        )
        sim_raw = json.loads(compute_similarity(current_prompt_text, proposed_prompt))
        similarity = sim_raw["similarity"]
        print(f"  [SAFETY]   safe={safety['safe']}  similarity={safety['similarity']}  "
              f"checks={safety['checks']}")

        if not safety["safe"] or not vars_valid:
            reason = f"Blocked: safety={safety['safe']} vars_valid={vars_valid}"
            if not safety["safe"]:
                reason += f" reason={safety['blocked_reason']}"
            print(f"  [DECISION] DISCARD — {reason}")
            results.append(IterationResult(
                iteration=iteration,
                active_version=current_version,
                active_prompt_preview=current_prompt_text[:80].replace("\n", " "),
                metrics=metrics,
                metric_means=metric_means,
                composite_score=composite,
                analysis=analysis,
                proposed_version=proposed_version_num,
                proposed_prompt_preview=proposed_preview,
                safety_check=safety,
                template_vars_valid=vars_valid,
                similarity=similarity,
                accepted=False,
                reason=reason,
                baseline_score=baseline_score,
                delta=composite - baseline_score,
            ))
            baseline_score = composite
            continue

        # Step 6: Shadow-test — collect metrics for the proposed version
        proposed_metrics = _mock_metrics_for_version(proposed_version_num, n=SESSIONS_PER_ITER)
        proposed_means = {k: round(statistics.mean(v), 4) for k, v in proposed_metrics.items()}
        proposed_composite = _composite_from_metric_means(proposed_means)
        print(f"  [SHADOW]   proposed engagement={proposed_means['engagement_rate']:.4f}  "
              f"composite={proposed_composite:.4f}")

        # Step 7: Decide keep/discard
        improved = is_improvement(proposed_composite, composite, IMPROVEMENT_THRESHOLD)
        if improved:
            all_versions.append(proposed_prompt)
            current_version = proposed_version_num
            accepted = True
            reason = (f"Accepted: composite {composite:.4f} → {proposed_composite:.4f} "
                      f"(+{proposed_composite - composite:.4f})")
            print(f"  [DECISION] KEEP v{proposed_version_num} — {reason}")
        else:
            accepted = False
            reason = (f"Discarded: composite {composite:.4f} → {proposed_composite:.4f} "
                      f"(delta {proposed_composite - composite:+.4f} below threshold "
                      f"{IMPROVEMENT_THRESHOLD})")
            print(f"  [DECISION] DISCARD — {reason}")

        results.append(IterationResult(
            iteration=iteration,
            active_version=current_version if accepted else current_version,
            active_prompt_preview=current_prompt_text[:80].replace("\n", " "),
            metrics=metrics,
            metric_means=metric_means,
            composite_score=composite,
            analysis=analysis,
            proposed_version=proposed_version_num,
            proposed_prompt_preview=proposed_preview,
            safety_check=safety,
            template_vars_valid=vars_valid,
            similarity=similarity,
            accepted=accepted,
            reason=reason,
            baseline_score=baseline_score,
            delta=composite - baseline_score,
        ))

        # Update baseline for next iteration
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
        trend = "↑ improving" if score_delta > 0.001 else ("↓ declining" if score_delta < -0.001 else "→ stable")
        print(f"  First → last     : {scores[0]:.4f} → {scores[-1]:.4f}  ({score_delta:+.4f})  {trend}")

    # Convergence check
    if len(scores) >= 4:
        last_3 = scores[-3:]
        spread = max(last_3) - min(last_3)
        converged = spread < 0.005
        print(f"  Last-3 spread    : {spread:.4f}  → {'CONVERGED' if converged else 'still evolving'}")

    print("\n  Per-iteration table:")
    print(f"  {'Iter':>4}  {'v':>3}  {'Score':>7}  {'Delta':>7}  {'Accept':>6}  Reason")
    print(f"  {'─'*4}  {'─'*3}  {'─'*7}  {'─'*7}  {'─'*6}  {'─'*30}")
    for r in results:
        print(
            f"  {r.iteration:>4}  v{r.active_version:<2}  {r.composite_score:.4f}  "
            f"{r.delta:>+.4f}  {'YES' if r.accepted else 'no':>6}  "
            f"{r.reason[:50]}"
        )

    print("\n" + "=" * 70)
    if len(accepted) > 0:
        print("  CONCLUSION: Loop produced improvements — optimization is working.")
    else:
        print("  CONCLUSION: No improvements accepted — check threshold or proposals.")
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

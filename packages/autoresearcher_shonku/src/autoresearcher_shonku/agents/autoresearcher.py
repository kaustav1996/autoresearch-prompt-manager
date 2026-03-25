"""AutoResearcherAgent -- orchestrator for autonomous prompt optimization."""

from __future__ import annotations

import json
from difflib import SequenceMatcher

from shonku.agent import ShonkuAgent
from shonku.decorators import tool


class AutoResearcherAgent(ShonkuAgent):
    """Autonomous prompt optimization loop following the autoresearch pattern.

    This is the top-level orchestrator that coordinates analysis, proposal
    generation, safety checking, experimentation, and evaluation.
    """

    name = "autoresearcher"
    description = "Autonomous prompt optimization loop following the autoresearch pattern"
    version = "0.1.0"
    instructions = (
        "You are an autonomous prompt researcher. Your job is to continuously improve a prompt.\n\n"
        "Follow this loop:\n"
        "1. ANALYZE: Call analyze_prompt to get current performance analysis\n"
        "2. PROPOSE: Call propose_improvement to generate an improved version\n"
        "3. VALIDATE: Call check_safety to ensure the proposal is safe\n"
        "4. DEPLOY: Call deploy_experiment to shadow-test the new version\n"
        "5. EVALUATE: Call evaluate_experiment to check if it improved\n"
        "6. DECIDE: If improved, keep. If not, discard.\n\n"
        "After each iteration, report your findings. Keep going until you've completed "
        "the requested number of iterations or run out of ideas.\n\n"
        "Use check_safety_rails before deploying any change. Never skip safety checks."
    )

    required_tools = [
        "get_prompt",
        "get_metrics",
        "get_sample_interactions",
        "create_version",
        "create_experiment",
        "conclude_experiment",
    ]
    max_steps = 100

    @tool(description="Check safety rails before deploying")
    def check_safety_rails(
        self,
        original_prompt: str,
        proposed_prompt: str,
        iteration: str,
        max_iterations: str,
    ) -> str:
        """Check if the proposed change is safe to deploy.

        Parameters
        ----------
        original_prompt:
            The current prompt text.
        proposed_prompt:
            The proposed replacement text.
        iteration:
            Current iteration number (as string).
        max_iterations:
            Maximum allowed iterations (as string).
        """
        similarity = SequenceMatcher(None, original_prompt, proposed_prompt).ratio()
        iteration_num = int(iteration)
        max_iter = int(max_iterations)
        original_len = max(len(original_prompt), 1)

        checks = {
            "similarity_ok": similarity >= 0.3,
            "not_empty": len(proposed_prompt.strip()) > 10,
            "within_budget": iteration_num <= max_iter,
            "length_reasonable": 0.3 <= len(proposed_prompt) / original_len <= 3.0,
        }

        all_passed = all(checks.values())
        return json.dumps({
            "safe": all_passed,
            "checks": checks,
            "similarity": round(similarity, 3),
        })

"""ExperimentManagerAgent -- manages prompt experiment lifecycle."""

from __future__ import annotations

from shonku.agent import ShonkuAgent


class ExperimentManagerAgent(ShonkuAgent):
    """Manages A/B experiments for prompt optimization."""

    name = "experiment-manager"
    description = "Manages prompt experiment lifecycle"
    instructions = (
        "You manage A/B experiments for prompt optimization.\n"
        "1. Create experiments with create_experiment\n"
        "2. Monitor metrics with get_metrics\n"
        "3. Conclude experiments with conclude_experiment\n\n"
        "Respond with JSON: "
        '{"action": "created|monitoring|concluded", '
        '"experiment_id": "...", "winner_version": "..."|null}'
    )

    required_tools = [
        "create_experiment",
        "get_metrics",
        "conclude_experiment",
        "create_version",
    ]

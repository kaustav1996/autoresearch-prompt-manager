"""Agent definitions for autoresearcher-shonku."""

from autoresearcher_shonku.agents.analyzer import PromptAnalyzerAgent
from autoresearcher_shonku.agents.autoresearcher import AutoResearcherAgent
from autoresearcher_shonku.agents.experiment_mgr import ExperimentManagerAgent
from autoresearcher_shonku.agents.optimizer import PromptOptimizerAgent

__all__ = [
    "AutoResearcherAgent",
    "ExperimentManagerAgent",
    "PromptAnalyzerAgent",
    "PromptOptimizerAgent",
]

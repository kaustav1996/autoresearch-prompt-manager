"""autoresearcher-shonku: Optimization agents for autonomous prompt improvement."""

from autoresearcher_shonku.agents.analyzer import PromptAnalyzerAgent
from autoresearcher_shonku.agents.autoresearcher import AutoResearcherAgent
from autoresearcher_shonku.agents.experiment_mgr import ExperimentManagerAgent
from autoresearcher_shonku.agents.optimizer import PromptOptimizerAgent
from autoresearcher_shonku.config import AutoResearcherConfig

__all__ = [
    "AutoResearcherAgent",
    "AutoResearcherConfig",
    "ExperimentManagerAgent",
    "PromptAnalyzerAgent",
    "PromptOptimizerAgent",
]

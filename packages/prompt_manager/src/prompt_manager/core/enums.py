"""Status enums used across the prompt-manager domain."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        """Backport of StrEnum for Python 3.10."""
        pass


class ExperimentStatus(StrEnum):
    """Lifecycle states of an experiment."""

    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    CONCLUDED = "concluded"


class VersionSource(StrEnum):
    """How a prompt version was created."""

    MANUAL = "manual"
    OPTIMIZATION = "optimization"
    ROLLBACK = "rollback"


class OptimizationRunStatus(StrEnum):
    """Status of an optimization run."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"

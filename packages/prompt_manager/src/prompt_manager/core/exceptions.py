"""Domain exceptions for the prompt-manager."""

from __future__ import annotations


class PromptManagerError(Exception):
    """Base class for all prompt-manager errors."""


class PromptNotFoundError(PromptManagerError):
    """Raised when a prompt slug cannot be resolved."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Prompt not found: {slug}")


class VersionNotFoundError(PromptManagerError):
    """Raised when a specific version does not exist."""

    def __init__(self, prompt_slug: str, version: int) -> None:
        self.prompt_slug = prompt_slug
        self.version = version
        super().__init__(f"Version {version} not found for prompt '{prompt_slug}'")


class DuplicateSlugError(PromptManagerError):
    """Raised when creating a prompt with a slug that already exists."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Prompt slug already exists: {slug}")


class DuplicateContentError(PromptManagerError):
    """Raised when a version body is identical to the current version."""

    def __init__(self, content_hash: str) -> None:
        self.content_hash = content_hash
        super().__init__(f"Duplicate content detected (hash={content_hash})")


class ExperimentNotFoundError(PromptManagerError):
    """Raised when an experiment cannot be found."""

    def __init__(self, experiment_id: str) -> None:
        self.experiment_id = experiment_id
        super().__init__(f"Experiment not found: {experiment_id}")


class ExperimentStateError(PromptManagerError):
    """Raised for invalid experiment state transitions."""

    def __init__(self, current: str, desired: str) -> None:
        self.current = current
        self.desired = desired
        super().__init__(f"Cannot transition from '{current}' to '{desired}'")


class InvalidWeightsError(PromptManagerError):
    """Raised when experiment arm weights do not sum to 100."""

    def __init__(self, total: float) -> None:
        self.total = total
        super().__init__(f"Arm weights must sum to 100, got {total}")

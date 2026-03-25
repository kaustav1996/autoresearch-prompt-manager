"""Error types for autoresearcher-shonku."""

from __future__ import annotations


class AutoResearcherError(Exception):
    """Base exception for all autoresearcher errors."""


class AnalysisError(AutoResearcherError):
    """Raised when prompt analysis fails."""

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        self.cause = cause
        super().__init__(message)


class ProposalError(AutoResearcherError):
    """Raised when a prompt improvement proposal is invalid."""

    def __init__(self, message: str, missing_vars: list[str] | None = None) -> None:
        self.missing_vars = missing_vars or []
        super().__init__(message)


class SafetyError(AutoResearcherError):
    """Raised when a safety check fails."""

    def __init__(self, message: str, failed_checks: dict[str, bool] | None = None) -> None:
        self.failed_checks = failed_checks or {}
        super().__init__(message)


class ScoringError(AutoResearcherError):
    """Raised when composite scoring encounters invalid data."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class ExperimentError(AutoResearcherError):
    """Raised when experiment management fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message)

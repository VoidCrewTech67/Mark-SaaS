"""
optimizer/exceptions.py – Framework-specific exception hierarchy.

All framework exceptions inherit from ``OptimizationError`` so callers can
use a single ``except OptimizationError`` to catch everything, or narrow
down to a specific subclass.
"""

from __future__ import annotations


class OptimizationError(Exception):
    """Base exception for the optimization framework."""


# ── Registry exceptions ──────────────────────────────────────────────────────


class PassNotFoundError(OptimizationError):
    """Raised when a pass name cannot be found in the registry."""

    def __init__(self, name: str) -> None:
        self.pass_name = name
        super().__init__(f"No pass registered with name '{name}'")


class PassAlreadyRegisteredError(OptimizationError):
    """Raised when attempting to register a pass name that already exists."""

    def __init__(self, name: str) -> None:
        self.pass_name = name
        super().__init__(
            f"A pass named '{name}' is already registered. "
            f"Use force=True to override, or unregister it first."
        )


# ── Configuration exceptions ─────────────────────────────────────────────────


class PassConfigError(OptimizationError):
    """Raised when a pass configuration is invalid."""

    def __init__(self, pass_name: str, reason: str) -> None:
        self.pass_name = pass_name
        self.reason = reason
        super().__init__(f"Invalid config for pass '{pass_name}': {reason}")


# ── Execution exceptions ─────────────────────────────────────────────────────


class PassExecutionError(OptimizationError):
    """Raised when a pass fails during execution."""

    def __init__(
        self,
        pass_name: str,
        reason: str,
        original_error: Exception | None = None,
    ) -> None:
        self.pass_name = pass_name
        self.reason = reason
        self.original_error = original_error
        super().__init__(f"Pass '{pass_name}' failed: {reason}")


class PipelineError(OptimizationError):
    """Raised for pipeline-level orchestration failures."""

    def __init__(
        self,
        reason: str,
        errors: list[Exception] | None = None,
    ) -> None:
        self.reason = reason
        self.errors = errors or []
        super().__init__(f"Pipeline error: {reason}")

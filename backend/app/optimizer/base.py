"""
optimizer/base.py – OptimizerPass abstract base class.

Every optimization pass must subclass ``OptimizerPass`` and implement:

    - ``name``           (property)  → unique identifier string
    - ``description``    (property)  → human-readable purpose
    - ``default_config`` (property)  → PassConfig with defaults
    - ``run(ctx, config)``           → execute the pass, return updated context

Optional override:

    - ``validate_config(config)``    → raise PassConfigError if invalid
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.optimizer.exceptions import PassConfigError
from app.optimizer.models import OptimizationContext, PassConfig


class OptimizerPass(ABC):
    """Abstract base class for all optimization passes.

    Passes are **stateless** — all mutable state flows through the
    ``OptimizationContext``.  This makes passes safe to reuse across
    pipeline runs and simplifies testing.

    Example::

        class StripWhitespacePass(OptimizerPass):
            @property
            def name(self) -> str:
                return "strip_whitespace"

            @property
            def description(self) -> str:
                return "Remove trailing whitespace from every line."

            @property
            def default_config(self) -> PassConfig:
                return PassConfig(priority=10)

            def run(
                self,
                ctx: OptimizationContext,
                config: PassConfig,
            ) -> OptimizationContext:
                import re
                ctx.content = re.sub(r"[ \\t]+$", "", ctx.content, flags=re.MULTILINE)
                return ctx
    """

    # ── Abstract interface ────────────────────────────────────────────────

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this pass (e.g. ``'strip_whitespace'``).

        Must be a valid Python identifier and unique within the registry.
        """

    @property
    @abstractmethod
    def description(self) -> str:
        """Short human-readable description of what this pass does."""

    @property
    @abstractmethod
    def default_config(self) -> PassConfig:
        """Default configuration for this pass.

        The pipeline executor merges per-pipeline overrides on top of
        this default before calling ``run()``.
        """

    @abstractmethod
    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        """Execute the optimization pass.

        Implementations should:
        1. Read ``ctx.content`` (the current markdown).
        2. Apply transformations.
        3. Write the result back to ``ctx.content``.
        4. Optionally update ``ctx.metadata`` for downstream passes.
        5. Return ``ctx``.

        **Do not** modify ``ctx.original_content`` or ``ctx.pass_history``
        — the pipeline executor manages those.

        Args:
            ctx:    The current optimization context.
            config: Merged configuration (defaults + overrides).

        Returns:
            The same ``OptimizationContext`` instance with updated content.

        Raises:
            PassExecutionError: If the pass encounters an unrecoverable error.
        """

    # ── Optional hooks ────────────────────────────────────────────────────

    def validate_config(self, config: PassConfig) -> None:
        """Validate the merged configuration before execution.

        Override this method to enforce pass-specific constraints on
        ``config.params``.  The default implementation is a no-op.

        Args:
            config: The merged PassConfig to validate.

        Raises:
            PassConfigError: If the configuration is invalid.
        """

    # ── Dunder helpers ────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name={self.name!r})>"

    def __str__(self) -> str:
        return self.name

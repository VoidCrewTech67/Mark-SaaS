"""
optimizer/passes/_example.py – Example pass (not auto-discovered).

This file demonstrates how to implement an ``OptimizerPass``.
It is prefixed with ``_`` so ``PassRegistry.discover()`` skips it.

To register it for real, either:
  1. Rename the file (remove the underscore prefix), or
  2. Import it explicitly somewhere, or
  3. Call ``PassRegistry().register(ExampleUpperCasePass)`` manually.

───────────────────────────────────────────────────────────────────────

HOW TO WRITE A NEW PASS
========================

1. Create a new file in ``app/optimizer/passes/`` (e.g. ``strip_ocr.py``).
2. Subclass ``OptimizerPass``.
3. Implement the four required members:
   - ``name``           → unique string identifier
   - ``description``    → human-readable purpose
   - ``default_config`` → PassConfig with sensible defaults
   - ``run()``          → the transformation logic
4. Optionally override ``validate_config()`` for custom validation.
5. Decorate with ``@register_pass`` for automatic registration.

The pass below is a minimal working example.
"""

from __future__ import annotations

from app.optimizer.base import OptimizerPass
from app.optimizer.exceptions import PassConfigError
from app.optimizer.models import OptimizationContext, PassConfig

# NOTE: No @register_pass decorator — this is intentionally NOT registered.
#       Add the decorator when you want it active.


class ExampleUpperCasePass(OptimizerPass):
    """Example pass that converts headings to uppercase.

    This is a trivial example purely for demonstration.  Real passes
    would do things like stripping OCR artifacts, deduplicating content,
    normalising Unicode, etc.

    Config params:
        heading_levels (list[int]): Which heading levels to transform.
            Default: [1, 2] (only H1 and H2).
    """

    @property
    def name(self) -> str:
        return "example_uppercase_headings"

    @property
    def description(self) -> str:
        return "Convert heading text to UPPERCASE (example/demo pass)."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=999,  # low priority — just an example
            params={
                "heading_levels": [1, 2],
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        """Ensure heading_levels is a non-empty list of ints 1–6."""
        levels = config.params.get("heading_levels", [])
        if not isinstance(levels, list) or not levels:
            raise PassConfigError(
                self.name,
                "params.heading_levels must be a non-empty list of ints.",
            )
        for level in levels:
            if not isinstance(level, int) or not (1 <= level <= 6):
                raise PassConfigError(
                    self.name,
                    f"Invalid heading level: {level}. Must be 1–6.",
                )

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        """Transform heading text to uppercase for configured levels."""
        import re

        levels: list[int] = config.params.get("heading_levels", [1, 2])
        lines = ctx.content.splitlines(keepends=True)
        result: list[str] = []

        for line in lines:
            stripped = line.strip()
            for level in levels:
                prefix = "#" * level + " "
                if stripped.startswith(prefix):
                    # Preserve leading whitespace and the prefix
                    heading_text = stripped[len(prefix):]
                    line = line[: line.index(prefix)] + prefix + heading_text.upper()
                    if not line.endswith("\n") and lines[-1] != line:
                        line += "\n"
                    break
            result.append(line)

        ctx.content = "".join(result)
        return ctx

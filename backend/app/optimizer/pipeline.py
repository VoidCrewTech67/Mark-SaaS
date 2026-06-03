"""
optimizer/pipeline.py – Pipeline executor (orchestration engine).

``PipelineExecutor`` resolves passes from the registry, merges configs,
and executes them in order against an ``OptimizationContext``.

Usage::

    from app.optimizer.pipeline import PipelineExecutor
    from app.optimizer.config import PipelineConfig
    from app.optimizer.registry import PassRegistry

    config = PipelineConfig(pass_order=["strip_ocr", "deduplicate"])
    executor = PipelineExecutor(registry=PassRegistry(), config=config)

    result = executor.run("# Hello\\n\\n\\n\\nWorld")
    print(result.output)
    print(result.report.summary())
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.optimizer.base import OptimizerPass
from app.optimizer.config import PipelineConfig
from app.optimizer.exceptions import (
    PassConfigError,
    PassExecutionError,
    PipelineError,
)
from app.optimizer.models import (
    OptimizationContext,
    PassConfig,
    PassStatistics,
    PipelineResult,
)
from app.optimizer.registry import PassRegistry
from app.optimizer.report import ReportGenerator

logger = logging.getLogger(__name__)


class PipelineExecutor:
    """Orchestrates the execution of optimization passes.

    The executor is **reusable** — you can call ``run()`` multiple times
    with different inputs.  It is also **reconfigurable** via
    ``with_config()`` which returns a new executor sharing the same
    registry.

    Attributes:
        registry: The ``PassRegistry`` to resolve pass names from.
        config:   The ``PipelineConfig`` governing this execution.
    """

    def __init__(
        self,
        registry: PassRegistry | None = None,
        config: PipelineConfig | None = None,
    ) -> None:
        self._registry = registry or PassRegistry()
        self._config = config or PipelineConfig()
        self._report_generator = ReportGenerator()

    # ── Public properties ─────────────────────────────────────────────────

    @property
    def registry(self) -> PassRegistry:
        return self._registry

    @property
    def config(self) -> PipelineConfig:
        return self._config

    # ── Configuration helpers ─────────────────────────────────────────────

    def with_config(self, config: PipelineConfig) -> PipelineExecutor:
        """Return a new executor with a different config (same registry)."""
        return PipelineExecutor(registry=self._registry, config=config)

    # ── Main execution ────────────────────────────────────────────────────

    def run(
        self,
        content: str,
        metadata: Dict[str, Any] | None = None,
    ) -> PipelineResult:
        """Execute the full optimization pipeline.

        Args:
            content:  Raw markdown string to optimise.
            metadata: Optional metadata dict passed to the context.

        Returns:
            ``PipelineResult`` containing the output, context, report,
            and any errors.
        """
        started_at = datetime.now(timezone.utc)
        errors: List[str] = []

        # Build context
        ctx = OptimizationContext(
            content=content,
            original_content=content,
            metadata=metadata or {},
        )

        if not self._config.pass_order:
            logger.info("Pipeline has no passes configured; returning input as-is.")
            completed_at = datetime.now(timezone.utc)
            report = self._report_generator.build(
                context=ctx,
                started_at=started_at,
                completed_at=completed_at,
                errors=errors,
            )
            return PipelineResult(
                output=content,
                context=ctx,
                report=report,
                success=True,
                errors=errors,
            )

        # Execute passes in order
        for pass_name in self._config.pass_order:
            ctx, pass_errors = self._execute_pass(pass_name, ctx)
            errors.extend(pass_errors)

            if pass_errors and self._config.fail_fast:
                logger.error(
                    "Pipeline stopping (fail_fast=True) after error in '%s'.",
                    pass_name,
                )
                break

        completed_at = datetime.now(timezone.utc)

        # Build report
        report = self._report_generator.build(
            context=ctx,
            started_at=started_at,
            completed_at=completed_at,
            errors=errors,
        )

        success = len(errors) == 0

        logger.info(
            "Pipeline completed: %s | %s",
            "SUCCESS" if success else f"ERRORS ({len(errors)})",
            report.summary(),
        )

        return PipelineResult(
            output=ctx.content,
            context=ctx,
            report=report,
            success=success,
            errors=errors,
        )

    # ── Single-pass convenience ───────────────────────────────────────────

    def run_single_pass(
        self,
        name: str,
        content: str,
        config_overrides: Dict[str, Any] | None = None,
    ) -> str:
        """Execute a single pass by name and return the result string.

        This is a convenience method for running one pass in isolation,
        useful for debugging or testing individual passes.

        Args:
            name:             The registered pass name.
            content:          Markdown input.
            config_overrides: Optional dict merged on top of the pass defaults.

        Returns:
            The optimized string after the single pass.

        Raises:
            PassNotFoundError: If the pass is not registered.
            PassExecutionError: If the pass fails.
        """
        single_config = PipelineConfig(
            pass_order=[name],
            pass_configs=(
                {name: PassConfig.model_validate(config_overrides)}
                if config_overrides
                else {}
            ),
            fail_fast=True,
            collect_statistics=False,
        )
        executor = self.with_config(single_config)
        result = executor.run(content)

        if not result.success:
            raise PassExecutionError(
                pass_name=name,
                reason="; ".join(result.errors),
            )
        return result.output

    # ── Dry run ───────────────────────────────────────────────────────────

    def dry_run(self, content: str | None = None) -> List[str]:
        """Return the ordered list of pass names that *would* execute.

        Respects the ``enabled`` flag in both default and override configs.
        Passes that would be skipped due to ``enabled=False`` are excluded.

        Args:
            content: Unused (accepted for API consistency). May be used
                     in the future for content-dependent pass selection.

        Returns:
            List of pass names in execution order.
        """
        result: List[str] = []
        for pass_name in self._config.pass_order:
            merged_config = self._resolve_config(pass_name)
            if merged_config is not None and merged_config.enabled:
                result.append(pass_name)
        return result

    # ── Internal execution ────────────────────────────────────────────────

    def _execute_pass(
        self,
        pass_name: str,
        ctx: OptimizationContext,
    ) -> tuple[OptimizationContext, List[str]]:
        """Execute a single pass and record statistics.

        Returns (updated_context, list_of_error_strings).
        """
        errors: List[str] = []

        # 1. Resolve pass class from registry
        try:
            pass_cls = self._registry.get(pass_name)
        except Exception as exc:
            msg = f"Pass '{pass_name}': {exc}"
            errors.append(msg)
            logger.error(msg)
            ctx.add_pass_result(PassStatistics(
                pass_name=pass_name,
                skipped=True,
                skip_reason=f"Not found in registry: {exc}",
            ))
            return ctx, errors

        pass_instance: OptimizerPass = pass_cls()

        # 2. Resolve merged config
        merged_config = self._resolve_config_for_pass(pass_instance)

        # 3. Check enabled
        if not merged_config.enabled:
            logger.debug("Pass '%s' is disabled; skipping.", pass_name)
            ctx.add_pass_result(PassStatistics(
                pass_name=pass_name,
                skipped=True,
                skip_reason="Disabled via config",
            ))
            return ctx, errors

        # 4. Validate config
        try:
            pass_instance.validate_config(merged_config)
        except PassConfigError:
            raise
        except Exception as exc:
            msg = f"Config validation failed for '{pass_name}': {exc}"
            errors.append(msg)
            logger.error(msg)
            ctx.add_pass_result(PassStatistics(
                pass_name=pass_name,
                skipped=True,
                skip_reason=f"Config validation failed: {exc}",
            ))
            return ctx, errors

        # 5. Measure before-state
        chars_before = len(ctx.content)
        tokens_before = self._estimate_tokens(ctx.content) if self._config.collect_statistics else 0

        # 6. Execute
        t0 = time.perf_counter()
        try:
            ctx = pass_instance.run(ctx, merged_config)
        except PassExecutionError:
            raise
        except Exception as exc:
            duration = time.perf_counter() - t0
            msg = f"Pass '{pass_name}' raised {type(exc).__name__}: {exc}"
            errors.append(msg)
            logger.exception("Pass '%s' failed after %.3fs", pass_name, duration)
            ctx.add_pass_result(PassStatistics(
                pass_name=pass_name,
                duration_s=round(duration, 4),
                chars_before=chars_before,
                chars_after=len(ctx.content),
                tokens_before=tokens_before,
                tokens_after=tokens_before,  # unchanged on error
                skipped=False,
                custom_metrics={"error": str(exc)},
            ))
            return ctx, errors

        duration = time.perf_counter() - t0

        # 7. Measure after-state
        chars_after = len(ctx.content)
        tokens_after = self._estimate_tokens(ctx.content) if self._config.collect_statistics else 0

        # 8. Collect custom metrics deposited by the pass (convention-based)
        metrics_key = f"_pass_metrics_{pass_name}"
        custom_metrics = ctx.metadata.pop(metrics_key, {})

        # 9. Record statistics
        stats = PassStatistics(
            pass_name=pass_name,
            duration_s=round(duration, 4),
            chars_before=chars_before,
            chars_after=chars_after,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            custom_metrics=custom_metrics,
        )
        ctx.add_pass_result(stats)

        logger.debug(
            "Pass '%s' completed in %.3fs | %d→%d tokens (-%d, %.1f%%)",
            pass_name, duration,
            tokens_before, tokens_after,
            stats.tokens_saved, stats.percent_saved,
        )

        return ctx, errors

    # ── Config resolution ─────────────────────────────────────────────────

    def _resolve_config_for_pass(self, pass_instance: OptimizerPass) -> PassConfig:
        """Merge the pass's default_config with any pipeline-level overrides."""
        default = pass_instance.default_config
        override = self._config.get_pass_config(pass_instance.name)

        if override is None:
            return default

        return default.merge(override.model_dump(exclude_defaults=False))

    def _resolve_config(self, pass_name: str) -> Optional[PassConfig]:
        """Resolve config for a pass by name (for dry_run)."""
        try:
            pass_cls = self._registry.get(pass_name)
        except Exception:
            return None

        instance = pass_cls()
        return self._resolve_config_for_pass(instance)

    # ── Token estimation ──────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Estimate token count using the project's token counter.

        Lazily imports to avoid hard coupling — falls back to chars/4
        if the token_counter module is unavailable.
        """
        try:
            from app.utils.token_counter import estimate_tokens
            return estimate_tokens(text)
        except ImportError:
            return max(1, len(text) // 4) if text else 0

    # ── Dunder ────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<PipelineExecutor "
            f"passes={self._config.pass_order} "
            f"registry_size={self._registry.size}>"
        )

"""
optimizer/models.py – Data models for the optimization framework.

Provides:
  - ``PassConfig``           – per-pass configuration (enabled, priority, params).
  - ``PassStatistics``       – immutable record of a single pass execution.
  - ``OptimizationContext``  – mutable document flowing through the pipeline.
  - ``PipelineResult``       – final result returned by the executor.
  - ``PipelineReport``       – aggregate statistics and formatted reports.
  - ``PassInfo``             – lightweight descriptor for registry introspection.

All models use Pydantic v2 for validation and serialization.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


# ── Per-pass configuration ────────────────────────────────────────────────────


class PassConfig(BaseModel):
    """Configuration for a single optimizer pass.

    Attributes:
        enabled:  Whether this pass should be executed.
        priority: Numeric priority for secondary sorting (lower runs first).
        params:   Arbitrary key-value parameters consumed by the pass.
    """

    enabled: bool = True
    priority: int = 100
    params: Dict[str, Any] = Field(default_factory=dict)

    def merge(self, overrides: Dict[str, Any]) -> PassConfig:
        """Return a *new* PassConfig with ``overrides`` applied on top.

        Top-level keys (enabled, priority) are replaced directly.
        ``params`` dicts are shallow-merged (override keys win).
        """
        merged_data = self.model_dump()

        override_params = overrides.pop("params", None)
        merged_data.update(overrides)

        if override_params is not None:
            merged_data["params"] = {**merged_data.get("params", {}), **override_params}

        return PassConfig.model_validate(merged_data)


# ── Per-pass execution statistics ─────────────────────────────────────────────


class PassStatistics(BaseModel, frozen=True):
    """Immutable record of a single pass execution.

    Attributes:
        pass_name:      Name of the pass that produced these stats.
        duration_s:     Wall-clock execution time in seconds.
        chars_before:   Character count before the pass.
        chars_after:    Character count after the pass.
        tokens_before:  Token count before the pass.
        tokens_after:   Token count after the pass.
        skipped:        Whether the pass was skipped (disabled, etc.).
        skip_reason:    Human-readable reason if skipped.
        custom_metrics: Pass-specific metrics (e.g. "duplicate_headings_removed": 4).
    """

    pass_name: str
    duration_s: float = 0.0
    chars_before: int = 0
    chars_after: int = 0
    tokens_before: int = 0
    tokens_after: int = 0
    skipped: bool = False
    skip_reason: str = ""
    custom_metrics: Dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tokens_saved(self) -> int:
        """Tokens removed by this pass (non-negative)."""
        return max(0, self.tokens_before - self.tokens_after)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def percent_saved(self) -> float:
        """Percentage of tokens removed by this pass."""
        if self.tokens_before == 0:
            return 0.0
        return round(self.tokens_saved / self.tokens_before * 100, 2)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def chars_saved(self) -> int:
        """Characters removed by this pass (non-negative)."""
        return max(0, self.chars_before - self.chars_after)


# ── Optimization context ─────────────────────────────────────────────────────


class OptimizationContext(BaseModel):
    """Mutable document that flows through the optimization pipeline.

    Each pass receives the context, mutates ``content`` (and optionally
    ``metadata``), and the executor records a ``PassStatistics`` entry
    into ``pass_history``.

    Attributes:
        content:          Current markdown content (mutated by each pass).
        original_content: Snapshot of the input before any passes ran.
        metadata:         Arbitrary metadata dict for inter-pass communication.
        pass_history:     Ordered list of per-pass statistics.
    """

    content: str = ""
    original_content: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    pass_history: List[PassStatistics] = Field(default_factory=list)

    def add_pass_result(self, stats: PassStatistics) -> None:
        """Append a ``PassStatistics`` entry to the history."""
        self.pass_history.append(stats)

    def total_tokens_saved(self) -> int:
        """Total tokens saved across all executed (non-skipped) passes."""
        if not self.pass_history:
            return 0
        first = next((s for s in self.pass_history if not s.skipped), None)
        last = next((s for s in reversed(self.pass_history) if not s.skipped), None)
        if first is None or last is None:
            return 0
        return max(0, first.tokens_before - last.tokens_after)

    def total_percent_saved(self) -> float:
        """Percentage of tokens saved across the entire pipeline."""
        if not self.pass_history:
            return 0.0
        first = next((s for s in self.pass_history if not s.skipped), None)
        if first is None or first.tokens_before == 0:
            return 0.0
        return round(self.total_tokens_saved() / first.tokens_before * 100, 2)


# ── Pipeline report ──────────────────────────────────────────────────────────


class PipelineReport(BaseModel, frozen=True):
    """Aggregate report for a complete pipeline execution.

    Attributes:
        pipeline_id:        Unique identifier for this run.
        started_at:         UTC timestamp when the pipeline started.
        completed_at:       UTC timestamp when the pipeline finished.
        total_duration_s:   Wall-clock time for the entire pipeline.
        total_tokens_before: Token count of the original input.
        total_tokens_after:  Token count of the final output.
        total_tokens_saved:  Tokens removed across all passes.
        total_percent_saved: Percentage reduction.
        pass_details:        Per-pass statistics in execution order.
        errors:              Error messages collected during execution.
    """

    pipeline_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_duration_s: float = 0.0
    total_tokens_before: int = 0
    total_tokens_after: int = 0
    total_tokens_saved: int = 0
    total_percent_saved: float = 0.0
    total_chars_before: int = 0
    total_chars_after: int = 0
    pass_details: List[PassStatistics] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return self.model_dump(mode="json")

    def to_markdown(self) -> str:
        """Render a human-readable Markdown report."""
        lines: list[str] = [
            f"# Optimization Report — `{self.pipeline_id}`",
            "",
            f"**Started:** {self.started_at.isoformat()}  ",
            f"**Completed:** {self.completed_at.isoformat()}  ",
            f"**Duration:** {self.total_duration_s:.3f}s  ",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Tokens before | {self.total_tokens_before:,} |",
            f"| Tokens after | {self.total_tokens_after:,} |",
            f"| Tokens saved | {self.total_tokens_saved:,} |",
            f"| Reduction | {self.total_percent_saved:.1f}% |",
            f"| Characters before | {self.total_chars_before:,} |",
            f"| Characters after | {self.total_chars_after:,} |",
            "",
        ]

        if self.pass_details:
            lines.extend([
                "## Pass Details",
                "",
                "| # | Pass | Duration | Tokens In | Tokens Out | Saved | Status |",
                "|---|------|----------|-----------|------------|-------|--------|",
            ])
            for i, ps in enumerate(self.pass_details, 1):
                status = "⏭ Skipped" if ps.skipped else "✅ OK"
                if ps.skipped:
                    lines.append(
                        f"| {i} | {ps.pass_name} | — | — | — | — | {status}: {ps.skip_reason} |"
                    )
                else:
                    lines.append(
                        f"| {i} | {ps.pass_name} | {ps.duration_s:.3f}s "
                        f"| {ps.tokens_before:,} | {ps.tokens_after:,} "
                        f"| {ps.tokens_saved:,} ({ps.percent_saved:.1f}%) | {status} |"
                    )
            lines.append("")

        if self.errors:
            lines.extend(["## Errors", ""])
            for err in self.errors:
                lines.append(f"- ❌ {err}")
            lines.append("")

        return "\n".join(lines)

    def summary(self) -> str:
        """One-line summary string."""
        n_executed = sum(1 for p in self.pass_details if not p.skipped)
        n_skipped = sum(1 for p in self.pass_details if p.skipped)
        return (
            f"Pipeline {self.pipeline_id}: "
            f"{n_executed} passes executed, {n_skipped} skipped | "
            f"{self.total_tokens_before:,} → {self.total_tokens_after:,} tokens "
            f"({self.total_percent_saved:.1f}% saved) | "
            f"{self.total_duration_s:.3f}s"
        )


# ── Pipeline result ──────────────────────────────────────────────────────────


class PipelineResult(BaseModel):
    """Final result returned by ``PipelineExecutor.run()``.

    Attributes:
        output:   The optimized markdown string.
        context:  The full ``OptimizationContext`` (includes history).
        report:   Aggregate ``PipelineReport``.
        success:  Whether the pipeline completed without errors.
        errors:   Error messages (populated when ``fail_fast=False``).
    """

    output: str = ""
    context: OptimizationContext = Field(default_factory=OptimizationContext)
    report: PipelineReport = Field(default_factory=PipelineReport)
    success: bool = True
    errors: List[str] = Field(default_factory=list)


# ── Pass info (for registry introspection) ────────────────────────────────────


class PassInfo(BaseModel, frozen=True):
    """Lightweight descriptor for a registered pass.

    Used by ``PassRegistry.list_passes()`` for introspection without
    instantiating pass objects.
    """

    name: str
    description: str
    default_config: PassConfig

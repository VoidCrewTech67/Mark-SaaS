"""
optimizer/pipeline_v2.py – V2 pipeline with validation + rollback.

Architecture
============

::

    Input
     │
     ▼
    EquationExtractionPass ──── placeholders in
     │
     ▼
    OCRCleanupPass
     │
     ▼
    ContentBoilerplatePass
     │
     ▼
    BoilerplateSectionRemovalPass
     │
     ▼
    ReferenceSectionRemovalPass
     │
     ▼
    CitationRemovalPass
     │
     ▼
    SemanticTableTransformPass
     │
     ▼
    GlobalParagraphDeduplicationPass
     │
     ▼
    AbbreviationMiningPass
     │
     ▼
    ImportanceAwarePass
     │
     ▼
    EquationRestorationPass ──── placeholders out
     │
     ▼
    SemanticQualityValidator ──── rollback if below threshold
     │
     ▼
    Output + V2Report

Features:

1. **Pass-level metrics** — per-pass token delta, runtime, custom metrics.
2. **Rollback** — if validation fails, revert to pre-optimization content.
3. **Configurable** — enable/disable passes, custom thresholds, pass params.
4. **Benchmark** — total runtime, per-pass timing, throughput.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.optimizer.config import PipelineConfig
from app.optimizer.models import PassConfig, PassStatistics, PipelineResult
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry
from app.optimizer.validator import (
    SemanticQualityValidator,
    ValidationReport,
    ValidationThresholds,
)
from app.utils.token_counter import estimate_tokens

logger = logging.getLogger(__name__)


# ── Default V2 pass order ─────────────────────────────────────────────────────

DEFAULT_V2_PASSES = [
    "equation_extraction",
    "ocr_cleanup",
    "header_footer_detection",
    "content_boilerplate",
    "boilerplate_section_removal",
    "reference_section_removal",
    "citation_removal",
    "table_compression",
    "semantic_table_transform",
    "global_paragraph_deduplication",
    "abbreviation_mining",
    "importance_aware",
    "equation_restoration",
]


# ── Output ────────────────────────────────────────────────────────────────────

@dataclass
class V2Report:
    """Rich output report for pipeline V2."""

    original_tokens: int = 0
    optimized_tokens: int = 0
    reduction_percent: float = 0.0
    semantic_score: float = 0.0
    structure_score: float = 0.0
    equation_score: float = 0.0
    equations_preserved: bool = True
    tables_transformed: int = 0
    warnings: List[str] = field(default_factory=list)
    passed_validation: bool = True
    rolled_back: bool = False
    total_runtime_ms: float = 0.0
    pass_metrics: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "originalTokens": self.original_tokens,
            "optimizedTokens": self.optimized_tokens,
            "reductionPercent": round(self.reduction_percent, 2),
            "semanticScore": round(self.semantic_score, 4),
            "structureScore": round(self.structure_score, 4),
            "equationScore": round(self.equation_score, 4),
            "equationsPreserved": self.equations_preserved,
            "tablesTransformed": self.tables_transformed,
            "warnings": self.warnings,
            "passedValidation": self.passed_validation,
            "rolledBack": self.rolled_back,
            "totalRuntimeMs": round(self.total_runtime_ms, 1),
            "passMetrics": self.pass_metrics,
        }


# ── Pipeline V2 ──────────────────────────────────────────────────────────────

class OptimizerPipelineV2:
    """V2 pipeline with semantic validation and rollback.

    Parameters
    ----------
    pass_order : list[str], optional
        Custom pass order. Defaults to ``DEFAULT_V2_PASSES``.
    pass_configs : dict, optional
        Per-pass config overrides. Key = pass name, value = dict of
        PassConfig fields (e.g. ``{"params": {"remove_tier3": True}}``).
    thresholds : ValidationThresholds, optional
        Quality thresholds. Below → rollback.
    enable_validation : bool
        Run SemanticQualityValidator after pipeline.
    enable_rollback : bool
        Revert to original if validation fails.
    use_embeddings : bool
        Use sentence-transformers for semantic scoring.
    """

    def __init__(
        self,
        pass_order: List[str] | None = None,
        pass_configs: Dict[str, Any] | None = None,
        thresholds: ValidationThresholds | None = None,
        enable_validation: bool = True,
        enable_rollback: bool = True,
        use_embeddings: bool = False,
    ) -> None:
        # Use the singleton registry — discover passes into it
        self._registry = PassRegistry()
        self._registry.discover("app.optimizer.passes")

        self._pass_order = pass_order or list(DEFAULT_V2_PASSES)
        self._pass_configs = pass_configs or {}
        self._enable_validation = enable_validation
        self._enable_rollback = enable_rollback

        # Build pipeline config
        pc_map: Dict[str, PassConfig] = {}
        for name, overrides in self._pass_configs.items():
            if isinstance(overrides, dict):
                pc_map[name] = PassConfig(**overrides)
            else:
                pc_map[name] = overrides

        self._pipeline_config = PipelineConfig(
            pass_order=self._pass_order,
            pass_configs=pc_map,
            collect_statistics=True,
            fail_fast=False,
        )
        self._executor = PipelineExecutor(
            registry=self._registry,
            config=self._pipeline_config,
        )
        self._validator = SemanticQualityValidator(
            thresholds=thresholds or ValidationThresholds(),
            use_embeddings=use_embeddings,
        )

        logger.info(
            "[pipeline_v2] Initialized with %d passes, registry has %d total",
            len(self._pass_order),
            self._registry.size,
        )

    def run(self, content: str) -> tuple[str, V2Report]:
        """Run the full V2 pipeline.

        Returns (optimized_content, report).
        If validation fails and rollback is enabled, returns original content.
        """
        report = V2Report()
        t_start = time.perf_counter()

        # Token count original
        report.original_tokens = estimate_tokens(content)

        if not content.strip():
            report.total_runtime_ms = (time.perf_counter() - t_start) * 1000
            return content, report

        # ── Run pipeline ──────────────────────────────────────────────────
        pipeline_result: PipelineResult = self._executor.run(content)
        optimized = pipeline_result.output

        # ── Collect pass-level metrics ────────────────────────────────────
        report.pass_metrics = self._collect_pass_metrics(pipeline_result)

        # ── Extract table/equation metrics from pass data ─────────────────
        report.tables_transformed = self._extract_table_count(pipeline_result)

        # ── Token counts ──────────────────────────────────────────────────
        report.optimized_tokens = estimate_tokens(optimized)
        if report.original_tokens > 0:
            report.reduction_percent = (
                (report.original_tokens - report.optimized_tokens)
                / report.original_tokens * 100
            )

        # ── Semantic validation ───────────────────────────────────────────
        if self._enable_validation:
            validation: ValidationReport = self._validator.validate(
                content, optimized,
            )
            report.semantic_score = validation.semantic_score
            report.structure_score = validation.structure_score
            report.equation_score = validation.equation_score
            report.equations_preserved = validation.equation_score >= 0.95
            report.warnings = validation.warnings
            report.passed_validation = validation.passed

            if not validation.passed:
                report.warnings.append(
                    f"Validation failed: {validation.rejection_reasons}"
                )
                if self._enable_rollback:
                    logger.warning(
                        "[pipeline_v2] Validation failed — rolling back. "
                        "Reasons: %s",
                        validation.rejection_reasons,
                    )
                    optimized = content
                    report.rolled_back = True
                    report.optimized_tokens = report.original_tokens
                    report.reduction_percent = 0.0
        else:
            report.semantic_score = -1.0  # not computed
            report.passed_validation = True

        report.total_runtime_ms = (time.perf_counter() - t_start) * 1000

        logger.info(
            "[pipeline_v2] Done: %d→%d tokens (%.1f%%), "
            "semantic=%.3f, eq=%.3f, %.0fms%s",
            report.original_tokens, report.optimized_tokens,
            report.reduction_percent, report.semantic_score,
            report.equation_score, report.total_runtime_ms,
            " [ROLLED BACK]" if report.rolled_back else "",
        )

        return optimized, report

    # ── Pass metrics collection ───────────────────────────────────────────

    @staticmethod
    def _collect_pass_metrics(result: PipelineResult) -> List[Dict[str, Any]]:
        metrics: List[Dict[str, Any]] = []
        for detail in result.report.pass_details:
            metrics.append({
                "name": detail.pass_name,
                "runtime_ms": round(detail.duration_s * 1000, 2),
                "tokens_before": detail.tokens_before,
                "tokens_after": detail.tokens_after,
                "tokens_saved": detail.tokens_before - detail.tokens_after,
                "custom_metrics": detail.custom_metrics,
                "skipped": detail.skipped,
            })
        return metrics

    # ── Extract table count from pass metrics ─────────────────────────────

    @staticmethod
    def _extract_table_count(result: PipelineResult) -> int:
        for detail in result.report.pass_details:
            if detail.pass_name == "semantic_table_transform":
                return detail.custom_metrics.get("tables_transformed", 0)
            if detail.pass_name == "table_compression":
                return detail.custom_metrics.get("tables_compressed", 0)
        return 0

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def pass_order(self) -> List[str]:
        return list(self._pass_order)

    @property
    def available_passes(self) -> List[str]:
        return [p.name for p in self._registry.list_passes()]

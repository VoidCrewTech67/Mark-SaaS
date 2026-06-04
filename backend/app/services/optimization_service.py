"""
services/optimization_service.py

Universal, mode-aware optimization pipeline.

Modes:
  safe       — cleanup only (equation protection, OCR cleanup, headers/footers)
  balanced   — safe + reference/boilerplate removal + deduplication (DEFAULT)
  aggressive — balanced + table compression, abbreviations, semantic dedup
  rag        — balanced + structured extraction metadata

The optimizer is extractor-agnostic: it receives markdown and returns
optimized markdown, regardless of whether MarkItDown or Docling produced it.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from app.optimizer.config import PipelineConfig
from app.optimizer.models import PassConfig, PipelineResult
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry
from app.optimizer.report import OptimizationReportGenerator
from app.utils.optimizer import optimize_markdown, OptimizationStats

logger = logging.getLogger(__name__)

# ── Mode-to-pass mapping ─────────────────────────────────────────────────────
# Each mode is a superset of the previous (except RAG which branches).
# equation_extraction/restoration always bookend the pipeline.

_SAFE_PASSES = [
    "equation_extraction",       # FIRST — protect equations
    "ocr_cleanup",
    "header_footer_detection",
    "equation_restoration",      # LAST — restore equations
]

_BALANCED_PASSES = [
    "equation_extraction",
    "ocr_cleanup",
    "header_footer_detection",
    "content_boilerplate",
    "reference_section_removal",
    "boilerplate_section_removal",
    "citation_removal",
    "global_paragraph_deduplication",
    "equation_restoration",
]

_AGGRESSIVE_PASSES = [
    "equation_extraction",
    "ocr_cleanup",
    "header_footer_detection",
    "content_boilerplate",
    "reference_section_removal",
    "boilerplate_section_removal",
    "citation_removal",
    "table_compression",
    "semantic_table_transform",
    "global_paragraph_deduplication",
    "abbreviation_mining",
    "semantic_deduplication",
    "importance_aware",
    "equation_restoration",
]

# RAG = balanced passes (same quality) — structured extraction happens
# downstream in the chunking layer, not in the optimizer.
_RAG_PASSES = list(_BALANCED_PASSES)

_MODE_PASSES: dict[str, list[str]] = {
    "safe": _SAFE_PASSES,
    "balanced": _BALANCED_PASSES,
    "aggressive": _AGGRESSIVE_PASSES,
    "rag": _RAG_PASSES,
}

VALID_MODES = set(_MODE_PASSES.keys())

# Legacy default (full pipeline) — used when mode is None
_DEFAULT_PASS_ORDER = _BALANCED_PASSES


class OptimizationService:
    """Async facade over legacy optimizer + modular pipeline.

    Supports mode-based pass selection. The same service is used for
    both general_document and research_paper document types.
    """

    def __init__(
        self,
        pass_order: list[str] | None = None,
        pass_configs: Dict[str, PassConfig] | None = None,
        enable_pipeline: bool = True,
    ) -> None:
        self._enable_pipeline = enable_pipeline
        self._report_gen = OptimizationReportGenerator()
        self._pass_configs = pass_configs or {}

        # Discover all registered passes (once)
        self._registry = PassRegistry()
        self._registry.discover("app.optimizer.passes")

        # Build default pipeline config (can be overridden per-call via mode)
        self._default_pass_order = pass_order or _DEFAULT_PASS_ORDER
        self._pipeline_config = PipelineConfig(
            pass_order=self._default_pass_order,
            pass_configs=self._pass_configs,
            collect_statistics=True,
            fail_fast=False,
        )
        self._executor = PipelineExecutor(
            registry=self._registry,
            config=self._pipeline_config,
        )

        logger.info(
            "[optimization_service] Pipeline initialized with %d default passes: %s",
            len(self._default_pass_order),
            self._default_pass_order,
        )

    def _get_executor_for_mode(self, mode: str) -> PipelineExecutor:
        """Return a PipelineExecutor configured for the given mode."""
        passes = _MODE_PASSES.get(mode, _DEFAULT_PASS_ORDER)
        config = PipelineConfig(
            pass_order=passes,
            pass_configs=self._pass_configs,
            collect_statistics=True,
            fail_fast=False,
        )
        return PipelineExecutor(
            registry=self._registry,
            config=config,
        )

    async def optimize(
        self,
        markdown: str,
        mode: str = "balanced",
    ) -> tuple[str, OptimizationStats]:
        """Run full optimization pipeline asynchronously.

        1. Legacy ``optimize_markdown()`` (Unicode, OCR artifacts, page numbers)
        2. Mode-specific modular pipeline passes

        Args:
            markdown: Raw markdown from any extractor.
            mode: One of 'safe', 'balanced', 'aggressive', 'rag'.

        Returns (optimized_markdown, stats).
        """
        if mode not in VALID_MODES:
            logger.warning(
                "[optimization_service] Unknown mode '%s', falling back to 'balanced'",
                mode,
            )
            mode = "balanced"

        loop = asyncio.get_event_loop()

        # Step 1: Legacy cleanup (Unicode normalization, OCR artifacts, etc.)
        cleaned: str = await loop.run_in_executor(
            None, lambda: optimize_markdown(markdown),
        )

        # Step 2: Mode-specific modular pipeline
        if self._enable_pipeline:
            executor = self._get_executor_for_mode(mode)

            pipeline_result: PipelineResult = await loop.run_in_executor(
                None, lambda: executor.run(cleaned),
            )

            if pipeline_result.success:
                final = pipeline_result.output
            else:
                logger.warning(
                    "[optimization_service] Pipeline had errors (mode=%s): %s",
                    mode, pipeline_result.errors,
                )
                final = pipeline_result.output  # use partial result

            # Generate structured report for logging
            report_json = self._report_gen.from_report(pipeline_result.report)
            logger.info(
                "[optimization_service] mode=%s: tokens %d→%d (-%d, %.1f%%), "
                "%d passes, %d errors",
                mode,
                report_json["tokens"]["original"],
                report_json["tokens"]["optimized"],
                report_json["tokens"]["saved"],
                report_json["tokens"]["reduction_percent"],
                report_json["passes_executed"],
                len(report_json["errors"]),
            )
        else:
            final = cleaned

        stats = OptimizationStats(
            original_text=markdown,
            optimized_text=final,
        )

        # Step 3: Semantic preservation scoring
        try:
            from app.services.semantic_scoring import SemanticScoringService
            sem = await loop.run_in_executor(
                None, lambda: SemanticScoringService.score(markdown, final)
            )
            if sem is not None:
                stats.semantic_preservation = sem.semantic_preservation
                stats.semantic_loss         = sem.semantic_loss
                stats.context_preservation  = sem.context_preservation
                stats.overall_preservation  = sem.overall_preservation
                stats.scoring_method        = sem.method
                stats.context_breakdown     = sem.context_breakdown
                stats.issues                = [i.to_dict() for i in sem.issues]
                logger.info(
                    "[optimization_service] sem=%.1f%% ctx=%.1f%% overall=%.1f%% (%s)",
                    sem.semantic_preservation, sem.context_preservation,
                    sem.overall_preservation, sem.method,
                )
        except Exception as exc:
            logger.warning("[optimization_service] Semantic scoring failed: %s", exc)

        logger.info(
            "[optimization_service] mode=%s: total saved %d tokens (%.1f%%)",
            mode, stats.tokens_saved, stats.percent_saved,
        )
        return final, stats

    async def optimize_with_report(
        self,
        markdown: str,
        mode: str = "balanced",
    ) -> tuple[str, OptimizationStats, Dict[str, Any]]:
        """Like ``optimize()`` but also returns the structured JSON report."""
        if mode not in VALID_MODES:
            mode = "balanced"

        loop = asyncio.get_event_loop()

        cleaned: str = await loop.run_in_executor(
            None, lambda: optimize_markdown(markdown),
        )

        report_json: Dict[str, Any] = {}

        if self._enable_pipeline:
            executor = self._get_executor_for_mode(mode)
            pipeline_result: PipelineResult = await loop.run_in_executor(
                None, lambda: executor.run(cleaned),
            )
            final = pipeline_result.output
            report_json = self._report_gen.from_report(pipeline_result.report)
        else:
            final = cleaned

        stats = OptimizationStats(
            original_text=markdown,
            optimized_text=final,
        )

        # Semantic scoring
        try:
            from app.services.semantic_scoring import SemanticScoringService
            sem = await loop.run_in_executor(
                None, lambda: SemanticScoringService.score(markdown, final)
            )
            if sem is not None:
                stats.semantic_preservation = sem.semantic_preservation
                stats.semantic_loss         = sem.semantic_loss
                stats.context_preservation  = sem.context_preservation
                stats.overall_preservation  = sem.overall_preservation
                stats.scoring_method        = sem.method
                stats.context_breakdown     = sem.context_breakdown
                stats.issues                = [i.to_dict() for i in sem.issues]
        except Exception as exc:
            logger.warning("[optimization_service] Semantic scoring failed: %s", exc)

        return final, stats, report_json

    @property
    def available_passes(self) -> list[str]:
        """List all registered pass names."""
        return [p.name for p in self._registry.list_passes()]

    @property
    def active_passes(self) -> list[str]:
        """List passes in current default pipeline order."""
        return list(self._default_pass_order)

    @staticmethod
    def passes_for_mode(mode: str) -> list[str]:
        """Return the pass list for a given mode."""
        return list(_MODE_PASSES.get(mode, _DEFAULT_PASS_ORDER))

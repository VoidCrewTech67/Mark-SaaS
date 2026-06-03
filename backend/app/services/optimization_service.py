"""
services/optimization_service.py

Async wrapper around the modular optimization pipeline.

Runs the legacy ``optimize_markdown()`` first (Unicode normalization,
OCR artifacts, page numbers, etc.) then the new ``PipelineExecutor``
passes (citations, references, boilerplate, dedup, tables, abbreviations).
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

# ── Default pass ordering ─────────────────────────────────────────────────────

_DEFAULT_PASS_ORDER = [
    "equation_extraction",       # FIRST — protect equations
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
    "equation_restoration",      # LAST — restore equations
]


class OptimizationService:
    """Async facade over legacy optimizer + modular pipeline."""

    def __init__(
        self,
        pass_order: list[str] | None = None,
        pass_configs: Dict[str, PassConfig] | None = None,
        enable_pipeline: bool = True,
    ) -> None:
        self._enable_pipeline = enable_pipeline
        self._report_gen = OptimizationReportGenerator()

        # Discover all registered passes
        self._registry = PassRegistry()
        self._registry.discover("app.optimizer.passes")

        # Build pipeline config
        self._pipeline_config = PipelineConfig(
            pass_order=pass_order or _DEFAULT_PASS_ORDER,
            pass_configs=pass_configs or {},
            collect_statistics=True,
            fail_fast=False,
        )
        self._executor = PipelineExecutor(
            registry=self._registry,
            config=self._pipeline_config,
        )

        logger.info(
            "[optimization_service] Pipeline initialized with %d passes: %s",
            len(self._pipeline_config.pass_order),
            self._pipeline_config.pass_order,
        )

    async def optimize(
        self, markdown: str,
    ) -> tuple[str, OptimizationStats]:
        """Run full optimization pipeline asynchronously.

        1. Legacy ``optimize_markdown()`` (Unicode, OCR artifacts, page numbers)
        2. Modular pipeline passes (citations, references, boilerplate, etc.)

        Returns (optimized_markdown, stats).
        """
        loop = asyncio.get_event_loop()

        # Step 1: Legacy cleanup
        cleaned: str = await loop.run_in_executor(
            None, lambda: optimize_markdown(markdown),
        )

        # Step 2: Modular pipeline
        if self._enable_pipeline:
            pipeline_result: PipelineResult = await loop.run_in_executor(
                None, lambda: self._executor.run(cleaned),
            )

            if pipeline_result.success:
                final = pipeline_result.output
            else:
                logger.warning(
                    "[optimization_service] Pipeline had errors: %s",
                    pipeline_result.errors,
                )
                final = pipeline_result.output  # use partial result

            # Generate structured report for logging
            report_json = self._report_gen.from_report(pipeline_result.report)
            logger.info(
                "[optimization_service] Pipeline report: "
                "tokens %d→%d (-%d, %.1f%%), %d passes, %d errors",
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
        logger.info(
            "[optimization_service] Total saved %d tokens (%.1f%%)",
            stats.tokens_saved, stats.percent_saved,
        )
        return final, stats

    async def optimize_with_report(
        self, markdown: str,
    ) -> tuple[str, OptimizationStats, Dict[str, Any]]:
        """Like ``optimize()`` but also returns the structured JSON report."""
        loop = asyncio.get_event_loop()

        cleaned: str = await loop.run_in_executor(
            None, lambda: optimize_markdown(markdown),
        )

        report_json: Dict[str, Any] = {}

        if self._enable_pipeline:
            pipeline_result: PipelineResult = await loop.run_in_executor(
                None, lambda: self._executor.run(cleaned),
            )
            final = pipeline_result.output
            report_json = self._report_gen.from_report(pipeline_result.report)
        else:
            final = cleaned

        stats = OptimizationStats(
            original_text=markdown,
            optimized_text=final,
        )
        return final, stats, report_json

    @property
    def available_passes(self) -> list[str]:
        """List all registered pass names."""
        return [p.name for p in self._registry.list_passes()]

    @property
    def active_passes(self) -> list[str]:
        """List passes in current pipeline order."""
        return list(self._pipeline_config.pass_order)

"""
optimizer/report.py – Optimization report generator.

``OptimizationReportGenerator`` extends the base ``ReportGenerator``
to produce **structured JSON reports** that aggregate pass-specific
metrics (removed citations, removed sections, duplicates, etc.)
alongside token/char/runtime statistics.

JSON schema::

    {
      "pipeline_id": str,
      "timestamps": { "started_at": str, "completed_at": str },
      "runtime_seconds": float,
      "tokens": { "original": int, "optimized": int, "saved": int, "reduction_percent": float },
      "characters": { "original": int, "optimized": int, "saved": int },
      "passes_executed": int,
      "passes_skipped": int,
      "pass_breakdown": [ { ...per-pass detail... } ],
      "content_removed": {
        "citations": { ... },
        "reference_sections": { ... },
        "boilerplate_sections": { ... },
        "duplicate_paragraphs": { ... },
        "headers_footers": { ... }
      },
      "errors": [str]
    }
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from app.optimizer.models import OptimizationContext, PassStatistics, PipelineReport


# ── Base report generator (unchanged) ─────────────────────────────────────────


class ReportGenerator:
    """Builds ``PipelineReport`` instances from raw execution data.

    This is deliberately a plain class (not a singleton) so it can be
    replaced or extended in tests.
    """

    @staticmethod
    def build(
        context: OptimizationContext,
        started_at: datetime,
        completed_at: datetime,
        errors: List[str] | None = None,
        pipeline_id: str | None = None,
    ) -> PipelineReport:
        """Construct a ``PipelineReport`` from a completed pipeline run.

        Args:
            context:      The ``OptimizationContext`` after all passes ran.
            started_at:   UTC timestamp when execution began.
            completed_at: UTC timestamp when execution ended.
            errors:       Error messages collected (if ``fail_fast=False``).
            pipeline_id:  Optional custom run ID; auto-generated if omitted.

        Returns:
            A frozen ``PipelineReport`` with all aggregates computed.
        """
        errors = errors or []
        pass_details: List[PassStatistics] = list(context.pass_history)

        # Compute aggregates from the first and last non-skipped passes
        executed = [s for s in pass_details if not s.skipped]

        if executed:
            tokens_before = executed[0].tokens_before
            tokens_after = executed[-1].tokens_after
            chars_before = executed[0].chars_before
            chars_after = executed[-1].chars_after
        else:
            tokens_before = tokens_after = 0
            chars_before = chars_after = 0

        tokens_saved = max(0, tokens_before - tokens_after)
        percent_saved = (
            round(tokens_saved / tokens_before * 100, 2)
            if tokens_before > 0
            else 0.0
        )

        total_duration = (completed_at - started_at).total_seconds()

        kwargs: dict = dict(
            started_at=started_at,
            completed_at=completed_at,
            total_duration_s=round(total_duration, 4),
            total_tokens_before=tokens_before,
            total_tokens_after=tokens_after,
            total_tokens_saved=tokens_saved,
            total_percent_saved=percent_saved,
            total_chars_before=chars_before,
            total_chars_after=chars_after,
            pass_details=pass_details,
            errors=errors,
        )

        if pipeline_id is not None:
            kwargs["pipeline_id"] = pipeline_id

        return PipelineReport(**kwargs)


# ── Extended report generator ─────────────────────────────────────────────────


class OptimizationReportGenerator:
    """Produces structured JSON reports from pipeline executions.

    Enriches base ``PipelineReport`` data with pass-specific metrics
    extracted from ``custom_metrics``.
    """

    _base = ReportGenerator()

    # Known pass name → extraction method mapping
    _EXTRACTORS = {
        "citation_removal": "_extract_citation_metrics",
        "reference_section_removal": "_extract_reference_metrics",
        "boilerplate_section_removal": "_extract_boilerplate_metrics",
        "global_paragraph_deduplication": "_extract_dedup_metrics",
        "header_footer_detection": "_extract_header_footer_metrics",
    }

    def generate(
        self,
        context: OptimizationContext,
        started_at: datetime,
        completed_at: datetime,
        errors: List[str] | None = None,
        pipeline_id: str | None = None,
    ) -> Dict[str, Any]:
        """Build structured JSON report from pipeline execution data.

        Returns dict matching schema documented at module level.
        """
        report = self._base.build(
            context=context,
            started_at=started_at,
            completed_at=completed_at,
            errors=errors,
            pipeline_id=pipeline_id,
        )
        return self._build_json(report)

    def from_report(self, report: PipelineReport) -> Dict[str, Any]:
        """Build structured JSON from existing ``PipelineReport``."""
        return self._build_json(report)

    # ── Core builder ──────────────────────────────────────────────────────

    def _build_json(self, report: PipelineReport) -> Dict[str, Any]:
        executed = [p for p in report.pass_details if not p.skipped]
        skipped = [p for p in report.pass_details if p.skipped]

        return {
            "pipeline_id": report.pipeline_id,
            "timestamps": {
                "started_at": report.started_at.isoformat(),
                "completed_at": report.completed_at.isoformat(),
            },
            "runtime_seconds": report.total_duration_s,
            "tokens": {
                "original": report.total_tokens_before,
                "optimized": report.total_tokens_after,
                "saved": report.total_tokens_saved,
                "reduction_percent": report.total_percent_saved,
            },
            "characters": {
                "original": report.total_chars_before,
                "optimized": report.total_chars_after,
                "saved": max(0, report.total_chars_before - report.total_chars_after),
            },
            "passes_executed": len(executed),
            "passes_skipped": len(skipped),
            "pass_breakdown": [
                self._format_pass(ps) for ps in report.pass_details
            ],
            "content_removed": self._extract_all_content_metrics(
                report.pass_details,
            ),
            "errors": report.errors,
        }

    # ── Per-pass formatting ───────────────────────────────────────────────

    @staticmethod
    def _format_pass(ps: PassStatistics) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "name": ps.pass_name,
            "status": "skipped" if ps.skipped else "executed",
            "duration_seconds": ps.duration_s,
        }
        if ps.skipped:
            base["skip_reason"] = ps.skip_reason
        else:
            base["tokens_before"] = ps.tokens_before
            base["tokens_after"] = ps.tokens_after
            base["tokens_saved"] = ps.tokens_saved
            base["percent_saved"] = ps.percent_saved
            base["chars_before"] = ps.chars_before
            base["chars_after"] = ps.chars_after
            if ps.custom_metrics:
                base["details"] = ps.custom_metrics
        return base

    # ── Content-removed aggregation ───────────────────────────────────────

    def _extract_all_content_metrics(
        self,
        pass_details: List[PassStatistics],
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}

        for ps in pass_details:
            if ps.skipped or not ps.custom_metrics:
                continue
            extractor_name = self._EXTRACTORS.get(ps.pass_name)
            if extractor_name:
                method = getattr(self, extractor_name)
                result.update(method(ps.custom_metrics))

        return result

    # ── Per-pass metric extractors ────────────────────────────────────────

    @staticmethod
    def _extract_citation_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "citations": {
                "mode": m.get("mode", "unknown"),
                "total_removed": m.get("total_citations_found", 0),
                "numeric_bracket": m.get("numeric_citations_found", 0),
                "author_year": m.get("author_year_citations_found", 0),
                "protected_zones_skipped": m.get("protected_zone_skips", 0),
            },
        }

    @staticmethod
    def _extract_reference_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
        sections = m.get("sections", [])
        total_entries = sum(s.get("entry_count", 0) for s in sections)
        return {
            "reference_sections": {
                "mode": m.get("mode", "unknown"),
                "sections_found": m.get("sections_found", 0),
                "total_entries": total_entries,
                "lines_affected": m.get("total_lines_affected", 0),
            },
        }

    @staticmethod
    def _extract_boilerplate_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "boilerplate_sections": {
                "mode": m.get("mode", "unknown"),
                "sections_found": m.get("sections_found", 0),
                "groups_found": m.get("groups_found", {}),
                "lines_affected": m.get("total_lines_affected", 0),
            },
        }

    @staticmethod
    def _extract_dedup_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "duplicate_paragraphs": {
                "mode": m.get("mode", "unknown"),
                "paragraphs_scanned": m.get("paragraphs_scanned", 0),
                "duplicates_removed": m.get("total_duplicates_removed", 0),
                "duplicate_groups": m.get("duplicate_groups", 0),
            },
        }

    @staticmethod
    def _extract_header_footer_metrics(m: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "headers_footers": {
                "patterns_detected": m.get("patterns_detected", 0),
                "lines_removed": m.get("lines_removed", 0),
            },
        }

"""
Tests for OptimizationReportGenerator.

Covers:
  - JSON schema structure
  - Token/char/runtime aggregation
  - Pass-by-pass breakdown
  - Content-removed extraction (citations, references, boilerplate, dedup, headers)
  - Empty/error/skipped edge cases
  - from_report() convenience method
  - ReportGenerator backward compatibility
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from app.optimizer.models import (
    OptimizationContext,
    PassStatistics,
    PipelineReport,
)
from app.optimizer.report import OptimizationReportGenerator, ReportGenerator


# ── Helpers ───────────────────────────────────────────────────────────────────

_T0 = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_T1 = _T0 + timedelta(seconds=1.5)


def _ctx_with_passes(*stats: PassStatistics) -> OptimizationContext:
    ctx = OptimizationContext(content="out", original_content="original")
    for s in stats:
        ctx.add_pass_result(s)
    return ctx


def _pass_stat(
    name: str = "test_pass",
    *,
    tokens_before: int = 100,
    tokens_after: int = 80,
    chars_before: int = 400,
    chars_after: int = 320,
    duration: float = 0.05,
    custom: dict | None = None,
    skipped: bool = False,
    skip_reason: str = "",
) -> PassStatistics:
    return PassStatistics(
        pass_name=name,
        duration_s=duration,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        chars_before=chars_before,
        chars_after=chars_after,
        skipped=skipped,
        skip_reason=skip_reason,
        custom_metrics=custom or {},
    )


# ── Tests: JSON Schema Structure ─────────────────────────────────────────────


class TestJSONSchema:

    def test_top_level_keys(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat())
        result = gen.generate(ctx, _T0, _T1)

        expected_keys = {
            "pipeline_id", "timestamps", "runtime_seconds",
            "tokens", "characters", "passes_executed",
            "passes_skipped", "pass_breakdown", "content_removed",
            "errors",
        }
        assert set(result.keys()) == expected_keys

    def test_timestamps_structure(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat())
        result = gen.generate(ctx, _T0, _T1)

        ts = result["timestamps"]
        assert "started_at" in ts
        assert "completed_at" in ts

    def test_tokens_structure(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat())
        result = gen.generate(ctx, _T0, _T1)

        tok = result["tokens"]
        assert set(tok.keys()) == {"original", "optimized", "saved", "reduction_percent"}

    def test_characters_structure(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat())
        result = gen.generate(ctx, _T0, _T1)

        ch = result["characters"]
        assert set(ch.keys()) == {"original", "optimized", "saved"}


# ── Tests: Token Aggregation ─────────────────────────────────────────────────


class TestTokenAggregation:

    def test_single_pass(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat(tokens_before=1000, tokens_after=700))
        result = gen.generate(ctx, _T0, _T1)

        assert result["tokens"]["original"] == 1000
        assert result["tokens"]["optimized"] == 700
        assert result["tokens"]["saved"] == 300
        assert result["tokens"]["reduction_percent"] == 30.0

    def test_multi_pass(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat("p1", tokens_before=1000, tokens_after=800),
            _pass_stat("p2", tokens_before=800, tokens_after=600),
        )
        result = gen.generate(ctx, _T0, _T1)

        assert result["tokens"]["original"] == 1000
        assert result["tokens"]["optimized"] == 600
        assert result["tokens"]["saved"] == 400

    def test_no_passes(self):
        gen = OptimizationReportGenerator()
        ctx = OptimizationContext(content="x", original_content="x")
        result = gen.generate(ctx, _T0, _T1)

        assert result["tokens"]["original"] == 0
        assert result["tokens"]["saved"] == 0


# ── Tests: Character Aggregation ──────────────────────────────────────────────


class TestCharAggregation:

    def test_chars_saved(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat(chars_before=500, chars_after=300),
        )
        result = gen.generate(ctx, _T0, _T1)

        assert result["characters"]["original"] == 500
        assert result["characters"]["optimized"] == 300
        assert result["characters"]["saved"] == 200


# ── Tests: Runtime ────────────────────────────────────────────────────────────


class TestRuntime:

    def test_runtime_recorded(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat())
        result = gen.generate(ctx, _T0, _T1)

        assert result["runtime_seconds"] == 1.5


# ── Tests: Pass Breakdown ─────────────────────────────────────────────────────


class TestPassBreakdown:

    def test_executed_pass_fields(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat("my_pass", tokens_before=100, tokens_after=80))
        result = gen.generate(ctx, _T0, _T1)

        bd = result["pass_breakdown"][0]
        assert bd["name"] == "my_pass"
        assert bd["status"] == "executed"
        assert bd["tokens_before"] == 100
        assert bd["tokens_after"] == 80
        assert bd["tokens_saved"] == 20

    def test_skipped_pass_fields(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat("skip_me", skipped=True, skip_reason="Disabled"),
        )
        result = gen.generate(ctx, _T0, _T1)

        bd = result["pass_breakdown"][0]
        assert bd["status"] == "skipped"
        assert bd["skip_reason"] == "Disabled"

    def test_custom_metrics_in_details(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat("x", custom={"foo": 42}),
        )
        result = gen.generate(ctx, _T0, _T1)

        assert result["pass_breakdown"][0]["details"]["foo"] == 42

    def test_pass_count(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat("a"),
            _pass_stat("b", skipped=True, skip_reason="off"),
            _pass_stat("c"),
        )
        result = gen.generate(ctx, _T0, _T1)

        assert result["passes_executed"] == 2
        assert result["passes_skipped"] == 1


# ── Tests: Content Removed — Citations ────────────────────────────────────────


class TestCitationMetrics:

    def test_citation_extraction(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat(
            "citation_removal",
            custom={
                "mode": "remove",
                "total_citations_found": 15,
                "numeric_citations_found": 10,
                "author_year_citations_found": 5,
                "protected_zone_skips": 2,
            },
        ))
        result = gen.generate(ctx, _T0, _T1)

        cit = result["content_removed"]["citations"]
        assert cit["mode"] == "remove"
        assert cit["total_removed"] == 15
        assert cit["numeric_bracket"] == 10
        assert cit["author_year"] == 5
        assert cit["protected_zones_skipped"] == 2


# ── Tests: Content Removed — References ───────────────────────────────────────


class TestReferenceMetrics:

    def test_reference_extraction(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat(
            "reference_section_removal",
            custom={
                "mode": "remove",
                "sections_found": 1,
                "total_lines_affected": 20,
                "sections": [{"entry_count": 15}],
            },
        ))
        result = gen.generate(ctx, _T0, _T1)

        ref = result["content_removed"]["reference_sections"]
        assert ref["sections_found"] == 1
        assert ref["total_entries"] == 15
        assert ref["lines_affected"] == 20


# ── Tests: Content Removed — Boilerplate ──────────────────────────────────────


class TestBoilerplateMetrics:

    def test_boilerplate_extraction(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat(
            "boilerplate_section_removal",
            custom={
                "mode": "remove",
                "sections_found": 3,
                "groups_found": {"funding": 1, "acknowledgements": 1, "ethics_statement": 1},
                "total_lines_affected": 12,
            },
        ))
        result = gen.generate(ctx, _T0, _T1)

        bp = result["content_removed"]["boilerplate_sections"]
        assert bp["sections_found"] == 3
        assert bp["groups_found"]["funding"] == 1
        assert bp["lines_affected"] == 12


# ── Tests: Content Removed — Duplicates ───────────────────────────────────────


class TestDedupMetrics:

    def test_dedup_extraction(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat(
            "global_paragraph_deduplication",
            custom={
                "mode": "normalized",
                "paragraphs_scanned": 50,
                "total_duplicates_removed": 5,
                "duplicate_groups": 3,
            },
        ))
        result = gen.generate(ctx, _T0, _T1)

        dd = result["content_removed"]["duplicate_paragraphs"]
        assert dd["duplicates_removed"] == 5
        assert dd["duplicate_groups"] == 3
        assert dd["paragraphs_scanned"] == 50


# ── Tests: Content Removed — Headers/Footers ─────────────────────────────────


class TestHeaderFooterMetrics:

    def test_header_footer_extraction(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat(
            "header_footer_detection",
            custom={
                "patterns_detected": 4,
                "lines_removed": 12,
            },
        ))
        result = gen.generate(ctx, _T0, _T1)

        hf = result["content_removed"]["headers_footers"]
        assert hf["patterns_detected"] == 4
        assert hf["lines_removed"] == 12


# ── Tests: Multi-pass Content Removed ─────────────────────────────────────────


class TestMultiPassContentRemoved:

    def test_all_extractors_combined(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat("reference_section_removal", custom={
                "mode": "remove", "sections_found": 1,
                "total_lines_affected": 10, "sections": [{"entry_count": 8}],
            }),
            _pass_stat("boilerplate_section_removal", custom={
                "mode": "remove", "sections_found": 2,
                "groups_found": {"funding": 1, "ethics_statement": 1},
                "total_lines_affected": 6,
            }),
            _pass_stat("citation_removal", custom={
                "mode": "remove", "total_citations_found": 7,
                "numeric_citations_found": 7, "author_year_citations_found": 0,
                "protected_zone_skips": 1,
            }),
            _pass_stat("global_paragraph_deduplication", custom={
                "mode": "normalized", "paragraphs_scanned": 30,
                "total_duplicates_removed": 2, "duplicate_groups": 1,
            }),
        )
        result = gen.generate(ctx, _T0, _T1)

        cr = result["content_removed"]
        assert "reference_sections" in cr
        assert "boilerplate_sections" in cr
        assert "citations" in cr
        assert "duplicate_paragraphs" in cr


# ── Tests: Edge Cases ─────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_context(self):
        gen = OptimizationReportGenerator()
        ctx = OptimizationContext(content="", original_content="")
        result = gen.generate(ctx, _T0, _T1)

        assert result["passes_executed"] == 0
        assert result["content_removed"] == {}

    def test_errors_propagated(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat())
        result = gen.generate(ctx, _T0, _T1, errors=["boom"])

        assert result["errors"] == ["boom"]

    def test_unknown_pass_no_content_removed(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(
            _pass_stat("some_custom_pass", custom={"x": 1}),
        )
        result = gen.generate(ctx, _T0, _T1)

        assert result["content_removed"] == {}

    def test_pass_without_custom_metrics(self):
        gen = OptimizationReportGenerator()
        ctx = _ctx_with_passes(_pass_stat("citation_removal", custom={}))
        result = gen.generate(ctx, _T0, _T1)

        # No custom_metrics → no content_removed entry
        assert result["content_removed"] == {}


# ── Tests: from_report() ─────────────────────────────────────────────────────


class TestFromReport:

    def test_from_report(self):
        gen = OptimizationReportGenerator()
        report = PipelineReport(
            pipeline_id="abc123",
            total_tokens_before=500,
            total_tokens_after=300,
            total_tokens_saved=200,
            total_percent_saved=40.0,
            total_chars_before=2000,
            total_chars_after=1200,
            total_duration_s=0.5,
        )
        result = gen.from_report(report)

        assert result["pipeline_id"] == "abc123"
        assert result["tokens"]["saved"] == 200


# ── Tests: Backward Compatibility ────────────────────────────────────────────


class TestReportGeneratorCompat:
    """Ensure base ReportGenerator still works."""

    def test_build_returns_pipeline_report(self):
        ctx = _ctx_with_passes(_pass_stat())
        report = ReportGenerator.build(ctx, _T0, _T1)
        assert isinstance(report, PipelineReport)
        assert report.total_tokens_saved == 20

    def test_build_with_pipeline_id(self):
        ctx = _ctx_with_passes(_pass_stat())
        report = ReportGenerator.build(ctx, _T0, _T1, pipeline_id="custom")
        assert report.pipeline_id == "custom"

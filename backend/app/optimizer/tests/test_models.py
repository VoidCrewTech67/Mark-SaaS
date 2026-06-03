"""
Tests for data models: PassConfig, PassStatistics, OptimizationContext,
PipelineReport, PipelineResult, PassInfo.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.optimizer.models import (
    OptimizationContext,
    PassConfig,
    PassInfo,
    PassStatistics,
    PipelineReport,
    PipelineResult,
)


class TestPassConfig:
    """PassConfig creation and merge behaviour."""

    def test_defaults(self):
        cfg = PassConfig()
        assert cfg.enabled is True
        assert cfg.priority == 100
        assert cfg.params == {}

    def test_custom_values(self):
        cfg = PassConfig(enabled=False, priority=5, params={"key": "val"})
        assert cfg.enabled is False
        assert cfg.priority == 5
        assert cfg.params == {"key": "val"}

    def test_merge_replaces_top_level(self):
        base = PassConfig(enabled=True, priority=10)
        merged = base.merge({"enabled": False, "priority": 99})
        assert merged.enabled is False
        assert merged.priority == 99
        # Base unchanged
        assert base.enabled is True

    def test_merge_shallow_merges_params(self):
        base = PassConfig(params={"a": 1, "b": 2})
        merged = base.merge({"params": {"b": 99, "c": 3}})
        assert merged.params == {"a": 1, "b": 99, "c": 3}

    def test_merge_with_empty_overrides(self):
        base = PassConfig(priority=10, params={"x": 1})
        merged = base.merge({})
        assert merged.priority == 10
        assert merged.params == {"x": 1}

    def test_merge_returns_new_instance(self):
        base = PassConfig()
        merged = base.merge({"priority": 50})
        assert merged is not base


class TestPassStatistics:
    """PassStatistics computed fields and immutability."""

    def test_tokens_saved(self):
        stats = PassStatistics(
            pass_name="test",
            tokens_before=1000,
            tokens_after=750,
        )
        assert stats.tokens_saved == 250

    def test_tokens_saved_non_negative(self):
        stats = PassStatistics(
            pass_name="test",
            tokens_before=100,
            tokens_after=200,  # pass increased size
        )
        assert stats.tokens_saved == 0

    def test_percent_saved(self):
        stats = PassStatistics(
            pass_name="test",
            tokens_before=1000,
            tokens_after=800,
        )
        assert stats.percent_saved == 20.0

    def test_percent_saved_zero_before(self):
        stats = PassStatistics(pass_name="test", tokens_before=0, tokens_after=0)
        assert stats.percent_saved == 0.0

    def test_chars_saved(self):
        stats = PassStatistics(
            pass_name="test",
            chars_before=500,
            chars_after=300,
        )
        assert stats.chars_saved == 200

    def test_skipped_defaults(self):
        stats = PassStatistics(pass_name="test")
        assert stats.skipped is False
        assert stats.skip_reason == ""

    def test_frozen(self):
        stats = PassStatistics(pass_name="test")
        with pytest.raises(Exception):
            stats.pass_name = "changed"  # type: ignore[misc]

    def test_custom_metrics(self):
        stats = PassStatistics(
            pass_name="test",
            custom_metrics={"duplicates_removed": 5},
        )
        assert stats.custom_metrics["duplicates_removed"] == 5


class TestOptimizationContext:
    """OptimizationContext mutations and aggregates."""

    def test_initial_state(self):
        ctx = OptimizationContext(content="hello", original_content="hello")
        assert ctx.content == "hello"
        assert ctx.original_content == "hello"
        assert ctx.metadata == {}
        assert ctx.pass_history == []

    def test_add_pass_result(self):
        ctx = OptimizationContext(content="x", original_content="x")
        stats = PassStatistics(pass_name="p1", tokens_before=100, tokens_after=80)
        ctx.add_pass_result(stats)
        assert len(ctx.pass_history) == 1
        assert ctx.pass_history[0].pass_name == "p1"

    def test_total_tokens_saved_single_pass(self):
        ctx = OptimizationContext(content="x", original_content="x")
        ctx.add_pass_result(
            PassStatistics(pass_name="p1", tokens_before=100, tokens_after=70)
        )
        assert ctx.total_tokens_saved() == 30

    def test_total_tokens_saved_multi_pass(self):
        ctx = OptimizationContext(content="x", original_content="x")
        ctx.add_pass_result(
            PassStatistics(pass_name="p1", tokens_before=100, tokens_after=80)
        )
        ctx.add_pass_result(
            PassStatistics(pass_name="p2", tokens_before=80, tokens_after=60)
        )
        assert ctx.total_tokens_saved() == 40  # 100 → 60

    def test_total_tokens_saved_with_skipped(self):
        ctx = OptimizationContext(content="x", original_content="x")
        ctx.add_pass_result(
            PassStatistics(pass_name="skipped", skipped=True)
        )
        ctx.add_pass_result(
            PassStatistics(pass_name="p1", tokens_before=100, tokens_after=70)
        )
        assert ctx.total_tokens_saved() == 30

    def test_total_tokens_saved_all_skipped(self):
        ctx = OptimizationContext(content="x", original_content="x")
        ctx.add_pass_result(PassStatistics(pass_name="s1", skipped=True))
        assert ctx.total_tokens_saved() == 0

    def test_total_percent_saved(self):
        ctx = OptimizationContext(content="x", original_content="x")
        ctx.add_pass_result(
            PassStatistics(pass_name="p1", tokens_before=200, tokens_after=100)
        )
        assert ctx.total_percent_saved() == 50.0

    def test_total_percent_saved_empty(self):
        ctx = OptimizationContext(content="x", original_content="x")
        assert ctx.total_percent_saved() == 0.0

    def test_metadata_mutation(self):
        ctx = OptimizationContext(content="x", original_content="x")
        ctx.metadata["key"] = "value"
        assert ctx.metadata["key"] == "value"


class TestPipelineReport:
    """PipelineReport serialization and rendering."""

    def _make_report(self, **kwargs) -> PipelineReport:
        defaults = dict(
            pipeline_id="test123",
            started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            completed_at=datetime(2025, 1, 1, 0, 0, 1, tzinfo=timezone.utc),
            total_duration_s=1.0,
            total_tokens_before=1000,
            total_tokens_after=700,
            total_tokens_saved=300,
            total_percent_saved=30.0,
            total_chars_before=4000,
            total_chars_after=2800,
            pass_details=[
                PassStatistics(
                    pass_name="pass_a",
                    duration_s=0.5,
                    tokens_before=1000,
                    tokens_after=850,
                ),
                PassStatistics(
                    pass_name="pass_b",
                    duration_s=0.5,
                    tokens_before=850,
                    tokens_after=700,
                ),
            ],
        )
        defaults.update(kwargs)
        return PipelineReport(**defaults)

    def test_to_dict(self):
        report = self._make_report()
        d = report.to_dict()
        assert d["pipeline_id"] == "test123"
        assert d["total_tokens_saved"] == 300
        assert isinstance(d["pass_details"], list)
        assert len(d["pass_details"]) == 2

    def test_to_markdown_contains_table(self):
        report = self._make_report()
        md = report.to_markdown()
        assert "# Optimization Report" in md
        assert "pass_a" in md
        assert "pass_b" in md
        assert "1,000" in md  # formatted token count

    def test_to_markdown_with_errors(self):
        report = self._make_report(errors=["Something broke"])
        md = report.to_markdown()
        assert "Errors" in md
        assert "Something broke" in md

    def test_to_markdown_with_skipped_pass(self):
        report = self._make_report(
            pass_details=[
                PassStatistics(pass_name="skipped_one", skipped=True, skip_reason="Disabled"),
            ]
        )
        md = report.to_markdown()
        assert "Skipped" in md
        assert "Disabled" in md

    def test_summary(self):
        report = self._make_report()
        s = report.summary()
        assert "test123" in s
        assert "2 passes executed" in s
        assert "30.0% saved" in s

    def test_frozen(self):
        report = self._make_report()
        with pytest.raises(Exception):
            report.pipeline_id = "changed"  # type: ignore[misc]


class TestPipelineResult:
    """PipelineResult structure."""

    def test_defaults(self):
        result = PipelineResult()
        assert result.output == ""
        assert result.success is True
        assert result.errors == []
        assert isinstance(result.context, OptimizationContext)
        assert isinstance(result.report, PipelineReport)

    def test_with_errors(self):
        result = PipelineResult(
            success=False,
            errors=["error1", "error2"],
        )
        assert result.success is False
        assert len(result.errors) == 2


class TestPassInfo:
    """PassInfo lightweight descriptor."""

    def test_creation(self):
        info = PassInfo(
            name="test",
            description="A test pass",
            default_config=PassConfig(priority=5),
        )
        assert info.name == "test"
        assert info.description == "A test pass"
        assert info.default_config.priority == 5

    def test_frozen(self):
        info = PassInfo(
            name="test",
            description="test",
            default_config=PassConfig(),
        )
        with pytest.raises(Exception):
            info.name = "changed"  # type: ignore[misc]

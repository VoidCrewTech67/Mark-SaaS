"""
Tests for PipelineExecutor — the orchestration engine.
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.exceptions import PassNotFoundError
from app.optimizer.models import PassConfig, PipelineResult
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry

from app.optimizer.tests.conftest import (
    AppendPass,
    DisabledPass,
    ErrorPass,
    MetadataPass,
    NoOpPass,
    StripWhitespacePass,
    UpperCasePass,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_executor(
    registry: PassRegistry,
    pass_order: list[str],
    **kwargs,
) -> PipelineExecutor:
    config = PipelineConfig(pass_order=pass_order, **kwargs)
    return PipelineExecutor(registry=registry, config=config)


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestEmptyPipeline:
    """Pipeline with no passes."""

    def test_returns_input_unchanged(self, registry: PassRegistry):
        executor = _make_executor(registry, pass_order=[])
        result = executor.run("hello world")
        assert result.output == "hello world"
        assert result.success is True
        assert result.errors == []

    def test_report_has_zero_passes(self, registry: PassRegistry):
        executor = _make_executor(registry, pass_order=[])
        result = executor.run("x")
        assert len(result.report.pass_details) == 0


class TestSinglePass:
    """Pipeline with one pass."""

    def test_noop_pass(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["noop"])
        result = executor.run("hello")
        assert result.output == "hello"
        assert result.success is True
        assert len(result.report.pass_details) == 1
        assert result.report.pass_details[0].pass_name == "noop"

    def test_uppercase_pass(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["uppercase"])
        result = executor.run("hello world")
        assert result.output == "HELLO WORLD"

    def test_append_pass(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["append"])
        result = executor.run("content")
        assert result.output == "content_appended"

    def test_strip_whitespace_pass(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["strip_whitespace"])
        result = executor.run("  hello  ")
        assert result.output == "hello"


class TestMultiPassOrdering:
    """Pipeline executes passes in the configured order."""

    def test_order_matters_uppercase_then_append(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["uppercase", "append"]
        )
        result = executor.run("hello")
        assert result.output == "HELLO_appended"

    def test_order_matters_append_then_uppercase(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["append", "uppercase"]
        )
        result = executor.run("hello")
        assert result.output == "HELLO_APPENDED"

    def test_three_passes(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["strip_whitespace", "uppercase", "append"]
        )
        result = executor.run("  hi  ")
        assert result.output == "HI_appended"

    def test_statistics_recorded_for_all_passes(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["noop", "uppercase", "append"]
        )
        result = executor.run("test")
        assert len(result.report.pass_details) == 3
        names = [s.pass_name for s in result.report.pass_details]
        assert names == ["noop", "uppercase", "append"]


class TestDisabledPasses:
    """Passes with enabled=False are skipped."""

    def test_disabled_pass_skipped(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["disabled_pass", "uppercase"]
        )
        result = executor.run("hello")
        assert result.output == "HELLO"  # disabled_pass didn't append

    def test_disabled_pass_recorded_as_skipped(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["disabled_pass"]
        )
        result = executor.run("hello")
        assert result.output == "hello"
        assert len(result.report.pass_details) == 1
        assert result.report.pass_details[0].skipped is True
        assert "Disabled" in result.report.pass_details[0].skip_reason

    def test_enable_via_config_override(self, registered_passes, registry):
        """A pass disabled by default can be enabled via config override."""
        config = PipelineConfig(
            pass_order=["disabled_pass"],
            pass_configs={
                "disabled_pass": PassConfig(enabled=True),
            },
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run("hello")
        # DisabledPass appends "_SHOULD_NOT_RUN" when it actually runs
        assert "_SHOULD_NOT_RUN" in result.output


class TestErrorHandling:
    """Error handling with fail_fast=True and fail_fast=False."""

    def test_fail_fast_stops_on_error(self, registered_passes, registry):
        executor = _make_executor(
            registry,
            pass_order=["error_pass", "uppercase"],
            fail_fast=True,
        )
        result = executor.run("hello")
        assert result.success is False
        assert len(result.errors) > 0
        # uppercase should NOT have run
        assert result.output == "hello"

    def test_fail_fast_false_collects_errors(self, registered_passes, registry):
        executor = _make_executor(
            registry,
            pass_order=["uppercase", "error_pass", "append"],
            fail_fast=False,
        )
        result = executor.run("hello")
        assert result.success is False
        assert len(result.errors) > 0
        # uppercase ran, error_pass failed, append should still run
        assert result.output == "HELLO_appended"

    def test_missing_pass_name_is_error(self, registered_passes, registry):
        executor = _make_executor(
            registry,
            pass_order=["nonexistent_pass", "uppercase"],
            fail_fast=True,
        )
        result = executor.run("hello")
        assert result.success is False
        assert any("nonexistent_pass" in e for e in result.errors)

    def test_missing_pass_fail_fast_false_continues(self, registered_passes, registry):
        executor = _make_executor(
            registry,
            pass_order=["nonexistent_pass", "uppercase"],
            fail_fast=False,
        )
        result = executor.run("hello")
        assert result.success is False
        assert result.output == "HELLO"  # uppercase still ran


class TestMetadata:
    """Passes can read and write context metadata."""

    def test_metadata_pass(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["metadata_writer"]
        )
        result = executor.run("content")
        assert result.context.metadata["metadata_pass_ran"] is True
        assert result.context.metadata["pass_count"] == 1

    def test_initial_metadata_passed_through(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["metadata_writer"]
        )
        result = executor.run("content", metadata={"source": "test"})
        assert result.context.metadata["source"] == "test"
        assert result.context.metadata["metadata_pass_ran"] is True


class TestConfigOverrides:
    """Per-pass config overrides from PipelineConfig."""

    def test_override_params(self, registered_passes, registry):
        config = PipelineConfig(
            pass_order=["append"],
            pass_configs={
                "append": PassConfig(params={"suffix": "_CUSTOM"}),
            },
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run("hello")
        assert result.output == "hello_CUSTOM"


class TestStatisticsCollection:
    """Statistics are collected when enabled."""

    def test_statistics_have_timing(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["uppercase"]
        )
        result = executor.run("hello world")
        stats = result.report.pass_details[0]
        assert stats.duration_s >= 0
        assert stats.chars_before > 0
        assert stats.chars_after > 0

    def test_statistics_disabled(self, registered_passes, registry):
        executor = _make_executor(
            registry,
            pass_order=["uppercase"],
            collect_statistics=False,
        )
        result = executor.run("hello world")
        stats = result.report.pass_details[0]
        # tokens should be 0 when stats collection is disabled
        assert stats.tokens_before == 0
        assert stats.tokens_after == 0

    def test_original_content_preserved(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["uppercase"]
        )
        result = executor.run("hello")
        assert result.context.original_content == "hello"
        assert result.context.content == "HELLO"


class TestReport:
    """Pipeline report generation."""

    def test_report_summary(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["uppercase", "append"]
        )
        result = executor.run("hello")
        summary = result.report.summary()
        assert "2 passes executed" in summary

    def test_report_markdown(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["uppercase"]
        )
        result = executor.run("hello")
        md = result.report.to_markdown()
        assert "Optimization Report" in md
        assert "uppercase" in md

    def test_report_dict(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["noop"]
        )
        result = executor.run("x")
        d = result.report.to_dict()
        assert isinstance(d, dict)
        assert "pipeline_id" in d
        assert "pass_details" in d


class TestDryRun:
    """dry_run() returns the list of passes that would execute."""

    def test_dry_run_all_enabled(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["noop", "uppercase", "append"]
        )
        names = executor.dry_run()
        assert names == ["noop", "uppercase", "append"]

    def test_dry_run_excludes_disabled(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["noop", "disabled_pass", "uppercase"]
        )
        names = executor.dry_run()
        assert "disabled_pass" not in names
        assert names == ["noop", "uppercase"]

    def test_dry_run_excludes_missing(self, registered_passes, registry):
        executor = _make_executor(
            registry, pass_order=["noop", "missing_pass"]
        )
        names = executor.dry_run()
        assert names == ["noop"]

    def test_dry_run_empty_pipeline(self, registry):
        executor = _make_executor(registry, pass_order=[])
        assert executor.dry_run() == []


class TestRunSinglePass:
    """run_single_pass() convenience method."""

    def test_single_pass(self, registered_passes, registry):
        executor = PipelineExecutor(registry=registry)
        result = executor.run_single_pass("uppercase", "hello")
        assert result == "HELLO"

    def test_single_pass_with_overrides(self, registered_passes, registry):
        executor = PipelineExecutor(registry=registry)
        result = executor.run_single_pass(
            "append", "hello", config_overrides={"params": {"suffix": "!"}}
        )
        assert result == "hello!"

    def test_single_pass_missing_raises(self, registry):
        executor = PipelineExecutor(registry=registry)
        with pytest.raises(Exception):
            executor.run_single_pass("nonexistent", "hello")


class TestWithConfig:
    """with_config() returns a new executor."""

    def test_with_config_new_instance(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["noop"])
        new_config = PipelineConfig(pass_order=["uppercase"])
        new_executor = executor.with_config(new_config)

        assert new_executor is not executor
        assert new_executor.config.pass_order == ["uppercase"]
        assert executor.config.pass_order == ["noop"]

    def test_with_config_shares_registry(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["noop"])
        new_executor = executor.with_config(PipelineConfig(pass_order=["uppercase"]))
        assert new_executor.registry is executor.registry


class TestRepr:
    """String representations."""

    def test_repr(self, registered_passes, registry):
        executor = _make_executor(registry, pass_order=["noop"])
        r = repr(executor)
        assert "PipelineExecutor" in r
        assert "noop" in r

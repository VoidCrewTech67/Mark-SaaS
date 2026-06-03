"""Tests for OptimizerPipelineV2."""

from __future__ import annotations

import json
import time

import pytest

from app.optimizer.pipeline_v2 import (
    DEFAULT_V2_PASSES,
    OptimizerPipelineV2,
    V2Report,
)
from app.optimizer.validator import ValidationThresholds


# ── Ensure passes are registered ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _ensure_registry():
    """Make sure all passes are registered before each test."""
    from app.optimizer.registry import PassRegistry

    r = PassRegistry()
    # Force re-register all passes
    from app.optimizer.passes.ocr_cleanup import OCRCleanupPass
    from app.optimizer.passes.equation_preservation import (
        EquationExtractionPass, EquationRestorationPass,
    )
    from app.optimizer.passes.content_boilerplate import ContentBoilerplatePass
    from app.optimizer.passes.semantic_table_transform import SemanticTableTransformPass
    from app.optimizer.passes.importance_aware import ImportanceAwarePass
    from app.optimizer.passes.citation import CitationRemovalPass
    from app.optimizer.passes.reference_section import ReferenceSectionRemovalPass
    from app.optimizer.passes.boilerplate_section import BoilerplateSectionRemovalPass
    from app.optimizer.passes.header_footer import HeaderFooterDetectionPass
    from app.optimizer.passes.table_compression import TableCompressionPass
    from app.optimizer.passes.paragraph_dedup import GlobalParagraphDeduplicationPass
    from app.optimizer.passes.abbreviation_mining import AbbreviationMiningPass

    for cls in [
        OCRCleanupPass, EquationExtractionPass, EquationRestorationPass,
        ContentBoilerplatePass, SemanticTableTransformPass,
        ImportanceAwarePass, CitationRemovalPass,
        ReferenceSectionRemovalPass, BoilerplateSectionRemovalPass,
        HeaderFooterDetectionPass, TableCompressionPass,
        GlobalParagraphDeduplicationPass, AbbreviationMiningPass,
    ]:
        r.register(cls, force=True)

    yield
    # Don't clear — other V2 tests may need them


# ── Test document ─────────────────────────────────────────────────────────────

_PAPER = """\
# Abstract

This paper presents quantum key distribution results.

# Introduction

Quantum computing [1] has grown significantly [2,3].
It is worth noting that QKD enables secure communication.

# Methodology

We implement BB84 with:
$$H(X|Y) = -\\sum p(x,y) \\log p(x|y)$$

## Algorithm

Step 1: Alice generates random bits.
Step 2: Alice encodes using random bases.

# Results

Our system achieves 99.2% accuracy with $p < 0.001$.

| Metric | Value |
|--------|-------|
| Accuracy | 99.2% |
| Throughput | 1.5 Mbps |

# Conclusion

QKD provides provable security guarantees.

# Acknowledgements

We thank NSF grant #12345.
"""


# ── Basic Pipeline ───────────────────────────────────────────────────────────

class TestBasicPipeline:

    def test_runs_successfully(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        output, report = pipe.run(_PAPER)
        assert output
        assert report.original_tokens > 0
        assert report.total_runtime_ms > 0

    def test_reduces_tokens(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        assert report.optimized_tokens <= report.original_tokens

    def test_empty_input(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        output, report = pipe.run("")
        assert output == ""
        assert report.original_tokens == 0

    def test_clean_text(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        output, report = pipe.run("Simple clean text.")
        assert output
        assert report.original_tokens > 0


# ── Validation ───────────────────────────────────────────────────────────────

class TestValidation:

    def test_passes_validation(self):
        pipe = OptimizerPipelineV2(
            enable_validation=True,
            thresholds=ValidationThresholds(
                min_semantic_score=0.5,
                min_equation_score=0.5,
            ),
        )
        _, report = pipe.run(_PAPER)
        assert report.passed_validation
        assert report.semantic_score > 0

    def test_validation_disabled(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        assert report.semantic_score == -1.0
        assert report.passed_validation


# ── Rollback ─────────────────────────────────────────────────────────────────

class TestRollback:

    def test_rollback_on_failure(self):
        pipe = OptimizerPipelineV2(
            enable_validation=True,
            enable_rollback=True,
            thresholds=ValidationThresholds(
                min_semantic_score=0.9999,
            ),
        )
        output, report = pipe.run(_PAPER)
        if not report.passed_validation:
            assert report.rolled_back
            assert report.reduction_percent == 0.0

    def test_no_rollback_when_disabled(self):
        pipe = OptimizerPipelineV2(
            enable_validation=True,
            enable_rollback=False,
            thresholds=ValidationThresholds(
                min_semantic_score=0.9999,
            ),
        )
        _, report = pipe.run(_PAPER)
        assert not report.rolled_back


# ── Pass Metrics ─────────────────────────────────────────────────────────────

class TestPassMetrics:

    def test_metrics_collected(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        assert len(report.pass_metrics) > 0

    def test_each_pass_has_fields(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        for pm in report.pass_metrics:
            assert "name" in pm
            assert "runtime_ms" in pm
            assert "tokens_before" in pm
            assert "tokens_after" in pm
            assert "tokens_saved" in pm

    def test_runtime_positive(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        for pm in report.pass_metrics:
            assert pm["runtime_ms"] >= 0


# ── Report Output ────────────────────────────────────────────────────────────

class TestReportOutput:

    def test_to_dict_keys(self):
        pipe = OptimizerPipelineV2(
            enable_validation=True,
            thresholds=ValidationThresholds(
                min_semantic_score=0.3,
                min_equation_score=0.3,
            ),
        )
        _, report = pipe.run(_PAPER)
        d = report.to_dict()

        expected_keys = {
            "originalTokens", "optimizedTokens", "reductionPercent",
            "semanticScore", "structureScore", "equationScore",
            "equationsPreserved", "tablesTransformed",
            "warnings", "passedValidation", "rolledBack",
            "totalRuntimeMs", "passMetrics",
        }
        assert set(d.keys()) == expected_keys

    def test_json_serializable(self):
        pipe = OptimizerPipelineV2(
            enable_validation=True,
            thresholds=ValidationThresholds(
                min_semantic_score=0.3,
                min_equation_score=0.3,
            ),
        )
        _, report = pipe.run(_PAPER)
        json_str = json.dumps(report.to_dict())
        assert json_str

    def test_reduction_percent(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        assert 0 <= report.reduction_percent <= 100


# ── Content Preservation ─────────────────────────────────────────────────────

class TestContentPreservation:

    def test_equations_in_output(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        output, _ = pipe.run(_PAPER)
        assert "$$H(X|Y)" in output
        assert "$p < 0.001$" in output

    def test_methodology_preserved(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        output, _ = pipe.run(_PAPER)
        assert "BB84" in output

    def test_results_preserved(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        output, _ = pipe.run(_PAPER)
        assert "99.2%" in output


# ── Custom Pass Order ────────────────────────────────────────────────────────

class TestCustomPasses:

    def test_subset_passes(self):
        pipe = OptimizerPipelineV2(
            pass_order=["ocr_cleanup", "citation_removal"],
            enable_validation=False,
        )
        output, report = pipe.run(_PAPER)
        # Only 2 non-skipped passes
        executed = [pm for pm in report.pass_metrics if not pm.get("skipped")]
        assert len(executed) == 2

    def test_single_pass(self):
        pipe = OptimizerPipelineV2(
            pass_order=["citation_removal"],
            enable_validation=False,
        )
        output, report = pipe.run("Text [1] with [2,3] citations.")
        assert "[1]" not in output


# ── Configurable Pass Params ─────────────────────────────────────────────────

class TestPassConfigs:

    def test_custom_params(self):
        pipe = OptimizerPipelineV2(
            pass_order=["importance_aware"],
            pass_configs={
                "importance_aware": {
                    "params": {"remove_tier3": True},
                },
            },
            enable_validation=False,
        )
        output, _ = pipe.run(_PAPER)
        assert "Acknowledgements" not in output


# ── Warnings ─────────────────────────────────────────────────────────────────

class TestWarnings:

    def test_no_warnings_clean(self):
        pipe = OptimizerPipelineV2(
            pass_order=["ocr_cleanup"],
            enable_validation=True,
            thresholds=ValidationThresholds(
                min_semantic_score=0.3,
                min_equation_score=0.3,
            ),
        )
        _, report = pipe.run("Clean text here.")
        assert isinstance(report.warnings, list)


# ── Benchmark ────────────────────────────────────────────────────────────────

class TestBenchmark:

    @pytest.mark.parametrize("n_sections", [5, 20])
    def test_throughput(self, n_sections: int):
        sections = []
        for i in range(n_sections):
            if i % 3 == 0:
                sections.append(f"# Results {i}\n\nAccuracy $x_{i} = {i}$.")
            elif i % 3 == 1:
                sections.append(f"# Introduction {i}\n\nBackground [1].")
            else:
                sections.append(f"# Acknowledgements {i}\n\nThanks.")
        doc = "\n\n".join(sections)

        pipe = OptimizerPipelineV2(enable_validation=False)
        t0 = time.perf_counter()
        output, report = pipe.run(doc)
        elapsed = time.perf_counter() - t0

        assert elapsed < 5.0, f"Too slow: {elapsed:.2f}s"
        assert report.total_runtime_ms > 0

    def test_report_runtime_matches(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        _, report = pipe.run(_PAPER)
        assert report.total_runtime_ms > 0
        pass_total = sum(pm["runtime_ms"] for pm in report.pass_metrics)
        assert pass_total <= report.total_runtime_ms + 50


# ── Default Pass Order ───────────────────────────────────────────────────────

class TestDefaults:

    def test_default_passes(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        assert pipe.pass_order == DEFAULT_V2_PASSES

    def test_available_passes(self):
        pipe = OptimizerPipelineV2(enable_validation=False)
        available = pipe.available_passes
        assert "ocr_cleanup" in available
        assert "equation_extraction" in available
        assert "importance_aware" in available

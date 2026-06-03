"""Tests for SemanticQualityValidator."""

from __future__ import annotations

import pytest

from app.optimizer.validator import (
    SemanticQualityValidator,
    ValidationReport,
    ValidationThresholds,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _validate(original: str, optimized: str, **kwargs) -> ValidationReport:
    v = SemanticQualityValidator(**kwargs)
    return v.validate(original, optimized)


_PAPER = """\
# Introduction

Quantum Key Distribution (QKD) enables secure communication.
The BB84 protocol was proposed by Bennett and Brassard in 1984.

## Methods

We implemented the protocol using $E = mc^2$ and tested with
$$\\int_0^\\infty e^{-x} dx = 1$$

### Results

- Accuracy: 99.2%
- Throughput: 1.5 Mbps
- Error rate: 0.3%

## Conclusion

QKD provides provable security guarantees.
"""


# ── Semantic Score ───────────────────────────────────────────────────────────

class TestSemanticScore:

    def test_identical_docs(self):
        r = _validate(_PAPER, _PAPER)
        assert r.semantic_score == 1.0

    def test_similar_docs(self):
        optimized = _PAPER.replace("enables secure communication", "allows secure comms")
        r = _validate(_PAPER, optimized)
        assert r.semantic_score > 0.9

    def test_very_different(self):
        r = _validate(_PAPER, "Completely unrelated content about cooking recipes.")
        assert r.semantic_score < 0.5

    def test_empty_both(self):
        r = _validate("", "")
        assert r.semantic_score == 1.0

    def test_empty_original(self):
        r = _validate("", "some text")
        assert r.semantic_score == 1.0  # empty original → pass

    def test_empty_optimized(self):
        r = _validate("some text here", "")
        assert r.semantic_score == 0.0


# ── Structure Score ──────────────────────────────────────────────────────────

class TestStructureScore:

    def test_preserved_headings(self):
        r = _validate(_PAPER, _PAPER)
        assert r.structure_score == 1.0

    def test_missing_heading(self):
        optimized = _PAPER.replace("## Conclusion\n\n", "")
        r = _validate(_PAPER, optimized)
        assert r.structure_score < 1.0

    def test_all_headings_removed(self):
        import re
        no_headings = re.sub(r"^#{1,6}\s+.+$", "", _PAPER, flags=re.MULTILINE)
        r = _validate(_PAPER, no_headings)
        assert r.structure_score < 0.8  # heading component pulls it down

    def test_lists_preserved(self):
        doc = "- Item 1\n- Item 2\n- Item 3"
        r = _validate(doc, doc)
        assert r.structure_score == 1.0

    def test_lists_removed(self):
        doc = "- Item 1\n- Item 2\n- Item 3"
        r = _validate(doc, "No lists here.")
        assert r.structure_score < 1.0

    def test_code_blocks(self):
        doc = "Text.\n\n```python\nprint('hi')\n```\n\nMore."
        r = _validate(doc, doc)
        assert r.structure_score == 1.0


# ── Equation Score ───────────────────────────────────────────────────────────

class TestEquationScore:

    def test_equations_preserved(self):
        r = _validate(_PAPER, _PAPER)
        assert r.equation_score == 1.0

    def test_inline_math_lost(self):
        optimized = _PAPER.replace("$E = mc^2$", "E equals mc squared")
        r = _validate(_PAPER, optimized)
        assert r.equation_score < 1.0

    def test_display_math_lost(self):
        optimized = _PAPER.replace(
            "$$\\int_0^\\infty e^{-x} dx = 1$$",
            "The integral equals 1.",
        )
        r = _validate(_PAPER, optimized)
        assert r.equation_score < 1.0

    def test_no_equations(self):
        doc = "No math here."
        r = _validate(doc, doc)
        assert r.equation_score == 1.0

    def test_sci_notation(self):
        doc = "Value is 3.14e-5 and 2.7e8."
        r = _validate(doc, doc)
        assert r.equation_score == 1.0

    def test_partial_loss(self):
        doc = "$a$ and $b$ and $c$"
        optimized = "$a$ and b and $c$"
        r = _validate(doc, optimized)
        # 2 out of 3 preserved
        assert 0.5 < r.equation_score < 1.0


# ── Token Reduction ──────────────────────────────────────────────────────────

class TestTokenReduction:

    def test_no_reduction(self):
        r = _validate(_PAPER, _PAPER)
        assert r.token_reduction == 0.0

    def test_some_reduction(self):
        optimized = _PAPER[:len(_PAPER) // 2]
        r = _validate(_PAPER, optimized)
        assert 0.0 < r.token_reduction < 1.0

    def test_full_reduction(self):
        r = _validate("some words here", "")
        assert r.token_reduction == 1.0


# ── Warnings ─────────────────────────────────────────────────────────────────

class TestWarnings:

    def test_no_warnings_identical(self):
        r = _validate(_PAPER, _PAPER)
        assert len(r.warnings) == 0

    def test_empty_output_warning(self):
        r = _validate("Content.", "")
        assert any("empty" in w.lower() for w in r.warnings)

    def test_high_reduction_warning(self):
        # Create a heavily reduced output
        r = _validate(_PAPER, "Short.")
        assert any("reduction" in w.lower() for w in r.warnings)

    def test_equation_loss_warning(self):
        optimized = _PAPER.replace("$E = mc^2$", "E")
        r = _validate(_PAPER, optimized)
        assert any("equation" in w.lower() for w in r.warnings)


# ── Threshold Rejection ─────────────────────────────────────────────────────

class TestThresholds:

    def test_passes_default(self):
        r = _validate(_PAPER, _PAPER)
        assert r.passed is True
        assert len(r.rejection_reasons) == 0

    def test_rejects_low_semantic(self):
        thresholds = ValidationThresholds(min_semantic_score=0.99)
        r = _validate(
            _PAPER,
            "Completely different topic about cooking.",
            thresholds=thresholds,
        )
        assert r.passed is False
        assert any("semantic_score" in reason for reason in r.rejection_reasons)

    def test_rejects_lost_equations(self):
        thresholds = ValidationThresholds(min_equation_score=1.0)
        optimized = _PAPER.replace("$E = mc^2$", "E")
        r = _validate(_PAPER, optimized, thresholds=thresholds)
        assert r.passed is False
        assert any("equation_score" in reason for reason in r.rejection_reasons)

    def test_rejects_extreme_reduction(self):
        thresholds = ValidationThresholds(max_token_reduction=0.3)
        r = _validate(_PAPER, "Short.", thresholds=thresholds)
        assert r.passed is False
        assert any("token_reduction" in reason for reason in r.rejection_reasons)

    def test_custom_thresholds(self):
        thresholds = ValidationThresholds(
            min_semantic_score=0.5,
            min_structure_score=0.3,
            min_equation_score=0.8,
            max_token_reduction=0.9,
        )
        thresholds.validate()  # no error
        r = _validate(_PAPER, _PAPER, thresholds=thresholds)
        assert r.passed is True


# ── Threshold Validation ─────────────────────────────────────────────────────

class TestThresholdValidation:

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            ValidationThresholds(min_semantic_score=1.5).validate()

    def test_negative(self):
        with pytest.raises(ValueError):
            ValidationThresholds(min_equation_score=-0.1).validate()


# ── to_dict Output ───────────────────────────────────────────────────────────

class TestToDict:

    def test_keys(self):
        r = _validate(_PAPER, _PAPER)
        d = r.to_dict()
        expected = {
            "semanticScore", "structureScore", "equationScore",
            "tokenReduction", "originalTokens", "optimizedTokens",
            "warnings", "passed", "rejectionReasons",
        }
        assert set(d.keys()) == expected

    def test_types(self):
        r = _validate(_PAPER, _PAPER)
        d = r.to_dict()
        assert isinstance(d["semanticScore"], float)
        assert isinstance(d["structureScore"], float)
        assert isinstance(d["equationScore"], float)
        assert isinstance(d["tokenReduction"], float)
        assert isinstance(d["originalTokens"], int)
        assert isinstance(d["optimizedTokens"], int)
        assert isinstance(d["warnings"], list)
        assert isinstance(d["passed"], bool)


# ── Benchmark ────────────────────────────────────────────────────────────────

class TestBenchmark:

    @pytest.mark.parametrize("n_paras", [10, 50, 100])
    def test_throughput(self, n_paras: int):
        import time

        paras = [
            f"Paragraph {i}: This discusses concept {i} with equation $x_{i} = {i}$."
            for i in range(n_paras)
        ]
        doc = "\n\n".join(paras)
        optimized = "\n\n".join(paras[::2])  # keep every other

        t0 = time.perf_counter()
        r = _validate(doc, optimized)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0, f"Too slow: {elapsed:.3f}s"
        assert 0.0 < r.semantic_score <= 1.0


# ── Integration with Pipeline ────────────────────────────────────────────────

class TestPipelineIntegration:

    def test_validate_after_pipeline(self):
        """Simulate: run pipeline → validate quality."""
        from app.optimizer.config import PipelineConfig
        from app.optimizer.passes.citation import CitationRemovalPass
        from app.optimizer.pipeline import PipelineExecutor
        from app.optimizer.registry import PassRegistry

        r = PassRegistry()
        r.register(CitationRemovalPass, force=True)
        config = PipelineConfig(pass_order=["citation_removal"])
        result = PipelineExecutor(registry=r, config=config).run(
            "BB84 [1] was proposed [2,3] by Bennett."
        )

        v = SemanticQualityValidator()
        report = v.validate(
            "BB84 [1] was proposed [2,3] by Bennett.",
            result.output,
        )
        # Removing citations shouldn't destroy semantics
        assert report.semantic_score > 0.5
        assert report.passed is True
        r.clear()

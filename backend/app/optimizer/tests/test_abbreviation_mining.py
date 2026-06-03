"""
Tests for AbbreviationMiningPass.
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.abbreviation_mining import (
    AbbreviationMiningPass,
    _at_word_boundary,
    _in_protected,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(content: str, params: dict | None = None) -> tuple[str, dict]:
    p = AbbreviationMiningPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


def _repeat(phrase: str, n: int = 5) -> str:
    """Build doc with *phrase* appearing *n* times across paragraphs."""
    paras = []
    for i in range(n):
        paras.append(f"In section {i}, the {phrase} is discussed further.")
    return "\n\n".join(paras)


# ── Tests: Basic Replacement ─────────────────────────────────────────────────


class TestBasicReplacement:

    def test_simple_abbreviation(self):
        doc = _repeat("Quantum Key Distribution", 4)
        output, metrics = _run(doc, params={"min_frequency": 3})
        assert "QKD" in output
        assert "Quantum Key Distribution (QKD)" in output
        assert metrics["abbreviations_created"] == 1

    def test_multiple_phrases(self):
        doc = (
            _repeat("Natural Language Processing", 4)
            + "\n\n"
            + _repeat("Machine Learning Model", 4)
        )
        output, metrics = _run(doc, params={"min_frequency": 3})
        assert "NLP" in output
        assert "MLM" in output
        assert metrics["abbreviations_created"] == 2

    def test_first_occurrence_introduced(self):
        doc = _repeat("Deterministic Finite Automata", 3)
        output, _ = _run(doc, params={"min_frequency": 3})
        # First occurrence has intro format
        idx_intro = output.find("Deterministic Finite Automata (DFA)")
        idx_abbr = output.find("DFA")
        assert idx_intro >= 0
        assert idx_abbr >= 0
        assert idx_intro <= idx_abbr  # intro comes first

    def test_subsequent_occurrences_replaced(self):
        doc = _repeat("Probabilistic Automata", 5)
        output, metrics = _run(doc, params={"min_frequency": 3})
        # First occurrence kept + intro, rest replaced
        assert output.count("PA") >= 4  # intro has PA + 4 replacements
        assert metrics["total_replacements"] >= 4


# ── Tests: Acronym Generation ────────────────────────────────────────────────


class TestAcronymGeneration:

    def test_simple(self):
        assert AbbreviationMiningPass.generate_acronym("Quantum Key Distribution") == "QKD"

    def test_skips_connectors(self):
        assert AbbreviationMiningPass.generate_acronym("Conflict of Interest") == "CI"

    def test_multiple_connectors(self):
        assert AbbreviationMiningPass.generate_acronym("Department of Energy and Science") == "DES"

    def test_two_words(self):
        assert AbbreviationMiningPass.generate_acronym("Machine Learning") == "ML"


# ── Tests: Collision Detection ───────────────────────────────────────────────


class TestCollisionDetection:

    def test_collision_keeps_higher_freq(self):
        # Both phrases → same acronym "ML"
        # "Machine Learning" appears more → wins
        doc = _repeat("Machine Learning", 6) + "\n\n" + _repeat("Meta Linguistics", 3)
        output, metrics = _run(doc, params={"min_frequency": 3})
        # Only one abbreviation for ML
        created = metrics["abbreviations"]
        ml_entries = [a for a in created if a["acronym"] == "ML"]
        assert len(ml_entries) <= 1

    def test_existing_abbreviation_skipped(self):
        """If acronym already exists in doc, skip it."""
        doc = "NLP is great.\n\n" + _repeat("Natural Language Processing", 4)
        output, metrics = _run(doc, params={"min_frequency": 3})
        # NLP already exists → should not create abbreviation
        created = [a for a in metrics["abbreviations"] if a["acronym"] == "NLP"]
        assert len(created) == 0


# ── Tests: Confidence Scoring ────────────────────────────────────────────────


class TestConfidenceScoring:

    def test_high_frequency_high_confidence(self):
        doc = _repeat("Quantum Key Distribution", 10)
        _, metrics = _run(doc, params={"min_frequency": 3})
        abbr = metrics["abbreviations"]
        assert len(abbr) == 1
        assert abbr[0]["confidence"] > 0.5

    def test_min_confidence_filters(self):
        doc = _repeat("Quantum Key Distribution", 3)
        _, metrics = _run(doc, params={"min_frequency": 3, "min_confidence": 1.1})
        # Impossible threshold → filtered
        assert metrics["abbreviations_created"] == 0


# ── Tests: Frequency Threshold ───────────────────────────────────────────────


class TestFrequencyThreshold:

    def test_below_threshold_skipped(self):
        doc = _repeat("Quantum Key Distribution", 2)
        _, metrics = _run(doc, params={"min_frequency": 3})
        assert metrics["phrases_detected"] == 0

    def test_at_threshold_included(self):
        doc = _repeat("Quantum Key Distribution", 3)
        _, metrics = _run(doc, params={"min_frequency": 3})
        assert metrics["phrases_detected"] >= 1


# ── Tests: Protected Zones ───────────────────────────────────────────────────


class TestProtectedZones:

    def test_code_block_protected(self):
        code = "```python\nQuantum Key Distribution is here\n```"
        doc = code + "\n\n" + _repeat("Quantum Key Distribution", 4)
        output, _ = _run(doc, params={"min_frequency": 3})
        # Code block should be untouched
        assert "```python\nQuantum Key Distribution is here\n```" in output

    def test_inline_code_protected(self):
        doc = (
            "Use `Quantum Key Distribution` module.\n\n"
            + _repeat("Quantum Key Distribution", 4)
        )
        output, _ = _run(doc, params={"min_frequency": 3})
        assert "`Quantum Key Distribution`" in output

    def test_heading_protected(self):
        doc = "# Quantum Key Distribution\n\n" + _repeat("Quantum Key Distribution", 4)
        output, _ = _run(doc, params={"min_frequency": 3})
        assert "# Quantum Key Distribution" in output  # heading untouched

    def test_heading_protection_disabled(self):
        doc = "# Quantum Key Distribution\n\n" + _repeat("Quantum Key Distribution", 4)
        output, _ = _run(doc, params={"min_frequency": 3, "protect_headings": False})
        # Heading may be modified now
        assert "QKD" in output


# ── Tests: Phrase with Connectors ────────────────────────────────────────────


class TestConnectorPhrases:

    def test_phrase_with_of(self):
        doc = _repeat("Conflict of Interest", 4)
        output, metrics = _run(doc, params={"min_frequency": 3})
        assert "CI" in output
        assert metrics["abbreviations_created"] == 1

    def test_phrase_with_and(self):
        doc = _repeat("Science and Technology", 4)
        output, _ = _run(doc, params={"min_frequency": 3})
        assert "ST" in output


# ── Tests: Custom Intro Format ───────────────────────────────────────────────


class TestIntroFormat:

    def test_custom_format(self):
        doc = _repeat("Quantum Key Distribution", 4)
        output, _ = _run(doc, params={
            "min_frequency": 3,
            "intro_format": "{phrase} [{acronym}]",
        })
        assert "Quantum Key Distribution [QKD]" in output


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_doc(self):
        output, metrics = _run("")
        assert output == ""
        assert metrics["phrases_detected"] == 0

    def test_no_phrases(self):
        output, metrics = _run("just lowercase text with no proper nouns at all")
        assert metrics["phrases_detected"] == 0

    def test_single_occurrence_no_replacement(self):
        doc = "The Quantum Key Distribution protocol is important."
        output, metrics = _run(doc, params={"min_frequency": 1})
        assert "QKD" not in output  # need 2+ occurrences

    def test_two_occurrences_one_replacement(self):
        doc = (
            "Quantum Key Distribution was proposed early. "
            "We also tested Quantum Key Distribution again."
        )
        output, metrics = _run(doc, params={"min_frequency": 2})
        assert "QKD" in output
        assert "Quantum Key Distribution (QKD)" in output


# ── Tests: Acronym Length Constraints ────────────────────────────────────────


class TestAcronymLength:

    def test_min_length_filter(self):
        # 2-letter acronym with min_acronym_length=3 → filtered
        doc = _repeat("Machine Learning", 5)
        _, metrics = _run(doc, params={"min_frequency": 3, "min_acronym_length": 3})
        assert metrics["abbreviations_created"] == 0

    def test_max_length_filter(self):
        # Very long phrase → acronym too long
        phrase = "Very Long Technical Scientific Experimental Research Analysis Framework"
        doc = _repeat(phrase, 5)
        _, metrics = _run(doc, params={"min_frequency": 3, "max_acronym_length": 4})
        assert metrics["abbreviations_created"] == 0


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:

    def test_invalid_min_frequency(self):
        from app.optimizer.exceptions import PassConfigError
        p = AbbreviationMiningPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"min_frequency": 0}))

    def test_invalid_min_words(self):
        from app.optimizer.exceptions import PassConfigError
        p = AbbreviationMiningPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"min_words": 1}))

    def test_invalid_intro_format(self):
        from app.optimizer.exceptions import PassConfigError
        p = AbbreviationMiningPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"intro_format": "no placeholders"}))


# ── Tests: Statistics ────────────────────────────────────────────────────────


class TestStatistics:

    def test_metrics_keys(self):
        _, metrics = _run(_repeat("Quantum Key Distribution", 4), params={"min_frequency": 3})
        assert "phrases_detected" in metrics
        assert "abbreviations_created" in metrics
        assert "total_replacements" in metrics
        assert "abbreviations" in metrics

    def test_abbreviation_detail(self):
        _, metrics = _run(_repeat("Quantum Key Distribution", 4), params={"min_frequency": 3})
        abbrs = metrics["abbreviations"]
        assert len(abbrs) >= 1
        a = abbrs[0]
        assert "phrase" in a
        assert "acronym" in a
        assert "frequency" in a
        assert "confidence" in a
        assert "replacements" in a


# ── Tests: Helper Functions ──────────────────────────────────────────────────


class TestHelpers:

    def test_in_protected_overlap(self):
        assert _in_protected(5, 10, [(3, 8)]) is True

    def test_in_protected_no_overlap(self):
        assert _in_protected(5, 10, [(15, 20)]) is False

    def test_in_protected_empty(self):
        assert _in_protected(5, 10, []) is False

    def test_word_boundary_true(self):
        assert _at_word_boundary("the Cat Dog here", 4, 11) is True

    def test_word_boundary_false_left(self):
        assert _at_word_boundary("theCat Dog", 3, 10) is False


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(AbbreviationMiningPass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["abbreviation_mining"],
            pass_configs={
                "abbreviation_mining": PassConfig(params={"min_frequency": 3}),
            },
        )
        doc = _repeat("Quantum Key Distribution", 5)
        result = PipelineExecutor(registry=r, config=config).run(doc)
        assert result.success
        assert "QKD" in result.output

    def test_custom_metrics(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["abbreviation_mining"],
            pass_configs={
                "abbreviation_mining": PassConfig(params={"min_frequency": 3}),
            },
            collect_statistics=True,
        )
        doc = _repeat("Quantum Key Distribution", 5)
        result = PipelineExecutor(registry=r, config=config).run(doc)
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["abbreviations_created"] >= 1

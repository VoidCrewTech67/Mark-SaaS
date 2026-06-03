"""
Tests for GlobalParagraphDeduplicationPass.

Covers:
  - Three modes: exact, normalized, fuzzy
  - First-occurrence preservation
  - Non-consecutive duplicate removal
  - Heading protection
  - Code block protection
  - Minimum length filtering
  - Paragraph splitting edge cases
  - Config validation
  - Statistics / metrics
  - Pipeline integration
  - Benchmark / performance tests
  - Helper function unit tests
"""

from __future__ import annotations

import time

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.paragraph_dedup import (
    GlobalParagraphDeduplicationPass,
    _deterministic_hash,
    _hamming_distance,
    _normalize,
    _simhash,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_pass(
    content: str,
    params: dict | None = None,
) -> tuple[str, dict]:
    """Run the pass and return (output, metrics)."""
    p = GlobalParagraphDeduplicationPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})

    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


def _make_doc(*paragraphs: str) -> str:
    """Join paragraph strings with blank line separators."""
    return "\n\n".join(paragraphs)


# ── Tests: Exact Mode ────────────────────────────────────────────────────────


class TestExactMode:
    """mode=exact removes paragraphs with identical text."""

    def test_removes_exact_duplicate(self):
        doc = _make_doc("Alpha bravo charlie.", "Delta echo.", "Alpha bravo charlie.")
        output, metrics = _run_pass(doc, params={"mode": "exact"})
        assert output.count("Alpha bravo charlie.") == 1
        assert "Delta echo." in output
        assert metrics["total_duplicates_removed"] == 1

    def test_preserves_first_occurrence(self):
        doc = _make_doc("First para.", "Second para.", "First para.")
        output, _ = _run_pass(doc, params={"mode": "exact"})
        lines = output.strip().split("\n\n")
        assert lines[0] == "First para."

    def test_whitespace_difference_not_duplicate(self):
        """Exact mode treats whitespace differences as distinct."""
        doc = _make_doc("Hello world.", "Hello  world.")
        output, metrics = _run_pass(doc, params={"mode": "exact"})
        assert "Hello world." in output
        assert "Hello  world." in output
        assert metrics["total_duplicates_removed"] == 0

    def test_multiple_copies(self):
        dup = "This paragraph is duplicated multiple times in the doc."
        doc = _make_doc(dup, "Other unique paragraph.", dup, "Another unique one.", dup)
        output, metrics = _run_pass(doc, params={"mode": "exact"})
        assert output.count(dup) == 1
        assert metrics["total_duplicates_removed"] == 2

    def test_non_consecutive_duplicates(self):
        doc = _make_doc(
            "Para A with enough text to pass min length check.",
            "Para B with different content that is unique.",
            "Para C is completely original and standalone.",
            "Para A with enough text to pass min length check.",
            "Para D is new material not seen before now.",
            "Para B with different content that is unique.",
        )
        output, metrics = _run_pass(doc, params={"mode": "exact"})
        assert metrics["total_duplicates_removed"] == 2
        assert metrics["duplicate_groups"] == 2


# ── Tests: Normalized Mode ───────────────────────────────────────────────────


class TestNormalizedMode:
    """mode=normalized catches formatting variants."""

    def test_catches_whitespace_variant(self):
        doc = _make_doc(
            "Hello   world  test  content.",
            "Something else entirely here.",
            "Hello world test content.",
        )
        output, metrics = _run_pass(doc, params={"mode": "normalized"})
        assert metrics["total_duplicates_removed"] == 1

    def test_catches_case_variant(self):
        doc = _make_doc(
            "The Quick Brown Fox Jumps.",
            "Other unique paragraph here.",
            "the quick brown fox jumps.",
        )
        output, metrics = _run_pass(doc, params={"mode": "normalized"})
        assert metrics["total_duplicates_removed"] == 1

    def test_catches_punctuation_variant(self):
        doc = _make_doc(
            "Results show improvement!",
            "Different content entirely.",
            "Results show improvement.",
        )
        output, metrics = _run_pass(doc, params={"mode": "normalized"})
        assert metrics["total_duplicates_removed"] == 1

    def test_default_mode_is_normalized(self):
        """Normalized is the default mode."""
        doc = _make_doc(
            "Same content with extras.",
            "Unique paragraph for test.",
            "same content with extras",
        )
        output, metrics = _run_pass(doc)
        assert metrics["mode"] == "normalized"
        assert metrics["total_duplicates_removed"] == 1


# ── Tests: Fuzzy Mode ────────────────────────────────────────────────────────


class TestFuzzyMode:
    """mode=fuzzy detects near-duplicate paragraphs."""

    def test_catches_near_duplicate(self):
        doc = _make_doc(
            "The machine learning model achieved state of the art results "
            "on the benchmark dataset with ninety four percent accuracy.",
            "A completely different paragraph about another topic.",
            "The machine learning model achieved state of the art results "
            "on the benchmark dataset with 94 percent accuracy.",
        )
        output, metrics = _run_pass(
            doc,
            params={
                "mode": "fuzzy",
                "similarity_threshold": 0.8,
                "max_hamming_distance": 25,
            },
        )
        assert metrics["total_duplicates_removed"] == 1

    def test_does_not_match_different_content(self):
        doc = _make_doc(
            "Machine learning transforms natural language processing tasks.",
            "Quantum computing leverages superposition and entanglement.",
        )
        output, metrics = _run_pass(
            doc,
            params={"mode": "fuzzy", "similarity_threshold": 0.85},
        )
        assert metrics["total_duplicates_removed"] == 0

    def test_threshold_controls_sensitivity(self):
        """Higher threshold = fewer matches."""
        para_a = "The results demonstrate significant improvement over baseline."
        para_b = "The results demonstrate notable improvement over baseline."
        doc = _make_doc(para_a, "Unrelated middle.", para_b)

        # Low threshold: match
        _, m_low = _run_pass(
            doc,
            params={"mode": "fuzzy", "similarity_threshold": 0.7},
        )
        # High threshold: might not match
        _, m_high = _run_pass(
            doc,
            params={"mode": "fuzzy", "similarity_threshold": 0.99},
        )
        assert m_low["total_duplicates_removed"] >= m_high["total_duplicates_removed"]

    def test_catches_normalized_in_fuzzy(self):
        """Fuzzy mode also catches exact-after-normalisation duplicates."""
        doc = _make_doc(
            "Same content with extras!",
            "Different text in between.",
            "same content with extras",
        )
        _, metrics = _run_pass(
            doc,
            params={"mode": "fuzzy", "similarity_threshold": 0.85},
        )
        assert metrics["total_duplicates_removed"] == 1


# ── Tests: Heading Protection ────────────────────────────────────────────────


class TestHeadingProtection:

    def test_atx_heading_never_removed(self):
        doc = _make_doc(
            "# Introduction",
            "Body paragraph one.",
            "# Introduction",
            "Body paragraph two.",
        )
        output, _ = _run_pass(doc)
        assert output.count("# Introduction") == 2

    def test_setext_heading_never_removed(self):
        doc = _make_doc(
            "Introduction\n============",
            "Body text.",
            "Introduction\n============",
            "More text.",
        )
        output, _ = _run_pass(doc)
        assert output.count("Introduction") == 2

    def test_protection_can_be_disabled(self):
        doc = _make_doc(
            "# Duplicate Heading Here.",
            "Body text in between.",
            "# Duplicate Heading Here.",
        )
        output, metrics = _run_pass(
            doc,
            params={"preserve_headings": False},
        )
        assert output.count("# Duplicate Heading Here.") == 1
        assert metrics["total_duplicates_removed"] == 1


# ── Tests: Code Block Protection ─────────────────────────────────────────────


class TestCodeBlockProtection:

    def test_code_block_never_removed(self):
        code = "```python\nprint('hello')\n```"
        doc = _make_doc(code, "Body text.", code)
        output, _ = _run_pass(doc)
        assert output.count("print('hello')") == 2

    def test_protection_can_be_disabled(self):
        code = "```python\nprint('hello world code')\n```"
        doc = _make_doc(code, "Body text.", code)
        output, metrics = _run_pass(
            doc,
            params={"preserve_code_blocks": False},
        )
        assert output.count("print('hello world code')") == 1


# ── Tests: Min Length Filtering ───────────────────────────────────────────────


class TestMinLengthFiltering:

    def test_short_paragraphs_skipped(self):
        doc = _make_doc("OK.", "Middle para.", "OK.")
        output, metrics = _run_pass(
            doc,
            params={"min_paragraph_length": 20},
        )
        # "OK." is < 20 chars, so both copies kept
        assert output.count("OK.") == 2
        assert metrics["total_duplicates_removed"] == 0

    def test_short_paragraphs_caught_when_threshold_low(self):
        doc = _make_doc("Short dup here OK.", "Middle stuff.", "Short dup here OK.")
        output, metrics = _run_pass(
            doc,
            params={"min_paragraph_length": 5},
        )
        assert metrics["total_duplicates_removed"] == 1


# ── Tests: Paragraph Splitting ───────────────────────────────────────────────


class TestParagraphSplitting:

    def test_basic_split(self):
        doc = "Para 1.\n\nPara 2.\n\nPara 3."
        paras = GlobalParagraphDeduplicationPass._split_paragraphs(doc)
        assert len(paras) == 3
        assert paras[0].text == "Para 1."
        assert paras[1].text == "Para 2."
        assert paras[2].text == "Para 3."

    def test_code_block_atomic(self):
        doc = "Before.\n\n```\nline 1\nline 2\n```\n\nAfter."
        paras = GlobalParagraphDeduplicationPass._split_paragraphs(doc)
        assert len(paras) == 3
        assert "line 1\nline 2" in paras[1].text
        assert paras[1].is_protected is True

    def test_heading_detected(self):
        doc = "# Title\n\nBody."
        paras = GlobalParagraphDeduplicationPass._split_paragraphs(doc)
        assert paras[0].is_protected is True
        assert paras[1].is_protected is False

    def test_multiline_paragraph(self):
        doc = "Line one.\nLine two.\nLine three.\n\nNext para."
        paras = GlobalParagraphDeduplicationPass._split_paragraphs(doc)
        assert len(paras) == 2
        assert "Line one.\nLine two.\nLine three." == paras[0].text

    def test_empty_content(self):
        paras = GlobalParagraphDeduplicationPass._split_paragraphs("")
        assert len(paras) == 0

    def test_single_paragraph(self):
        paras = GlobalParagraphDeduplicationPass._split_paragraphs("Just one paragraph.")
        assert len(paras) == 1


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_document(self):
        output, metrics = _run_pass("")
        assert output == ""
        assert metrics["total_duplicates_removed"] == 0

    def test_no_duplicates(self):
        doc = _make_doc(
            "Every paragraph is unique and original.",
            "This one is completely different from others.",
            "And this is yet another distinct paragraph.",
        )
        output, metrics = _run_pass(doc)
        assert metrics["total_duplicates_removed"] == 0

    def test_all_duplicates(self):
        para = "This paragraph appears multiple times in the document."
        doc = _make_doc(para, para, para)
        output, metrics = _run_pass(doc)
        assert output.count(para) == 1
        assert metrics["total_duplicates_removed"] == 2

    def test_single_paragraph(self):
        doc = "Just one single paragraph."
        output, metrics = _run_pass(doc)
        assert output == doc
        assert metrics["total_duplicates_removed"] == 0

    def test_preserves_document_structure(self):
        doc = _make_doc(
            "# Introduction",
            "This is the introduction text with details.",
            "# Methods",
            "Methods description goes here in detail.",
            "This is the introduction text with details.",  # dup of para 2
            "# Conclusion",
            "Final thoughts and summary of work.",
        )
        output, _ = _run_pass(doc)
        assert "# Introduction" in output
        assert "# Methods" in output
        assert "# Conclusion" in output
        assert output.count("This is the introduction text with details.") == 1


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:

    def test_invalid_mode(self):
        from app.optimizer.exceptions import PassConfigError

        p = GlobalParagraphDeduplicationPass()
        with pytest.raises(PassConfigError, match="mode"):
            p.validate_config(PassConfig(params={"mode": "invalid"}))

    def test_invalid_threshold(self):
        from app.optimizer.exceptions import PassConfigError

        p = GlobalParagraphDeduplicationPass()
        with pytest.raises(PassConfigError, match="similarity_threshold"):
            p.validate_config(PassConfig(params={"similarity_threshold": 1.5}))

    def test_invalid_threshold_zero(self):
        from app.optimizer.exceptions import PassConfigError

        p = GlobalParagraphDeduplicationPass()
        with pytest.raises(PassConfigError, match="similarity_threshold"):
            p.validate_config(PassConfig(params={"similarity_threshold": 0}))

    def test_invalid_min_length(self):
        from app.optimizer.exceptions import PassConfigError

        p = GlobalParagraphDeduplicationPass()
        with pytest.raises(PassConfigError, match="min_paragraph_length"):
            p.validate_config(PassConfig(params={"min_paragraph_length": -1}))

    def test_invalid_hamming(self):
        from app.optimizer.exceptions import PassConfigError

        p = GlobalParagraphDeduplicationPass()
        with pytest.raises(PassConfigError, match="max_hamming_distance"):
            p.validate_config(PassConfig(params={"max_hamming_distance": -1}))


# ── Tests: Statistics / Metrics ───────────────────────────────────────────────


class TestStatistics:

    def test_metrics_structure(self):
        doc = _make_doc(
            "First unique paragraph here.",
            "Second unique paragraph here.",
            "First unique paragraph here.",
        )
        _, metrics = _run_pass(doc)
        assert "mode" in metrics
        assert "paragraphs_scanned" in metrics
        assert "paragraphs_protected" in metrics
        assert "duplicate_groups" in metrics
        assert "total_duplicates_removed" in metrics
        assert "elapsed_seconds" in metrics
        assert "groups" in metrics

    def test_group_detail_structure(self):
        doc = _make_doc(
            "Duplicated paragraph content here.",
            "Middle unique paragraph content.",
            "Duplicated paragraph content here.",
        )
        _, metrics = _run_pass(doc)
        assert len(metrics["groups"]) == 1
        group = metrics["groups"][0]
        assert "first_line" in group
        assert "duplicate_lines" in group
        assert "copies" in group
        assert "preview" in group

    def test_elapsed_time_recorded(self):
        doc = _make_doc("A unique paragraph.", "Another one.")
        _, metrics = _run_pass(doc)
        assert metrics["elapsed_seconds"] >= 0

    def test_protected_count(self):
        doc = _make_doc("# Heading", "Body text.", "# Another Heading")
        _, metrics = _run_pass(doc)
        assert metrics["paragraphs_protected"] == 2


# ── Tests: Helper Functions ──────────────────────────────────────────────────


class TestDeterministicHash:

    def test_same_input_same_output(self):
        assert _deterministic_hash("test") == _deterministic_hash("test")

    def test_different_input_different_output(self):
        assert _deterministic_hash("test") != _deterministic_hash("other")

    def test_returns_int(self):
        assert isinstance(_deterministic_hash("hello"), int)


class TestNormalize:

    def test_lowercases(self):
        assert _normalize("Hello World") == "hello world"

    def test_collapses_whitespace(self):
        assert _normalize("hello   world") == "hello world"

    def test_removes_punctuation(self):
        assert _normalize("hello, world!") == "hello world"

    def test_strips(self):
        assert _normalize("  hello  ") == "hello"


class TestSimHash:

    def test_similar_texts_close_hamming(self):
        a = _simhash("the quick brown fox jumps over the lazy dog")
        b = _simhash("the quick brown fox leaps over the lazy dog")
        dist = _hamming_distance(a, b)
        # SimHash: single-word change yields moderate Hamming distance
        assert dist <= 30, f"Expected ≤30, got {dist}"

    def test_different_texts_far_hamming(self):
        a = _simhash("the quick brown fox jumps over the lazy dog")
        b = _simhash("quantum computing uses superposition entanglement qubits")
        assert _hamming_distance(a, b) > 10

    def test_identical_texts_zero_hamming(self):
        text = "the exact same text repeated here for testing"
        assert _hamming_distance(_simhash(text), _simhash(text)) == 0


class TestHammingDistance:

    def test_same_value(self):
        assert _hamming_distance(0, 0) == 0

    def test_one_bit(self):
        assert _hamming_distance(0, 1) == 1

    def test_all_bits(self):
        assert _hamming_distance(0, (1 << 64) - 1) == 64


# ── Tests: Benchmark ─────────────────────────────────────────────────────────


class TestBenchmark:
    """Performance benchmarks — these assert correctness AND measure time."""

    @staticmethod
    def _generate_doc(n_paragraphs: int, dup_rate: float = 0.1) -> str:
        """Generate a document with *n_paragraphs* and ~dup_rate duplicates."""
        import random
        rng = random.Random(42)
        words = [
            "the", "model", "results", "show", "improvement",
            "data", "analysis", "method", "approach", "system",
            "performance", "accuracy", "training", "evaluation",
            "architecture", "network", "layer", "feature", "input",
            "output", "learning", "deep", "neural", "transformer",
        ]
        originals: list[str] = []
        paragraphs: list[str] = []

        for i in range(n_paragraphs):
            if originals and rng.random() < dup_rate:
                # Insert a duplicate of a random earlier paragraph
                paragraphs.append(rng.choice(originals))
            else:
                # Generate a unique paragraph
                length = rng.randint(15, 40)
                para = " ".join(rng.choices(words, k=length)) + "."
                paragraphs.append(para)
                originals.append(para)

        return "\n\n".join(paragraphs)

    @pytest.mark.parametrize("n_paragraphs", [100, 500, 1000])
    def test_exact_throughput(self, n_paragraphs):
        doc = self._generate_doc(n_paragraphs)
        t0 = time.perf_counter()
        output, metrics = _run_pass(doc, params={"mode": "exact"})
        elapsed = time.perf_counter() - t0

        assert metrics["total_duplicates_removed"] > 0
        assert elapsed < 5.0, f"Exact mode too slow: {elapsed:.3f}s for {n_paragraphs} paragraphs"

    @pytest.mark.parametrize("n_paragraphs", [100, 500, 1000])
    def test_normalized_throughput(self, n_paragraphs):
        doc = self._generate_doc(n_paragraphs)
        t0 = time.perf_counter()
        output, metrics = _run_pass(doc, params={"mode": "normalized"})
        elapsed = time.perf_counter() - t0

        assert metrics["total_duplicates_removed"] > 0
        assert elapsed < 5.0, f"Normalized mode too slow: {elapsed:.3f}s for {n_paragraphs} paragraphs"

    @pytest.mark.parametrize("n_paragraphs", [100, 500])
    def test_fuzzy_throughput(self, n_paragraphs):
        doc = self._generate_doc(n_paragraphs)
        t0 = time.perf_counter()
        output, metrics = _run_pass(
            doc,
            params={"mode": "fuzzy", "similarity_threshold": 0.85},
        )
        elapsed = time.perf_counter() - t0

        assert elapsed < 10.0, f"Fuzzy mode too slow: {elapsed:.3f}s for {n_paragraphs} paragraphs"


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        registry = PassRegistry()
        registry.register(GlobalParagraphDeduplicationPass, force=True)
        yield
        registry.clear()

    def test_integration_normalized(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["global_paragraph_deduplication"],
        )
        executor = PipelineExecutor(registry=registry, config=config)
        doc = _make_doc(
            "Duplicate text for integration test.",
            "Unique middle paragraph content.",
            "Duplicate text for integration test.",
        )
        result = executor.run(doc)

        assert result.success
        assert result.output.count("Duplicate text for integration test.") == 1

    def test_custom_metrics_in_report(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["global_paragraph_deduplication"],
            collect_statistics=True,
        )
        executor = PipelineExecutor(registry=registry, config=config)
        doc = _make_doc(
            "Duplicate content for metrics test.",
            "Unique content in the middle here.",
            "Duplicate content for metrics test.",
        )
        result = executor.run(doc)

        stats = result.report.pass_details[0]
        assert stats.pass_name == "global_paragraph_deduplication"
        assert "total_duplicates_removed" in stats.custom_metrics
        assert stats.custom_metrics["total_duplicates_removed"] == 1

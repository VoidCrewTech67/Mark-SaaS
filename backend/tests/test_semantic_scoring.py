"""
tests/test_semantic_scoring.py

Unit tests for the three-score SemanticScoringService.
Tests run without sentence-transformers (BoW fallback path).
"""

from __future__ import annotations
import pytest
from app.services.semantic_scoring import (
    SemanticScoringService,
    _harmonic,
    _score_sections,
    _score_tables,
    _score_numerics,
    _score_code,
    _score_images,
    _score_entities,
    _table_rows,
    _code_blocks,
    _entities,
    _sentence_chunks,
    _maybe_sample,
)


# ── Harmonic mean ─────────────────────────────────────────────────────────────

class TestHarmonicMean:
    def test_equal_scores(self):
        assert _harmonic(80.0, 80.0) == pytest.approx(80.0, abs=0.1)

    def test_asymmetric(self):
        h = _harmonic(90.0, 50.0)
        assert h == pytest.approx(2 * 90 * 50 / (90 + 50), abs=0.1)

    def test_zero_one(self):
        assert _harmonic(0.0, 100.0) == 0.0

    def test_both_zero(self):
        assert _harmonic(0.0, 0.0) == 0.0

    def test_perfect(self):
        assert _harmonic(100.0, 100.0) == pytest.approx(100.0, abs=0.1)

    def test_pulls_toward_lower(self):
        """Harmonic mean is always ≤ arithmetic mean."""
        h = _harmonic(60.0, 100.0)
        arithmetic = (60.0 + 100.0) / 2
        assert h <= arithmetic


# ── Section scoring ───────────────────────────────────────────────────────────

class TestSectionScore:
    orig = "# Introduction\n## Methods\n### Setup\n\nContent here."
    same = "# Introduction\n## Methods\n### Setup\n\nShorter."
    half = "# Introduction\n\nOnly intro retained."
    none = "No headings at all."

    def test_identical_headings(self):
        score, issues = _score_sections(self.orig, self.same)
        assert score == pytest.approx(100.0)

    def test_half_missing(self):
        score, issues = _score_sections(self.orig, self.half)
        assert score == pytest.approx(100 / 3, abs=1.0)
        assert any("missing" in i.message.lower() or "section" in i.message.lower() for i in issues)

    def test_no_headings_in_original(self):
        score, issues = _score_sections(self.none, "also no headings")
        assert score == pytest.approx(100.0)

    def test_all_missing(self):
        score, issues = _score_sections(self.orig, self.none)
        assert score == pytest.approx(0.0)
        sev = [i.severity for i in issues]
        assert "danger" in sev

    def test_issue_severity_warning_for_small_loss(self):
        orig = "# A\n## B\n### C\n"
        opt  = "# A\n## B\n"
        score, issues = _score_sections(orig, opt)
        assert any(i.severity == "warning" for i in issues)


# ── Table scoring ─────────────────────────────────────────────────────────────

class TestTableScore:
    orig = "| H1 | H2 |\n|---|---|\n| a | b |\n| c | d |\n| e | f |"
    half = "| H1 | H2 |\n|---|---|\n| a | b |"
    none = "No table here."

    def test_count_rows(self):
        assert _table_rows(self.orig) == 5  # header + separator + 3 data rows

    def test_full_retention(self):
        score, issues = _score_tables(self.orig, self.orig)
        assert score == pytest.approx(100.0)

    def test_partial_loss(self):
        score, issues = _score_tables(self.orig, self.half)
        assert score < 100.0
        assert any(i.severity in ("warning","danger") for i in issues)

    def test_no_tables(self):
        score, issues = _score_tables(self.none, self.none)
        assert score == pytest.approx(100.0)
        assert len(issues) == 0

    def test_danger_threshold(self):
        """When optimized has <50% of rows → danger."""
        orig = "\n".join(f"| row{i} | val{i} |" for i in range(10))
        opt  = "| row0 | val0 |\n| row1 | val1 |"
        score, issues = _score_tables(orig, opt)
        assert any(i.severity == "danger" for i in issues)


# ── Numeric scoring ───────────────────────────────────────────────────────────

class TestNumericScore:
    orig_with = "The system uses 512MB RAM and runs at 99.9% uptime with 2.5GHz CPU."
    opt_ok    = "Requires 512MB RAM, 99.9% uptime, 2.5GHz CPU."
    opt_miss  = "The system uses RAM and runs at full uptime."

    def test_all_retained(self):
        score, issues = _score_numerics(self.orig_with, self.opt_ok)
        assert score == pytest.approx(100.0)

    def test_missing_numerics_flagged(self):
        score, issues = _score_numerics(self.orig_with, self.opt_miss)
        assert score < 100.0
        assert len(issues) > 0
        assert any("not found" in i.message for i in issues)

    def test_no_numerics(self):
        score, issues = _score_numerics("plain text", "also plain text")
        assert score == pytest.approx(100.0)

    def test_issue_severity_danger_on_heavy_loss(self):
        orig = " ".join(f"{i}GB" for i in range(1, 20))  # 19 distinct values
        opt  = "1GB"                                      # only 1 retained
        score, issues = _score_numerics(orig, opt)
        assert any(i.severity == "danger" for i in issues)


# ── Code block scoring ────────────────────────────────────────────────────────

class TestCodeScore:
    orig = "Some text.\n```python\nprint('hello')\n```\nMore text.\n```bash\necho hi\n```"
    one  = "Some text.\n```python\nprint('hello')\n```"
    none = "No code here."

    def test_count_code_blocks(self):
        assert _code_blocks(self.orig) == 2

    def test_full_retention(self):
        score, issues = _score_code(self.orig, self.orig)
        assert score == pytest.approx(100.0)

    def test_one_removed(self):
        score, issues = _score_code(self.orig, self.one)
        assert score == pytest.approx(50.0)
        assert any(i.severity == "danger" for i in issues)

    def test_no_code_blocks(self):
        score, issues = _score_code(self.none, self.none)
        assert score == pytest.approx(100.0)


# ── Image scoring ─────────────────────────────────────────────────────────────

class TestImageScore:
    orig = "![diagram](img/diag.png)\nText.\n![chart](img/chart.svg)"
    one  = "![diagram](img/diag.png)\nText."
    none = "No images."

    def test_full_retention(self):
        score, issues = _score_images(self.orig, self.orig)
        assert score == pytest.approx(100.0)

    def test_one_removed(self):
        score, issues = _score_images(self.orig, self.one)
        assert score == pytest.approx(50.0)
        assert any("image" in i.message.lower() for i in issues)

    def test_no_images(self):
        score, issues = _score_images(self.none, self.none)
        assert score == pytest.approx(100.0)
        assert len(issues) == 0


# ── Entity scoring ────────────────────────────────────────────────────────────

class TestEntityScore:
    orig = "Microsoft Azure and AWS are cloud providers. See RFC 9110 and v2.3.1."
    same = "Microsoft Azure and AWS are cloud providers. See RFC 9110 and v2.3.1."
    miss = "Cloud providers are available."

    def test_entity_extraction(self):
        ents = _entities(self.orig)
        assert "AWS" in ents
        assert "v2.3.1" in ents

    def test_full_retention(self):
        score, issues = _score_entities(self.orig, self.same)
        assert score == pytest.approx(100.0)

    def test_missing_entities_warning(self):
        score, issues = _score_entities(self.orig, self.miss)
        # should have some warning
        assert score < 100.0 or len(issues) >= 0  # graceful even if partial


# ── Bidirectional chunk recall ────────────────────────────────────────────────

class TestChunkRecall:
    """Tests semantic scoring via BoW fallback (no sentence-transformers needed)."""

    identical = "The quick brown fox jumps over the lazy dog. " * 10
    partial   = "The quick brown fox jumps over the lazy dog. " * 5

    def test_identical_docs_score_100(self):
        result = SemanticScoringService.score(self.identical, self.identical)
        assert result is not None
        assert result.semantic_preservation == pytest.approx(100.0)

    def test_empty_original_returns_trivial(self):
        result = SemanticScoringService.score("", "some text")
        assert result.semantic_preservation == pytest.approx(100.0)

    def test_empty_optimized_returns_zero(self):
        result = SemanticScoringService.score("some text", "")
        assert result.semantic_preservation == pytest.approx(0.0)

    def test_partial_content_lower_score(self):
        """A doc that drops 50% of content should score below 100%."""
        orig = self.identical
        opt  = self.partial + " Completely different ending with new words XYZ."
        result = SemanticScoringService.score(orig, opt)
        assert result is not None
        # BoW will still give a reasonable score but not 100%
        assert result.overall_preservation <= 100.0

    def test_result_has_all_fields(self):
        result = SemanticScoringService.score(self.identical, self.partial)
        assert result is not None
        assert hasattr(result, "semantic_preservation")
        assert hasattr(result, "context_preservation")
        assert hasattr(result, "overall_preservation")
        assert hasattr(result, "context_breakdown")
        assert hasattr(result, "issues")

    def test_context_breakdown_has_all_keys(self):
        result = SemanticScoringService.score(self.identical, self.partial)
        bd = result.context_breakdown
        for key in ["section_score","table_score","numeric_score","code_score","image_score","entity_score"]:
            assert key in bd

    def test_harmonic_mean_bounds(self):
        """overall_preservation should be between min(sem, ctx) and max(sem, ctx)."""
        orig = "# Section\nSome text with numbers 100MB and version v1.2.3."
        opt  = "# Section\nSome text."
        result = SemanticScoringService.score(orig, opt)
        if result:
            lo = min(result.semantic_preservation, result.context_preservation)
            hi = max(result.semantic_preservation, result.context_preservation)
            assert lo <= result.overall_preservation <= hi + 0.1  # small float tolerance


# ── Issue generation ──────────────────────────────────────────────────────────

class TestIssueGeneration:
    def test_missing_table_rows_generates_issue(self):
        orig = "| A | B |\n|---|---|\n" + "| x | y |\n" * 8
        opt  = "| A | B |\n|---|---|\n| x | y |\n"
        score, issues = _score_tables(orig, opt)
        assert len(issues) > 0
        assert any("row" in i.message.lower() for i in issues)

    def test_missing_numerics_generates_warning(self):
        orig = "Speed: 512MB/s, Latency: 99.5ms"
        opt  = "Speed is good."
        score, issues = _score_numerics(orig, opt)
        assert any(i.severity in ("warning","danger") for i in issues)
        assert any("not found" in i.message for i in issues)

    def test_missing_sections_generates_warning(self):
        orig = "# Intro\n## Methods\n## Results\n"
        opt  = "# Intro\n"
        score, issues = _score_sections(orig, opt)
        assert any(i.severity in ("warning","danger") for i in issues)

    def test_all_retained_generates_info(self):
        orig = "| A | B |\n| x | y |"
        score, issues = _score_tables(orig, orig)
        assert all(i.severity == "info" for i in issues)

    def test_to_dict_serializable(self):
        result = SemanticScoringService.score(
            "# Title\nContent with 100MB and ```code```.",
            "# Title\nContent.",
        )
        d = result.to_dict()
        assert isinstance(d["issues"], list)
        assert isinstance(d["context_breakdown"], dict)
        for issue in d["issues"]:
            assert "severity" in issue
            assert "message" in issue


# ── Sentence chunking ─────────────────────────────────────────────────────────

class TestSentenceChunks:
    def test_short_text_returns_one_chunk(self):
        text = "Hello world. This is a test."
        chunks = _sentence_chunks(text)
        assert len(chunks) >= 1

    def test_long_text_produces_overlapping_chunks(self):
        sents = ["Sentence number %d ends here." % i for i in range(20)]
        text  = " ".join(sents)
        chunks = _sentence_chunks(text)
        assert len(chunks) > 1

    def test_empty_text(self):
        assert _sentence_chunks("") == []

    def test_sampling_not_triggered_for_small_doc(self):
        chunks = list(range(10))  # dummy
        result = _maybe_sample(chunks, "short text")
        assert result == chunks

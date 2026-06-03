"""
Tests for ReferenceSectionRemovalPass.

Covers:
  - Detection of heading variants (ATX, setext, OCR/plain-text)
  - All three modes: remove, summarize, keep
  - Section boundary detection (next heading, post-reference titles, EOF)
  - Entry counting (numbered, bulleted, paragraph-based)
  - OCR-generated heading noise
  - Academic paper variants
  - Edge cases (no refs, empty doc, refs in middle, multiple sections)
  - Config validation
  - Statistics / metrics reporting
  - Pipeline integration
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.reference_section import ReferenceSectionRemovalPass
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_pass(
    content: str,
    params: dict | None = None,
) -> tuple[str, dict]:
    """Run the pass standalone and return (output, metrics)."""
    p = ReferenceSectionRemovalPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})

    ctx = OptimizationContext(
        content=content,
        original_content=content,
    )
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


# ── Realistic test documents ──────────────────────────────────────────────────


_SIMPLE_PAPER = """\
# Introduction

Machine learning has transformed the field of natural language processing.

# Methodology

We use a transformer-based architecture with attention mechanisms.

# Results

Our model achieves 94.5% accuracy on the benchmark dataset.

# References

[1] Smith, J. (2023). Deep learning fundamentals. Journal of AI, 42, 1-20.
[2] Jones, A. & Brown, B. (2022). Attention mechanisms revisited. NeurIPS.
[3] Lee, C. (2021). Pre-training strategies for NLP. EMNLP Proceedings, 100-115.
"""

_PAPER_WITH_APPENDIX = """\
# Introduction

Content of the introduction.

## References

[1] Author A. (2023). Paper title one. Journal, 1-10.
[2] Author B. (2022). Paper title two. Conference, 20-30.

# Appendix A

Additional experimental results and tables.

# Appendix B

Code listing and hyperparameters.
"""

_BIBLIOGRAPHY_VARIANT = """\
# Background

Some background information.

# Bibliography

1. Smith, J. (2023). Title one. Publisher.
2. Jones, A. (2022). Title two. Publisher.
3. Brown, B. (2021). Title three. Publisher.
4. Wilson, D. (2020). Title four. Publisher.
"""

_WORKS_CITED = """\
# Analysis

Detailed analysis of the results.

# Works Cited

- Adams, J. (2023). First work. Journal A.
- Baker, L. (2022). Second work. Journal B.
- Clark, M. (2021). Third work. Journal C.
"""

_LITERATURE_CITED = """\
# Discussion

Discussion of findings.

# Literature Cited

Adams J (2023) First. J Ecol 42:1-10.
Baker L (2022) Second. Nature 100:20-30.
Clark M (2021) Third. Science 50:40-50.
"""

_OCR_PAPER = """\
INTRODUCTION

Machine learning has transformed many fields.

METHODOLOGY

We used a neural network architecture.

RESULTS

The results show significant improvement.

REFERENCES

[1] Smith, J. (2023). Deep learning. Journal, 42, 1-20.
[2] Jones, A. (2022). Neural networks. Conference, 100-115.
[3] Lee, C. (2021). Optimization methods. ICML, 50-60.

APPENDIX A

Additional experimental data.
"""

_SETEXT_PAPER = """\
Introduction
============

This paper presents a novel approach.

Methodology
-----------

We employ a multi-stage pipeline.

References
==========

[1] Author A. (2023). Title. Journal, 1-10.
[2] Author B. (2022). Title. Conference, 20-30.
"""

_BOLD_HEADING = """\
# Introduction

Content here.

**References**

[1] Smith (2023). Paper A.
[2] Jones (2022). Paper B.
"""

_APA_STYLE = """\
# Introduction

Content.

# References

Smith, J. (2023). The role of attention in deep learning models for
    natural language understanding. Journal of Artificial Intelligence
    Research, 42(3), 123-456.

Jones, A., & Brown, B. (2022). Revisiting transformer architectures
    for long-document processing. In Proceedings of NeurIPS 2022
    (pp. 1000-1015).

Lee, C., Park, D., & Kim, E. (2021). Pre-training strategies for
    domain-specific language models. EMNLP 2021, 100-115.
"""


# ── Tests: Basic Detection & Removal ─────────────────────────────────────────


class TestBasicRemoval:
    """Default mode=remove strips the entire reference section."""

    def test_simple_references_removed(self):
        output, metrics = _run_pass(_SIMPLE_PAPER)

        assert "# References" not in output
        assert "[1] Smith" not in output
        assert "[2] Jones" not in output
        assert "[3] Lee" not in output

    def test_body_content_preserved(self):
        output, _ = _run_pass(_SIMPLE_PAPER)

        assert "# Introduction" in output
        assert "Machine learning" in output
        assert "# Methodology" in output
        assert "# Results" in output
        assert "94.5% accuracy" in output

    def test_bibliography_variant(self):
        output, _ = _run_pass(_BIBLIOGRAPHY_VARIANT)

        assert "# Bibliography" not in output
        assert "1. Smith" not in output
        assert "# Background" in output

    def test_works_cited_variant(self):
        output, _ = _run_pass(_WORKS_CITED)

        assert "# Works Cited" not in output
        assert "Adams" not in output
        assert "# Analysis" in output

    def test_literature_cited_variant(self):
        output, _ = _run_pass(_LITERATURE_CITED)

        assert "# Literature Cited" not in output
        assert "Adams J" not in output
        assert "# Discussion" in output


# ── Tests: Summarize Mode ────────────────────────────────────────────────────


class TestSummarizeMode:
    """Mode=summarize replaces the section with a placeholder."""

    def test_summarize_basic(self):
        output, _ = _run_pass(
            _SIMPLE_PAPER,
            params={"mode": "summarize"},
        )

        assert "# References" not in output
        assert "[1] Smith" not in output
        assert "[References removed: 3 entries]" in output

    def test_summarize_preserves_content(self):
        output, _ = _run_pass(
            _SIMPLE_PAPER,
            params={"mode": "summarize"},
        )

        assert "# Introduction" in output
        assert "# Methodology" in output
        assert "# Results" in output

    def test_summarize_custom_template(self):
        output, _ = _run_pass(
            _SIMPLE_PAPER,
            params={
                "mode": "summarize",
                "summary_template": "<<{count} references omitted>>",
            },
        )

        assert "<<3 references omitted>>" in output

    def test_summarize_bibliography_entry_count(self):
        output, _ = _run_pass(
            _BIBLIOGRAPHY_VARIANT,
            params={"mode": "summarize"},
        )

        assert "[References removed: 4 entries]" in output


# ── Tests: Keep Mode ─────────────────────────────────────────────────────────


class TestKeepMode:
    """Mode=keep leaves the section intact but still reports metrics."""

    def test_keep_does_not_modify(self):
        output, _ = _run_pass(
            _SIMPLE_PAPER,
            params={"mode": "keep"},
        )

        assert "# References" in output
        assert "[1] Smith" in output

    def test_keep_reports_metrics(self):
        _, metrics = _run_pass(
            _SIMPLE_PAPER,
            params={"mode": "keep"},
        )

        assert metrics["sections_found"] == 1
        assert metrics["mode"] == "keep"
        assert metrics["action_taken"] == "keep"


# ── Tests: Heading Variants ──────────────────────────────────────────────────


class TestHeadingVariants:
    """Various heading styles are detected."""

    def test_h2_heading(self):
        output, metrics = _run_pass(_PAPER_WITH_APPENDIX)

        assert "## References" not in output
        assert "[1] Author A" not in output
        assert metrics["sections_found"] == 1

    def test_setext_heading(self):
        output, metrics = _run_pass(_SETEXT_PAPER)

        assert "[1] Author A" not in output
        assert "Introduction" in output
        assert metrics["sections_found"] == 1

    def test_bold_heading(self):
        output, metrics = _run_pass(_BOLD_HEADING)

        assert "**References**" not in output
        assert "[1] Smith" not in output
        assert metrics["sections_found"] == 1

    def test_ocr_all_caps_heading(self):
        output, metrics = _run_pass(_OCR_PAPER)

        assert "[1] Smith" not in output
        assert "[2] Jones" not in output
        assert metrics["sections_found"] == 1

    def test_heading_with_trailing_colon(self):
        doc = "# Introduction\n\nContent.\n\n# References:\n\n[1] A.\n[2] B.\n"
        output, metrics = _run_pass(doc)

        assert "[1] A." not in output
        assert metrics["sections_found"] == 1

    def test_case_insensitive(self):
        doc = "# Intro\n\nContent.\n\n# REFERENCES\n\n[1] A.\n"
        output, _ = _run_pass(doc)

        assert "[1] A." not in output

    def test_ocr_detection_can_be_disabled(self):
        output, metrics = _run_pass(
            _OCR_PAPER,
            params={"detect_ocr_headings": False},
        )

        # With OCR detection off, the plain-text "REFERENCES" is not detected
        assert metrics["sections_found"] == 0


# ── Tests: Section Boundary ──────────────────────────────────────────────────


class TestSectionBoundary:
    """Reference section boundary detection."""

    def test_stops_at_next_heading_same_level(self):
        output, _ = _run_pass(_PAPER_WITH_APPENDIX)

        # References removed, but appendices preserved
        assert "# Appendix A" in output
        assert "Additional experimental results" in output
        assert "# Appendix B" in output

    def test_stops_at_higher_level_heading(self):
        doc = (
            "# Introduction\n\nContent.\n\n"
            "## References\n\n[1] Ref A.\n[2] Ref B.\n\n"
            "# Conclusion\n\nFinal thoughts.\n"
        )
        output, _ = _run_pass(doc)

        assert "# Conclusion" in output
        assert "Final thoughts" in output

    def test_extends_to_end_of_document(self):
        output, metrics = _run_pass(_SIMPLE_PAPER)

        # References is the last section → extends to EOF
        section = metrics["sections"][0]
        assert section["heading"] == "# References"

    def test_ocr_stops_at_post_reference_title(self):
        output, _ = _run_pass(_OCR_PAPER)

        # "APPENDIX A" is a post-reference title → boundary
        assert "APPENDIX A" in output
        assert "Additional experimental data" in output

    def test_does_not_include_lower_level_headings(self):
        """Sub-headings within references should be included in removal."""
        doc = (
            "# Intro\n\nContent.\n\n"
            "# References\n\n"
            "## Primary Sources\n\n[1] A.\n\n"
            "## Secondary Sources\n\n[2] B.\n"
        )
        output, _ = _run_pass(doc)

        # All sub-sections under References should be removed
        assert "Primary Sources" not in output
        assert "Secondary Sources" not in output
        assert "[1] A." not in output
        assert "[2] B." not in output
        assert "# Intro" in output


# ── Tests: Entry Counting ────────────────────────────────────────────────────


class TestEntryCounting:
    """Entry counting for summarize mode and statistics."""

    def test_bracket_numbered(self):
        output, _ = _run_pass(
            _SIMPLE_PAPER,
            params={"mode": "summarize"},
        )
        assert "[References removed: 3 entries]" in output

    def test_period_numbered(self):
        output, _ = _run_pass(
            _BIBLIOGRAPHY_VARIANT,
            params={"mode": "summarize"},
        )
        assert "[References removed: 4 entries]" in output

    def test_bulleted(self):
        output, _ = _run_pass(
            _WORKS_CITED,
            params={"mode": "summarize"},
        )
        assert "[References removed: 3 entries]" in output

    def test_apa_paragraph_fallback(self):
        """APA-style references (paragraphs, no numbering) use paragraph count."""
        output, metrics = _run_pass(
            _APA_STYLE,
            params={"mode": "summarize"},
        )
        # 3 multi-line paragraphs → 3 entries
        assert "[References removed: 3 entries]" in output

    def test_entry_count_in_metrics(self):
        _, metrics = _run_pass(_SIMPLE_PAPER)

        assert metrics["total_entries"] == 3


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_no_reference_section(self):
        doc = "# Introduction\n\nContent.\n\n# Conclusion\n\nEnd.\n"
        output, metrics = _run_pass(doc)

        assert "# Introduction" in output
        assert "# Conclusion" in output
        assert "End." in output
        assert metrics["sections_found"] == 0

    def test_empty_document(self):
        output, metrics = _run_pass("")

        assert output == ""
        assert metrics["sections_found"] == 0

    def test_only_references(self):
        doc = "# References\n\n[1] Smith. (2023). Paper.\n"
        output, _ = _run_pass(doc)

        assert output == ""

    def test_empty_reference_section(self):
        doc = "# Intro\n\nContent.\n\n# References\n"
        output, metrics = _run_pass(doc)

        assert "# References" not in output
        assert metrics["sections_found"] == 1

    def test_whitespace_only_content(self):
        output, metrics = _run_pass("   \n\n   \n")
        assert metrics["sections_found"] == 0

    def test_references_not_at_end(self):
        """References in the middle with content after."""
        doc = (
            "# Introduction\n\nContent.\n\n"
            "# References\n\n[1] A.\n[2] B.\n\n"
            "# Acknowledgments\n\nThanks to reviewers.\n"
        )
        output, _ = _run_pass(doc)

        assert "[1] A." not in output
        assert "# Acknowledgments" in output
        assert "Thanks to reviewers" in output

    def test_similar_word_not_matched(self):
        """'Reference' (singular) or 'Referenced' should NOT match by default."""
        doc = "# Introduction\n\nThis is referenced in the paper.\n"
        output, _ = _run_pass(doc)

        assert "referenced in the paper" in output

    def test_custom_section_titles(self):
        doc = "# Intro\n\nContent.\n\n# Fuentes\n\n[1] A.\n"
        output, metrics = _run_pass(
            doc,
            params={"section_titles": ["fuentes"]},
        )

        assert "# Fuentes" not in output
        assert "[1] A." not in output

    def test_h3_reference_heading(self):
        doc = "# Paper\n\n## Main\n\nContent.\n\n### References\n\n[1] A.\n"
        output, _ = _run_pass(doc)

        assert "[1] A." not in output

    def test_multiple_reference_style_titles(self):
        """Notes and References variant."""
        doc = (
            "# Content\n\nBody text.\n\n"
            "# Notes and References\n\n"
            "[1] Smith (2023). Title.\n"
            "[2] Jones (2022). Title.\n"
        )
        output, metrics = _run_pass(doc)

        assert "# Notes and References" not in output
        assert metrics["sections_found"] == 1


# ── Tests: OCR Noise Handling ────────────────────────────────────────────────


class TestOCRHandling:
    """OCR-generated documents with formatting noise."""

    def test_bold_ocr_heading(self):
        doc = "# Intro\n\nContent.\n\n**BIBLIOGRAPHY**\n\n[1] A.\n[2] B.\n"
        output, _ = _run_pass(doc)

        assert "[1] A." not in output
        assert "[2] B." not in output

    def test_italic_ocr_heading(self):
        doc = "# Intro\n\nContent.\n\n*References*\n\n[1] A.\n"
        output, _ = _run_pass(doc)

        assert "[1] A." not in output

    def test_underscore_bold_heading(self):
        doc = "# Intro\n\nContent.\n\n__References__\n\n[1] A.\n"
        output, _ = _run_pass(doc)

        assert "[1] A." not in output


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:
    """validate_config() catches invalid parameters."""

    def test_invalid_mode(self):
        from app.optimizer.exceptions import PassConfigError

        p = ReferenceSectionRemovalPass()
        config = PassConfig(params={"mode": "destroy"})

        with pytest.raises(PassConfigError, match="mode"):
            p.validate_config(config)

    def test_empty_section_titles(self):
        from app.optimizer.exceptions import PassConfigError

        p = ReferenceSectionRemovalPass()
        config = PassConfig(params={"section_titles": []})

        with pytest.raises(PassConfigError, match="section_titles"):
            p.validate_config(config)

    def test_invalid_max_heading_length(self):
        from app.optimizer.exceptions import PassConfigError

        p = ReferenceSectionRemovalPass()
        config = PassConfig(params={"max_heading_length": 0})

        with pytest.raises(PassConfigError, match="max_heading_length"):
            p.validate_config(config)


# ── Tests: Statistics / Metrics ───────────────────────────────────────────────


class TestStatistics:
    """Metrics reported via custom_metrics."""

    def test_metrics_structure(self):
        _, metrics = _run_pass(_SIMPLE_PAPER)

        assert "mode" in metrics
        assert "sections_found" in metrics
        assert "total_entries" in metrics
        assert "total_lines_affected" in metrics
        assert "action_taken" in metrics
        assert "sections" in metrics

    def test_section_detail_structure(self):
        _, metrics = _run_pass(_SIMPLE_PAPER)

        section = metrics["sections"][0]
        assert "heading" in section
        assert "heading_level" in section
        assert "start_line" in section
        assert "end_line" in section
        assert "entry_count" in section
        assert "content_lines" in section

    def test_correct_entry_count(self):
        _, metrics = _run_pass(_SIMPLE_PAPER)

        assert metrics["total_entries"] == 3

    def test_no_sections_metrics(self):
        doc = "# Intro\n\nJust content.\n"
        _, metrics = _run_pass(doc)

        assert metrics["sections_found"] == 0
        assert metrics["action_taken"] == "none"

    def test_mode_reported(self):
        _, metrics = _run_pass(
            _SIMPLE_PAPER,
            params={"mode": "summarize"},
        )
        assert metrics["mode"] == "summarize"

    def test_lines_affected(self):
        _, metrics = _run_pass(_SIMPLE_PAPER)

        # References heading + 3 entries + blank lines
        assert metrics["total_lines_affected"] > 0

    def test_heading_level_reported(self):
        _, metrics = _run_pass(_SIMPLE_PAPER)

        section = metrics["sections"][0]
        assert section["heading_level"] == 1  # "# References" is H1


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:
    """Run through PipelineExecutor to verify framework integration."""

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        registry = PassRegistry()
        registry.register(ReferenceSectionRemovalPass, force=True)
        yield
        registry.clear()

    def test_integration_remove(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["reference_section_removal"],
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run(_SIMPLE_PAPER)

        assert result.success
        assert "# References" not in result.output
        assert "# Introduction" in result.output

    def test_integration_summarize(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["reference_section_removal"],
            pass_configs={
                "reference_section_removal": PassConfig(
                    params={"mode": "summarize"},
                ),
            },
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run(_SIMPLE_PAPER)

        assert result.success
        assert "[References removed: 3 entries]" in result.output

    def test_custom_metrics_in_report(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["reference_section_removal"],
            collect_statistics=True,
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run(_SIMPLE_PAPER)

        stats = result.report.pass_details[0]
        assert stats.pass_name == "reference_section_removal"
        assert "sections_found" in stats.custom_metrics
        assert stats.custom_metrics["sections_found"] == 1


# ── Tests: _count_entries static method ──────────────────────────────────────


class TestCountEntries:
    """Unit tests for the entry counting helper."""

    @staticmethod
    def _count(text: str) -> int:
        return ReferenceSectionRemovalPass._count_entries(text)

    def test_bracket_numbered(self):
        text = "[1] A.\n[2] B.\n[3] C.\n"
        assert self._count(text) == 3

    def test_period_numbered(self):
        text = "1. A.\n2. B.\n"
        assert self._count(text) == 2

    def test_paren_numbered(self):
        text = "1) A.\n2) B.\n3) C.\n4) D.\n"
        assert self._count(text) == 4

    def test_bulleted(self):
        text = "- A.\n- B.\n- C.\n"
        assert self._count(text) == 3

    def test_paragraph_fallback(self):
        text = "Smith (2023). Title.\n\nJones (2022). Title.\n"
        assert self._count(text) == 2

    def test_empty(self):
        assert self._count("") == 0
        assert self._count("   \n   \n") == 0

    def test_single_entry_paragraph(self):
        text = "Smith, J. (2023). The only reference."
        assert self._count(text) == 1


# ── Tests: _clean_title static method ────────────────────────────────────────


class TestCleanTitle:
    """Unit tests for the title cleaning helper."""

    @staticmethod
    def _clean(text: str) -> str:
        return ReferenceSectionRemovalPass._clean_title(text)

    def test_strips_bold(self):
        assert self._clean("**References**") == "References"

    def test_strips_italic(self):
        assert self._clean("*References*") == "References"

    def test_strips_underscore_bold(self):
        assert self._clean("__Bibliography__") == "Bibliography"

    def test_strips_trailing_colon(self):
        assert self._clean("References:") == "References"

    def test_whitespace(self):
        assert self._clean("  References  ") == "References"

    def test_combined(self):
        assert self._clean("**Works Cited:**") == "Works Cited"

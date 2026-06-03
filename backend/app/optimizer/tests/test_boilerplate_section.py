"""
Tests for BoilerplateSectionRemovalPass.

Covers:
  - Detection of all six default section groups
  - Heading styles (ATX, setext, OCR/plain-text, bold, italic)
  - All three modes: remove, summarize, keep
  - Per-group enable/disable configuration
  - Custom title extensions
  - Section boundary detection
  - Multiple boilerplate sections in one document
  - OCR-tolerant matching (ALL CAPS, bold markers)
  - Edge cases (no sections, empty doc, only boilerplate)
  - Config validation
  - Statistics / metrics reporting
  - Pipeline integration
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.boilerplate_section import (
    BoilerplateSectionRemovalPass,
    SECTION_GROUPS,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_pass(
    content: str,
    params: dict | None = None,
) -> tuple[str, dict]:
    """Run the pass and return (output, metrics)."""
    p = BoilerplateSectionRemovalPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})

    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


# ── Realistic test documents ──────────────────────────────────────────────────


_FULL_PAPER = """\
# Introduction

Machine learning has transformed NLP.

# Methodology

We use a transformer-based architecture.

# Results

Our model achieves 94.5% accuracy.

# Acknowledgements

The authors thank the reviewers for their helpful comments. We also
acknowledge the support of the university computing cluster.

# Funding

This work was supported by Grant No. 12345 from the National Science
Foundation and Grant No. 67890 from the European Research Council.

# Conflict of Interest

The authors declare no competing interests.

# Author Contributions

J.S. designed the study. A.B. implemented the model. C.D. analysed
the results. All authors reviewed the manuscript.

# Data Availability

The datasets used in this study are available at
https://example.com/datasets.
"""

_PAPER_WITH_ETHICS = """\
# Methods

We conducted a human evaluation study.

# Ethics Statement

This study was approved by the Institutional Review Board (IRB-2023-042).
All participants provided informed consent.

# Results

The results show significant improvement.
"""

_OCR_PAPER = """\
INTRODUCTION

Machine learning overview.

RESULTS

Results summary.

ACKNOWLEDGEMENTS

Thanks to all contributors.

FUNDING

Funded by Grant 12345.

CONFLICT OF INTEREST

None declared.
"""

_SETEXT_PAPER = """\
Introduction
============

Overview of the study.

Acknowledgements
================

Thanks to the reviewers.

Funding
-------

Grant No. 42 from NSF.
"""


# ── Tests: Basic Detection & Removal ─────────────────────────────────────────


class TestBasicRemoval:
    """Default mode=remove strips boilerplate sections."""

    def test_acknowledgements_removed(self):
        output, _ = _run_pass(_FULL_PAPER)
        assert "# Acknowledgements" not in output
        assert "thank the reviewers" not in output

    def test_funding_removed(self):
        output, _ = _run_pass(_FULL_PAPER)
        assert "# Funding" not in output
        assert "Grant No. 12345" not in output

    def test_conflict_of_interest_removed(self):
        output, _ = _run_pass(_FULL_PAPER)
        assert "# Conflict of Interest" not in output
        assert "no competing interests" not in output

    def test_author_contributions_removed(self):
        output, _ = _run_pass(_FULL_PAPER)
        assert "# Author Contributions" not in output
        assert "designed the study" not in output

    def test_data_availability_removed(self):
        output, _ = _run_pass(_FULL_PAPER)
        assert "# Data Availability" not in output

    def test_body_content_preserved(self):
        output, _ = _run_pass(_FULL_PAPER)
        assert "# Introduction" in output
        assert "# Methodology" in output
        assert "# Results" in output
        assert "94.5% accuracy" in output

    def test_ethics_statement_removed(self):
        output, _ = _run_pass(_PAPER_WITH_ETHICS)
        assert "# Ethics Statement" not in output
        assert "IRB-2023-042" not in output
        assert "# Methods" in output
        assert "# Results" in output


# ── Tests: All Section Groups ────────────────────────────────────────────────


class TestAllGroups:
    """Each group has title variants that match."""

    @pytest.mark.parametrize("title", [
        "Acknowledgements",
        "Acknowledgments",
        "Acknowledgement",
        "Acknowledgment",
    ])
    def test_acknowledgement_variants(self, title):
        doc = f"# Intro\n\nContent.\n\n# {title}\n\nThanks.\n"
        output, metrics = _run_pass(doc)
        assert f"# {title}" not in output
        assert metrics["groups_found"].get("acknowledgements", 0) == 1

    @pytest.mark.parametrize("title", [
        "Funding",
        "Funding Statement",
        "Financial Support",
    ])
    def test_funding_variants(self, title):
        doc = f"# Intro\n\nContent.\n\n# {title}\n\nGrant info.\n"
        output, _ = _run_pass(doc)
        assert f"# {title}" not in output

    @pytest.mark.parametrize("title", [
        "Conflict of Interest",
        "Competing Interests",
        "Declaration of Interest",
        "Disclosure",
    ])
    def test_conflict_variants(self, title):
        doc = f"# Intro\n\nContent.\n\n# {title}\n\nNone.\n"
        output, _ = _run_pass(doc)
        assert f"# {title}" not in output

    @pytest.mark.parametrize("title", [
        "Ethics Statement",
        "Ethical Approval",
        "Ethics Approval",
    ])
    def test_ethics_variants(self, title):
        doc = f"# Intro\n\nContent.\n\n# {title}\n\nApproved.\n"
        output, _ = _run_pass(doc)
        assert f"# {title}" not in output

    @pytest.mark.parametrize("title", [
        "Author Contributions",
        "Contributors",
    ])
    def test_contributions_variants(self, title):
        doc = f"# Intro\n\nContent.\n\n# {title}\n\nA.B. wrote.\n"
        output, _ = _run_pass(doc)
        assert f"# {title}" not in output

    @pytest.mark.parametrize("title", [
        "Data Availability",
        "Code Availability",
        "Data Availability Statement",
    ])
    def test_data_availability_variants(self, title):
        doc = f"# Intro\n\nContent.\n\n# {title}\n\nData at url.\n"
        output, _ = _run_pass(doc)
        assert f"# {title}" not in output


# ── Tests: Summarize Mode ────────────────────────────────────────────────────


class TestSummarizeMode:

    def test_summarize_basic(self):
        doc = "# Intro\n\nContent.\n\n# Funding\n\nGrant info.\n"
        output, _ = _run_pass(doc, params={"mode": "summarize"})
        assert "# Funding" not in output
        assert "[Funding section removed]" in output

    def test_summarize_custom_template(self):
        doc = "# Intro\n\nContent.\n\n# Funding\n\nGrant info.\n"
        output, _ = _run_pass(doc, params={
            "mode": "summarize",
            "summary_template": "<<{group} omitted>>",
        })
        assert "<<Funding omitted>>" in output

    def test_summarize_preserves_body(self):
        output, _ = _run_pass(_FULL_PAPER, params={"mode": "summarize"})
        assert "# Introduction" in output
        assert "# Methodology" in output

    def test_summarize_multiple_sections(self):
        output, _ = _run_pass(_FULL_PAPER, params={"mode": "summarize"})
        assert "[Acknowledgements section removed]" in output
        assert "[Funding section removed]" in output
        assert "[Conflict Of Interest section removed]" in output


# ── Tests: Keep Mode ─────────────────────────────────────────────────────────


class TestKeepMode:

    def test_content_unchanged(self):
        output, _ = _run_pass(_FULL_PAPER, params={"mode": "keep"})
        assert "# Acknowledgements" in output
        assert "# Funding" in output

    def test_metrics_still_reported(self):
        _, metrics = _run_pass(_FULL_PAPER, params={"mode": "keep"})
        assert metrics["sections_found"] >= 5
        assert metrics["mode"] == "keep"


# ── Tests: Per-Group Configuration ───────────────────────────────────────────


class TestPerGroupConfig:
    """Individual section groups can be disabled."""

    def test_disable_acknowledgements(self):
        output, metrics = _run_pass(_FULL_PAPER, params={
            "sections": {
                "acknowledgements": False,
                "funding": True,
                "conflict_of_interest": True,
                "ethics_statement": True,
                "author_contributions": True,
                "data_availability": True,
            },
        })
        # Acknowledgements preserved
        assert "# Acknowledgements" in output
        assert "thank the reviewers" in output
        # Others still removed
        assert "# Funding" not in output

    def test_disable_all_except_funding(self):
        output, metrics = _run_pass(_FULL_PAPER, params={
            "sections": {
                "acknowledgements": False,
                "funding": True,
                "conflict_of_interest": False,
                "ethics_statement": False,
                "author_contributions": False,
                "data_availability": False,
            },
        })
        assert "# Acknowledgements" in output
        assert "# Funding" not in output
        assert "# Conflict of Interest" in output
        assert metrics["sections_found"] == 1

    def test_disable_all(self):
        output, metrics = _run_pass(_FULL_PAPER, params={
            "sections": {group: False for group in SECTION_GROUPS},
        })
        assert "# Acknowledgements" in output
        assert "# Funding" in output
        assert metrics["sections_found"] == 0


# ── Tests: Custom Title Extensions ───────────────────────────────────────────


class TestCustomTitles:

    def test_add_custom_group(self):
        doc = "# Intro\n\nContent.\n\n# Colophon\n\nPrinted by XYZ.\n"
        output, metrics = _run_pass(doc, params={
            "custom_titles": {"colophon": ["colophon"]},
        })
        assert "# Colophon" not in output
        assert metrics["groups_found"].get("colophon", 0) == 1

    def test_extend_existing_group(self):
        doc = "# Intro\n\nContent.\n\n# Money Sources\n\nGrant.\n"
        output, _ = _run_pass(doc, params={
            "custom_titles": {"funding": ["money sources"]},
        })
        assert "# Money Sources" not in output


# ── Tests: Heading Styles ────────────────────────────────────────────────────


class TestHeadingStyles:

    def test_h2_heading(self):
        doc = "# Paper\n\n## Acknowledgements\n\nThanks.\n"
        output, _ = _run_pass(doc)
        assert "## Acknowledgements" not in output

    def test_h3_heading(self):
        doc = "# Paper\n\n### Funding\n\nGrant.\n"
        output, _ = _run_pass(doc)
        assert "### Funding" not in output

    def test_setext_h1(self):
        output, metrics = _run_pass(_SETEXT_PAPER)
        assert "Thanks to the reviewers" not in output
        assert metrics["sections_found"] >= 1

    def test_setext_h2(self):
        output, _ = _run_pass(_SETEXT_PAPER)
        assert "Grant No. 42" not in output

    def test_ocr_all_caps(self):
        output, metrics = _run_pass(_OCR_PAPER)
        assert "Thanks to all contributors" not in output
        assert "Funded by Grant 12345" not in output
        assert "None declared" not in output

    def test_bold_heading(self):
        doc = "# Intro\n\nContent.\n\n**Funding**\n\nGrant.\n"
        output, _ = _run_pass(doc)
        assert "**Funding**" not in output
        assert "Grant." not in output

    def test_italic_heading(self):
        doc = "# Intro\n\nContent.\n\n*Acknowledgements*\n\nThanks.\n"
        output, _ = _run_pass(doc)
        assert "*Acknowledgements*" not in output

    def test_heading_with_colon(self):
        doc = "# Intro\n\nContent.\n\n# Funding:\n\nGrant.\n"
        output, _ = _run_pass(doc)
        assert "Grant." not in output

    def test_case_insensitive(self):
        doc = "# Intro\n\nContent.\n\n# CONFLICT OF INTEREST\n\nNone.\n"
        output, _ = _run_pass(doc)
        assert "# CONFLICT OF INTEREST" not in output

    def test_ocr_disabled(self):
        output, metrics = _run_pass(
            _OCR_PAPER,
            params={"detect_ocr_headings": False},
        )
        # Without OCR detection, plain-text headings aren't matched
        assert metrics["sections_found"] == 0


# ── Tests: Section Boundary ──────────────────────────────────────────────────


class TestSectionBoundary:

    def test_stops_at_next_same_level(self):
        output, _ = _run_pass(_FULL_PAPER)
        # Funding section should not eat into Conflict of Interest
        # (both removed, but each independently)
        assert "# Introduction" in output

    def test_preserves_content_after_boilerplate(self):
        doc = (
            "# Introduction\n\nContent.\n\n"
            "# Funding\n\nGrant.\n\n"
            "# Conclusion\n\nFinal thoughts.\n"
        )
        output, _ = _run_pass(doc)
        assert "# Conclusion" in output
        assert "Final thoughts" in output

    def test_extends_to_eof(self):
        doc = "# Intro\n\nContent.\n\n# Acknowledgements\n\nThanks.\n"
        output, _ = _run_pass(doc)
        assert "Thanks." not in output

    def test_sub_headings_included(self):
        doc = (
            "# Intro\n\nContent.\n\n"
            "# Author Contributions\n\n"
            "## Design\n\nJ.S. designed.\n\n"
            "## Implementation\n\nA.B. coded.\n"
        )
        output, _ = _run_pass(doc)
        assert "## Design" not in output
        assert "## Implementation" not in output
        assert "# Intro" in output


# ── Tests: Multiple Sections ─────────────────────────────────────────────────


class TestMultipleSections:

    def test_all_boilerplate_removed(self):
        _, metrics = _run_pass(_FULL_PAPER)
        assert metrics["sections_found"] == 5  # ack, funding, coi, contrib, data

    def test_metrics_groups_found(self):
        _, metrics = _run_pass(_FULL_PAPER)
        groups = metrics["groups_found"]
        assert "acknowledgements" in groups
        assert "funding" in groups
        assert "conflict_of_interest" in groups
        assert "author_contributions" in groups
        assert "data_availability" in groups

    def test_ocr_multiple_sections(self):
        _, metrics = _run_pass(_OCR_PAPER)
        assert metrics["sections_found"] == 3  # ack, funding, coi


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_document(self):
        output, metrics = _run_pass("")
        assert output == ""
        assert metrics["sections_found"] == 0

    def test_no_boilerplate(self):
        doc = "# Introduction\n\nContent.\n\n# Conclusion\n\nEnd.\n"
        output, metrics = _run_pass(doc)
        assert "# Introduction" in output
        assert "# Conclusion" in output
        assert metrics["sections_found"] == 0

    def test_only_boilerplate(self):
        doc = "# Funding\n\nGrant.\n\n# Acknowledgements\n\nThanks.\n"
        output, _ = _run_pass(doc)
        assert output == ""

    def test_empty_section(self):
        doc = "# Intro\n\nContent.\n\n# Funding\n"
        output, metrics = _run_pass(doc)
        assert "# Funding" not in output
        assert metrics["sections_found"] == 1

    def test_similar_word_not_matched(self):
        """'Funded' in body text should not trigger removal."""
        doc = "# Intro\n\nThis project was funded by a grant.\n"
        output, _ = _run_pass(doc)
        assert "funded by a grant" in output


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:

    def test_invalid_mode(self):
        from app.optimizer.exceptions import PassConfigError

        p = BoilerplateSectionRemovalPass()
        with pytest.raises(PassConfigError, match="mode"):
            p.validate_config(PassConfig(params={"mode": "destroy"}))

    def test_invalid_sections_type(self):
        from app.optimizer.exceptions import PassConfigError

        p = BoilerplateSectionRemovalPass()
        with pytest.raises(PassConfigError, match="sections"):
            p.validate_config(PassConfig(params={"sections": "not_a_dict"}))

    def test_invalid_sections_value(self):
        from app.optimizer.exceptions import PassConfigError

        p = BoilerplateSectionRemovalPass()
        with pytest.raises(PassConfigError, match="sections"):
            p.validate_config(PassConfig(params={
                "sections": {"funding": "yes"},
            }))

    def test_invalid_max_heading_length(self):
        from app.optimizer.exceptions import PassConfigError

        p = BoilerplateSectionRemovalPass()
        with pytest.raises(PassConfigError, match="max_heading_length"):
            p.validate_config(PassConfig(params={"max_heading_length": 0}))

    def test_invalid_custom_titles(self):
        from app.optimizer.exceptions import PassConfigError

        p = BoilerplateSectionRemovalPass()
        with pytest.raises(PassConfigError, match="custom_titles"):
            p.validate_config(PassConfig(params={"custom_titles": "bad"}))


# ── Tests: Statistics / Metrics ───────────────────────────────────────────────


class TestStatistics:

    def test_metrics_structure(self):
        _, metrics = _run_pass(_FULL_PAPER)
        assert "mode" in metrics
        assert "sections_found" in metrics
        assert "total_lines_affected" in metrics
        assert "groups_found" in metrics
        assert "action_taken" in metrics
        assert "sections" in metrics

    def test_section_detail_structure(self):
        _, metrics = _run_pass(_FULL_PAPER)
        section = metrics["sections"][0]
        assert "heading" in section
        assert "heading_level" in section
        assert "group" in section
        assert "start_line" in section
        assert "end_line" in section
        assert "content_lines" in section

    def test_no_sections_metrics(self):
        doc = "# Intro\n\nJust content.\n"
        _, metrics = _run_pass(doc)
        assert metrics["sections_found"] == 0
        assert metrics["action_taken"] == "none"

    def test_lines_affected(self):
        _, metrics = _run_pass(_FULL_PAPER)
        assert metrics["total_lines_affected"] > 0

    def test_mode_reported(self):
        _, metrics = _run_pass(_FULL_PAPER, params={"mode": "summarize"})
        assert metrics["mode"] == "summarize"


# ── Tests: _clean_title helper ───────────────────────────────────────────────


class TestCleanTitle:

    @staticmethod
    def _clean(text: str) -> str:
        return BoilerplateSectionRemovalPass._clean_title(text)

    def test_strips_bold(self):
        assert self._clean("**Funding**") == "Funding"

    def test_strips_italic(self):
        assert self._clean("*Ethics Statement*") == "Ethics Statement"

    def test_strips_trailing_colon(self):
        assert self._clean("Funding:") == "Funding"

    def test_whitespace(self):
        assert self._clean("  Acknowledgements  ") == "Acknowledgements"


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        registry = PassRegistry()
        registry.register(BoilerplateSectionRemovalPass, force=True)
        yield
        registry.clear()

    def test_integration_remove(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["boilerplate_section_removal"],
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run(_FULL_PAPER)

        assert result.success
        assert "# Acknowledgements" not in result.output
        assert "# Introduction" in result.output

    def test_integration_summarize(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["boilerplate_section_removal"],
            pass_configs={
                "boilerplate_section_removal": PassConfig(
                    params={"mode": "summarize"},
                ),
            },
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run(_FULL_PAPER)

        assert result.success
        assert "[Funding section removed]" in result.output

    def test_custom_metrics_in_report(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["boilerplate_section_removal"],
            collect_statistics=True,
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run(_FULL_PAPER)

        stats = result.report.pass_details[0]
        assert stats.pass_name == "boilerplate_section_removal"
        assert "sections_found" in stats.custom_metrics
        assert stats.custom_metrics["sections_found"] >= 5

"""
Tests for CitationRemovalPass.

Covers:
  - Numeric bracket citations ([1], [2,3], [1-5], [1,3-5,7])
  - Author-year citations ((Smith, 2020), (Smith et al., 2020))
  - Three modes: remove, replace_with_placeholder, keep
  - Markdown link protection
  - Equation / math protection
  - Footnote protection
  - Code block protection
  - Whitespace cleanup after removal
  - Adjacent placeholder merging
  - Edge cases
  - Config validation
  - Statistics / metrics
  - Pipeline integration
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.citation import (
    CitationRemovalPass,
    _AUTHOR_YEAR_RE,
    _NUMERIC_CITE_RE,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_pass(
    content: str,
    params: dict | None = None,
) -> tuple[str, dict]:
    """Run the pass and return (output, metrics)."""
    p = CitationRemovalPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})

    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


# ── Tests: Numeric Citation Detection ─────────────────────────────────────────


class TestNumericDetection:
    """Regex matches for [N]-style citations."""

    def test_single_number(self):
        output, _ = _run_pass("As shown [1] in the study.")
        assert "[1]" not in output
        assert "As shown in the study." in output

    def test_multi_digit(self):
        output, _ = _run_pass("Results [42] confirm.")
        assert "[42]" not in output

    def test_comma_separated(self):
        output, _ = _run_pass("See [1,2] for details.")
        assert "[1,2]" not in output

    def test_comma_with_spaces(self):
        output, _ = _run_pass("See [1, 2, 3] for details.")
        assert "[1, 2, 3]" not in output

    def test_range(self):
        output, _ = _run_pass("Prior work [12-15] shows.")
        assert "[12-15]" not in output

    def test_en_dash_range(self):
        output, _ = _run_pass("Prior work [12\u201315] shows.")
        assert "[12\u201315]" not in output

    def test_mixed_items(self):
        output, _ = _run_pass("Studies [1,3-5,7] confirm.")
        assert "[1,3-5,7]" not in output

    def test_semicolon_separated(self):
        output, _ = _run_pass("Evidence [1;2;3] suggests.")
        assert "[1;2;3]" not in output

    def test_multiple_citations_in_text(self):
        text = "First [1] then [2] and also [3]."
        output, metrics = _run_pass(text)
        assert "[1]" not in output
        assert "[2]" not in output
        assert "[3]" not in output
        assert metrics["numeric_citations_found"] == 3


# ── Tests: Author-Year Citation Detection ─────────────────────────────────────


class TestAuthorYearDetection:
    """Regex matches for (Author, Year)-style citations."""

    def test_simple(self):
        output, _ = _run_pass("As noted (Smith, 2020) the result.")
        assert "(Smith, 2020)" not in output
        assert "As noted the result." in output

    def test_et_al(self):
        output, _ = _run_pass("Studies (Smith et al., 2020) show.")
        assert "(Smith et al., 2020)" not in output

    def test_two_authors_ampersand(self):
        output, _ = _run_pass("Work by (Smith & Jones, 2020) is.")
        assert "(Smith & Jones, 2020)" not in output

    def test_two_authors_and(self):
        output, _ = _run_pass("Work by (Smith and Jones, 2020) is.")
        assert "(Smith and Jones, 2020)" not in output

    def test_multiple_citations_semicolon(self):
        text = "Evidence (Smith, 2020; Jones, 2019) confirms."
        output, _ = _run_pass(text)
        assert "(Smith, 2020; Jones, 2019)" not in output

    def test_with_see_prefix(self):
        output, _ = _run_pass("Results (see Smith, 2020) indicate.")
        assert "(see Smith, 2020)" not in output

    def test_with_cf_prefix(self):
        output, _ = _run_pass("Compare (cf. Brown, 2021) the data.")
        assert "(cf. Brown, 2021)" not in output

    def test_with_page_number(self):
        output, _ = _run_pass("Quote (Smith, 2020, p. 42) here.")
        assert "(Smith, 2020, p. 42)" not in output

    def test_with_page_range(self):
        output, _ = _run_pass("See (Smith, 2020, pp. 10-20) for.")
        assert "(Smith, 2020, pp. 10-20)" not in output

    def test_year_with_letter(self):
        output, _ = _run_pass("According to (Smith, 2020a) the.")
        assert "(Smith, 2020a)" not in output

    def test_hyphenated_author(self):
        output, _ = _run_pass("By (Garcia-Lopez, 2019) the model.")
        assert "(Garcia-Lopez, 2019)" not in output

    def test_does_not_match_plain_parens(self):
        """Regular parenthetical text should NOT be removed."""
        text = "The model (which was trained for 3 epochs) converged."
        output, _ = _run_pass(text)
        assert "(which was trained for 3 epochs)" in output

    def test_does_not_match_math_parens(self):
        """Math expressions in parens should NOT be removed."""
        text = "We compute (x + y) for each sample."
        output, _ = _run_pass(text)
        assert "(x + y)" in output


# ── Tests: Remove Mode ───────────────────────────────────────────────────────


class TestRemoveMode:
    """Default mode: citations are deleted."""

    def test_numeric_removed(self):
        output, _ = _run_pass("Text [1] here.", params={"mode": "remove"})
        assert "[1]" not in output

    def test_author_year_removed(self):
        output, _ = _run_pass(
            "Text (Smith, 2020) here.",
            params={"mode": "remove"},
        )
        assert "(Smith, 2020)" not in output

    def test_whitespace_collapsed(self):
        """Double space left by removal is collapsed to single."""
        output, _ = _run_pass("Before [1] after.")
        assert "Before after." in output

    def test_space_before_punct_cleaned(self):
        """Space before punctuation is removed after citation removal."""
        output, _ = _run_pass("Evidence [1].")
        assert "Evidence." in output

    def test_body_preserved(self):
        text = "Introduction. Methodology [1] results [2] conclusion."
        output, _ = _run_pass(text)
        assert "Introduction." in output
        assert "results" in output
        assert "conclusion." in output


# ── Tests: Replace Mode ──────────────────────────────────────────────────────


class TestReplaceMode:
    """Mode replace_with_placeholder inserts configurable text."""

    def test_default_placeholder(self):
        output, _ = _run_pass(
            "Text [1] here.",
            params={"mode": "replace_with_placeholder"},
        )
        assert "[citation]" in output
        assert "[1]" not in output

    def test_custom_placeholder(self):
        output, _ = _run_pass(
            "Text (Smith, 2020) here.",
            params={
                "mode": "replace_with_placeholder",
                "placeholder": "<ref>",
            },
        )
        assert "<ref>" in output
        assert "(Smith, 2020)" not in output

    def test_adjacent_placeholders_merged(self):
        """Consecutive placeholders are merged into one."""
        output, _ = _run_pass(
            "Text [1] [2] [3] here.",
            params={"mode": "replace_with_placeholder"},
        )
        # Should not have three separate placeholders
        assert output.count("[citation]") == 1

    def test_merge_can_be_disabled(self):
        output, _ = _run_pass(
            "Text [1] [2] here.",
            params={
                "mode": "replace_with_placeholder",
                "merge_adjacent_placeholders": False,
            },
        )
        assert output.count("[citation]") == 2


# ── Tests: Keep Mode ─────────────────────────────────────────────────────────


class TestKeepMode:
    """Mode=keep leaves text unchanged but still reports metrics."""

    def test_content_unchanged(self):
        text = "As shown [1] and (Smith, 2020)."
        output, _ = _run_pass(text, params={"mode": "keep"})
        assert output == text

    def test_metrics_still_reported(self):
        text = "Ref [1] and (Smith, 2020)."
        _, metrics = _run_pass(text, params={"mode": "keep"})
        assert metrics["total_citations_found"] >= 2
        assert metrics["citations_actioned"] == 0


# ── Tests: Markdown Link Protection ──────────────────────────────────────────


class TestMarkdownLinkProtection:
    """[N](url) must not be touched."""

    def test_link_not_removed(self):
        text = "Click [1](http://example.com) for info."
        output, _ = _run_pass(text)
        assert "[1](http://example.com)" in output

    def test_image_link_not_removed(self):
        text = "See ![Figure 1](image.png) below."
        output, _ = _run_pass(text)
        assert "![Figure 1](image.png)" in output

    def test_reference_link_not_removed(self):
        text = "See [details][1] for more."
        output, _ = _run_pass(text)
        assert "[details][1]" in output

    def test_link_definition_not_removed(self):
        text = "Text here.\n\n[1]: http://example.com\n"
        output, _ = _run_pass(text)
        assert "[1]: http://example.com" in output

    def test_nearby_citation_still_removed(self):
        """A real citation near a link should still be removed."""
        text = "See [here](url) and also [1] for details."
        output, _ = _run_pass(text)
        assert "[here](url)" in output
        assert "[1]" not in output

    def test_protection_can_be_disabled(self):
        text = "Click [1](http://example.com) for info."
        output, _ = _run_pass(
            text,
            params={"protect_markdown_links": False},
        )
        # With protection off, [1] part may be matched
        # (the full link structure may be damaged)
        assert "[1](http://example.com)" not in output


# ── Tests: Equation Protection ────────────────────────────────────────────────


class TestEquationProtection:
    """Math content must not be modified."""

    def test_inline_math_preserved(self):
        text = "The interval $[1, 2]$ is bounded."
        output, _ = _run_pass(text)
        assert "$[1, 2]$" in output

    def test_display_math_preserved(self):
        text = "$$\n[1] + [2] = [3]\n$$"
        output, _ = _run_pass(text)
        assert "[1] + [2] = [3]" in output

    def test_latex_display_preserved(self):
        text = "Equation: \\[[1, 2, 3]\\] is a vector."
        output, _ = _run_pass(text)
        assert "[1, 2, 3]" in output

    def test_latex_inline_preserved(self):
        text = r"We have \([1]\) in the formula."
        output, _ = _run_pass(text)
        assert "[1]" in output

    def test_citation_outside_math_removed(self):
        """Citations outside math blocks should still be removed."""
        text = "The result $x = 5$ confirms [1] the theory."
        output, _ = _run_pass(text)
        assert "$x = 5$" in output
        assert "[1]" not in output


# ── Tests: Footnote Protection ────────────────────────────────────────────────


class TestFootnoteProtection:
    """Markdown footnotes [^N] must not be removed."""

    def test_footnote_marker_preserved(self):
        text = "The finding[^1] is significant."
        output, _ = _run_pass(text)
        assert "[^1]" in output

    def test_footnote_with_text(self):
        text = "Claim[^note] is debatable."
        output, _ = _run_pass(text)
        assert "[^note]" in output


# ── Tests: Code Block Protection ─────────────────────────────────────────────


class TestCodeBlockProtection:
    """Code blocks and inline code must not be modified."""

    def test_fenced_code_preserved(self):
        text = "Example:\n```\narray[1] = 42;\narray[2] = 99;\n```\nEnd."
        output, _ = _run_pass(text)
        assert "array[1] = 42;" in output
        assert "array[2] = 99;" in output

    def test_inline_code_preserved(self):
        text = "Use `data[1]` to access the first element."
        output, _ = _run_pass(text)
        assert "`data[1]`" in output

    def test_citation_outside_code_removed(self):
        text = "Use `arr[0]` as baseline [1] for comparison."
        output, _ = _run_pass(text)
        assert "`arr[0]`" in output
        assert "[1]" not in output


# ── Tests: Selective Detection ────────────────────────────────────────────────


class TestSelectiveDetection:
    """Disabling individual detection families."""

    def test_numeric_only(self):
        text = "Ref [1] and (Smith, 2020) here."
        output, _ = _run_pass(text, params={"detect_author_year": False})
        assert "[1]" not in output
        assert "(Smith, 2020)" in output

    def test_author_year_only(self):
        text = "Ref [1] and (Smith, 2020) here."
        output, _ = _run_pass(text, params={"detect_numeric": False})
        assert "[1]" in output
        assert "(Smith, 2020)" not in output


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:
    """Boundary conditions and special inputs."""

    def test_empty_content(self):
        output, metrics = _run_pass("")
        assert output == ""
        assert metrics["total_citations_found"] == 0

    def test_no_citations(self):
        text = "A document with no citations at all."
        output, metrics = _run_pass(text)
        assert output == text
        assert metrics["total_citations_found"] == 0

    def test_citation_at_start(self):
        output, _ = _run_pass("[1] This is the first point.")
        assert "[1]" not in output
        assert "This is the first point." in output

    def test_citation_at_end(self):
        output, _ = _run_pass("Evidence shows improvement [1].")
        assert "[1]" not in output

    def test_consecutive_numeric(self):
        output, _ = _run_pass("Studies [1][2][3] confirm.")
        assert "[1]" not in output
        assert "[2]" not in output
        assert "[3]" not in output

    def test_mixed_types(self):
        text = "See [1] and (Smith, 2020) for evidence."
        output, metrics = _run_pass(text)
        assert "[1]" not in output
        assert "(Smith, 2020)" not in output
        assert metrics["numeric_citations_found"] >= 1
        assert metrics["author_year_citations_found"] >= 1

    def test_multiline_content(self):
        text = (
            "# Introduction\n\n"
            "Machine learning [1] has advanced.\n"
            "Deep learning (Smith et al., 2020) drives progress.\n\n"
            "# Results\n\n"
            "Our model outperforms baselines [2,3].\n"
        )
        output, metrics = _run_pass(text)
        assert "[1]" not in output
        assert "[2,3]" not in output
        assert "(Smith et al., 2020)" not in output
        assert "# Introduction" in output
        assert "# Results" in output


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:

    def test_invalid_mode(self):
        from app.optimizer.exceptions import PassConfigError

        p = CitationRemovalPass()
        config = PassConfig(params={"mode": "destroy"})
        with pytest.raises(PassConfigError, match="mode"):
            p.validate_config(config)

    def test_empty_placeholder(self):
        from app.optimizer.exceptions import PassConfigError

        p = CitationRemovalPass()
        config = PassConfig(params={"placeholder": ""})
        with pytest.raises(PassConfigError, match="placeholder"):
            p.validate_config(config)


# ── Tests: Statistics / Metrics ───────────────────────────────────────────────


class TestStatistics:

    def test_metrics_structure(self):
        _, metrics = _run_pass("Text [1] and (Smith, 2020).")
        assert "mode" in metrics
        assert "numeric_citations_found" in metrics
        assert "author_year_citations_found" in metrics
        assert "total_citations_found" in metrics
        assert "citations_in_protected_zones" in metrics
        assert "citations_actioned" in metrics
        assert "examples" in metrics

    def test_counts_correct(self):
        text = "A [1] B [2] C (Smith, 2020)."
        _, metrics = _run_pass(text)
        assert metrics["numeric_citations_found"] == 2
        assert metrics["author_year_citations_found"] == 1
        assert metrics["total_citations_found"] == 3

    def test_protected_count(self):
        text = "Link [1](url) and citation [2] here."
        _, metrics = _run_pass(text)
        assert metrics["citations_in_protected_zones"] >= 1
        assert metrics["total_citations_found"] >= 1

    def test_examples_capped(self):
        """Examples list is capped at 20 entries."""
        citations = " ".join(f"[{i}]" for i in range(1, 50))
        text = f"Text {citations} end."
        _, metrics = _run_pass(text)
        assert len(metrics["examples"]) <= 20

    def test_keep_mode_zero_actioned(self):
        _, metrics = _run_pass("[1] text.", params={"mode": "keep"})
        assert metrics["citations_actioned"] == 0


# ── Tests: Regex Unit Tests ──────────────────────────────────────────────────


class TestNumericRegex:
    """Direct regex match tests."""

    @pytest.mark.parametrize("text,expected", [
        ("[1]", True),
        ("[42]", True),
        ("[1,2]", True),
        ("[1, 2, 3]", True),
        ("[1-3]", True),
        ("[1,3-5,7]", True),
        ("[1;2]", True),
        ("[abc]", False),
        ("[^1]", False),
        ("[]", False),
        ("[1, a]", False),
    ])
    def test_pattern(self, text, expected):
        match = _NUMERIC_CITE_RE.fullmatch(text)
        assert bool(match) is expected, f"Pattern {'should' if expected else 'should not'} match: {text}"


class TestAuthorYearRegex:
    """Direct regex match tests."""

    @pytest.mark.parametrize("text,expected", [
        ("(Smith, 2020)", True),
        ("(Smith et al., 2020)", True),
        ("(Smith & Jones, 2020)", True),
        ("(Smith and Jones, 2020)", True),
        ("(Smith, 2020; Jones, 2019)", True),
        ("(see Smith, 2020)", True),
        ("(Smith, 2020a)", True),
        ("(Smith, 2020, p. 42)", True),
        ("(for example)", False),
        ("(x + y)", False),
        ("(n = 5)", False),
    ])
    def test_pattern(self, text, expected):
        match = _AUTHOR_YEAR_RE.fullmatch(text)
        assert bool(match) is expected, f"Pattern {'should' if expected else 'should not'} match: {text}"


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        registry = PassRegistry()
        registry.register(CitationRemovalPass, force=True)
        yield
        registry.clear()

    def test_integration_remove(self):
        registry = PassRegistry()
        config = PipelineConfig(pass_order=["citation_removal"])
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run("Text [1] and (Smith, 2020).")

        assert result.success
        assert "[1]" not in result.output
        assert "(Smith, 2020)" not in result.output

    def test_integration_replace(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["citation_removal"],
            pass_configs={
                "citation_removal": PassConfig(
                    params={"mode": "replace_with_placeholder"},
                ),
            },
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run("Evidence [1] here.")

        assert result.success
        assert "[citation]" in result.output

    def test_custom_metrics_in_report(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["citation_removal"],
            collect_statistics=True,
        )
        executor = PipelineExecutor(registry=registry, config=config)
        result = executor.run("Text [1].")

        stats = result.report.pass_details[0]
        assert stats.pass_name == "citation_removal"
        assert "total_citations_found" in stats.custom_metrics

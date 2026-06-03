"""
Tests for HeaderFooterDetectionPass.

Covers:
  - Basic header / footer detection and removal
  - Frequency threshold behaviour (above, below, at boundary)
  - Page-aware zone extraction
  - Markdown heading preservation
  - OCR noise tolerance (fuzzy matching)
  - Embedded page-number normalisation in fingerprints
  - Edge cases: too few pages, empty pages, no delimiters, very short pages
  - Custom configuration overrides
  - Statistics / metrics reporting
  - Integration with the PipelineExecutor
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.header_footer import HeaderFooterDetectionPass
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run_pass(
    content: str,
    params: dict | None = None,
) -> tuple[str, dict]:
    """Run the pass standalone and return (output, metrics)."""
    pass_instance = HeaderFooterDetectionPass()
    config = pass_instance.default_config
    if params:
        config = config.merge({"params": params})

    ctx = OptimizationContext(
        content=content,
        original_content=content,
    )
    ctx = pass_instance.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{pass_instance.name}", {})
    return ctx.content, metrics


def _make_document(
    pages: list[str],
    delimiter: str = "---",
) -> str:
    """Join pages with the given delimiter."""
    return f"\n{delimiter}\n".join(pages)


def _make_page(
    header: str,
    body: str,
    footer: str = "",
) -> str:
    """Build a single page with header, body, and optional footer."""
    parts = [header, "", body]
    if footer:
        parts.extend(["", footer])
    return "\n".join(parts)


# ── Test data ─────────────────────────────────────────────────────────────────


def _journal_document(n_pages: int = 5) -> str:
    """Simulated academic paper with repeated journal header."""
    pages = []
    sections = [
        ("Introduction", "We present a novel approach to solving the problem."),
        ("Related Work", "Prior work by Smith et al. established the baseline."),
        ("Methodology", "Our method uses a three-phase pipeline architecture."),
        ("Results", "The experiments show a 30% improvement over baselines."),
        ("Conclusion", "We demonstrated significant improvements in accuracy."),
        ("References", "1. Smith, J. (2023). A survey of methods."),
        ("Appendix A", "Additional experimental data is provided here."),
    ]
    for i in range(n_pages):
        section = sections[i % len(sections)]
        pages.append(_make_page(
            header="International Journal of Computer Science, Vol. 42",
            body=f"## {section[0]}\n\n{section[1]}",
            footer="Confidential – Do Not Distribute",
        ))
    return _make_document(pages)


def _conference_document() -> str:
    """Conference proceedings with header and page numbers."""
    pages = []
    for i in range(4):
        pages.append(_make_page(
            header=f"Proceedings of ICML 2025 – {i + 1}",
            body=f"## Section {i + 1}\n\nContent for section {i + 1}.",
        ))
    return _make_document(pages)


# ── Tests: Basic Detection ────────────────────────────────────────────────────


class TestBasicHeaderDetection:
    """Detect and remove repeated text at the top of pages."""

    def test_repeated_header_removed(self):
        doc = _journal_document()
        output, metrics = _run_pass(doc)

        assert "International Journal of Computer Science" not in output
        assert metrics["patterns_detected"] >= 1
        assert metrics["total_lines_removed"] >= 5

    def test_body_content_preserved(self):
        doc = _journal_document()
        output, _ = _run_pass(doc)

        assert "We present a novel approach" in output
        assert "Prior work by Smith" in output

    def test_section_headings_preserved(self):
        doc = _journal_document()
        output, _ = _run_pass(doc)

        assert "## Introduction" in output
        assert "## Related Work" in output


class TestBasicFooterDetection:
    """Detect and remove repeated text at the bottom of pages."""

    def test_repeated_footer_removed(self):
        doc = _journal_document()
        output, metrics = _run_pass(doc)

        assert "Confidential – Do Not Distribute" not in output

    def test_footer_pattern_in_metrics(self):
        doc = _journal_document()
        _, metrics = _run_pass(doc)

        footer_patterns = [
            p for p in metrics.get("patterns", [])
            if p["zone"] == "footer"
        ]
        assert len(footer_patterns) >= 1


class TestBothHeaderAndFooter:
    """Documents with both repeated headers and footers."""

    def test_both_detected(self):
        doc = _journal_document()
        _, metrics = _run_pass(doc)

        zones = {p["zone"] for p in metrics.get("patterns", [])}
        assert "header" in zones
        assert "footer" in zones

    def test_content_between_preserved(self):
        doc = _journal_document()
        output, _ = _run_pass(doc)

        # All section bodies should survive
        assert "novel approach" in output
        assert "improvements in accuracy" in output


# ── Tests: Frequency Threshold ────────────────────────────────────────────────


class TestFrequencyThreshold:
    """Behaviour around the min_frequency_ratio boundary."""

    def test_below_threshold_not_removed(self):
        """A header appearing on only 1 out of 5 pages should be kept."""
        pages = [
            _make_page("RARE HEADER", "Body of page 1."),
            _make_page("", "Body of page 2."),
            _make_page("", "Body of page 3."),
            _make_page("", "Body of page 4."),
            _make_page("", "Body of page 5."),
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={"min_frequency_ratio": 0.5})

        assert "RARE HEADER" in output

    def test_at_threshold_removed(self):
        """Header on exactly 50% of pages (3/6) should be removed at 0.5."""
        pages = [
            _make_page("REPEATED", "Body 1."),
            _make_page("REPEATED", "Body 2."),
            _make_page("REPEATED", "Body 3."),
            _make_page("", "Body 4."),
            _make_page("", "Body 5."),
            _make_page("", "Body 6."),
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={"min_frequency_ratio": 0.5})

        assert "REPEATED" not in output

    def test_above_threshold_removed(self):
        """Header on all pages should definitely be removed."""
        pages = [
            _make_page("ALWAYS HERE", f"Body {i}.")
            for i in range(5)
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc)

        assert "ALWAYS HERE" not in output

    def test_high_threshold_preserves_moderate(self):
        """With threshold=0.9, a header on 3/5 pages should be kept."""
        pages = [
            _make_page("MODERATE", "Body."),
            _make_page("MODERATE", "Body."),
            _make_page("MODERATE", "Body."),
            _make_page("", "Body."),
            _make_page("", "Body."),
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={"min_frequency_ratio": 0.9})

        assert "MODERATE" in output


# ── Tests: Page Awareness ─────────────────────────────────────────────────────


class TestPageAwareness:
    """Lines in the middle of pages are not candidates."""

    def test_middle_content_not_removed(self):
        """A line repeated in the middle (not header/footer zone) survives."""
        pages = []
        for i in range(5):
            body_lines = [f"Line {j}" for j in range(20)]
            # Place repeated text in the middle
            body_lines[10] = "This appears in every page middle"
            pages.append(_make_page(
                header=f"Unique header {i}",
                body="\n".join(body_lines),
            ))
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={
            "header_zone_lines": 3,
            "footer_zone_lines": 3,
        })

        assert "This appears in every page middle" in output

    def test_header_zone_size_respected(self):
        """Only the first N lines are checked for headers."""
        pages = []
        for i in range(4):
            # Line at position 2 (0-indexed) = within zone of 3 but outside zone of 1
            # Each page has enough unique body lines to push REPEATING TEXT
            # outside the footer zone too.
            pages.append(
                f"Unique first line page {i}\n"
                f"Second unique line page {i}\n"
                "REPEATING TEXT\n"
                "\n"
                + "\n".join(f"Body line {j} of page {i}" for j in range(10))
            )
        doc = _make_document(pages)

        # With zone=3, the repeating line IS in the header zone → removed
        output_wide, _ = _run_pass(doc, params={
            "header_zone_lines": 3,
            "footer_zone_lines": 2,
        })
        assert "REPEATING TEXT" not in output_wide

        # With zone=1, the repeating line is NOT in the header zone → kept
        # Footer zone also set to 1 so it doesn't catch it from the other end
        output_narrow, _ = _run_pass(doc, params={
            "header_zone_lines": 1,
            "footer_zone_lines": 1,
        })
        assert "REPEATING TEXT" in output_narrow


# ── Tests: Markdown Heading Preservation ──────────────────────────────────────


class TestMarkdownHeadingPreservation:
    """Markdown headings (# ...) are protected by default."""

    def test_repeated_markdown_heading_preserved(self):
        """A heading like '## Abstract' repeated on every page is kept."""
        pages = [
            _make_page(
                header="## Summary",
                body=f"Summary content for page {i}.",
            )
            for i in range(5)
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc)

        # Markdown headings are preserved by default
        assert "## Summary" in output

    def test_preservation_can_be_disabled(self):
        """With preserve_md_headings=False, repeated headings ARE removed."""
        pages = [
            _make_page(
                header="## Summary",
                body=f"Content for page {i}.",
            )
            for i in range(5)
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={"preserve_md_headings": False})

        assert "## Summary" not in output


# ── Tests: OCR Noise / Fuzzy Matching ─────────────────────────────────────────


class TestFuzzyMatching:
    """Fuzzy matching groups OCR variants of the same header."""

    def test_ocr_variants_grouped(self):
        """Slightly different OCR reads of the same header are merged."""
        pages = [
            _make_page("International Journal of CS", "Body 1."),
            _make_page("lnternational Journal of CS", "Body 2."),  # l vs I
            _make_page("International Journa1 of CS", "Body 3."),  # 1 vs l
            _make_page("International Journal of CS", "Body 4."),
        ]
        doc = _make_document(pages)
        output, metrics = _run_pass(doc, params={"fuzzy_threshold": 0.8})

        # All OCR variants should be removed
        assert "International Journal" not in output
        assert "lnternational" not in output

    def test_fuzzy_disabled(self):
        """Without fuzzy matching, OCR variants are independent entries."""
        pages = [
            _make_page("International Journal of CS", "Body 1."),
            _make_page("lnternational Journal of CS", "Body 2."),
            _make_page("Xnternational Journal of CS", "Body 3."),
            _make_page("International Journal of CS", "Body 4."),
        ]
        doc = _make_document(pages)

        # "International Journal" appears 2/4 = 50%, which IS at threshold...
        # but "lnternational" and "Xnternational" are 1/4 each, below threshold
        output, metrics = _run_pass(doc, params={
            "fuzzy_matching": False,
            "min_frequency_ratio": 0.5,
        })

        # The exact match "International Journal of CS" hits 2/4 = 50% → removed
        # The variants are < 50% individually → kept (since fuzzy is off)
        assert "lnternational" in output or "Xnternational" in output


# ── Tests: Embedded Page Numbers ──────────────────────────────────────────────


class TestPageNumberNormalisation:
    """Fingerprinting strips embedded page numbers."""

    def test_trailing_dash_number(self):
        """'Title – 1', 'Title – 2', ... share the same fingerprint."""
        doc = _conference_document()
        output, metrics = _run_pass(doc, params={"min_pages": 3})

        assert "Proceedings of ICML 2025" not in output

    def test_page_of_pattern(self):
        """Lines like 'Page 3 of 10' embedded in headers are normalised."""
        pages = [
            _make_page(f"Report - Page {i + 1} of 5", f"Content {i}.")
            for i in range(5)
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc)

        assert "Report - Page" not in output

    def test_standalone_page_numbers_skipped(self):
        """Standalone numbers (like '42') produce empty fingerprints."""
        fp = HeaderFooterDetectionPass._fingerprint("  42  ")
        assert fp == ""


# ── Tests: Edge Cases ─────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_too_few_pages_skips(self):
        """With < min_pages, the pass does nothing."""
        pages = [
            _make_page("HEADER", "Body 1."),
            _make_page("HEADER", "Body 2."),
        ]
        doc = _make_document(pages)
        output, metrics = _run_pass(doc, params={"min_pages": 3})

        assert "HEADER" in output
        assert metrics.get("skipped") is True

    def test_no_delimiters_single_page(self):
        """Document without delimiters is treated as one page → skips."""
        doc = "# Title\n\nNo page breaks here.\n\nJust one long page."
        output, metrics = _run_pass(doc)

        assert output == doc.strip()
        assert metrics.get("skipped") is True

    def test_empty_content(self):
        """Empty string input."""
        output, metrics = _run_pass("")
        assert output == ""

    def test_empty_pages_between_delimiters(self):
        """Empty pages (just delimiters) are ignored."""
        pages = [
            _make_page("HEADER", "Body 1."),
            "",  # empty page
            _make_page("HEADER", "Body 2."),
            "",  # empty page
            _make_page("HEADER", "Body 3."),
        ]
        doc = _make_document(pages)
        output, metrics = _run_pass(doc)

        # 3 content pages detected, empty ones skipped
        assert metrics["pages_detected"] == 3
        assert "HEADER" not in output

    def test_very_short_pages(self):
        """Pages with fewer lines than zone size still work."""
        pages = [
            "HEADER\nBody.",  # 2 lines only
            "HEADER\nMore body.",
            "HEADER\nEven more.",
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={
            "header_zone_lines": 10,  # larger than page size
            "footer_zone_lines": 10,
        })

        assert "HEADER" not in output

    def test_long_lines_preserved(self):
        """Lines exceeding max_line_length are never removed."""
        long_text = "A" * 250
        pages = [
            _make_page(long_text, f"Body {i}.")
            for i in range(5)
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={"max_line_length": 200})

        assert long_text in output

    def test_short_lines_ignored(self):
        """Lines shorter than min_line_length are not candidates."""
        pages = [
            _make_page("X", f"Body {i}.")
            for i in range(5)
        ]
        doc = _make_document(pages)
        output, _ = _run_pass(doc, params={"min_line_length": 2})

        # "X" is only 1 char, below min_line_length → preserved
        assert "X" in output

    def test_custom_delimiter(self):
        """Custom page delimiter regex."""
        pages = ["HEADER\n\nBody 1.", "HEADER\n\nBody 2.", "HEADER\n\nBody 3."]
        doc = "\n===PAGE===\n".join(pages)
        output, _ = _run_pass(doc, params={
            "page_delimiter": r"^===PAGE===$",
        })

        assert "HEADER" not in output


# ── Tests: Configuration Validation ──────────────────────────────────────────


class TestConfigValidation:
    """validate_config() catches invalid parameters."""

    def test_invalid_frequency_ratio(self):
        from app.optimizer.exceptions import PassConfigError

        pass_instance = HeaderFooterDetectionPass()
        config = PassConfig(params={"min_frequency_ratio": 0.0})

        with pytest.raises(PassConfigError, match="min_frequency_ratio"):
            pass_instance.validate_config(config)

    def test_invalid_frequency_ratio_above_one(self):
        from app.optimizer.exceptions import PassConfigError

        pass_instance = HeaderFooterDetectionPass()
        config = PassConfig(params={"min_frequency_ratio": 1.5})

        with pytest.raises(PassConfigError, match="min_frequency_ratio"):
            pass_instance.validate_config(config)

    def test_invalid_zone_lines(self):
        from app.optimizer.exceptions import PassConfigError

        pass_instance = HeaderFooterDetectionPass()
        config = PassConfig(params={"header_zone_lines": 0})

        with pytest.raises(PassConfigError, match="header_zone_lines"):
            pass_instance.validate_config(config)

    def test_invalid_fuzzy_threshold(self):
        from app.optimizer.exceptions import PassConfigError

        pass_instance = HeaderFooterDetectionPass()
        config = PassConfig(params={"fuzzy_threshold": 0.0})

        with pytest.raises(PassConfigError, match="fuzzy_threshold"):
            pass_instance.validate_config(config)


# ── Tests: Statistics / Metrics ───────────────────────────────────────────────


class TestStatistics:
    """Metrics reported via custom_metrics."""

    def test_metrics_structure(self):
        doc = _journal_document()
        _, metrics = _run_pass(doc)

        assert "pages_detected" in metrics
        assert "patterns_detected" in metrics
        assert "total_lines_removed" in metrics
        assert "patterns" in metrics
        assert isinstance(metrics["patterns"], list)

    def test_pattern_detail_structure(self):
        doc = _journal_document()
        _, metrics = _run_pass(doc)

        for pattern in metrics["patterns"]:
            assert "pattern" in pattern
            assert "example" in pattern
            assert "zone" in pattern
            assert "frequency" in pattern
            assert "total_pages" in pattern
            assert "frequency_ratio" in pattern
            assert "lines_removed" in pattern

    def test_pages_detected_count(self):
        doc = _journal_document(n_pages=5)
        _, metrics = _run_pass(doc)

        assert metrics["pages_detected"] == 5

    def test_skip_metrics_on_few_pages(self):
        pages = [
            _make_page("HEADER", "Body."),
            _make_page("HEADER", "Body."),
        ]
        doc = _make_document(pages)
        _, metrics = _run_pass(doc, params={"min_pages": 3})

        assert metrics["skipped"] is True
        assert "skip_reason" in metrics
        assert metrics["patterns_detected"] == 0

    def test_no_patterns_detected(self):
        """All unique headers and bodies → no patterns above threshold."""
        topics = [
            ("Alpha Project Overview", "The alpha project focuses on machine learning infrastructure."),
            ("Beta Release Notes", "Version 2.0 introduces a new rendering pipeline."),
            ("Gamma Architecture", "The system uses event-driven microservices throughout."),
            ("Delta Migration Guide", "Follow these steps to upgrade from the legacy platform."),
            ("Epsilon Performance Report", "Throughput improved by forty percent after optimisation."),
        ]
        pages = [
            _make_page(title, body)
            for title, body in topics
        ]
        doc = _make_document(pages)
        _, metrics = _run_pass(doc)

        assert metrics["patterns_detected"] == 0
        assert metrics["total_lines_removed"] == 0


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:
    """Run through PipelineExecutor to verify framework integration."""

    @pytest.fixture(autouse=True)
    def _setup_registry(self):
        """Ensure the pass is registered (it auto-registers on import)."""
        registry = PassRegistry()
        # The @register_pass decorator already registered it at import time.
        # The conftest autouse fixture clears the registry, so we need to
        # re-register after the clear.
        registry.register(HeaderFooterDetectionPass, force=True)
        yield
        registry.clear()

    def test_integration_basic(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["header_footer_detection"],
        )
        executor = PipelineExecutor(registry=registry, config=config)

        doc = _journal_document()
        result = executor.run(doc)

        assert result.success
        assert "International Journal" not in result.output
        assert "## Introduction" in result.output

    def test_custom_metrics_in_report(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["header_footer_detection"],
            collect_statistics=True,
        )
        executor = PipelineExecutor(registry=registry, config=config)

        doc = _journal_document()
        result = executor.run(doc)

        # custom_metrics should be populated on the PassStatistics entry
        pass_stats = result.report.pass_details[0]
        assert pass_stats.pass_name == "header_footer_detection"
        assert "pages_detected" in pass_stats.custom_metrics
        assert pass_stats.custom_metrics["patterns_detected"] >= 1

    def test_config_override_via_pipeline(self):
        registry = PassRegistry()
        config = PipelineConfig(
            pass_order=["header_footer_detection"],
            pass_configs={
                "header_footer_detection": PassConfig(
                    params={"min_frequency_ratio": 1.0}
                ),
            },
        )
        executor = PipelineExecutor(registry=registry, config=config)

        # Header on 5/5 pages → exactly 100% → should be removed with ratio=1.0
        doc = _journal_document(n_pages=5)
        result = executor.run(doc)

        assert result.success
        assert "International Journal" not in result.output


# ── Tests: Fingerprint Unit Tests ─────────────────────────────────────────────


class TestFingerprint:
    """Unit tests for the _fingerprint static method."""

    @staticmethod
    def _fp(text: str) -> str:
        return HeaderFooterDetectionPass._fingerprint(text)

    def test_basic_normalisation(self):
        assert self._fp("  Hello World  ") == "hello world"

    def test_whitespace_collapse(self):
        assert self._fp("Hello    World") == "hello world"

    def test_unicode_normalisation(self):
        # ﬁ ligature → fi
        assert "fi" in self._fp("\ufb01nance")

    def test_trailing_dash_number(self):
        assert self._fp("Title \u2013 42") == "title"
        assert self._fp("Title - 1") == "title"

    def test_trailing_pipe_number(self):
        assert self._fp("Header | 7") == "header"

    def test_embedded_page_of(self):
        result = self._fp("Report Page 3 of 10 Footer")
        assert "page" not in result
        assert "report" in result
        assert "footer" in result

    def test_standalone_number_empty(self):
        assert self._fp("42") == ""
        assert self._fp("  7  ") == ""

    def test_empty_line(self):
        assert self._fp("") == ""
        assert self._fp("   ") == ""

    def test_case_insensitive(self):
        assert self._fp("HELLO") == self._fp("hello")

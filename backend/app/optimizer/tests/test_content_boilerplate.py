"""Tests for ContentBoilerplatePass."""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.content_boilerplate import ContentBoilerplatePass
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helper ────────────────────────────────────────────────────────────────────

def _run(content: str, params: dict | None = None) -> tuple[str, dict]:
    p = ContentBoilerplatePass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


# ── TOC Removal ──────────────────────────────────────────────────────────────

class TestTOCRemoval:

    def test_basic_toc(self):
        doc = (
            "# Table of Contents\n"
            "Introduction .................. 1\n"
            "Methods ...................... 5\n"
            "Results ...................... 10\n\n"
            "# Introduction\n"
            "Real content here."
        )
        output, m = _run(doc)
        assert "Table of Contents" not in output
        assert "Introduction" in output  # heading kept
        assert "Real content" in output
        assert m["toc_removed"] == 1

    def test_contents_heading(self):
        doc = "## Contents\nChapter 1 ........... 3\n\nActual text."
        output, m = _run(doc)
        assert "Contents" not in output
        assert "Actual text" in output
        assert m["toc_removed"] == 1

    def test_no_toc(self):
        doc = "# Introduction\nSome text."
        _, m = _run(doc)
        assert m["toc_removed"] == 0

    def test_disabled(self):
        doc = "# Table of Contents\nA .... 1\n\nText."
        output, m = _run(doc, params={"remove_toc": False})
        assert "Table of Contents" in output
        assert m["toc_removed"] == 0


# ── Certificate Removal ─────────────────────────────────────────────────────

class TestCertificateRemoval:

    def test_basic_cert(self):
        doc = (
            "Important content.\n\n"
            "This is to certify that John Doe has completed the course.\n\n"
            "More content."
        )
        output, m = _run(doc)
        assert "certify" not in output
        assert "Important content" in output
        assert "More content" in output
        assert m["certificates_removed"] == 1

    def test_certificate_of(self):
        doc = "Certificate of Completion\n\nAwarded to Jane Smith."
        output, m = _run(doc)
        assert m["certificates_removed"] >= 1

    def test_disabled(self):
        doc = "This is to certify that..."
        output, _ = _run(doc, params={"remove_certificates": False})
        assert "certify" in output


# ── Eval Sheet Removal ───────────────────────────────────────────────────────

class TestEvalSheetRemoval:

    def test_score_line(self):
        doc = "Content.\n\nScore: 85/100\n\nMore content."
        output, m = _run(doc)
        assert "Score:" not in output
        assert m["eval_sheets_removed"] >= 1

    def test_grade_line(self):
        doc = "Text.\n\nGrade: A+\n\nMore."
        output, m = _run(doc)
        assert "Grade:" not in output

    def test_rubric(self):
        doc = "Text.\n\nEvaluation Rubric for Assignment\n\nMore."
        output, m = _run(doc)
        assert m["eval_sheets_removed"] >= 1

    def test_disabled(self):
        doc = "Score: 85"
        output, _ = _run(doc, params={"remove_eval_sheets": False})
        assert "Score" in output


# ── Page Number Removal ──────────────────────────────────────────────────────

class TestPageNumberRemoval:

    def test_standalone_number(self):
        doc = "Content line.\n42\nMore content."
        output, m = _run(doc)
        assert m["page_numbers_removed"] >= 1

    def test_page_x_of_y(self):
        doc = "Text.\nPage 3 of 10\nMore."
        output, m = _run(doc)
        assert "Page 3" not in output
        assert m["page_numbers_removed"] >= 1

    def test_dashed_number(self):
        doc = "Text.\n- 5 -\nMore."
        output, m = _run(doc)
        assert "- 5 -" not in output

    def test_disabled(self):
        doc = "Text.\n42\nMore."
        output, m = _run(doc, params={"remove_page_numbers": False})
        assert m["page_numbers_removed"] == 0


# ── Repeated Lines ───────────────────────────────────────────────────────────

class TestRepeatedLines:

    def test_institution_name(self):
        doc = (
            "University of Technology\n"
            "Content here.\n"
            "University of Technology\n"
            "More content.\n"
            "University of Technology\n"
            "Final content."
        )
        output, m = _run(doc)
        # First occurrence kept, others removed
        assert output.count("University of Technology") == 1
        assert m["repeated_lines_removed"] == 2

    def test_header_footer(self):
        doc = "\n".join([
            "CONFIDENTIAL",
            "Page content 1.",
            "CONFIDENTIAL",
            "Page content 2.",
            "CONFIDENTIAL",
            "Page content 3.",
        ])
        output, m = _run(doc)
        assert output.count("CONFIDENTIAL") == 1
        assert m["repeated_lines_removed"] == 2

    def test_below_threshold(self):
        doc = "Repeat\nContent.\nRepeat\nMore."
        _, m = _run(doc)
        assert m["repeated_lines_removed"] == 0  # only 2 times, threshold=3

    def test_custom_threshold(self):
        doc = "Repeat\nContent.\nRepeat\nMore."
        _, m = _run(doc, params={"min_repeat_count": 2})
        assert m["repeated_lines_removed"] == 1

    def test_long_lines_skipped(self):
        long = "A" * 100
        doc = f"{long}\nText.\n{long}\nMore.\n{long}"
        _, m = _run(doc, params={"max_repeat_line_length": 80})
        assert m["repeated_lines_removed"] == 0

    def test_disabled(self):
        doc = "X\nA.\nX\nB.\nX"
        _, m = _run(doc, params={"remove_repeated_lines": False})
        assert m["repeated_lines_removed"] == 0


# ── Whitelist ────────────────────────────────────────────────────────────────

class TestWhitelist:

    def test_whitelist_protects_cert(self):
        doc = "This is to certify that John completed the program."
        output, m = _run(doc, params={"whitelist": ["John"]})
        assert "certify" in output
        assert m["certificates_removed"] == 0

    def test_whitelist_protects_repeated(self):
        doc = "MIT\nText.\nMIT\nMore.\nMIT"
        output, m = _run(doc, params={"whitelist": ["MIT"]})
        assert output.count("MIT") == 3
        assert m["repeated_lines_removed"] == 0


# ── Code Block Protection ───────────────────────────────────────────────────

class TestCodeProtection:

    def test_code_block_preserved(self):
        doc = "```\nScore: 85\nPage 1 of 5\n```"
        output, _ = _run(doc)
        assert "Score: 85" in output
        assert "Page 1 of 5" in output


# ── Academic Paper ───────────────────────────────────────────────────────────

class TestAcademicPaper:

    def test_full_paper(self):
        doc = (
            "# Table of Contents\n"
            "Introduction ............ 1\n"
            "Methods ................. 3\n\n"
            "# Introduction\n"
            "This paper presents novel findings.\n\n"
            "University of Cambridge\n"
            "More analysis.\n"
            "University of Cambridge\n"
            "Results section.\n"
            "University of Cambridge\n\n"
            "This is to certify that the paper was reviewed.\n\n"
            "Score: 95/100\n\n"
            "# Conclusion\n"
            "Final thoughts."
        )
        output, m = _run(doc)
        assert m["toc_removed"] >= 1
        assert m["certificates_removed"] >= 1
        assert m["eval_sheets_removed"] >= 1
        assert output.count("University of Cambridge") == 1
        assert "Final thoughts" in output
        assert "novel findings" in output


# ── Edge Cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty(self):
        output, m = _run("")
        assert output == ""
        assert m["total_items_removed"] == 0

    def test_no_boilerplate(self):
        doc = "Clean document.\n\nNo boilerplate here."
        output, m = _run(doc)
        assert m["total_items_removed"] == 0

    def test_no_excess_blanks(self):
        doc = "Text.\n\n\n\n42\n\n\n\nMore."
        output, _ = _run(doc)
        assert "\n\n\n" not in output


# ── Config Validation ────────────────────────────────────────────────────────

class TestConfigValidation:

    def test_invalid_min_repeat(self):
        from app.optimizer.exceptions import PassConfigError
        p = ContentBoilerplatePass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"min_repeat_count": 1}))

    def test_valid_config(self):
        p = ContentBoilerplatePass()
        p.validate_config(p.default_config)  # no error


# ── Statistics ───────────────────────────────────────────────────────────────

class TestStatistics:

    def test_keys(self):
        _, m = _run("Text.\n42\nMore.")
        expected = {
            "toc_removed", "certificates_removed", "eval_sheets_removed",
            "page_numbers_removed", "repeated_lines_removed",
            "total_items_removed",
        }
        assert set(m.keys()) == expected


# ── Pipeline Integration ─────────────────────────────────────────────────────

class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(ContentBoilerplatePass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["content_boilerplate"],
            collect_statistics=True,
        )
        doc = "# Contents\nA ... 1\n\nReal text."
        result = PipelineExecutor(registry=r, config=config).run(doc)
        assert result.success
        assert "Contents" not in result.output
        assert "Real text" in result.output

    def test_custom_metrics(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["content_boilerplate"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run("42\nText.")
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["page_numbers_removed"] >= 1

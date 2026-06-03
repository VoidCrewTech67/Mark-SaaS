"""Tests for OCRCleanupPass."""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.ocr_cleanup import OCRCleanupPass
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helper ────────────────────────────────────────────────────────────────────

def _run(content: str, params: dict | None = None) -> tuple[str, dict]:
    p = OCRCleanupPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


# ── CID Removal ──────────────────────────────────────────────────────────────

class TestCIDRemoval:

    def test_basic_cid(self):
        output, m = _run("Hello (cid:42) world")
        assert "(cid:42)" not in output
        assert "Hello" in output
        assert m["cid_removed"] == 1

    def test_multiple_cid(self):
        output, m = _run("A(cid:1)B(cid:2)C")
        assert "(cid:" not in output
        assert m["cid_removed"] == 2

    def test_cid_in_code_preserved(self):
        output, _ = _run("```\n(cid:99)\n```")
        assert "(cid:99)" in output

    def test_cid_disabled(self):
        output, m = _run("Hello (cid:42)", params={"remove_cid": False})
        assert "(cid:42)" in output
        assert m["cid_removed"] == 0


# ── Unicode / Ligatures ──────────────────────────────────────────────────────

class TestUnicodeNormalization:

    def test_ligature_fi(self):
        output, m = _run("ﬁnding ﬂow")
        assert "finding" in output
        assert "flow" in output
        assert m["ligatures_fixed"] == 2

    def test_ligature_ffi(self):
        output, _ = _run("oﬃce")
        assert "office" in output

    def test_nbsp_replaced(self):
        output, _ = _run("hello\u00a0world")
        assert "\u00a0" not in output
        assert "hello world" in output

    def test_replacement_char_removed(self):
        output, m = _run("data\ufffdhere")
        assert "\ufffd" not in output
        assert m["replacement_chars_removed"] == 1

    def test_zero_width_removed(self):
        output, _ = _run("hel\u200blo")
        assert "\u200b" not in output

    def test_ligature_in_math_preserved(self):
        # Inline math should be protected
        output, _ = _run("$f\u00fbn$")
        # NFKC still applies globally but ligatures skip protected
        assert "$" in output


# ── Control Characters ───────────────────────────────────────────────────────

class TestControlChars:

    def test_formfeed_removed(self):
        output, m = _run("page1\x0cpage2")
        assert "\x0c" not in output
        assert m["control_chars_removed"] == 1

    def test_null_removed(self):
        output, _ = _run("a\x00b")
        assert "\x00" not in output

    def test_tab_preserved(self):
        output, _ = _run("col1\tcol2")
        assert "\t" in output

    def test_newline_preserved(self):
        output, _ = _run("line1\nline2")
        assert "\n" in output


# ── Smart Quotes ─────────────────────────────────────────────────────────────

class TestSmartQuotes:

    def test_quotes_normalized(self):
        output, m = _run(
            "\u201cHello\u201d \u2018world\u2019",
            params={"normalize_quotes": True},
        )
        assert '"Hello"' in output
        assert "'world'" in output
        assert m["quotes_normalized"] == 4

    def test_quotes_off_by_default(self):
        output, _ = _run("\u201ctest\u201d")
        assert "\u201c" in output  # kept

    def test_emdash(self):
        output, _ = _run("word\u2014word", params={"normalize_quotes": True})
        assert "--" in output

    def test_ellipsis(self):
        output, _ = _run("wait\u2026", params={"normalize_quotes": True})
        assert "..." in output


# ── Whitespace Fixing ────────────────────────────────────────────────────────

class TestWhitespaceFix:

    def test_lower_upper_split(self):
        output, m = _run("quantumKey distributionMethod")
        assert "quantum Key" in output
        assert m["whitespace_fixed"] >= 1

    def test_merged_prepositions(self):
        output, m = _run("ofthe inthe")
        assert "of the" in output
        assert "in the" in output
        assert m["whitespace_fixed"] >= 2

    def test_code_block_no_split(self):
        output, _ = _run("```\ncamelCase\n```")
        assert "camelCase" in output  # not split

    def test_disabled(self):
        output, _ = _run("ofthe", params={"fix_whitespace": False})
        assert "ofthe" in output


# ── Line Unwrapping ──────────────────────────────────────────────────────────

class TestLineUnwrap:

    def test_mid_sentence_break(self):
        output, m = _run("the quantum\nkey distribution")
        assert "the quantum key distribution" in output
        assert m["lines_unwrapped"] == 1

    def test_heading_not_unwrapped(self):
        output, _ = _run("# Title\nparagraph text")
        # # Title\n... — not mid-sentence (starts with #)
        assert "# Title" in output

    def test_paragraph_break_preserved(self):
        output, _ = _run("End of para.\n\nStart of next.")
        assert "\n\n" in output

    def test_comma_continuation(self):
        output, m = _run("item one,\nitem two")
        assert "item one, item two" in output
        assert m["lines_unwrapped"] == 1

    def test_disabled(self):
        output, _ = _run("word\nword", params={"unwrap_lines": False})
        assert "\n" in output


# ── Punctuation Repair ───────────────────────────────────────────────────────

class TestPunctuationRepair:

    def test_double_period(self):
        output, m = _run("end of sentence.. Next")
        assert ".." not in output
        assert ". Next" in output
        assert m["punctuation_fixed"] >= 1

    def test_triple_period_preserved(self):
        output, _ = _run("wait... more")
        assert "..." in output

    def test_space_before_comma(self):
        output, m = _run("hello , world")
        assert "hello, world" in output
        assert m["punctuation_fixed"] >= 1

    def test_space_before_period(self):
        output, _ = _run("end .")
        assert "end." in output

    def test_disabled(self):
        output, _ = _run("hello ..", params={"fix_punctuation": False})
        assert ".." in output


# ── Protected Zones ──────────────────────────────────────────────────────────

class TestProtectedZones:

    def test_code_block_untouched(self):
        doc = "```python\n(cid:1) camelCase\n```"
        output, _ = _run(doc)
        assert "(cid:1)" in output
        assert "camelCase" in output

    def test_inline_code_untouched(self):
        doc = "Use `camelCase` naming"
        output, _ = _run(doc)
        assert "`camelCase`" in output

    def test_display_math_untouched(self):
        doc = "$$E = mc^2$$"
        output, _ = _run(doc)
        assert "$$E = mc^2$$" in output

    def test_inline_math_untouched(self):
        doc = "where $x_i$ is"
        output, _ = _run(doc)
        assert "$x_i$" in output


# ── Edge Cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_doc(self):
        output, m = _run("")
        assert output == ""
        assert m["artifacts_detected"] == 0

    def test_clean_doc(self):
        output, m = _run("Clean document with no artifacts.")
        assert m["artifacts_detected"] == 0
        assert m["confidence_score"] == 1.0

    def test_all_artifact_types(self):
        doc = (
            "(cid:42) the ﬁrst\x0c result..\n"
            "ofthe \u201cquote\u201d"
        )
        output, m = _run(doc, params={"normalize_quotes": True})
        assert m["cid_removed"] >= 1
        assert m["ligatures_fixed"] >= 1
        assert m["artifacts_detected"] >= 4


# ── Statistics ───────────────────────────────────────────────────────────────

class TestStatistics:

    def test_metrics_keys(self):
        _, m = _run("(cid:1) test")
        expected = {
            "artifacts_detected", "artifacts_repaired", "confidence_score",
            "cid_removed", "ligatures_fixed", "replacement_chars_removed",
            "control_chars_removed", "quotes_normalized", "whitespace_fixed",
            "lines_unwrapped", "punctuation_fixed",
        }
        assert expected == set(m.keys())

    def test_confidence_score(self):
        _, m = _run("(cid:1) ﬁx")
        assert m["confidence_score"] == 1.0  # all detected = all repaired


# ── Pipeline Integration ─────────────────────────────────────────────────────

class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(OCRCleanupPass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["ocr_cleanup"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run(
            "(cid:42) ﬁnd the ﬂow"
        )
        assert result.success
        assert "(cid:42)" not in result.output
        assert "find" in result.output
        assert "flow" in result.output

    def test_custom_metrics(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["ocr_cleanup"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run("(cid:1)")
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["cid_removed"] == 1

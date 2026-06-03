"""Tests for EquationExtractionPass + EquationRestorationPass."""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.equation_preservation import (
    EquationExtractionPass,
    EquationRestorationPass,
    _EQ_MAP_KEY,
    _PLACEHOLDER_RE,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract(content: str, params: dict | None = None) -> tuple[str, dict, dict]:
    p = EquationExtractionPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    eq_map = ctx.metadata.get(_EQ_MAP_KEY, {})
    return ctx.content, metrics, eq_map


def _roundtrip(content: str, params: dict | None = None) -> tuple[str, dict, dict]:
    """Extract → restore → return final content + both metrics."""
    ext = EquationExtractionPass()
    res = EquationRestorationPass()
    ext_cfg = ext.default_config
    if params:
        ext_cfg = ext_cfg.merge({"params": params})
    res_cfg = res.default_config

    ctx = OptimizationContext(content=content, original_content=content)
    ctx = ext.run(ctx, ext_cfg)
    ext_metrics = ctx.metadata.get(f"_pass_metrics_{ext.name}", {})

    ctx = res.run(ctx, res_cfg)
    res_metrics = ctx.metadata.get(f"_pass_metrics_{res.name}", {})

    return ctx.content, ext_metrics, res_metrics


# ── Display Math ─────────────────────────────────────────────────────────────

class TestDisplayMath:

    def test_basic_display(self):
        doc = "Text $$E = mc^2$$ more text"
        out, m, eq_map = _extract(doc)
        assert "$$E = mc^2$$" not in out
        assert _PLACEHOLDER_RE.search(out)
        assert m["equations_extracted"] == 1

    def test_multiline_display(self):
        doc = "Before\n$$\n\\frac{a}{b} + c\n$$\nAfter"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1
        assert "\\frac" not in out

    def test_roundtrip_display(self):
        doc = "Result: $$\\int_0^\\infty e^{-x} dx = 1$$"
        out, _, res_m = _roundtrip(doc)
        assert out == doc
        assert res_m["equations_restored"] == 1


# ── Inline Math ──────────────────────────────────────────────────────────────

class TestInlineMath:

    def test_basic_inline(self):
        doc = "where $x > 0$ holds"
        out, m, _ = _extract(doc)
        assert "$x > 0$" not in out
        assert m["equations_extracted"] == 1

    def test_multiple_inline(self):
        doc = "Let $a = 1$ and $b = 2$."
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 2

    def test_roundtrip_inline(self):
        doc = "Given $x_i$ and $y^2$."
        out, _, _ = _roundtrip(doc)
        assert out == doc

    def test_escaped_dollar_not_matched(self):
        doc = "Price is \\$50"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 0


# ── LaTeX Environments ───────────────────────────────────────────────────────

class TestLatexEnvironments:

    def test_equation_env(self):
        doc = "\\begin{equation}\nx^2 + y^2 = z^2\n\\end{equation}"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1
        assert "\\begin{equation}" not in out

    def test_align_env(self):
        doc = "\\begin{align}\na &= b \\\\\nc &= d\n\\end{align}"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1

    def test_roundtrip_env(self):
        doc = "See:\n\\begin{equation}\nE = mc^2\n\\end{equation}\nDone."
        out, _, _ = _roundtrip(doc)
        assert out == doc


# ── Bracket Display ──────────────────────────────────────────────────────────

class TestBracketDisplay:

    def test_bracket_math(self):
        doc = "Result: \\[a + b = c\\]"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1

    def test_roundtrip_bracket(self):
        doc = "\\[\\sum_{i=1}^{n} x_i\\]"
        out, _, _ = _roundtrip(doc)
        assert out == doc


# ── Paren Inline ─────────────────────────────────────────────────────────────

class TestParenInline:

    def test_paren_math(self):
        doc = "where \\(x > 0\\) always"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1

    def test_roundtrip_paren(self):
        doc = "value \\(\\alpha = 0.05\\) here"
        out, _, _ = _roundtrip(doc)
        assert out == doc


# ── LaTeX Commands ───────────────────────────────────────────────────────────

class TestLatexCommands:

    def test_frac(self):
        doc = "The ratio \\frac{a}{b} shows"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1

    def test_sum(self):
        doc = "Total \\sum_{i=1}^{n} values"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] >= 1

    def test_greek_letters(self):
        doc = "parameter \\alpha and \\beta"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] >= 1

    def test_disabled(self):
        doc = "\\frac{a}{b}"
        out, m, _ = _extract(doc, params={"detect_latex_commands": False})
        assert m["equations_extracted"] == 0


# ── Scientific Notation ──────────────────────────────────────────────────────

class TestScientificNotation:

    def test_e_notation(self):
        doc = "value is 3.14e-5 here"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1
        assert "3.14e-5" not in out

    def test_times_notation(self):
        doc = "Avogadro 6.022 × 10^{23}"
        out, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1

    def test_roundtrip_sci(self):
        doc = "Speed 3e8 m/s"
        out, _, _ = _roundtrip(doc)
        assert out == doc

    def test_disabled(self):
        doc = "val 3.14e-5"
        out, m, _ = _extract(doc, params={"detect_sci_notation": False})
        assert m["equations_extracted"] == 0


# ── Unicode Sub/Superscripts ─────────────────────────────────────────────────

class TestSubSuperscripts:

    def test_subscript_detected(self):
        doc = "H₂O molecule"
        out, m, _ = _extract(doc, params={"detect_sub_super": True})
        assert m["equations_extracted"] == 1

    def test_superscript_detected(self):
        doc = "x² value"
        out, m, _ = _extract(doc, params={"detect_sub_super": True})
        assert m["equations_extracted"] == 1

    def test_off_by_default(self):
        doc = "H₂O"
        _, m, _ = _extract(doc)
        assert m["equations_extracted"] == 0

    def test_roundtrip(self):
        doc = "CO₂ and H₂O"
        out, _, _ = _roundtrip(doc, params={"detect_sub_super": True})
        assert out == doc


# ── Zero Modification Guarantee ──────────────────────────────────────────────

class TestZeroModification:

    def test_complex_equation_preserved(self):
        eq = "$$\\int_{-\\infty}^{\\infty} \\frac{1}{\\sqrt{2\\pi\\sigma^2}} e^{-\\frac{(x-\\mu)^2}{2\\sigma^2}} dx = 1$$"
        doc = f"The Gaussian integral: {eq}"
        out, _, _ = _roundtrip(doc)
        assert out == doc

    def test_multiple_types_preserved(self):
        doc = (
            "Inline $x^2$ and display $$y = mx + b$$ "
            "and scientific 3.14e-5."
        )
        out, _, _ = _roundtrip(doc)
        assert out == doc

    def test_subscripts_superscripts_preserved(self):
        doc = "$x_i^2 + y_{j+1}^{n-1} = z$"
        out, _, _ = _roundtrip(doc)
        assert out == doc

    def test_symbols_preserved(self):
        doc = "$\\alpha \\beta \\gamma \\delta \\epsilon$"
        out, _, _ = _roundtrip(doc)
        assert out == doc


# ── Restoration Edge Cases ───────────────────────────────────────────────────

class TestRestorationEdgeCases:

    def test_no_equations(self):
        doc = "Plain text no math."
        out, ext_m, res_m = _roundtrip(doc)
        assert out == doc
        assert ext_m["equations_extracted"] == 0
        assert res_m["equations_restored"] == 0

    def test_empty_doc(self):
        out, _, _ = _roundtrip("")
        assert out == ""

    def test_orphaned_placeholder(self):
        """Placeholder removed by another pass → orphaned."""
        ext = EquationExtractionPass()
        res = EquationRestorationPass()
        ctx = OptimizationContext(content="$x$", original_content="$x$")
        ctx = ext.run(ctx, ext.default_config)
        # Simulate another pass removing placeholder
        ctx.content = "placeholder was removed"
        ctx = res.run(ctx, res.default_config)
        metrics = ctx.metadata.get(f"_pass_metrics_{res.name}", {})
        assert metrics["orphaned_placeholders"] == 1


# ── Statistics ───────────────────────────────────────────────────────────────

class TestStatistics:

    def test_extraction_metrics(self):
        doc = "$$a$$ and $b$ and 3e5"
        _, m, _ = _extract(doc)
        assert "equations_extracted" in m
        assert "by_type" in m
        assert m["equations_extracted"] == 3

    def test_restoration_metrics(self):
        doc = "$x$ and $y$"
        _, _, res_m = _roundtrip(doc)
        assert res_m["equations_restored"] == 2
        assert res_m["orphaned_placeholders"] == 0


# ── Non-Overlapping Detection ────────────────────────────────────────────────

class TestNonOverlapping:

    def test_display_not_inline(self):
        """$$...$$ should match as display, not two inline $...$."""
        doc = "$$E = mc^2$$"
        _, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1
        assert m["by_type"].get("display_math", 0) == 1

    def test_env_not_display(self):
        doc = "\\begin{equation}x\\end{equation}"
        _, m, _ = _extract(doc)
        assert m["equations_extracted"] == 1
        assert m["by_type"].get("latex_env", 0) == 1


# ── Pipeline Integration ─────────────────────────────────────────────────────

class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(EquationExtractionPass, force=True)
        r.register(EquationRestorationPass, force=True)
        yield
        r.clear()

    def test_full_pipeline(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["equation_extraction", "equation_restoration"],
            collect_statistics=True,
        )
        doc = "Prove $$E = mc^2$$ using $v < c$."
        result = PipelineExecutor(registry=r, config=config).run(doc)
        assert result.success
        assert result.output == doc  # zero modification

    def test_with_middle_pass(self):
        """Equations survive a pass that modifies surrounding text."""
        from app.optimizer.tests.conftest import UpperCasePass

        r = PassRegistry()
        r.register(UpperCasePass, force=True)
        config = PipelineConfig(
            pass_order=[
                "equation_extraction",
                "uppercase",
                "equation_restoration",
            ],
            collect_statistics=True,
        )
        doc = "hello $$E = mc^2$$ world"
        result = PipelineExecutor(registry=r, config=config).run(doc)
        assert result.success
        # Text uppercased but equation preserved exactly
        assert "$$E = mc^2$$" in result.output
        assert "HELLO" in result.output

    def test_metrics_in_report(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["equation_extraction", "equation_restoration"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run("$x$")
        ext_stats = result.report.pass_details[0]
        res_stats = result.report.pass_details[1]
        assert ext_stats.custom_metrics["equations_extracted"] == 1
        assert res_stats.custom_metrics["equations_restored"] == 1


# ── Benchmark ─────────────────────────────────────────────────────────────────

class TestBenchmark:

    @pytest.mark.parametrize("n_equations", [10, 50, 100])
    def test_throughput(self, n_equations: int):
        import time

        equations = [f"$x_{{{i}}}^2 + y_{{{i}}}^2 = z_{{{i}}}^2$" for i in range(n_equations)]
        doc = "\n\n".join(
            f"Paragraph {i} discusses {eq} in detail."
            for i, eq in enumerate(equations)
        )

        t0 = time.perf_counter()
        out, _, _ = _roundtrip(doc)
        elapsed = time.perf_counter() - t0

        assert out == doc  # zero modification
        assert elapsed < 2.0, f"Too slow: {elapsed:.3f}s for {n_equations} equations"

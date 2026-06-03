"""Tests for SemanticTableTransformPass."""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.semantic_table_transform import SemanticTableTransformPass
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helper ────────────────────────────────────────────────────────────────────

def _run(content: str, params: dict | None = None) -> tuple[str, dict]:
    p = SemanticTableTransformPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


_KV_TABLE = """\
| Feature | Description |
|---------|-------------|
| Period | Orbital period |
| Mass | Planet mass |"""

_MULTI_TABLE = """\
| Planet | Period | Mass |
|--------|--------|------|
| Earth | 365d | 1.0 |
| Mars | 687d | 0.107 |"""

_SCIENTIFIC = """\
| Variable | Mean ± SD | p-value |
|----------|-----------|---------|
| X1 | 4.2 ± 1.1 | 0.03 |"""


# ── 2-Column KV Transform ───────────────────────────────────────────────────

class TestKVTransform:

    def test_basic(self):
        output, m = _run(_KV_TABLE)
        assert "Feature (Description):" in output
        assert "- Period: Orbital period" in output
        assert "- Mass: Planet mass" in output
        assert "|" not in output
        assert m["tables_transformed"] == 1

    def test_no_pipe_in_output(self):
        output, _ = _run(_KV_TABLE)
        assert "|" not in output

    def test_preserves_all_data(self):
        output, _ = _run(_KV_TABLE)
        assert "Period" in output
        assert "Orbital period" in output
        assert "Mass" in output
        assert "Planet mass" in output


# ── Multi-Column Nested Transform ────────────────────────────────────────────

class TestMultiColNested:

    def test_basic(self):
        output, m = _run(_MULTI_TABLE)
        assert "Planet:" in output
        assert "- Earth:" in output
        assert "  - Period: 365d" in output
        assert "  - Mass: 1.0" in output
        assert "- Mars:" in output
        assert m["tables_transformed"] == 1

    def test_no_pipe_in_output(self):
        output, _ = _run(_MULTI_TABLE)
        assert "|" not in output

    def test_row_relationships_preserved(self):
        output, _ = _run(_MULTI_TABLE)
        # Earth's data comes before Mars's data
        earth_pos = output.find("Earth")
        mars_pos = output.find("Mars")
        assert earth_pos < mars_pos
        # Earth's period comes right after Earth
        earth_period = output.find("Period: 365d")
        assert earth_pos < earth_period < mars_pos


# ── Multi-Column Flat Transform ──────────────────────────────────────────────

class TestMultiColFlat:

    def test_flat_mode(self):
        output, m = _run(_MULTI_TABLE, params={"nested_multicolumn": False})
        assert "Planet:" in output
        assert "- Earth: Period=365d, Mass=1.0" in output
        assert "- Mars: Period=687d, Mass=0.107" in output


# ── Scientific Preservation ──────────────────────────────────────────────────

class TestScientificPreservation:

    def test_pvalue_preserved(self):
        output, m = _run(_SCIENTIFIC)
        assert "|" in output  # kept as table
        assert m["scientific_preserved"] == 1

    def test_guard_disabled(self):
        output, m = _run(_SCIENTIFIC, params={"preserve_scientific": False})
        assert m["tables_transformed"] == 1
        assert "|" not in output


# ── Malformed Tables ─────────────────────────────────────────────────────────

class TestMalformedTables:

    def test_missing_separator(self):
        doc = "| A | B |\n| 1 | 2 |\n| 3 | 4 |"
        output, m = _run(doc)
        assert m["malformed_repaired"] >= 1
        assert "|" not in output

    def test_inconsistent_columns(self):
        doc = "| A | B | C |\n|---|---|---|\n| 1 | 2 |\n| 3 | 4 | 5 |"
        output, m = _run(doc)
        assert m["tables_transformed"] >= 1

    def test_repair_disabled(self):
        doc = "| A | B |\n| 1 | 2 |"  # no separator = malformed
        output, m = _run(doc, params={"repair_malformed": False})
        assert m["malformed_repaired"] == 0


# ── Guards ───────────────────────────────────────────────────────────────────

class TestGuards:

    def test_wide_table_skipped(self):
        headers = "| " + " | ".join(f"C{i}" for i in range(12)) + " |"
        sep = "| " + " | ".join(["---"] * 12) + " |"
        row = "| " + " | ".join(["x"] * 12) + " |"
        doc = f"{headers}\n{sep}\n{row}"
        _, m = _run(doc, params={"max_columns": 10})
        assert m["tables_transformed"] == 0


# ── Keep Mode ────────────────────────────────────────────────────────────────

class TestKeepMode:

    def test_unchanged(self):
        output, m = _run(_KV_TABLE, params={"mode": "keep"})
        assert "| Feature" in output
        assert m["tables_transformed"] == 0


# ── Multiple Tables ──────────────────────────────────────────────────────────

class TestMultipleTables:

    def test_two_tables(self):
        doc = _KV_TABLE + "\n\nSome text.\n\n" + _MULTI_TABLE
        output, m = _run(doc)
        assert m["tables_transformed"] == 2
        assert "Feature (Description):" in output
        assert "Planet:" in output

    def test_mix_sci_and_normal(self):
        doc = _KV_TABLE + "\n\n" + _SCIENTIFIC
        _, m = _run(doc)
        assert m["tables_transformed"] == 1
        assert m["scientific_preserved"] == 1


# ── Context Preservation ─────────────────────────────────────────────────────

class TestContextPreservation:

    def test_surrounding_text(self):
        doc = "# Intro\n\nBefore.\n\n" + _KV_TABLE + "\n\nAfter."
        output, _ = _run(doc)
        assert "# Intro" in output
        assert "Before." in output
        assert "After." in output

    def test_no_excessive_blanks(self):
        doc = "Text.\n\n" + _KV_TABLE + "\n\nMore."
        output, _ = _run(doc)
        assert "\n\n\n" not in output


# ── Edge Cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_doc(self):
        output, m = _run("")
        assert output == ""
        assert m["tables_found"] == 0

    def test_no_tables(self):
        _, m = _run("Just text.")
        assert m["tables_found"] == 0

    def test_single_row(self):
        doc = "| A | B |\n|---|---|\n| 1 | 2 |"
        output, m = _run(doc)
        assert m["tables_transformed"] == 1


# ── Config Validation ────────────────────────────────────────────────────────

class TestConfigValidation:

    def test_invalid_mode(self):
        from app.optimizer.exceptions import PassConfigError
        p = SemanticTableTransformPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"mode": "nope"}))


# ── Statistics ───────────────────────────────────────────────────────────────

class TestStatistics:

    def test_keys(self):
        _, m = _run(_KV_TABLE)
        expected = {"tables_found", "tables_transformed",
                    "scientific_preserved", "malformed_repaired"}
        assert set(m.keys()) == expected


# ── Pipeline Integration ─────────────────────────────────────────────────────

class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(SemanticTableTransformPass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["semantic_table_transform"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run(_KV_TABLE)
        assert result.success
        assert "- Period: Orbital period" in result.output

    def test_custom_metrics(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["semantic_table_transform"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run(_KV_TABLE)
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["tables_transformed"] == 1

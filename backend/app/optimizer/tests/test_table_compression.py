"""
Tests for TableCompressionPass.
"""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.table_compression import (
    TableCompressionPass,
    _ParsedTable,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(content: str, params: dict | None = None) -> tuple[str, dict]:
    p = TableCompressionPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


_SIMPLE_2COL = """\
| State | Probability |
|-------|-------------|
| S1 | 0.5 |
| S2 | 0.5 |"""

_MULTI_COL = """\
| Name | Score | Rank |
|------|-------|------|
| Alice | 95 | 1 |
| Bob | 88 | 2 |
| Carol | 92 | 3 |"""

_SCIENTIFIC = """\
| Variable | Mean ± SD | p-value |
|----------|-----------|---------|
| X1 | 4.2 ± 1.1 | 0.03 |
| X2 | 3.8 ± 0.9 | 0.12 |"""

_UNIT_TABLE = """\
| Component | Weight (kg) | Length (cm) |
|-----------|-------------|-------------|
| A | 5.2 | 30 |
| B | 3.1 | 22 |"""

_CAPTIONED = """\
Table 1: Results summary

| Model | Accuracy | F1 |
|-------|----------|----|
| BERT | 0.94 | 0.93 |
| GPT | 0.96 | 0.95 |"""


# ── Tests: 2-Column KV Compression ───────────────────────────────────────────


class TestKVCompression:

    def test_basic_2col(self):
        output, metrics = _run(_SIMPLE_2COL)
        assert "StateProbability:" in output
        assert "S1=0.5" in output
        assert "S2=0.5" in output
        assert "|" not in output
        assert metrics["tables_compressed"] == 1

    def test_custom_kv_separator(self):
        output, _ = _run(_SIMPLE_2COL, params={"kv_separator": ": "})
        assert "S1: 0.5" in output

    def test_preserves_all_data(self):
        output, _ = _run(_SIMPLE_2COL)
        assert "S1" in output
        assert "S2" in output
        assert "0.5" in output


# ── Tests: Multi-Column Compression ──────────────────────────────────────────


class TestMultiColCompression:

    def test_basic_multi(self):
        output, metrics = _run(_MULTI_COL)
        assert "Name|Score|Rank:" in output
        assert "Alice|95|1" in output
        assert "Bob|88|2" in output
        assert metrics["tables_compressed"] == 1

    def test_custom_col_separator(self):
        output, _ = _run(_MULTI_COL, params={"col_separator": ","})
        assert "Name,Score,Rank:" in output
        assert "Alice,95,1" in output

    def test_no_separator_row(self):
        """Separator row (---) removed in output."""
        output, _ = _run(_MULTI_COL)
        assert "---" not in output


# ── Tests: Scientific Table Preservation ──────────────────────────────────────


class TestScientificPreservation:

    def test_pvalue_preserved(self):
        output, metrics = _run(_SCIENTIFIC)
        assert "p-value" in output
        assert "|" in output  # kept as markdown table
        assert metrics["scientific_tables_preserved"] == 1

    def test_unit_headers_preserved(self):
        output, metrics = _run(_UNIT_TABLE)
        assert "(kg)" in output
        assert "|" in output
        assert metrics["scientific_tables_preserved"] == 1

    def test_captioned_preserved(self):
        output, metrics = _run(_CAPTIONED)
        assert "| BERT" in output or "BERT" in output
        assert metrics["scientific_tables_preserved"] == 1

    def test_scientific_guard_disabled(self):
        output, metrics = _run(_SCIENTIFIC, params={"preserve_scientific": False})
        assert metrics["tables_compressed"] == 1
        assert "---" not in output

    def test_plus_minus_detected(self):
        doc = "| X | Val |\n|---|-----|\n| A | 3.2 ± 0.1 |"
        output, metrics = _run(doc)
        assert metrics["scientific_tables_preserved"] == 1


# ── Tests: Min Rows / Max Columns Guards ──────────────────────────────────────


class TestGuards:

    def test_single_row_skipped(self):
        doc = "| A | B |\n|---|---|\n| 1 | 2 |"
        _, metrics = _run(doc, params={"min_rows": 2})
        assert metrics["tables_skipped"] == 1
        assert metrics["tables_compressed"] == 0

    def test_single_row_compressed_when_threshold_1(self):
        doc = "| A | B |\n|---|---|\n| 1 | 2 |"
        output, metrics = _run(doc, params={"min_rows": 1})
        assert metrics["tables_compressed"] == 1

    def test_wide_table_skipped(self):
        headers = "| " + " | ".join(f"C{i}" for i in range(12)) + " |"
        sep = "| " + " | ".join(["---"] * 12) + " |"
        row = "| " + " | ".join(["x"] * 12) + " |"
        doc = f"{headers}\n{sep}\n{row}\n{row}"
        _, metrics = _run(doc, params={"max_columns": 10})
        assert metrics["tables_skipped"] == 1


# ── Tests: Keep Mode ─────────────────────────────────────────────────────────


class TestKeepMode:

    def test_content_unchanged(self):
        output, _ = _run(_SIMPLE_2COL, params={"mode": "keep"})
        assert "| State" in output

    def test_metrics_reported(self):
        _, metrics = _run(_SIMPLE_2COL, params={"mode": "keep"})
        assert metrics["tables_found"] == 1
        assert metrics["tables_compressed"] == 0


# ── Tests: Multiple Tables ───────────────────────────────────────────────────


class TestMultipleTables:

    def test_two_tables(self):
        doc = _SIMPLE_2COL + "\n\nSome text.\n\n" + _MULTI_COL
        output, metrics = _run(doc)
        assert metrics["tables_compressed"] == 2
        assert "StateProbability:" in output
        assert "Name|Score|Rank:" in output

    def test_mix_scientific_and_normal(self):
        doc = _SIMPLE_2COL + "\n\n" + _SCIENTIFIC
        _, metrics = _run(doc)
        assert metrics["tables_compressed"] == 1
        assert metrics["scientific_tables_preserved"] == 1


# ── Tests: Context Preservation ──────────────────────────────────────────────


class TestContextPreservation:

    def test_surrounding_text_preserved(self):
        doc = "# Intro\n\nBefore table.\n\n" + _SIMPLE_2COL + "\n\nAfter table."
        output, _ = _run(doc)
        assert "# Intro" in output
        assert "Before table." in output
        assert "After table." in output

    def test_no_excessive_blank_lines(self):
        doc = "Text.\n\n" + _SIMPLE_2COL + "\n\nMore text."
        output, _ = _run(doc)
        assert "\n\n\n" not in output


# ── Tests: Table Parsing ─────────────────────────────────────────────────────


class TestTableParsing:

    def test_finds_table(self):
        lines = _SIMPLE_2COL.split("\n")
        tables = TableCompressionPass._find_tables(lines)
        assert len(tables) == 1
        assert tables[0].headers == ["State", "Probability"]
        assert len(tables[0].rows) == 2

    def test_no_table(self):
        tables = TableCompressionPass._find_tables(["No table here."])
        assert len(tables) == 0

    def test_aligned_separator(self):
        doc = "| A | B |\n|:---:|---:|\n| 1 | 2 |"
        tables = TableCompressionPass._find_tables(doc.split("\n"))
        assert len(tables) == 1


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_doc(self):
        output, metrics = _run("")
        assert output == ""
        assert metrics["tables_found"] == 0

    def test_no_tables(self):
        output, metrics = _run("Just text.\n\nMore text.")
        assert metrics["tables_found"] == 0

    def test_malformed_table_ignored(self):
        doc = "| A | B |\n| not a sep |\n| 1 | 2 |"
        _, metrics = _run(doc)
        assert metrics["tables_found"] == 0


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:

    def test_invalid_mode(self):
        from app.optimizer.exceptions import PassConfigError
        p = TableCompressionPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"mode": "nope"}))

    def test_invalid_min_rows(self):
        from app.optimizer.exceptions import PassConfigError
        p = TableCompressionPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"min_rows": 0}))

    def test_invalid_max_columns(self):
        from app.optimizer.exceptions import PassConfigError
        p = TableCompressionPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"max_columns": -1}))


# ── Tests: Statistics ─────────────────────────────────────────────────────────


class TestStatistics:

    def test_metrics_keys(self):
        _, metrics = _run(_SIMPLE_2COL)
        expected = {"mode", "tables_found", "tables_compressed",
                    "tables_skipped", "scientific_tables_preserved"}
        assert set(metrics.keys()) == expected


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(TableCompressionPass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(pass_order=["table_compression"])
        result = PipelineExecutor(registry=r, config=config).run(_SIMPLE_2COL)
        assert result.success
        assert "S1=0.5" in result.output

    def test_custom_metrics(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["table_compression"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run(_SIMPLE_2COL)
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["tables_compressed"] == 1

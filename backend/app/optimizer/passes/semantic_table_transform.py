"""
optimizer/passes/semantic_table_transform.py – Tables → LLM-friendly structured text.

Architecture
============

1. **Detect** — Find markdown tables (valid + malformed).
2. **Classify** — 2-col key-value vs multi-col entity table.
3. **Transform**:
   - 2-col → ``Header:\\n- Key: Value``
   - Multi-col → ``Header:\\n- Row1Key:\\n  - Col2: Val\\n  - Col3: Val``
4. **Guard** — Preserve scientific tables (reuse heuristics).

Malformed table handling: tables w/ missing separator, inconsistent
column counts, or broken alignment are detected and repaired before
transform.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass

# ── Patterns ──────────────────────────────────────────────────────────────────

_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")
_SEPARATOR_CELL_RE = re.compile(r"^\s*:?-{1,}:?\s*$")
_CAPTION_RE = re.compile(r"(?:table|tbl\.?)\s*\d+", re.IGNORECASE)
_SCIENTIFIC_RE = re.compile(
    r"±|\\pm|p[\s\-]?value|σ|\\sigma|\bCI\b|\bSE\b|\bSD\b|"
    r"\bdf\b|\bχ²|chi[\s-]?square|\bt[\s\-]?test|\bANOVA\b",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"\b(?:kg|km|cm|mm|nm|μm|Hz|kHz|MHz|GHz|"
    r"mol|mL|mg|μg|°C|°F|Pa|kPa|MPa|m/s|m²|m³|"
    r"J|kJ|W|kW|eV|MeV|GeV)\b",
    re.IGNORECASE,
)
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")

# Malformed: lines with pipes but no proper separator
_PIPE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class _ParsedTable:
    headers: List[str]
    rows: List[List[str]]
    start_line: int
    end_line: int
    raw_text: str
    is_malformed: bool = False


# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class SemanticTableTransformPass(OptimizerPass):
    """Convert markdown tables into LLM-friendly structured text.

    Config params
    ~~~~~~~~~~~~~

    ========================== ============ ================================
    Param                      Default      Description
    ========================== ============ ================================
    mode                       ``"transform"``  ``"transform"`` / ``"keep"``
    min_rows                   ``1``        Min data rows to transform.
    max_columns                ``10``       Tables wider → kept as-is.
    preserve_scientific        ``True``     Protect scientific tables.
    repair_malformed           ``True``     Attempt to fix malformed tables.
    nested_multicolumn         ``True``     Use nested bullets for multi-col.
    ========================== ============ ================================
    """

    @property
    def name(self) -> str:
        return "semantic_table_transform"

    @property
    def description(self) -> str:
        return "Convert markdown tables into LLM-friendly structured text."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=36,
            params={
                "mode": "transform",
                "min_rows": 1,
                "max_columns": 10,
                "preserve_scientific": True,
                "repair_malformed": True,
                "nested_multicolumn": True,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError
        p = config.params
        mode = p.get("mode", "transform")
        if mode not in ("transform", "keep"):
            raise PassConfigError(
                self.name, f"mode must be 'transform' or 'keep', got {mode!r}",
            )

    # ── Main ──────────────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        mode = p.get("mode", "transform")

        if not ctx.content.strip():
            self._report(ctx, 0, 0, 0, 0)
            return ctx

        lines = ctx.content.split("\n")
        tables = self._find_tables(lines)

        # Also detect malformed tables
        if p.get("repair_malformed", True):
            malformed = self._find_malformed(lines, tables)
            tables.extend(malformed)
            # Sort by start_line
            tables.sort(key=lambda t: t.start_line)

        if not tables:
            self._report(ctx, 0, 0, 0, 0)
            return ctx

        preserve_sci = p.get("preserve_scientific", True)
        min_rows = p.get("min_rows", 1)
        max_cols = p.get("max_columns", 10)
        nested = p.get("nested_multicolumn", True)

        transformed = 0
        skipped = 0
        scientific_skipped = 0
        malformed_repaired = 0

        if mode == "keep":
            self._report(ctx, len(tables), 0, 0,
                         sum(1 for t in tables if t.is_malformed))
            return ctx

        # Process reverse to preserve indices
        for table in reversed(tables):
            if preserve_sci and self._is_scientific(table, lines):
                scientific_skipped += 1
                skipped += 1
                continue
            if len(table.rows) < min_rows:
                skipped += 1
                continue
            if len(table.headers) > max_cols:
                skipped += 1
                continue

            if table.is_malformed:
                malformed_repaired += 1

            # Transform
            if len(table.headers) == 2:
                structured = self._transform_kv(table)
            elif nested:
                structured = self._transform_nested(table)
            else:
                structured = self._transform_flat(table)

            compact_lines = structured.split("\n")
            lines[table.start_line:table.end_line] = compact_lines
            transformed += 1

        ctx.content = "\n".join(lines)
        ctx.content = _EXCESS_BLANK_RE.sub("\n\n", ctx.content).strip()

        self._report(ctx, len(tables), transformed, scientific_skipped,
                     malformed_repaired)
        return ctx

    # ── Table detection ───────────────────────────────────────────────────

    @staticmethod
    def _find_tables(lines: List[str]) -> List[_ParsedTable]:
        tables: List[_ParsedTable] = []
        i = 0
        n = len(lines)

        while i < n:
            if i + 2 >= n:
                i += 1
                continue

            header_m = _TABLE_ROW_RE.match(lines[i])
            if not header_m:
                i += 1
                continue

            sep_m = _TABLE_ROW_RE.match(lines[i + 1])
            if not sep_m:
                i += 1
                continue

            sep_cells = [c.strip() for c in sep_m.group(1).split("|")]
            if not all(_SEPARATOR_CELL_RE.match(c) for c in sep_cells if c):
                i += 1
                continue

            headers = [c.strip() for c in header_m.group(1).split("|")]
            headers = [h for h in headers if h]

            rows: List[List[str]] = []
            j = i + 2
            while j < n:
                row_m = _TABLE_ROW_RE.match(lines[j])
                if not row_m:
                    break
                cells = [c.strip() for c in row_m.group(1).split("|")]
                cells = [c for c in cells if c or len(cells) > len(headers)]
                if cells:
                    # Pad/trim
                    while len(cells) < len(headers):
                        cells.append("")
                    rows.append(cells[:len(headers)])
                j += 1

            if rows:
                raw = "\n".join(lines[i:j])
                tables.append(_ParsedTable(
                    headers=headers, rows=rows,
                    start_line=i, end_line=j,
                    raw_text=raw, is_malformed=False,
                ))
                i = j
            else:
                i += 1

        return tables

    # ── Malformed table detection ─────────────────────────────────────────

    @staticmethod
    def _find_malformed(
        lines: List[str],
        valid_tables: List[_ParsedTable],
    ) -> List[_ParsedTable]:
        """Detect pipe-delimited lines not part of valid tables."""
        # Build set of lines already in valid tables
        valid_lines = set()
        for t in valid_tables:
            for ln in range(t.start_line, t.end_line):
                valid_lines.add(ln)

        malformed: List[_ParsedTable] = []
        i = 0
        n = len(lines)

        while i < n:
            if i in valid_lines or not _PIPE_LINE_RE.match(lines[i]):
                i += 1
                continue

            # Collect consecutive pipe lines
            j = i
            while j < n and _PIPE_LINE_RE.match(lines[j]) and j not in valid_lines:
                j += 1

            if j - i >= 2:  # at least 2 rows
                pipe_lines = lines[i:j]
                # Try to parse: first line = headers, skip separator-like lines
                all_rows: List[List[str]] = []
                for ln in pipe_lines:
                    m = _TABLE_ROW_RE.match(ln)
                    if m:
                        cells = [c.strip() for c in m.group(1).split("|")]
                        cells = [c for c in cells if c]
                        # Skip separator rows
                        if cells and all(_SEPARATOR_CELL_RE.match(c) for c in cells):
                            continue
                        all_rows.append(cells)

                if len(all_rows) >= 2:
                    headers = all_rows[0]
                    data_rows = all_rows[1:]
                    # Normalize column count
                    max_cols = max(len(r) for r in [headers] + data_rows)
                    headers = (headers + [""] * max_cols)[:max_cols]
                    norm_rows = [(r + [""] * max_cols)[:max_cols] for r in data_rows]

                    malformed.append(_ParsedTable(
                        headers=headers, rows=norm_rows,
                        start_line=i, end_line=j,
                        raw_text="\n".join(pipe_lines),
                        is_malformed=True,
                    ))

            i = j if j > i else i + 1

        return malformed

    # ── Scientific guard ──────────────────────────────────────────────────

    @staticmethod
    def _is_scientific(table: _ParsedTable, doc_lines: List[str]) -> bool:
        if _SCIENTIFIC_RE.search(table.raw_text):
            return True
        if _UNIT_RE.search(" ".join(table.headers)):
            return True
        look = table.start_line - 1
        while look >= 0 and not doc_lines[look].strip():
            look -= 1
        if look >= 0 and _CAPTION_RE.search(doc_lines[look]):
            return True
        return False

    # ── Transform: 2-col key-value ────────────────────────────────────────

    @staticmethod
    def _transform_kv(table: _ParsedTable) -> str:
        """2-col → ``Header:\\n- Key: Value`` format."""
        # Use first header as category label
        label = table.headers[0]
        if table.headers[1]:
            label = f"{table.headers[0]} ({table.headers[1]})"

        lines = [f"{label}:"]
        for row in table.rows:
            key = row[0] if len(row) > 0 else ""
            val = row[1] if len(row) > 1 else ""
            lines.append(f"- {key}: {val}")
        return "\n".join(lines)

    # ── Transform: multi-col nested bullets ───────────────────────────────

    @staticmethod
    def _transform_nested(table: _ParsedTable) -> str:
        """Multi-col → nested bullet format.

        Example::

            Planets:
            - Earth:
              - Period: 365d
              - Mass: 1.0
        """
        label = table.headers[0]
        lines = [f"{label}:"]

        for row in table.rows:
            key = row[0] if row else ""
            lines.append(f"- {key}:")
            for col_idx in range(1, len(table.headers)):
                header = table.headers[col_idx]
                val = row[col_idx] if col_idx < len(row) else ""
                lines.append(f"  - {header}: {val}")

        return "\n".join(lines)

    # ── Transform: multi-col flat ─────────────────────────────────────────

    @staticmethod
    def _transform_flat(table: _ParsedTable) -> str:
        """Multi-col → flat single-line per row.

        Example::

            Planets:
            - Earth: Period=365d, Mass=1.0
        """
        label = table.headers[0]
        lines = [f"{label}:"]

        for row in table.rows:
            key = row[0] if row else ""
            pairs = []
            for col_idx in range(1, len(table.headers)):
                header = table.headers[col_idx]
                val = row[col_idx] if col_idx < len(row) else ""
                pairs.append(f"{header}={val}")
            lines.append(f"- {key}: {', '.join(pairs)}")

        return "\n".join(lines)

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(
        self,
        ctx: OptimizationContext,
        found: int,
        transformed: int,
        scientific_skipped: int,
        malformed_repaired: int,
    ) -> None:
        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "tables_found": found,
            "tables_transformed": transformed,
            "scientific_preserved": scientific_skipped,
            "malformed_repaired": malformed_repaired,
        }

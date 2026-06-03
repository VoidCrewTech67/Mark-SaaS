"""
optimizer/passes/table_compression.py – Compress markdown tables.

Algorithm
=========

1. **Table detection** — Scan for consecutive pipe-delimited lines
   with a separator row (``| --- | --- |``).

2. **Scientific guard** — Tables with statistical notation (±, p-value,
   CI, SE), unit-bearing headers, or preceding captions (``Table N``)
   are preserved unchanged.

3. **Compression** — Two formats based on column count:

   - **2-column (key-value)**::

       StateProbability:
       S1=0.5
       S2=0.5

   - **Multi-column (pipe-delimited)**::

       Name|Score|Rank:
       Alice|95|1
       Bob|88|2

4. **Fallback** — Tables exceeding ``max_columns`` or failing parse
   are left as-is.
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
    r"±|\\pm|p[\s\-]?value|σ|\\sigma|"
    r"\bCI\b|\bSE\b|\bSD\b|"
    r"\bdf\b|\bχ²|chi[\s-]?square|"
    r"\bt[\s\-]?test|\bANOVA\b|\bF[\s\-]?stat",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"\b(?:kg|km|cm|mm|nm|μm|Hz|kHz|MHz|GHz|"
    r"mol|mL|mg|μg|°C|°F|Pa|kPa|MPa|"
    r"m/s|m²|m³|J|kJ|W|kW|eV|MeV|GeV)\b",
    re.IGNORECASE,
)
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class _ParsedTable:
    """A markdown table parsed from the document."""
    headers: List[str]
    rows: List[List[str]]
    start_line: int       # inclusive
    end_line: int         # exclusive
    raw_text: str         # original text for fallback


# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class TableCompressionPass(OptimizerPass):
    """Compress markdown tables into compact representations.

    Config params
    ~~~~~~~~~~~~~

    ======================== ================== ================================
    Param                    Default            Description
    ======================== ================== ================================
    mode                     ``"compress"``     ``"compress"`` / ``"keep"``
    min_rows                 ``2``              Min data rows to compress.
    max_columns              ``10``             Tables wider → kept as-is.
    preserve_scientific      ``True``           Protect scientific tables.
    kv_separator             ``"="``            Separator for 2-col kv format.
    col_separator            ``"|"``            Separator for multi-col format.
    ======================== ================== ================================
    """

    @property
    def name(self) -> str:
        return "table_compression"

    @property
    def description(self) -> str:
        return "Compress markdown tables into compact text representations."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=35,
            params={
                "mode": "compress",
                "min_rows": 2,
                "max_columns": 10,
                "preserve_scientific": True,
                "kv_separator": "=",
                "col_separator": "|",
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError

        p = config.params
        mode = p.get("mode", "compress")
        if mode not in ("compress", "keep"):
            raise PassConfigError(
                self.name,
                f"mode must be 'compress' or 'keep', got {mode!r}",
            )
        mr = p.get("min_rows", 2)
        if not isinstance(mr, int) or mr < 1:
            raise PassConfigError(
                self.name,
                f"min_rows must be positive int, got {mr!r}",
            )
        mc = p.get("max_columns", 10)
        if not isinstance(mc, int) or mc < 1:
            raise PassConfigError(
                self.name,
                f"max_columns must be positive int, got {mc!r}",
            )

    # ── Main ──────────────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        mode: str = p.get("mode", "compress")

        if not ctx.content.strip():
            self._report(ctx, [], 0, 0, mode)
            return ctx

        lines = ctx.content.split("\n")
        tables = self._find_tables(lines)

        if not tables:
            self._report(ctx, [], 0, 0, mode)
            return ctx

        preserve_sci: bool = p.get("preserve_scientific", True)
        min_rows: int = p.get("min_rows", 2)
        max_cols: int = p.get("max_columns", 10)
        kv_sep: str = p.get("kv_separator", "=")
        col_sep: str = p.get("col_separator", "|")

        compressed = 0
        skipped = 0
        scientific_skipped = 0

        if mode == "keep":
            for t in tables:
                if preserve_sci and self._is_scientific(t, lines):
                    scientific_skipped += 1
                    skipped += 1
                elif len(t.rows) < min_rows or len(t.headers) > max_cols:
                    skipped += 1
            self._report(ctx, tables, 0, skipped, mode,
                         scientific_skipped=scientific_skipped)
            return ctx

        # Process in reverse to preserve line indices
        for table in reversed(tables):
            # Guard: scientific table (check first so small scientific tables kept)
            if preserve_sci and self._is_scientific(table, lines):
                scientific_skipped += 1
                skipped += 1
                continue
            # Guard: too few rows
            if len(table.rows) < min_rows:
                skipped += 1
                continue
            # Guard: too many columns
            if len(table.headers) > max_cols:
                skipped += 1
                continue

            # Compress
            if len(table.headers) == 2:
                compact = self._compress_kv(table, kv_sep)
            else:
                compact = self._compress_multi(table, col_sep)

            # Replace in lines
            compact_lines = compact.split("\n")
            lines[table.start_line: table.end_line] = compact_lines
            compressed += 1

        ctx.content = "\n".join(lines)
        ctx.content = _EXCESS_BLANK_RE.sub("\n\n", ctx.content).strip()

        self._report(ctx, tables, compressed, skipped, mode,
                     scientific_skipped=scientific_skipped)
        return ctx

    # ── Table detection ───────────────────────────────────────────────────

    @staticmethod
    def _find_tables(lines: List[str]) -> List[_ParsedTable]:
        """Find all markdown tables in *lines*."""
        tables: List[_ParsedTable] = []
        i = 0
        n = len(lines)

        while i < n:
            # Need at least 3 lines: header, separator, 1 data row
            if i + 2 >= n:
                i += 1
                continue

            header_m = _TABLE_ROW_RE.match(lines[i])
            if not header_m:
                i += 1
                continue

            # Check separator
            sep_m = _TABLE_ROW_RE.match(lines[i + 1])
            if not sep_m:
                i += 1
                continue

            sep_cells = [c.strip() for c in sep_m.group(1).split("|")]
            if not all(_SEPARATOR_CELL_RE.match(c) for c in sep_cells if c):
                i += 1
                continue

            # Parse header
            headers = [c.strip() for c in header_m.group(1).split("|")]
            headers = [h for h in headers if h]  # drop empty from leading/trailing |

            # Collect data rows
            rows: List[List[str]] = []
            j = i + 2
            while j < n:
                row_m = _TABLE_ROW_RE.match(lines[j])
                if not row_m:
                    break
                cells = [c.strip() for c in row_m.group(1).split("|")]
                cells = [c for c in cells if c or len(cells) > len(headers)]
                # Pad/trim to header count
                if cells:
                    rows.append(cells[:len(headers)])
                j += 1

            if rows:
                raw = "\n".join(lines[i:j])
                tables.append(_ParsedTable(
                    headers=headers,
                    rows=rows,
                    start_line=i,
                    end_line=j,
                    raw_text=raw,
                ))
                i = j
            else:
                i += 1

        return tables

    # ── Scientific detection ──────────────────────────────────────────────

    @staticmethod
    def _is_scientific(table: _ParsedTable, doc_lines: List[str]) -> bool:
        """Heuristic: is this a scientific/statistical table?"""
        full_text = table.raw_text

        # Check for statistical notation in cells
        if _SCIENTIFIC_RE.search(full_text):
            return True

        # Check for units in headers
        header_text = " ".join(table.headers)
        if _UNIT_RE.search(header_text):
            return True

        # Check preceding lines for caption "Table N" (skip blanks)
        look = table.start_line - 1
        while look >= 0 and not doc_lines[look].strip():
            look -= 1
        if look >= 0:
            prev = doc_lines[look].strip()
            if _CAPTION_RE.search(prev):
                return True

        return False

    # ── Compression formats ───────────────────────────────────────────────

    @staticmethod
    def _compress_kv(
        table: _ParsedTable,
        sep: str = "=",
    ) -> str:
        """2-column → key=value format."""
        header_label = "".join(table.headers) + ":"
        lines = [header_label]
        for row in table.rows:
            key = row[0] if len(row) > 0 else ""
            val = row[1] if len(row) > 1 else ""
            lines.append(f"{key}{sep}{val}")
        return "\n".join(lines)

    @staticmethod
    def _compress_multi(
        table: _ParsedTable,
        sep: str = "|",
    ) -> str:
        """Multi-column → pipe-delimited compact format."""
        header_label = sep.join(table.headers) + ":"
        lines = [header_label]
        for row in table.rows:
            lines.append(sep.join(row))
        return "\n".join(lines)

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(
        self,
        ctx: OptimizationContext,
        tables: List[_ParsedTable],
        compressed: int,
        skipped: int,
        mode: str,
        scientific_skipped: int = 0,
    ) -> None:
        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "mode": mode,
            "tables_found": len(tables),
            "tables_compressed": compressed,
            "tables_skipped": skipped,
            "scientific_tables_preserved": scientific_skipped,
        }

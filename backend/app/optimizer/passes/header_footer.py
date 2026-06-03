"""
optimizer/passes/header_footer.py – Detect and remove repeated headers/footers.

Algorithm
=========

Multi-page PDFs converted to Markdown frequently carry repeated text at
the top (headers) and bottom (footers) of every page — journal names,
conference titles, confidentiality notices, page decorations, etc.
These waste tokens and confuse LLMs.

Detection proceeds in six phases:

1. **Page splitting** — The document is divided into logical pages using
   configurable delimiters (horizontal rules ``---``, ``***``, ``___``,
   or form-feeds ``\\f``).

2. **Zone extraction** — For each page, the first *N* non-empty lines
   form the *header zone* and the last *M* non-empty lines form the
   *footer zone*.  Lines in the middle of a page are never candidates.

3. **Fingerprinting** — Each candidate line is normalised into a
   *fingerprint*: NFKC Unicode normalisation, lowercased, whitespace
   collapsed, and embedded page-number patterns stripped.  This allows
   "Journal of CS — 1" and "Journal of CS — 42" to share the same
   fingerprint.

4. **Fuzzy grouping** (optional) — Similar fingerprints are merged using
   ``difflib.SequenceMatcher`` so that OCR variants like "lnternational"
   and "International" are treated as the same pattern.

5. **Frequency thresholding** — A fingerprint is marked for removal only
   if it appears in ≥ *min_frequency_ratio* of all pages.

6. **Safety guards** — Markdown headings (``#``), lines exceeding a
   maximum length, and lines below a minimum length are preserved by
   default.  This prevents legitimate section headings from being
   stripped.

After removal the pass performs a light cleanup (collapse runs of 3+
blank lines) and reports detailed statistics.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Internal data structures ──────────────────────────────────────────────────


@dataclass
class _Page:
    """Internal representation of a detected page."""
    index: int
    start_line: int   # inclusive index into the original lines list
    end_line: int     # exclusive


@dataclass
class _FreqEntry:
    """Frequency table entry for a single fingerprint."""
    pages: Set[int] = field(default_factory=set)
    line_indices: Set[int] = field(default_factory=set)
    example: str = ""
    zone: str = ""          # "header", "footer", or "both"
    member_fingerprints: Set[str] = field(default_factory=set)


# ── Compiled patterns (module-level for performance) ──────────────────────────

# Default page delimiter: horizontal rules (3+ of -, *, or _)
_DEFAULT_DELIMITER_RE = re.compile(r"^\s*[-*_]{3,}\s*$")

# Embedded page-number patterns stripped during fingerprinting
_PAGE_NUM_TRAILING_DASH = re.compile(r"\s*[-–—]\s*\d+\s*$")
_PAGE_NUM_TRAILING_PIPE = re.compile(r"\s*\|\s*\d+\s*$")
_PAGE_NUM_EMBEDDED = re.compile(r"\bpage\s+\d+(\s+of\s+\d+)?\b", re.IGNORECASE)
_PAGE_NUM_STANDALONE = re.compile(r"^\s*\d+\s*$")

# Markdown heading detector
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")

# Excess blank lines (3+ consecutive newlines → 2)
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")


# ── Pass implementation ──────────────────────────────────────────────────────


@register_pass
class HeaderFooterDetectionPass(OptimizerPass):
    """Detect and remove repeated page headers and footers.

    This pass is frequency-based and page-aware: it only examines the
    first/last *N* lines of each logical page and only removes text that
    appears on a configurable fraction of all pages.

    Config params
    ~~~~~~~~~~~~~

    ==================== ===== ================================================
    Param                Default Description
    ==================== ===== ================================================
    min_frequency_ratio  0.5   Min fraction of pages a line must appear on.
    header_zone_lines    5     Lines from the top of each page to examine.
    footer_zone_lines    5     Lines from the bottom of each page to examine.
    min_pages            3     Skip detection if fewer pages exist.
    max_line_length      200   Lines longer than this are never removed.
    min_line_length      2     Lines shorter than this (stripped) are ignored.
    page_delimiter       None  Regex string for page delimiters. ``None`` uses
                               the built-in ``^\\s*[-*_]{3,}\\s*$`` pattern.
    preserve_md_headings True  Never remove lines starting with ``#``.
    fuzzy_matching       True  Group similar fingerprints via SequenceMatcher.
    fuzzy_threshold      0.85  Minimum similarity ratio for fuzzy grouping.
    ==================== ===== ================================================
    """

    # ── OptimizerPass interface ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "header_footer_detection"

    @property
    def description(self) -> str:
        return (
            "Detect and remove repeated page headers and footers "
            "using frequency-based, page-aware analysis."
        )

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=15,  # run early — before deduplication passes
            params={
                "min_frequency_ratio": 0.5,
                "header_zone_lines": 5,
                "footer_zone_lines": 5,
                "min_pages": 3,
                "max_line_length": 200,
                "min_line_length": 2,
                "page_delimiter": None,
                "preserve_md_headings": True,
                "fuzzy_matching": True,
                "fuzzy_threshold": 0.85,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError

        p = config.params
        ratio = p.get("min_frequency_ratio", 0.5)
        if not (0.0 < ratio <= 1.0):
            raise PassConfigError(
                self.name,
                f"min_frequency_ratio must be in (0, 1], got {ratio}",
            )
        for key in ("header_zone_lines", "footer_zone_lines", "min_pages"):
            val = p.get(key, 1)
            if not isinstance(val, int) or val < 1:
                raise PassConfigError(
                    self.name,
                    f"{key} must be a positive integer, got {val!r}",
                )
        threshold = p.get("fuzzy_threshold", 0.85)
        if not (0.0 < threshold <= 1.0):
            raise PassConfigError(
                self.name,
                f"fuzzy_threshold must be in (0, 1], got {threshold}",
            )

    # ── Main execution ────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        min_pages: int = p.get("min_pages", 3)

        original_lines = ctx.content.splitlines(keepends=True)
        # Stripped copies for comparison (no trailing newline)
        stripped = [l.rstrip("\n\r") for l in original_lines]

        # ── Phase 1: Page splitting ───────────────────────────────────────
        pages = self._detect_pages(stripped, p)
        n_pages = len(pages)

        if n_pages < min_pages:
            self._report_skip(ctx, n_pages, min_pages)
            return ctx

        # ── Phase 2: Zone extraction ──────────────────────────────────────
        header_candidates, footer_candidates = self._extract_zone_candidates(
            pages, stripped, p,
        )

        # ── Phase 3 & 4: Frequency table + fuzzy grouping ────────────────
        header_freq = self._build_frequency_table(header_candidates, stripped)
        footer_freq = self._build_frequency_table(footer_candidates, stripped)

        if p.get("fuzzy_matching", True):
            threshold = p.get("fuzzy_threshold", 0.85)
            header_freq = self._group_similar(header_freq, threshold)
            footer_freq = self._group_similar(footer_freq, threshold)

        # ── Phase 5 & 6: Thresholding + safety ────────────────────────────
        lines_to_remove: Set[int] = set()
        detected_patterns: List[Dict[str, Any]] = []

        for zone_label, freq_table in [("header", header_freq), ("footer", footer_freq)]:
            removals, patterns = self._apply_threshold(
                freq_table, n_pages, stripped, zone_label, p,
            )
            lines_to_remove.update(removals)
            detected_patterns.extend(patterns)

        if not lines_to_remove:
            self._report_metrics(ctx, n_pages, detected_patterns, 0)
            return ctx

        # ── Removal and cleanup ───────────────────────────────────────────
        result_lines = [
            line for i, line in enumerate(original_lines)
            if i not in lines_to_remove
        ]
        content = "".join(result_lines)
        content = _EXCESS_BLANK_RE.sub("\n\n", content)
        ctx.content = content.strip()

        self._report_metrics(ctx, n_pages, detected_patterns, len(lines_to_remove))
        return ctx

    # ── Phase 1: Page detection ───────────────────────────────────────────

    def _detect_pages(
        self,
        lines: List[str],
        params: Dict[str, Any],
    ) -> List[_Page]:
        """Split the document into logical pages at delimiter boundaries."""
        custom_delim = params.get("page_delimiter")
        if custom_delim:
            delim_re = re.compile(custom_delim)
        else:
            delim_re = _DEFAULT_DELIMITER_RE

        pages: List[_Page] = []
        current_start = 0

        for i, line in enumerate(lines):
            is_delim = bool(delim_re.match(line)) or line.strip() == "\f"
            if is_delim:
                if self._has_content(lines, current_start, i):
                    pages.append(_Page(
                        index=len(pages),
                        start_line=current_start,
                        end_line=i,
                    ))
                current_start = i + 1

        # Trailing content after last delimiter
        if current_start < len(lines) and self._has_content(lines, current_start, len(lines)):
            pages.append(_Page(
                index=len(pages),
                start_line=current_start,
                end_line=len(lines),
            ))

        return pages

    @staticmethod
    def _has_content(lines: List[str], start: int, end: int) -> bool:
        """Return True if any line in [start, end) has non-whitespace."""
        return any(lines[i].strip() for i in range(start, end))

    # ── Phase 2: Zone extraction ──────────────────────────────────────────

    def _extract_zone_candidates(
        self,
        pages: List[_Page],
        lines: List[str],
        params: Dict[str, Any],
    ) -> Tuple[
        Dict[int, List[int]],  # header: page_idx → [line_indices]
        Dict[int, List[int]],  # footer: page_idx → [line_indices]
    ]:
        """Extract line indices from header and footer zones of each page."""
        header_n: int = params.get("header_zone_lines", 5)
        footer_n: int = params.get("footer_zone_lines", 5)

        header_candidates: Dict[int, List[int]] = {}
        footer_candidates: Dict[int, List[int]] = {}

        for page in pages:
            non_empty = [
                i for i in range(page.start_line, page.end_line)
                if lines[i].strip()
            ]
            if not non_empty:
                continue

            header_candidates[page.index] = non_empty[:header_n]
            footer_candidates[page.index] = non_empty[-footer_n:]

        return header_candidates, footer_candidates

    # ── Phase 3: Frequency table ──────────────────────────────────────────

    def _build_frequency_table(
        self,
        zone_candidates: Dict[int, List[int]],
        lines: List[str],
    ) -> Dict[str, _FreqEntry]:
        """Build a frequency table mapping fingerprints to page sets."""
        freq: Dict[str, _FreqEntry] = defaultdict(
            lambda: _FreqEntry()
        )

        for page_idx, line_indices in zone_candidates.items():
            seen_on_page: Set[str] = set()  # avoid double-counting within a page
            for line_idx in line_indices:
                fp = self._fingerprint(lines[line_idx])
                if not fp:
                    continue
                if fp not in seen_on_page:
                    freq[fp].pages.add(page_idx)
                    seen_on_page.add(fp)
                freq[fp].line_indices.add(line_idx)
                if not freq[fp].example:
                    freq[fp].example = lines[line_idx].strip()

        return dict(freq)

    # ── Phase 3a: Fingerprinting ──────────────────────────────────────────

    @staticmethod
    def _fingerprint(line: str) -> str:
        """Normalise a line into a comparable fingerprint.

        Handles:
        - Unicode normalisation (NFKC): ligatures, lookalike chars
        - Case folding
        - Whitespace collapse
        - Embedded page-number patterns (``Title - 42``, ``Page 3 of 10``)
        """
        text = line.strip()
        if not text:
            return ""

        # Standalone page numbers → skip entirely (not useful as fingerprint)
        if _PAGE_NUM_STANDALONE.match(text):
            return ""

        text = unicodedata.normalize("NFKC", text)
        text = text.lower()
        text = re.sub(r"\s+", " ", text)

        # Strip embedded page numbers so "Title – 1" ≡ "Title – 42"
        text = _PAGE_NUM_TRAILING_DASH.sub("", text)
        text = _PAGE_NUM_TRAILING_PIPE.sub("", text)
        text = _PAGE_NUM_EMBEDDED.sub("", text)

        # Clean up residual whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ── Phase 4: Fuzzy grouping ───────────────────────────────────────────

    @staticmethod
    def _group_similar(
        freq: Dict[str, _FreqEntry],
        threshold: float,
    ) -> Dict[str, _FreqEntry]:
        """Merge fingerprints with SequenceMatcher ratio ≥ threshold.

        Groups are represented by the longest member (the "representative").
        This handles OCR noise like ``lnternational`` vs ``International``.
        """
        if not freq or threshold >= 1.0:
            return freq

        # Sort by length descending so the longest (most complete) string
        # becomes the group representative.
        sorted_fps = sorted(freq.keys(), key=len, reverse=True)

        groups: List[Tuple[str, _FreqEntry]] = []

        for fp in sorted_fps:
            entry = freq[fp]
            merged = False

            for _, group_entry in groups:
                # Compare against all members of the group
                for member_fp in group_entry.member_fingerprints:
                    ratio = SequenceMatcher(None, fp, member_fp).ratio()
                    if ratio >= threshold:
                        # Merge into this group
                        group_entry.pages.update(entry.pages)
                        group_entry.line_indices.update(entry.line_indices)
                        group_entry.member_fingerprints.add(fp)
                        if not group_entry.example and entry.example:
                            group_entry.example = entry.example
                        merged = True
                        break
                if merged:
                    break

            if not merged:
                new_entry = _FreqEntry(
                    pages=set(entry.pages),
                    line_indices=set(entry.line_indices),
                    example=entry.example,
                    member_fingerprints={fp},
                )
                groups.append((fp, new_entry))

        return {rep: entry for rep, entry in groups}

    # ── Phase 5: Thresholding and safety ──────────────────────────────────

    def _apply_threshold(
        self,
        freq: Dict[str, _FreqEntry],
        n_pages: int,
        lines: List[str],
        zone_label: str,
        params: Dict[str, Any],
    ) -> Tuple[Set[int], List[Dict[str, Any]]]:
        """Select fingerprints that exceed the threshold, respecting guards."""
        min_ratio: float = params.get("min_frequency_ratio", 0.5)
        max_len: int = params.get("max_line_length", 200)
        min_len: int = params.get("min_line_length", 2)
        preserve_headings: bool = params.get("preserve_md_headings", True)

        removal_indices: Set[int] = set()
        detected: List[Dict[str, Any]] = []

        for fp, entry in freq.items():
            ratio = len(entry.pages) / n_pages
            if ratio < min_ratio:
                continue

            example = entry.example

            # Safety: line length guard
            if len(example) < min_len:
                continue
            if len(example) > max_len:
                continue

            # Safety: preserve markdown headings
            if preserve_headings and _MARKDOWN_HEADING_RE.match(example):
                continue

            removal_indices.update(entry.line_indices)
            detected.append({
                "pattern": fp,
                "example": example,
                "zone": zone_label,
                "frequency": len(entry.pages),
                "total_pages": n_pages,
                "frequency_ratio": round(ratio, 3),
                "lines_removed": len(entry.line_indices),
            })

        return removal_indices, detected

    # ── Metrics reporting ─────────────────────────────────────────────────

    def _report_metrics(
        self,
        ctx: OptimizationContext,
        n_pages: int,
        patterns: List[Dict[str, Any]],
        total_removed: int,
    ) -> None:
        """Store detailed metrics in ctx.metadata for the executor to pick up."""
        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "pages_detected": n_pages,
            "patterns_detected": len(patterns),
            "total_lines_removed": total_removed,
            "patterns": patterns,
        }

    def _report_skip(
        self,
        ctx: OptimizationContext,
        n_pages: int,
        min_pages: int,
    ) -> None:
        """Report a skip due to insufficient pages."""
        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "pages_detected": n_pages,
            "skipped": True,
            "skip_reason": (
                f"Need {min_pages}+ pages for header/footer detection, "
                f"found {n_pages}"
            ),
            "patterns_detected": 0,
            "total_lines_removed": 0,
            "patterns": [],
        }

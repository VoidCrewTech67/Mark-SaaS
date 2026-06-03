"""
optimizer/passes/reference_section.py – Detect and remove reference sections.

Algorithm
=========

Academic papers and technical documents converted from PDF to Markdown
typically include a **References** / **Bibliography** / **Works Cited**
section that is pure citation metadata.  These sections consume
significant token budget when sent to an LLM and rarely contribute to
comprehension of the document's arguments.

Detection proceeds in four phases:

1. **Heading detection** — Scan every line for reference-section
   headings.  Three heading styles are recognised:

   a. *ATX headings*: ``# References``, ``## Bibliography``, etc.
   b. *Setext headings*: ``References`` followed by ``===`` or ``---``
      on the next line.
   c. *OCR / plain-text headings*: ``REFERENCES`` as a standalone
      short line, optionally wrapped in bold markers (``**``).

   Matching is case-insensitive and tolerates trailing colons,
   whitespace, and Markdown bold/italic formatting.

2. **Section boundary** — Once a heading is found, the section extends
   until:

   a. The next Markdown heading at the *same level or higher*.
   b. A recognised *post-reference* section title (Appendix,
      Supplementary Materials, Author Contributions, …).
   c. The end of the document.

3. **Entry counting** — The number of individual reference entries is
   estimated by matching structured patterns (``[1]``, ``1.``, ``-``,
   ``•``, …) and falling back to paragraph counting when no structure
   is detected.

4. **Action** — Depending on the ``mode`` parameter the section is:

   - ``remove`` — deleted entirely.
   - ``summarize`` — replaced by a one-line placeholder such as
     ``[References removed: 42 entries]``.
   - ``keep`` — left untouched (metrics still reported).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Constants ─────────────────────────────────────────────────────────────────

_DEFAULT_SECTION_TITLES: List[str] = [
    "references",
    "bibliography",
    "works cited",
    "literature cited",
    "cited references",
    "references and notes",
    "notes and references",
    "bibliographic references",
    "cited works",
    "citations",
]

# Titles of sections that commonly appear *after* a reference section.
# Used for boundary detection when the reference heading is OCR/plain-text.
_POST_REFERENCE_TITLES: set[str] = {
    "appendix", "appendices",
    "appendix a", "appendix b", "appendix c", "appendix d",
    "supplementary", "supplemental",
    "supplementary material", "supplementary materials",
    "supplementary information", "supporting information",
    "about the authors", "author biographies", "biographical notes",
    "author contributions", "competing interests",
    "data availability", "code availability",
    "glossary", "index", "notes", "endnotes",
    "errata", "erratum", "corrigendum",
    "acknowledgments", "acknowledgements",
    "disclosure", "conflict of interest",
    "funding",
}


# ── Compiled patterns ────────────────────────────────────────────────────────

# ATX heading: #{1,6} then text
_ATX_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*(?:#+\s*)?$")

# Setext underlines
_SETEXT_H1_RE = re.compile(r"^={3,}\s*$")
_SETEXT_H2_RE = re.compile(r"^-{3,}\s*$")

# Markdown bold/italic wrapper
_MD_FORMAT_RE = re.compile(r"^[\s*_]*(.+?)[\s*_]*$")

# Structured reference entry patterns
_ENTRY_PATTERNS: List[re.Pattern[str]] = [
    re.compile(r"^\s*\[\d+\]"),          # [1] Author …
    re.compile(r"^\s*\d{1,4}\.\s"),      # 1. Author …
    re.compile(r"^\s*\d{1,4}\)\s"),      # 1) Author …
    re.compile(r"^\s*[-*•–—]\s"),        # - Author …  / • Author …
]

# Excess blank lines (3+ → 2)
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")


# ── Internal data structures ─────────────────────────────────────────────────

@dataclass
class _DetectedSection:
    """A reference section detected in the document."""
    heading_text: str       # original heading line (stripped)
    heading_level: int      # 1–6 for ATX/Setext, 0 for OCR plain-text
    start_line: int         # line index of the heading (inclusive)
    end_line: int           # line index of section end (exclusive)
    entry_count: int        # estimated number of reference entries
    content_lines: int      # total non-empty content lines (excl. heading)


# ── Pass implementation ──────────────────────────────────────────────────────

@register_pass
class ReferenceSectionRemovalPass(OptimizerPass):
    """Detect and remove or summarize reference / bibliography sections.

    Supports three modes via the ``mode`` config parameter:

    - ``remove``    — delete the entire section (default).
    - ``summarize`` — replace with a one-line placeholder showing the
      entry count.
    - ``keep``      — leave the section intact but still report metrics.

    Config params
    ~~~~~~~~~~~~~

    ==================== ================ =====================================
    Param                Default          Description
    ==================== ================ =====================================
    mode                 ``"remove"``     Action: ``"remove"``/``"summarize"``/
                                          ``"keep"``
    section_titles       *(see source)*   List of title strings to match.
    summary_template     ``"[References   Template for ``summarize`` mode.
                         removed: …"``    ``{count}`` is replaced by entry
                                          count.
    detect_ocr_headings  ``True``         Match plain-text headings (no ``#``).
    detect_setext        ``True``         Match setext-style (underline)
                                          headings.
    max_heading_length   ``50``           Ignore lines longer than this when
                                          detecting plain-text headings.
    ==================== ================ =====================================
    """

    # ── OptimizerPass interface ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "reference_section_removal"

    @property
    def description(self) -> str:
        return (
            "Detect and remove or summarize reference/bibliography "
            "sections in academic and technical documents."
        )

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=20,  # after header/footer detection (15)
            params={
                "mode": "remove",
                "section_titles": list(_DEFAULT_SECTION_TITLES),
                "summary_template": "[References removed: {count} entries]",
                "detect_ocr_headings": True,
                "detect_setext": True,
                "max_heading_length": 50,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError

        p = config.params
        mode = p.get("mode", "remove")
        if mode not in ("remove", "summarize", "keep"):
            raise PassConfigError(
                self.name,
                f"mode must be 'remove', 'summarize', or 'keep', got {mode!r}",
            )
        titles = p.get("section_titles", _DEFAULT_SECTION_TITLES)
        if not titles or not isinstance(titles, list):
            raise PassConfigError(
                self.name,
                "section_titles must be a non-empty list of strings",
            )
        max_len = p.get("max_heading_length", 50)
        if not isinstance(max_len, int) or max_len < 1:
            raise PassConfigError(
                self.name,
                f"max_heading_length must be a positive integer, got {max_len!r}",
            )

    # ── Main execution ────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        mode: str = p.get("mode", "remove")

        if not ctx.content.strip():
            self._report_metrics(ctx, sections=[], mode=mode)
            return ctx

        lines = ctx.content.splitlines(keepends=True)
        stripped = [l.rstrip("\n\r") for l in lines]

        titles_set = self._build_titles_set(p)

        # ── Phase 1 & 2: Find all reference sections ─────────────────────
        sections = self._find_all_sections(stripped, p, titles_set)

        if not sections:
            self._report_metrics(ctx, sections=[], mode=mode)
            return ctx

        if mode == "keep":
            self._report_metrics(ctx, sections=sections, mode=mode)
            return ctx

        # ── Phase 4: Apply action (remove / summarize) ────────────────────
        # Process sections in reverse order to preserve indices
        template: str = p.get(
            "summary_template",
            "[References removed: {count} entries]",
        )

        for section in reversed(sections):
            if mode == "summarize":
                replacement = template.format(count=section.entry_count)
                lines[section.start_line: section.end_line] = [
                    replacement + "\n",
                ]
            elif mode == "remove":
                del lines[section.start_line: section.end_line]

        content = "".join(lines)
        content = _EXCESS_BLANK_RE.sub("\n\n", content)
        ctx.content = content.strip()

        self._report_metrics(ctx, sections=sections, mode=mode)
        return ctx

    # ── Heading detection ─────────────────────────────────────────────────

    def _find_all_sections(
        self,
        lines: List[str],
        params: Dict[str, Any],
        titles_set: set[str],
    ) -> List[_DetectedSection]:
        """Scan for all reference-section headings and compute boundaries."""
        detect_ocr: bool = params.get("detect_ocr_headings", True)
        detect_setext: bool = params.get("detect_setext", True)
        max_heading_len: int = params.get("max_heading_length", 50)

        sections: List[_DetectedSection] = []
        skip_until = -1  # avoid detecting headings inside an already-found section

        for i, line in enumerate(lines):
            if i <= skip_until:
                continue

            result = self._detect_heading(
                lines, i, titles_set,
                detect_ocr=detect_ocr,
                detect_setext=detect_setext,
                max_heading_len=max_heading_len,
            )
            if result is None:
                continue

            heading_text, heading_level, heading_lines = result
            # heading_lines = number of lines the heading spans (1 for ATX/OCR, 2 for setext)

            # Find section end
            section_start = i
            content_start = i + heading_lines
            section_end = self._find_section_end(
                lines, content_start, heading_level, titles_set, max_heading_len,
            )

            # Count entries
            section_body = "\n".join(lines[content_start:section_end])
            entry_count = self._count_entries(section_body)
            content_line_count = sum(
                1 for l in lines[content_start:section_end] if l.strip()
            )

            sections.append(_DetectedSection(
                heading_text=heading_text,
                heading_level=heading_level,
                start_line=section_start,
                end_line=section_end,
                entry_count=entry_count,
                content_lines=content_line_count,
            ))

            skip_until = section_end - 1

        return sections

    def _detect_heading(
        self,
        lines: List[str],
        idx: int,
        titles_set: set[str],
        *,
        detect_ocr: bool,
        detect_setext: bool,
        max_heading_len: int,
    ) -> Optional[Tuple[str, int, int]]:
        """Check if line *idx* is a reference-section heading.

        Returns (heading_text, level, num_lines) or None.
        """
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            return None

        # 1. ATX heading: # References
        atx_m = _ATX_HEADING_RE.match(stripped)
        if atx_m:
            level = len(atx_m.group(1))
            title = self._clean_title(atx_m.group(2))
            if self._matches_title(title, titles_set):
                return (stripped, level, 1)

        # 2. Setext heading: References\n===
        if detect_setext and idx + 1 < len(lines):
            next_line = lines[idx + 1].strip()
            title = self._clean_title(stripped)
            if _SETEXT_H1_RE.match(next_line) and self._matches_title(title, titles_set):
                return (stripped, 1, 2)
            if _SETEXT_H2_RE.match(next_line) and self._matches_title(title, titles_set):
                return (stripped, 2, 2)

        # 3. OCR / plain-text heading
        if detect_ocr:
            title = self._clean_title(stripped)
            if (
                len(title) <= max_heading_len
                and self._matches_title(title, titles_set)
            ):
                # Heuristic: must look like a standalone heading
                # (not embedded in a sentence). Check it's not too long
                # and doesn't start with common reference-entry patterns.
                if not any(p.match(stripped) for p in _ENTRY_PATTERNS):
                    return (stripped, 0, 1)

        return None

    # ── Section boundary ──────────────────────────────────────────────────

    def _find_section_end(
        self,
        lines: List[str],
        content_start: int,
        heading_level: int,
        titles_set: set[str],
        max_heading_len: int,
    ) -> int:
        """Return the line index where the reference section ends (exclusive).

        The section ends at:
        1. The next ATX/setext heading at the same level or higher.
        2. A recognised post-reference section title (for OCR documents).
        3. End of document.
        """
        for i in range(content_start, len(lines)):
            stripped = lines[i].strip()
            if not stripped:
                continue

            # ATX heading at same level or higher?
            atx_m = _ATX_HEADING_RE.match(stripped)
            if atx_m:
                next_level = len(atx_m.group(1))
                if heading_level == 0:
                    # OCR heading: any markdown heading ends the section
                    return i
                if next_level <= heading_level:
                    return i

            # Setext heading on this line + next?
            if i + 1 < len(lines):
                next_stripped = lines[i + 1].strip()
                if _SETEXT_H1_RE.match(next_stripped):
                    return i
                if _SETEXT_H2_RE.match(next_stripped) and heading_level <= 2:
                    return i

            # OCR heading of a post-reference section?
            if heading_level == 0 and len(stripped) <= max_heading_len:
                clean = self._clean_title(stripped)
                normalised = clean.lower().strip()
                if normalised in _POST_REFERENCE_TITLES:
                    return i
                # Also check if it matches another reference title (second
                # reference section — unlikely but handle gracefully)

        return len(lines)

    # ── Entry counting ────────────────────────────────────────────────────

    @staticmethod
    def _count_entries(text: str) -> int:
        """Estimate the number of individual reference entries.

        Strategy:
        1. Try structured patterns (numbered, bulleted).  If any pattern
           matches ≥ 2 lines, use the highest-count pattern.
        2. Fall back to counting non-empty paragraph blocks.
        """
        if not text.strip():
            return 0

        raw_lines = text.strip().splitlines()

        # Count matches per pattern
        counts: List[int] = [0] * len(_ENTRY_PATTERNS)
        for raw_line in raw_lines:
            s = raw_line.strip()
            if not s:
                continue
            for j, pat in enumerate(_ENTRY_PATTERNS):
                if pat.match(s):
                    counts[j] += 1

        best = max(counts) if counts else 0
        if best >= 2:
            return best

        # Fallback: paragraph blocks
        paragraphs = re.split(r"\n\n+", text.strip())
        non_empty = [p for p in paragraphs if p.strip()]
        return len(non_empty) if non_empty else 0

    # ── Title matching helpers ────────────────────────────────────────────

    @staticmethod
    def _build_titles_set(params: Dict[str, Any]) -> set[str]:
        """Build a lowercase set of section titles from config."""
        titles = params.get("section_titles", _DEFAULT_SECTION_TITLES)
        return {t.lower().strip() for t in titles}

    @staticmethod
    def _clean_title(text: str) -> str:
        """Strip formatting markers from a potential heading.

        Removes: ``*``, ``_``, trailing ``:``, leading/trailing whitespace,
        and NFKC-normalises Unicode.
        """
        clean = unicodedata.normalize("NFKC", text.strip())
        # Remove bold / italic markers: ** __ * _
        clean = re.sub(r"\*{1,2}|_{1,2}", "", clean)
        # Remove trailing colon
        clean = re.sub(r":\s*$", "", clean)
        return clean.strip()

    @staticmethod
    def _matches_title(title: str, titles_set: set[str]) -> bool:
        """Check if *title* (already cleaned) matches a known section title."""
        return title.lower().strip() in titles_set

    # ── Metrics reporting ─────────────────────────────────────────────────

    def _report_metrics(
        self,
        ctx: OptimizationContext,
        sections: List[_DetectedSection],
        mode: str,
    ) -> None:
        """Store metrics in ctx.metadata for the executor to collect."""
        section_details = [
            {
                "heading": s.heading_text,
                "heading_level": s.heading_level,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "entry_count": s.entry_count,
                "content_lines": s.content_lines,
            }
            for s in sections
        ]
        total_lines = sum(s.end_line - s.start_line for s in sections)
        total_entries = sum(s.entry_count for s in sections)

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "mode": mode,
            "sections_found": len(sections),
            "total_entries": total_entries,
            "total_lines_affected": total_lines,
            "action_taken": mode if sections else "none",
            "sections": section_details,
        }

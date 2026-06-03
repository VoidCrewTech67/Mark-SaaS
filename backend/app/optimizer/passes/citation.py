"""
optimizer/passes/citation.py – Detect and remove inline citations.

Regex Strategy
==============

Two independent pattern families target different citation styles:

**Numeric bracket citations** — ``[1]``, ``[2,3]``, ``[12-15]``,
``[1,3-5,7]``::

    \\[  \\d+(?:\\s*[-–—]\\s*\\d+)?         # one item: number or range
    (?:\\s*[,;]\\s*                          # separator
       \\d+(?:\\s*[-–—]\\s*\\d+)?            # another item
    )*
    \\]

**Author-year parenthetical citations** — ``(Smith, 2020)``,
``(Smith et al., 2020; Jones & Lee, 2019)``::

    \\(
      (optional prefix: see | cf. | e.g., …)
      Author(s) ,  Year
      (optional suffix: , p. 42 | , pp. 10–20)
      (; Author(s) , Year …)*
    \\)

Safety
------

Before applying any replacement, every candidate match is checked
against **protected zones** — character ranges that must not be
modified:

=========================  =======================================
Zone                       Example
=========================  =======================================
Fenced code blocks         `````  code  `````
Inline code                ``` `code` ```
Display math               ``$$ … $$``, ``\\[ … \\]``
Inline math                ``$ … $``, ``\\( … \\)``
Markdown links             ``[text](url)``, ``![alt](url)``
Reference-style links      ``[text][ref]``
Footnote markers           ``[^1]``
Link definitions           ``[1]: http://…``
=========================  =======================================

After replacement, a lightweight cleanup pass collapses double spaces
and removes orphaned space-before-punctuation artefacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Citation regex patterns (module-level, compiled once) ─────────────────────

# Numeric bracket citations: [1], [2,3], [1-5], [1,3-5,7]
_NUM_ITEM = r"\d+(?:\s*[-\u2013\u2014]\s*\d+)?"
_NUMERIC_CITE_RE = re.compile(
    r"\[" + _NUM_ITEM + r"(?:\s*[,;]\s*" + _NUM_ITEM + r")*\]"
)

# Author-year parenthetical citations -----------------------------------------
# Author surname: capitalised, may contain hyphens/apostrophes
_AUTHOR = r"[A-Z][a-zA-Z\u2019'\-]+"
_ET_AL = r"\s+et\s+al\.?"
_YEAR = r"(?:19|20)\d{2}[a-z]?"

# Author group: Name [et al.] [and/& Name [et al.]]
_AUTHOR_GROUP = (
    _AUTHOR + r"(?:" + _ET_AL + r")?"
    + r"(?:\s*(?:and|&)\s*" + _AUTHOR + r"(?:" + _ET_AL + r")?)*"
)

# Optional prefix words
_AY_PREFIX = r"(?:(?:see|cf\.|e\.g\.,?\s*|i\.e\.,?\s*|also|compare)\s+)?"

# Optional page/section suffix
_AY_SUFFIX = r"(?:,\s*(?:pp?\.\s*)?\d+(?:\s*[-\u2013]\s*\d+)?)?"

# Single author-year entry
_SINGLE_AY = _AY_PREFIX + _AUTHOR_GROUP + r",\s*" + _YEAR + _AY_SUFFIX

# Multiple entries separated by semicolons
_MULTI_AY = _SINGLE_AY + r"(?:\s*;\s*" + _SINGLE_AY + r")*"

_AUTHOR_YEAR_RE = re.compile(r"\(\s*" + _MULTI_AY + r"\s*\)")


# ── Protected zone patterns ──────────────────────────────────────────────────

_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_DISPLAY_MATH_DOLLAR_RE = re.compile(r"\$\$[\s\S]*?\$\$")
_INLINE_MATH_DOLLAR_RE = re.compile(
    r"(?<!\$)\$(?!\$)(?!\s)(.+?)(?<!\s)(?<!\$)\$(?!\$)"
)
_LATEX_DISPLAY_RE = re.compile(r"\\\[[\s\S]*?\\\]")
_LATEX_INLINE_RE = re.compile(r"\\\(.*?\\\)")
_MD_LINK_RE = re.compile(r"!?\[[^\]]*\]\([^)]*\)")
_MD_REF_LINK_RE = re.compile(r"\[[^\]]*[a-zA-Z][^\]]*\]\[[^\]]*\]")
_MD_FOOTNOTE_RE = re.compile(r"\[\^[^\]]+\]")
_MD_LINK_DEF_RE = re.compile(r"^\s*\[[^\]]+\]:.*$", re.MULTILINE)

# Post-replacement cleanup
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,;:!?])")


# ── Internal data structures ─────────────────────────────────────────────────

@dataclass
class _CitationMatch:
    """A single detected citation occurrence."""
    start: int
    end: int
    text: str
    citation_type: str  # "numeric" or "author_year"


# ── Pass implementation ──────────────────────────────────────────────────────

@register_pass
class CitationRemovalPass(OptimizerPass):
    """Detect and remove or replace inline citations.

    Handles two citation families:

    - **Numeric brackets**: ``[1]``, ``[2,3]``, ``[1-5]``, ``[1,3-5,7]``
    - **Author-year**: ``(Smith, 2020)``, ``(Smith et al., 2020)``

    Safety guards prevent accidental modification of equations, markdown
    links, footnotes, and code blocks.

    Config params
    ~~~~~~~~~~~~~

    ============================ ================== =========================
    Param                        Default            Description
    ============================ ================== =========================
    mode                         ``"remove"``       ``"remove"`` /
                                                    ``"replace_with_placeholder"``
                                                    / ``"keep"``
    placeholder                  ``"[citation]"``   Text used in
                                                    ``replace_with_placeholder``
                                                    mode.
    detect_numeric               ``True``           Match ``[N]``-style
                                                    citations.
    detect_author_year           ``True``           Match ``(Author, Year)``
                                                    citations.
    protect_markdown_links       ``True``           Shield ``[text](url)``
                                                    from modification.
    protect_equations            ``True``           Shield ``$ … $`` and
                                                    ``$$ … $$`` math.
    protect_code_blocks          ``True``           Shield fenced and inline
                                                    code.
    protect_footnotes            ``True``           Shield ``[^N]`` markers.
    merge_adjacent_placeholders  ``True``           Collapse consecutive
                                                    placeholders into one.
    ============================ ================== =========================
    """

    # ── OptimizerPass interface ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "citation_removal"

    @property
    def description(self) -> str:
        return (
            "Detect and remove or replace inline citations "
            "(numeric brackets and author-year parentheticals)."
        )

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=25,  # after reference_section_removal (20)
            params={
                "mode": "remove",
                "placeholder": "[citation]",
                "detect_numeric": True,
                "detect_author_year": True,
                "protect_markdown_links": True,
                "protect_equations": True,
                "protect_code_blocks": True,
                "protect_footnotes": True,
                "merge_adjacent_placeholders": True,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError

        p = config.params
        mode = p.get("mode", "remove")
        if mode not in ("remove", "replace_with_placeholder", "keep"):
            raise PassConfigError(
                self.name,
                f"mode must be 'remove', 'replace_with_placeholder', or "
                f"'keep', got {mode!r}",
            )
        placeholder = p.get("placeholder", "[citation]")
        if not isinstance(placeholder, str) or not placeholder:
            raise PassConfigError(
                self.name,
                "placeholder must be a non-empty string",
            )

    # ── Main execution ────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        mode: str = p.get("mode", "remove")
        placeholder: str = p.get("placeholder", "[citation]")

        content = ctx.content
        if not content.strip():
            self._report_metrics(ctx, [], [], 0, mode)
            return ctx

        # ── Step 1: Compute protected zones ───────────────────────────────
        zones = self._find_protected_zones(content, p)

        # ── Step 2: Find all citation candidates ──────────────────────────
        numeric_matches: List[_CitationMatch] = []
        author_year_matches: List[_CitationMatch] = []

        if p.get("detect_numeric", True):
            numeric_matches = self._find_numeric_citations(content)

        if p.get("detect_author_year", True):
            author_year_matches = self._find_author_year_citations(content)

        all_matches = numeric_matches + author_year_matches

        # ── Step 3: Filter out protected matches ─────────────────────────
        safe_matches = [
            m for m in all_matches
            if not self._in_protected_zone(m.start, m.end, zones)
        ]

        protected_count = len(all_matches) - len(safe_matches)

        if not safe_matches or mode == "keep":
            self._report_metrics(
                ctx, safe_matches, all_matches, protected_count, mode,
            )
            return ctx

        # ── Step 4: Apply replacements ────────────────────────────────────
        ctx.content = self._apply_replacements(
            content, safe_matches, mode, placeholder,
            merge=p.get("merge_adjacent_placeholders", True),
        )

        self._report_metrics(
            ctx, safe_matches, all_matches, protected_count, mode,
        )
        return ctx

    # ── Citation detection ────────────────────────────────────────────────

    @staticmethod
    def _find_numeric_citations(content: str) -> List[_CitationMatch]:
        """Find all numeric bracket citation candidates."""
        matches: List[_CitationMatch] = []
        for m in _NUMERIC_CITE_RE.finditer(content):
            matches.append(_CitationMatch(
                start=m.start(),
                end=m.end(),
                text=m.group(),
                citation_type="numeric",
            ))
        return matches

    @staticmethod
    def _find_author_year_citations(content: str) -> List[_CitationMatch]:
        """Find all author-year parenthetical citation candidates."""
        matches: List[_CitationMatch] = []
        for m in _AUTHOR_YEAR_RE.finditer(content):
            matches.append(_CitationMatch(
                start=m.start(),
                end=m.end(),
                text=m.group(),
                citation_type="author_year",
            ))
        return matches

    # ── Protected zones ───────────────────────────────────────────────────

    @staticmethod
    def _find_protected_zones(
        content: str,
        params: Dict[str, Any],
    ) -> List[Tuple[int, int]]:
        """Identify character ranges that must not be modified.

        The order of pattern matching matters: longer constructs (fenced
        code blocks, display math) are matched first so they subsume
        shorter ones (inline code, inline math).
        """
        zones: List[Tuple[int, int]] = []

        if params.get("protect_code_blocks", True):
            for m in _FENCED_CODE_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _INLINE_CODE_RE.finditer(content):
                zones.append((m.start(), m.end()))

        if params.get("protect_equations", True):
            for m in _DISPLAY_MATH_DOLLAR_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _INLINE_MATH_DOLLAR_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _LATEX_DISPLAY_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _LATEX_INLINE_RE.finditer(content):
                zones.append((m.start(), m.end()))

        if params.get("protect_markdown_links", True):
            for m in _MD_LINK_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _MD_REF_LINK_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _MD_LINK_DEF_RE.finditer(content):
                zones.append((m.start(), m.end()))

        if params.get("protect_footnotes", True):
            for m in _MD_FOOTNOTE_RE.finditer(content):
                zones.append((m.start(), m.end()))

        # Merge overlapping zones
        return _merge_zones(zones)

    @staticmethod
    def _in_protected_zone(
        start: int,
        end: int,
        zones: List[Tuple[int, int]],
    ) -> bool:
        """Check whether [start, end) overlaps any protected zone."""
        for z_start, z_end in zones:
            # Any overlap counts
            if start < z_end and end > z_start:
                return True
            if z_start >= end:
                break  # zones are sorted
        return False

    # ── Replacement application ───────────────────────────────────────────

    @staticmethod
    def _apply_replacements(
        content: str,
        matches: List[_CitationMatch],
        mode: str,
        placeholder: str,
        *,
        merge: bool = True,
    ) -> str:
        """Build the result string with citations removed or replaced."""
        # Sort by position and deduplicate / remove overlaps
        matches = sorted(matches, key=lambda m: m.start)
        deduped: List[_CitationMatch] = []
        last_end = -1
        for m in matches:
            if m.start >= last_end:
                deduped.append(m)
                last_end = m.end

        # Build result
        parts: List[str] = []
        cursor = 0
        for m in deduped:
            parts.append(content[cursor:m.start])
            if mode == "replace_with_placeholder":
                parts.append(placeholder)
            # mode == "remove": append nothing
            cursor = m.end
        parts.append(content[cursor:])

        result = "".join(parts)

        # Cleanup: collapse multiple spaces (not newlines)
        result = _MULTI_SPACE_RE.sub(" ", result)
        # Cleanup: remove orphaned space before punctuation
        result = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", result)

        # Merge adjacent placeholders: "[citation] [citation]" → "[citation]"
        if merge and mode == "replace_with_placeholder":
            escaped = re.escape(placeholder)
            result = re.sub(
                rf"({escaped}\s*)+{escaped}",
                placeholder,
                result,
            )

        return result

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report_metrics(
        self,
        ctx: OptimizationContext,
        safe_matches: List[_CitationMatch],
        all_matches: List[_CitationMatch],
        protected_count: int,
        mode: str,
    ) -> None:
        numeric = [m for m in safe_matches if m.citation_type == "numeric"]
        author_year = [m for m in safe_matches if m.citation_type == "author_year"]

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "mode": mode,
            "numeric_citations_found": len(numeric),
            "author_year_citations_found": len(author_year),
            "total_citations_found": len(safe_matches),
            "citations_in_protected_zones": protected_count,
            "citations_actioned": len(safe_matches) if mode != "keep" else 0,
            "examples": [
                {"text": m.text, "type": m.citation_type}
                for m in safe_matches[:20]  # cap at 20 examples
            ],
        }


# ── Module-level helpers ─────────────────────────────────────────────────────


def _merge_zones(zones: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Merge overlapping or adjacent intervals."""
    if not zones:
        return []
    sorted_zones = sorted(zones)
    merged = [list(sorted_zones[0])]
    for start, end in sorted_zones[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]

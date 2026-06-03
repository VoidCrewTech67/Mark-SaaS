"""
optimizer/passes/boilerplate_section.py – Detect and remove boilerplate sections.

Algorithm
=========

Academic papers and technical documents contain boilerplate sections —
Acknowledgements, Funding, Conflict of Interest, etc. — that consume
tokens without contributing to the document's intellectual content.

This pass identifies and removes (or summarizes) these sections using
the same heading detection strategy as ``ReferenceSectionRemovalPass``:

1. **Heading detection** — ATX (``# Funding``), setext
   (``Funding\\n===``), and OCR plain-text (``FUNDING``,
   ``**Acknowledgements**``) headings are matched case-insensitively.

2. **Section boundary** — The section extends until the next heading
   at the same or higher level, or the end of the document.

3. **Per-group configuration** — Each boilerplate *group* (e.g.
   ``acknowledgements``, ``funding``) can be independently
   enabled/disabled.

4. **Action** — Depending on ``mode``:
   - ``remove``    — delete the entire section.
   - ``summarize`` — replace with ``[Section removed: Acknowledgements]``.
   - ``keep``      — leave untouched; still report metrics.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Section group definitions ─────────────────────────────────────────────────
# Each key is a group name; its value is a list of title variants (lowercase).

SECTION_GROUPS: Dict[str, List[str]] = {
    "acknowledgements": [
        "acknowledgements",
        "acknowledgments",
        "acknowledgement",
        "acknowledgment",
    ],
    "funding": [
        "funding",
        "funding statement",
        "financial support",
        "funding information",
        "funding sources",
        "funding and acknowledgements",
        "funding and acknowledgments",
    ],
    "conflict_of_interest": [
        "conflict of interest",
        "conflicts of interest",
        "competing interests",
        "declaration of interest",
        "declarations of interest",
        "declaration of competing interest",
        "declaration of competing interests",
        "disclosure",
        "disclosures",
        "conflict of interest statement",
    ],
    "ethics_statement": [
        "ethics statement",
        "ethical approval",
        "ethics approval",
        "ethical considerations",
        "ethics declarations",
        "ethical statement",
        "ethics",
        "ethical review",
    ],
    "author_contributions": [
        "author contributions",
        "authors contributions",
        "author contribution",
        "contributor roles",
        "contributors",
        "authorship contributions",
        "credit authorship contribution statement",
        "contributions",
    ],
    "data_availability": [
        "data availability",
        "data availability statement",
        "code availability",
        "data and code availability",
        "data accessibility",
        "availability of data",
        "data sharing",
        "data access",
        "data and materials availability",
    ],
}


# ── Compiled patterns ─────────────────────────────────────────────────────────

_ATX_HEADING_RE = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*(?:#+\s*)?$")
_SETEXT_H1_RE = re.compile(r"^={3,}\s*$")
_SETEXT_H2_RE = re.compile(r"^-{3,}\s*$")
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")


# ── Internal data structures ─────────────────────────────────────────────────

@dataclass
class _DetectedSection:
    """A boilerplate section detected in the document."""
    heading_text: str       # original heading line (stripped)
    heading_level: int      # 1–6 for ATX/Setext, 0 for OCR plain-text
    group: str              # group key (e.g. "acknowledgements")
    start_line: int         # line index of heading (inclusive)
    end_line: int           # line index of section end (exclusive)
    content_lines: int      # non-empty lines in section body


# ── Pass implementation ──────────────────────────────────────────────────────

@register_pass
class BoilerplateSectionRemovalPass(OptimizerPass):
    """Detect and remove boilerplate sections from academic documents.

    Targets six section groups by default, each independently
    configurable:

    - ``acknowledgements``
    - ``funding``
    - ``conflict_of_interest``
    - ``ethics_statement``
    - ``author_contributions``
    - ``data_availability``

    Config params
    ~~~~~~~~~~~~~

    ====================== =================== ================================
    Param                  Default             Description
    ====================== =================== ================================
    mode                   ``"remove"``        ``"remove"`` / ``"summarize"``
                                               / ``"keep"``
    sections               ``{all: True}``     Dict mapping group names to
                                               ``True``/``False`` to enable/
                                               disable each group.
    summary_template       ``"[{group} section  Template for summarize mode.
                           removed]"``         ``{group}`` is replaced.
    detect_ocr_headings    ``True``            Match plain-text headings.
    detect_setext          ``True``            Match underline-style headings.
    max_heading_length     ``60``              Ignore lines longer than this
                                               for plain-text heading matching.
    custom_titles          ``{}``              Dict of extra group → title
                                               list to add beyond defaults.
    ====================== =================== ================================
    """

    # ── OptimizerPass interface ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "boilerplate_section_removal"

    @property
    def description(self) -> str:
        return (
            "Detect and remove boilerplate sections "
            "(Acknowledgements, Funding, Conflict of Interest, etc.) "
            "from academic and technical documents."
        )

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=22,  # after reference_section_removal (20), before citation (25)
            params={
                "mode": "remove",
                "sections": {group: True for group in SECTION_GROUPS},
                "summary_template": "[{group} section removed]",
                "detect_ocr_headings": True,
                "detect_setext": True,
                "max_heading_length": 60,
                "custom_titles": {},
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
        sections = p.get("sections", {})
        if not isinstance(sections, dict):
            raise PassConfigError(
                self.name,
                "sections must be a dict mapping group names to booleans",
            )
        for key, val in sections.items():
            if not isinstance(val, bool):
                raise PassConfigError(
                    self.name,
                    f"sections[{key!r}] must be a boolean, got {type(val).__name__}",
                )
        max_len = p.get("max_heading_length", 60)
        if not isinstance(max_len, int) or max_len < 1:
            raise PassConfigError(
                self.name,
                f"max_heading_length must be a positive integer, got {max_len!r}",
            )
        custom = p.get("custom_titles", {})
        if not isinstance(custom, dict):
            raise PassConfigError(
                self.name,
                "custom_titles must be a dict mapping group names to title lists",
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

        # Build the active title → group lookup
        title_to_group = self._build_title_map(p)

        if not title_to_group:
            self._report_metrics(ctx, sections=[], mode=mode)
            return ctx

        # ── Detect all boilerplate sections ───────────────────────────────
        sections = self._find_all_sections(stripped, p, title_to_group)

        if not sections:
            self._report_metrics(ctx, sections=[], mode=mode)
            return ctx

        if mode == "keep":
            self._report_metrics(ctx, sections=sections, mode=mode)
            return ctx

        # ── Apply action (remove / summarize) ─────────────────────────────
        template: str = p.get(
            "summary_template",
            "[{group} section removed]",
        )

        for section in reversed(sections):
            if mode == "summarize":
                # Capitalise group name for display
                display = section.group.replace("_", " ").title()
                replacement = template.format(group=display)
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

    # ── Title map construction ────────────────────────────────────────────

    @staticmethod
    def _build_title_map(params: Dict[str, Any]) -> Dict[str, str]:
        """Build a lookup from lowercase title → group name.

        Only includes groups that are enabled in ``params["sections"]``.
        Also merges any ``params["custom_titles"]`` entries.
        """
        enabled: Dict[str, bool] = params.get("sections", {})
        custom: Dict[str, List[str]] = params.get("custom_titles", {})

        # Merge default + custom groups
        all_groups: Dict[str, List[str]] = {}
        for group, titles in SECTION_GROUPS.items():
            all_groups[group] = list(titles)
        for group, titles in custom.items():
            if group in all_groups:
                all_groups[group].extend(titles)
            else:
                all_groups[group] = list(titles)

        # Build title → group, filtering by enabled
        title_to_group: Dict[str, str] = {}
        for group, titles in all_groups.items():
            if not enabled.get(group, True):  # default to enabled
                continue
            for title in titles:
                title_to_group[title.lower().strip()] = group

        return title_to_group

    # ── Heading detection ─────────────────────────────────────────────────

    def _find_all_sections(
        self,
        lines: List[str],
        params: Dict[str, Any],
        title_to_group: Dict[str, str],
    ) -> List[_DetectedSection]:
        """Scan for all boilerplate section headings and compute boundaries."""
        detect_ocr: bool = params.get("detect_ocr_headings", True)
        detect_setext: bool = params.get("detect_setext", True)
        max_heading_len: int = params.get("max_heading_length", 60)

        sections: List[_DetectedSection] = []
        skip_until = -1

        for i, line in enumerate(lines):
            if i <= skip_until:
                continue

            result = self._detect_heading(
                lines, i, title_to_group,
                detect_ocr=detect_ocr,
                detect_setext=detect_setext,
                max_heading_len=max_heading_len,
            )
            if result is None:
                continue

            heading_text, heading_level, heading_lines, group = result

            # Find section boundary
            content_start = i + heading_lines
            section_end = self._find_section_end(
                lines, content_start, heading_level,
                title_to_group=title_to_group,
                max_heading_len=max_heading_len,
            )

            content_line_count = sum(
                1 for l in lines[content_start:section_end] if l.strip()
            )

            sections.append(_DetectedSection(
                heading_text=heading_text,
                heading_level=heading_level,
                group=group,
                start_line=i,
                end_line=section_end,
                content_lines=content_line_count,
            ))

            skip_until = section_end - 1

        return sections

    def _detect_heading(
        self,
        lines: List[str],
        idx: int,
        title_to_group: Dict[str, str],
        *,
        detect_ocr: bool,
        detect_setext: bool,
        max_heading_len: int,
    ) -> Optional[Tuple[str, int, int, str]]:
        """Check if line *idx* is a boilerplate section heading.

        Returns ``(heading_text, level, num_lines, group)`` or ``None``.
        """
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            return None

        # 1. ATX heading: # Acknowledgements
        atx_m = _ATX_HEADING_RE.match(stripped)
        if atx_m:
            level = len(atx_m.group(1))
            title = self._clean_title(atx_m.group(2))
            group = self._match_title(title, title_to_group)
            if group is not None:
                return (stripped, level, 1, group)

        # 2. Setext heading: Acknowledgements\n===
        if detect_setext and idx + 1 < len(lines):
            next_line = lines[idx + 1].strip()
            title = self._clean_title(stripped)
            if _SETEXT_H1_RE.match(next_line):
                group = self._match_title(title, title_to_group)
                if group is not None:
                    return (stripped, 1, 2, group)
            if _SETEXT_H2_RE.match(next_line):
                group = self._match_title(title, title_to_group)
                if group is not None:
                    return (stripped, 2, 2, group)

        # 3. OCR / plain-text heading
        if detect_ocr:
            title = self._clean_title(stripped)
            if len(title) <= max_heading_len:
                group = self._match_title(title, title_to_group)
                if group is not None:
                    return (stripped, 0, 1, group)

        return None

    # ── Section boundary ──────────────────────────────────────────────────

    @classmethod
    def _find_section_end(
        cls,
        lines: List[str],
        content_start: int,
        heading_level: int,
        *,
        title_to_group: Optional[Dict[str, str]] = None,
        max_heading_len: int = 60,
    ) -> int:
        """Return the line index where the section ends (exclusive).

        Stops at the next heading at the same level or higher, or EOF.
        For OCR headings (level 0), also checks whether a subsequent
        short line matches another known section title.
        """
        for i in range(content_start, len(lines)):
            stripped = lines[i].strip()
            if not stripped:
                continue

            # ATX heading at same or higher level?
            atx_m = _ATX_HEADING_RE.match(stripped)
            if atx_m:
                next_level = len(atx_m.group(1))
                if heading_level == 0:
                    # OCR heading: any markdown heading ends the section
                    return i
                if next_level <= heading_level:
                    return i

            # Setext heading?
            if i + 1 < len(lines):
                next_stripped = lines[i + 1].strip()
                if _SETEXT_H1_RE.match(next_stripped):
                    return i
                if _SETEXT_H2_RE.match(next_stripped) and heading_level <= 2:
                    return i

            # OCR plain-text heading for another known section?
            if heading_level == 0 and title_to_group:
                clean = cls._clean_title(stripped)
                if len(clean) <= max_heading_len:
                    if clean.lower().strip() in title_to_group:
                        return i

        return len(lines)

    # ── Title matching helpers ────────────────────────────────────────────

    @staticmethod
    def _clean_title(text: str) -> str:
        """Strip formatting markers from a potential heading."""
        clean = unicodedata.normalize("NFKC", text.strip())
        clean = re.sub(r"\*{1,2}|_{1,2}", "", clean)
        clean = re.sub(r":\s*$", "", clean)
        return clean.strip()

    @staticmethod
    def _match_title(
        title: str,
        title_to_group: Dict[str, str],
    ) -> Optional[str]:
        """Return the group name if *title* matches, else ``None``."""
        return title_to_group.get(title.lower().strip())

    # ── Metrics ───────────────────────────────────────────────────────────

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
                "group": s.group,
                "start_line": s.start_line,
                "end_line": s.end_line,
                "content_lines": s.content_lines,
            }
            for s in sections
        ]

        # Per-group summary
        groups_found: Dict[str, int] = {}
        for s in sections:
            groups_found[s.group] = groups_found.get(s.group, 0) + 1

        total_lines = sum(s.end_line - s.start_line for s in sections)

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "mode": mode,
            "sections_found": len(sections),
            "total_lines_affected": total_lines,
            "groups_found": groups_found,
            "action_taken": mode if sections else "none",
            "sections": section_details,
        }

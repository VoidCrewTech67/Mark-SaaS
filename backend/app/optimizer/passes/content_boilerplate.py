"""
optimizer/passes/content_boilerplate.py – Remove low-semantic-value content.

Targets
=======

1. **Table of Contents** — "Contents" heading + dotted/numbered lines
2. **Certificates** — "This is to certify", "Certificate of", etc.
3. **Evaluation sheets** — Rubric/grade blocks
4. **Page numbers** — Standalone nums, "Page X of Y", "- N -"
5. **Repeated institution names** — Lines appearing 3+ times
6. **Boilerplate headers** — Short repetitive lines across pages

All rules configurable. Whitelist protection available.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Patterns ──────────────────────────────────────────────────────────────────

# Table of Contents heading
_TOC_HEADING_RE = re.compile(
    r"^#{0,6}\s*(?:Table\s+of\s+Contents|Contents|CONTENTS|TOC)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# TOC entry: text followed by dots/spaces + page number
_TOC_ENTRY_RE = re.compile(
    r"^.{3,80}[.\s·…]{3,}\s*\d+\s*$", re.MULTILINE,
)
# TOC entry: numbered section (1.1 Introduction ... 5)
_TOC_NUMBERED_RE = re.compile(
    r"^\s*\d+(?:\.\d+)*\s+\S.*\d+\s*$", re.MULTILINE,
)

# Certificate patterns
_CERT_PATTERNS = [
    re.compile(r"(?:this\s+is\s+to\s+)?certif(?:y|ied|icate)", re.IGNORECASE),
    re.compile(r"awarded\s+to", re.IGNORECASE),
    re.compile(r"hereby\s+(?:certif|declar|confirm)", re.IGNORECASE),
    re.compile(r"certificate\s+of\s+(?:completion|achievement|participation|merit)",
               re.IGNORECASE),
    re.compile(r"has\s+(?:successfully\s+)?completed", re.IGNORECASE),
]

# Evaluation/rubric patterns
_EVAL_PATTERNS = [
    re.compile(r"^\s*(?:Score|Grade|Marks|Rating|Points)\s*[:=]\s*", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*(?:Excellent|Good|Average|Poor|Satisfactory|Unsatisfactory)\s*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\d+\s*/\s*\d+\s*$", re.MULTILINE),  # 85/100
    re.compile(r"(?:evaluation|assessment)\s+(?:sheet|form|rubric)", re.IGNORECASE),
]

# Page numbers (standalone)
_PAGE_NUM_RE = re.compile(
    r"^\s*(?:"
    r"Page\s+\d+\s+of\s+\d+|"   # Page 3 of 10
    r"Page\s+\d+|"               # Page 3
    r"-\s*\d+\s*-|"              # - 3 -
    r"\d+\s*/\s*\d+|"            # 3/10
    r"\d{1,4}"                   # standalone number
    r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Code block boundaries
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)

# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class ContentBoilerplatePass(OptimizerPass):
    """Remove low-semantic-value content (TOC, certificates, page nums, etc.).

    Config params
    ~~~~~~~~~~~~~

    ========================== ============ ================================
    Param                      Default      Description
    ========================== ============ ================================
    remove_toc                 ``True``     Remove Table of Contents.
    remove_certificates        ``True``     Remove certificate blocks.
    remove_eval_sheets         ``True``     Remove evaluation/rubric blocks.
    remove_page_numbers        ``True``     Remove standalone page numbers.
    remove_repeated_lines      ``True``     Remove lines appearing 3+ times.
    min_repeat_count           ``3``        Min occurrences for repeated removal.
    max_repeat_line_length     ``80``       Only short lines count as repeated.
    whitelist                  ``[]``       Phrases to never remove.
    ========================== ============ ================================
    """

    @property
    def name(self) -> str:
        return "content_boilerplate"

    @property
    def description(self) -> str:
        return "Remove low-semantic-value content like TOC, certificates, page numbers."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=12,
            params={
                "remove_toc": True,
                "remove_certificates": True,
                "remove_eval_sheets": True,
                "remove_page_numbers": True,
                "remove_repeated_lines": True,
                "min_repeat_count": 3,
                "max_repeat_line_length": 80,
                "whitelist": [],
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError
        p = config.params
        mrc = p.get("min_repeat_count", 3)
        if not isinstance(mrc, int) or mrc < 2:
            raise PassConfigError(
                self.name, f"min_repeat_count must be int >= 2, got {mrc!r}",
            )

    # ── Main ──────────────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        content = ctx.content

        if not content.strip():
            self._report(ctx, _Metrics())
            return ctx

        whitelist: List[str] = p.get("whitelist", [])
        whitelist_lower = {w.lower() for w in whitelist}
        metrics = _Metrics()

        # Find code block ranges (protect)
        protected = _find_code_ranges(content)

        # 1. Remove TOC
        if p.get("remove_toc", True):
            content, n = self._remove_toc(content, protected, whitelist_lower)
            metrics.toc_removed += n
            if n:
                protected = _find_code_ranges(content)

        # 2. Remove certificates
        if p.get("remove_certificates", True):
            content, n = self._remove_block_pattern(
                content, _CERT_PATTERNS, protected, whitelist_lower,
            )
            metrics.certificates_removed += n
            if n:
                protected = _find_code_ranges(content)

        # 3. Remove eval sheets
        if p.get("remove_eval_sheets", True):
            content, n = self._remove_block_pattern(
                content, _EVAL_PATTERNS, protected, whitelist_lower,
            )
            metrics.eval_sheets_removed += n
            if n:
                protected = _find_code_ranges(content)

        # 4. Remove page numbers
        if p.get("remove_page_numbers", True):
            content, n = self._remove_page_numbers(content, protected, whitelist_lower)
            metrics.page_numbers_removed += n
            if n:
                protected = _find_code_ranges(content)

        # 5. Remove repeated lines
        if p.get("remove_repeated_lines", True):
            min_reps = p.get("min_repeat_count", 3)
            max_len = p.get("max_repeat_line_length", 80)
            content, n = self._remove_repeated(
                content, min_reps, max_len, protected, whitelist_lower,
            )
            metrics.repeated_lines_removed += n

        # Cleanup excess blank lines
        content = re.sub(r"\n{3,}", "\n\n", content).strip()
        ctx.content = content
        self._report(ctx, metrics)
        return ctx

    # ── TOC removal ───────────────────────────────────────────────────────

    @staticmethod
    def _remove_toc(
        content: str,
        protected: List[Tuple[int, int]],
        whitelist: Set[str],
    ) -> Tuple[str, int]:
        count = 0
        # Find TOC heading
        for m in _TOC_HEADING_RE.finditer(content):
            if _in_protected(m.start(), m.end(), protected):
                continue
            if _in_whitelist(m.group(), whitelist):
                continue

            # Find end of TOC: collect subsequent TOC-like entries
            toc_start = m.start()
            rest = content[m.end():]
            lines = rest.split("\n")
            toc_end_offset = 0

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    toc_end_offset += len(line) + 1
                    continue
                if (_TOC_ENTRY_RE.match(line) or
                        _TOC_NUMBERED_RE.match(line)):
                    toc_end_offset += len(line) + 1
                else:
                    break

            toc_end = m.end() + toc_end_offset
            content = content[:toc_start] + content[toc_end:]
            count += 1
            break  # re-search after removal would need updated positions

        return content, count

    # ── Block pattern removal ─────────────────────────────────────────────

    @staticmethod
    def _remove_block_pattern(
        content: str,
        patterns: List[re.Pattern],
        protected: List[Tuple[int, int]],
        whitelist: Set[str],
    ) -> Tuple[str, int]:
        """Remove paragraphs matching any of *patterns*."""
        paragraphs = content.split("\n\n")
        kept: List[str] = []
        count = 0
        offset = 0

        for para in paragraphs:
            para_start = content.find(para, offset)
            para_end = para_start + len(para) if para_start >= 0 else 0
            offset = para_end

            if _in_protected(para_start, para_end, protected):
                kept.append(para)
                continue

            if _in_whitelist(para, whitelist):
                kept.append(para)
                continue

            matched = any(p.search(para) for p in patterns)
            if matched:
                count += 1
            else:
                kept.append(para)

        return "\n\n".join(kept), count

    # ── Page number removal ───────────────────────────────────────────────

    @staticmethod
    def _remove_page_numbers(
        content: str,
        protected: List[Tuple[int, int]],
        whitelist: Set[str],
    ) -> Tuple[str, int]:
        lines = content.split("\n")
        kept: List[str] = []
        count = 0
        char_offset = 0

        for line in lines:
            line_start = char_offset
            line_end = char_offset + len(line)
            char_offset = line_end + 1  # +1 for \n

            if _in_protected(line_start, line_end, protected):
                kept.append(line)
                continue

            stripped = line.strip()
            if not stripped:
                kept.append(line)
                continue

            if _in_whitelist(stripped, whitelist):
                kept.append(line)
                continue

            if _PAGE_NUM_RE.match(line):
                count += 1
                continue

            kept.append(line)

        return "\n".join(kept), count

    # ── Repeated line removal ─────────────────────────────────────────────

    @staticmethod
    def _remove_repeated(
        content: str,
        min_count: int,
        max_length: int,
        protected: List[Tuple[int, int]],
        whitelist: Set[str],
    ) -> Tuple[str, int]:
        lines = content.split("\n")

        # Count normalized line frequencies
        normalized_counts: Counter[str] = Counter()
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) <= max_length:
                # Skip headings — they repeat legitimately
                if not _HEADING_RE.match(stripped):
                    normalized_counts[stripped] += 1

        # Identify repeated lines
        repeated: Set[str] = {
            text for text, cnt in normalized_counts.items()
            if cnt >= min_count
        }

        if not repeated:
            return content, 0

        kept: List[str] = []
        count = 0
        char_offset = 0
        seen_once: Set[str] = set()  # keep first occurrence

        for line in lines:
            line_start = char_offset
            line_end = char_offset + len(line)
            char_offset = line_end + 1

            stripped = line.strip()

            if _in_protected(line_start, line_end, protected):
                kept.append(line)
                continue

            if stripped in repeated and not _in_whitelist(stripped, whitelist):
                if stripped not in seen_once:
                    seen_once.add(stripped)
                    kept.append(line)  # keep first
                else:
                    count += 1
                    continue
            else:
                kept.append(line)

        return "\n".join(kept), count

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(self, ctx: OptimizationContext, m: _Metrics) -> None:
        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "toc_removed": m.toc_removed,
            "certificates_removed": m.certificates_removed,
            "eval_sheets_removed": m.eval_sheets_removed,
            "page_numbers_removed": m.page_numbers_removed,
            "repeated_lines_removed": m.repeated_lines_removed,
            "total_items_removed": m.total,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

class _Metrics:
    __slots__ = (
        "toc_removed", "certificates_removed", "eval_sheets_removed",
        "page_numbers_removed", "repeated_lines_removed",
    )

    def __init__(self) -> None:
        self.toc_removed = 0
        self.certificates_removed = 0
        self.eval_sheets_removed = 0
        self.page_numbers_removed = 0
        self.repeated_lines_removed = 0

    @property
    def total(self) -> int:
        return (
            self.toc_removed + self.certificates_removed
            + self.eval_sheets_removed + self.page_numbers_removed
            + self.repeated_lines_removed
        )


def _find_code_ranges(content: str) -> List[Tuple[int, int]]:
    return [(m.start(), m.end()) for m in _CODE_BLOCK_RE.finditer(content)]


def _in_protected(start: int, end: int, zones: List[Tuple[int, int]]) -> bool:
    for zs, ze in zones:
        if start < ze and end > zs:
            return True
    return False


def _in_whitelist(text: str, whitelist: Set[str]) -> bool:
    text_lower = text.lower()
    return any(w in text_lower for w in whitelist)

"""
services/research_paper_optimizer.py — Four-profile optimizer for research papers.

Profiles:
  safe       — cleanup only (5-10% reduction)
  balanced   — safe + remove references/acknowledgements/funding (15-40%)
  aggressive — balanced + appendices/supplementary/boilerplate (30-60%)
  rag        — balanced + structured section extraction for retrieval

Each profile is a superset of the previous (except RAG which branches from
balanced). The optimizer applies passes sequentially and returns optimized
Markdown (or structured JSON for RAG mode).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from app.utils.token_counter import estimate_tokens

logger = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ResearchPaperResult:
    """Result from the research paper optimizer."""
    optimized_markdown: str
    original_tokens: int
    optimized_tokens: int
    reduction_percent: float
    mode: str
    passes_applied: list[str] = field(default_factory=list)
    # RAG-specific structured output (None for non-RAG modes)
    structured_output: Optional[dict] = None


# ── Main optimizer ────────────────────────────────────────────────────────────

class ResearchPaperOptimizer:
    """Applies mode-specific optimization passes to research paper Markdown."""

    VALID_MODES = {"safe", "balanced", "aggressive", "rag"}

    def optimize(self, markdown: str, mode: str = "balanced") -> ResearchPaperResult:
        """Run the optimization pipeline for the given mode.

        Args:
            markdown: Raw Markdown from Docling extraction.
            mode: One of 'safe', 'balanced', 'aggressive', 'rag'.

        Returns:
            ResearchPaperResult with optimized output and stats.
        """
        if mode not in self.VALID_MODES:
            logger.warning(
                "[research_paper_optimizer] Unknown mode '%s', falling back to 'balanced'",
                mode,
            )
            mode = "balanced"

        original_tokens = estimate_tokens(markdown)
        passes_applied: list[str] = []
        result = markdown

        # ── Safe passes (always applied) ──────────────────────────────────
        result = _normalize_unicode(result)
        passes_applied.append("unicode_normalization")

        result = _remove_page_numbers(result)
        passes_applied.append("remove_page_numbers")

        result = _remove_repeated_headers_footers(result)
        passes_applied.append("remove_repeated_headers_footers")

        result = _merge_broken_lines(result)
        passes_applied.append("merge_broken_lines")

        result = _normalize_whitespace(result)
        passes_applied.append("normalize_whitespace")

        if mode == "safe":
            return self._build_result(markdown, result, original_tokens, mode, passes_applied)

        # ── Balanced passes (safe + section removal) ──────────────────────
        result = _remove_references_section(result)
        passes_applied.append("remove_references")

        result = _remove_acknowledgements_section(result)
        passes_applied.append("remove_acknowledgements")

        result = _remove_funding_section(result)
        passes_applied.append("remove_funding")

        result = _remove_copyright_notices(result)
        passes_applied.append("remove_copyright")

        result = _normalize_whitespace(result)  # clean up after removals
        balanced_result = result  # snapshot for safety guard

        if mode == "balanced":
            return self._build_result(markdown, result, original_tokens, mode, passes_applied)

        # ── RAG mode (balanced + structured extraction) ───────────────────
        if mode == "rag":
            try:
                structured = _extract_structured(result)
            except Exception as exc:
                logger.warning("[research_paper_optimizer] RAG extraction failed: %s", exc)
                structured = {"title": "", "abstract": "", "sections": []}
            result = _normalize_whitespace(result)
            passes_applied.append("structured_extraction")
            res = self._build_result(markdown, result, original_tokens, mode, passes_applied)
            res.structured_output = structured
            return res

        # ── Aggressive passes (balanced + maximum reduction) ──────────────
        result = _safe_pass(result, _remove_appendices, "remove_appendices", passes_applied)
        result = _safe_pass(result, _remove_supplementary_material, "remove_supplementary", passes_applied)
        result = _safe_pass(result, _collapse_figure_descriptions, "collapse_figures", passes_applied)
        result = _safe_pass(result, _remove_conference_boilerplate, "remove_conference_boilerplate", passes_applied)
        result = _safe_pass(result, _compress_metadata_sections, "compress_metadata", passes_applied)

        result = _normalize_whitespace(result)

        # Safety guard: if aggressive removed too much, fall back to balanced
        if len(result.strip()) < len(balanced_result.strip()) * 0.1:
            logger.warning(
                "[research_paper_optimizer] Aggressive removed >90%% of content, "
                "falling back to balanced result"
            )
            result = balanced_result
            passes_applied.append("safety_fallback_to_balanced")

        return self._build_result(markdown, result, original_tokens, mode, passes_applied)

    def _build_result(
        self,
        original: str,
        optimized: str,
        original_tokens: int,
        mode: str,
        passes: list[str],
    ) -> ResearchPaperResult:
        opt_tokens = estimate_tokens(optimized)
        saved = max(0, original_tokens - opt_tokens)
        pct = round(saved / original_tokens * 100, 1) if original_tokens > 0 else 0.0
        logger.info(
            "[research_paper_optimizer] mode=%s: %d→%d tokens (-%d, %.1f%%), %d passes",
            mode, original_tokens, opt_tokens, saved, pct, len(passes),
        )
        return ResearchPaperResult(
            optimized_markdown=optimized,
            original_tokens=original_tokens,
            optimized_tokens=opt_tokens,
            reduction_percent=pct,
            mode=mode,
            passes_applied=passes,
        )


# ── Safe pass wrapper ─────────────────────────────────────────────────────────

def _safe_pass(text: str, fn, name: str, passes: list[str]) -> str:
    """Run a pass but roll back if it removes all content."""
    try:
        result = fn(text)
        if not result or not result.strip():
            logger.warning(
                "[research_paper_optimizer] Pass '%s' produced empty output, skipping", name
            )
            return text
        passes.append(name)
        return result
    except Exception as exc:
        logger.warning(
            "[research_paper_optimizer] Pass '%s' failed: %s, skipping", name, exc
        )
        return text


# ── Safe passes ───────────────────────────────────────────────────────────────

def _normalize_unicode(text: str) -> str:
    """NFKC normalize + strip invisible characters."""
    result = unicodedata.normalize("NFKC", text)
    for ch in ("\u00a0", "\u00ad", "\u200b", "\u200c", "\u200d", "\ufeff"):
        result = result.replace(ch, " " if ch == "\u00a0" else "")
    # Remove control characters (keep \t \n \r)
    result = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", result)
    return result


_PAGE_NUM_RE = re.compile(
    r"^[ \t]*(?:Page\s+\d+\s+of\s+\d+|\d+\s*/\s*\d+|\-\s*\d+\s*\-|\d{1,4})[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)

def _remove_page_numbers(text: str) -> str:
    """Remove standalone page number lines."""
    return _PAGE_NUM_RE.sub("", text)


def _remove_repeated_headers_footers(text: str) -> str:
    """Detect and remove lines that repeat across pages (headers/footers).

    Heuristic: any non-heading, non-empty line that appears 3+ times
    and is shorter than 120 chars is likely a header/footer.
    """
    lines = text.splitlines()
    if len(lines) < 10:
        return text

    # Count occurrences of short lines
    line_counts: dict[str, int] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) < 120 and not stripped.startswith("#"):
            line_counts[stripped] = line_counts.get(stripped, 0) + 1

    # Lines appearing 3+ times are likely repeated headers/footers
    repeated = {line for line, count in line_counts.items() if count >= 3}
    if not repeated:
        return text

    logger.debug(
        "[research_paper_optimizer] Removing %d repeated header/footer patterns",
        len(repeated),
    )
    return "\n".join(
        line for line in lines
        if line.strip() not in repeated
    )


_BROKEN_LINE_RE = re.compile(
    r"([a-z,;])\n([a-z])",
    re.MULTILINE,
)

def _merge_broken_lines(text: str) -> str:
    """Merge lines broken mid-sentence by PDF column layout.

    Joins lines where a lowercase letter ends one line and a lowercase
    letter starts the next — a strong signal of a mid-sentence break.
    """
    return _BROKEN_LINE_RE.sub(r"\1 \2", text)


def _normalize_whitespace(text: str) -> str:
    """Collapse excessive blank lines, strip trailing whitespace."""
    # 3+ blank lines → 2
    result = re.sub(r"\n{3,}", "\n\n", text)
    # Repeated horizontal rules
    result = re.sub(r"(\n[-*_]{3,}\n){2,}", "\n---\n", result)
    # Trailing whitespace per line
    result = re.sub(r"[ \t]+$", "", result, flags=re.MULTILINE)
    return result.strip()


# ── Balanced passes ───────────────────────────────────────────────────────────

_SECTION_REMOVAL_PATTERNS: dict[str, re.Pattern] = {
    "references": re.compile(
        r"^#{1,3}\s*(?:References|Bibliography|Works\s+Cited|Literature\s+Cited)\s*$"
        r".*?(?=^#{1,3}\s|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    ),
    "acknowledgements": re.compile(
        r"^#{1,3}\s*(?:Acknowledg(?:e?ments?)|ACKNOWLEDG(?:E?MENTS?))\s*$"
        r".*?(?=^#{1,3}\s|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    ),
    "funding": re.compile(
        r"^#{1,3}\s*(?:Funding|Financial\s+Support|Grant\s+Support|Funding\s+Statement)\s*$"
        r".*?(?=^#{1,3}\s|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    ),
}


def _remove_references_section(text: str) -> str:
    return _SECTION_REMOVAL_PATTERNS["references"].sub("", text)


def _remove_acknowledgements_section(text: str) -> str:
    return _SECTION_REMOVAL_PATTERNS["acknowledgements"].sub("", text)


def _remove_funding_section(text: str) -> str:
    return _SECTION_REMOVAL_PATTERNS["funding"].sub("", text)


# Copyright — only match lines that PRIMARILY are copyright/license,
# not lines that merely mention a publisher name in passing.
_COPYRIGHT_RE = re.compile(
    r"(?:^(?:©|Copyright\s+\d{4}|All\s+rights\s+reserved\.?|"
    r"Licensed\s+under\s+.{0,80}|Creative\s+Commons\s+.{0,80}|"
    r"CC\s+BY(?:-\w+)*\s+\d\.\d|arXiv:\d+\.\d+v?\d*|"
    r"DOI:\s*10\.\S+|https?://doi\.org/\S+).*$\n?)+",
    re.MULTILINE | re.IGNORECASE,
)

def _remove_copyright_notices(text: str) -> str:
    """Remove lines that START with copyright/license/DOI markers."""
    return _COPYRIGHT_RE.sub("", text)


# ── Aggressive passes ─────────────────────────────────────────────────────────

# Match appendix sections — stop at any same-or-higher-level heading
_APPENDIX_RE = re.compile(
    r"^(#{1,3})\s*(?:Appendi(?:x|ces))\s*.*$\n"
    r"(?:(?!^#{1,3}\s).*\n?)*",
    re.MULTILINE | re.IGNORECASE,
)

def _remove_appendices(text: str) -> str:
    return _APPENDIX_RE.sub("", text)


_SUPPLEMENTARY_RE = re.compile(
    r"^(#{1,3})\s*(?:Supplementary|Supporting)\s+(?:Materials?|Information|Data|Figures?|Tables?)\s*$\n"
    r"(?:(?!^#{1,3}\s).*\n?)*",
    re.MULTILINE | re.IGNORECASE,
)

def _remove_supplementary_material(text: str) -> str:
    return _SUPPLEMENTARY_RE.sub("", text)


_FIGURE_DESC_RE = re.compile(
    r"((?:^(?:Figure|Fig\.?)\s+\d+[.:]\s+.+$\n?){3,})",
    re.MULTILINE | re.IGNORECASE,
)

def _collapse_figure_descriptions(text: str) -> str:
    """Collapse blocks of 3+ consecutive figure descriptions into a summary."""
    def _replacer(m: re.Match) -> str:
        lines = [l.strip() for l in m.group(0).strip().splitlines() if l.strip()]
        if len(lines) <= 2:
            return m.group(0)
        first = lines[0]
        last = lines[-1]
        return f"{first}\n[... {len(lines) - 2} additional figure descriptions omitted ...]\n{last}\n"

    return _FIGURE_DESC_RE.sub(_replacer, text)


# Conference boilerplate — only match lines that START with these patterns,
# not lines that merely mention these terms in the middle of sentences.
_CONFERENCE_BOILERPLATE_RE = re.compile(
    r"(?:^(?:Proceedings\s+of\s+.{0,100}|"
    r"Accepted\s+(?:at|to|for)\s+.{0,100}|"
    r"Submitted\s+to\s+.{0,100}|"
    r"Under\s+review\s+.{0,60}|"
    r"CCS\s+Concepts\s*:.{0,200}|"
    r"ACM\s+Reference\s+Format\s*:.{0,200}|"
    r"Keywords?\s*:.{0,200}|"
    r"Categories\s+and\s+Subject\s+Descriptors\s*:.{0,200}"
    r")$\n?)+",
    re.MULTILINE | re.IGNORECASE,
)

def _remove_conference_boilerplate(text: str) -> str:
    return _CONFERENCE_BOILERPLATE_RE.sub("", text)


_AUTHOR_BLOCK_RE = re.compile(
    r"^(#{1,3})\s*(?:Author\s*(?:Information|Contributions?)|"
    r"Conflict\s+of\s+Interest(?:s)?|Competing\s+Interests?|Data\s+Availability|"
    r"Ethics\s+(?:Statement|Approval)|Consent\s+(?:Statement|to\s+Participate))\s*$\n"
    r"(?:(?!^#{1,3}\s).*\n?)*",
    re.MULTILINE | re.IGNORECASE,
)

def _compress_metadata_sections(text: str) -> str:
    """Remove non-critical metadata sections (author info, conflicts, data availability)."""
    return _AUTHOR_BLOCK_RE.sub("", text)


# ── RAG structured extraction ────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

def _extract_structured(text: str) -> dict:
    """Extract structured sections from the Markdown for RAG pipelines.

    Returns a dict with title, abstract, and ordered sections.
    """
    lines = text.splitlines()

    # Try to extract title (first H1)
    title = ""
    abstract = ""
    sections: list[dict] = []

    # Find title
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("## "):
            title = stripped.lstrip("# ").strip()
            break

    # Find abstract
    abstract_match = re.search(
        r"^#{1,3}\s*Abstract\s*$\n(.*?)(?=^#{1,3}\s|\Z)",
        text,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if abstract_match:
        abstract = abstract_match.group(1).strip()

    # Extract all sections
    heading_positions = list(_HEADING_RE.finditer(text))
    for i, m in enumerate(heading_positions):
        level = len(m.group(1))
        heading_text = m.group(2).strip()

        # Skip title and abstract (already extracted)
        if heading_text.lower() in ("abstract",) or (level == 1 and heading_text == title):
            continue

        # Content = text between this heading and the next
        start = m.end()
        end = heading_positions[i + 1].start() if i + 1 < len(heading_positions) else len(text)
        content = text[start:end].strip()

        if content:
            sections.append({
                "title": heading_text,
                "level": level,
                "content": content,
            })

    return {
        "title": title,
        "abstract": abstract,
        "sections": sections,
    }

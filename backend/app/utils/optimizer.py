"""
optimizer.py – Markdown cleanup and token-optimization utilities.

Provides:
  - ``optimize_markdown(text)``  → cleaned string
  - ``OptimizationStats``        → dataclass with before/after token counts
  - ``chunk_markdown(text, max_tokens, overlap_tokens)``  → list[str] chunks

All token counting delegates to the existing token_counter.py module.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.utils.token_counter import estimate_tokens, format_stat


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class OptimizationStats:
    """Holds before/after stats for a single optimization run."""

    original_text:  str
    optimized_text: str

    # Semantic scores — populated by SemanticScoringService after optimization
    semantic_preservation:  float | None = None   # 0–100  (embedding recall)
    semantic_loss:          float | None = None   # 0–100
    context_preservation:   float | None = None   # 0–100  (structural)
    overall_preservation:   float | None = None   # 0–100  (harmonic mean)
    scoring_method:         str   | None = None   # "embedding" | "bow" | ...
    context_breakdown:      dict  | None = None   # per-metric scores
    issues:                 list  | None = None   # PreservationIssue list

    @property
    def original_tokens(self) -> int:
        return estimate_tokens(self.original_text)

    @property
    def optimized_tokens(self) -> int:
        return estimate_tokens(self.optimized_text)

    @property
    def tokens_saved(self) -> int:
        return max(0, self.original_tokens - self.optimized_tokens)

    @property
    def percent_saved(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return round(self.tokens_saved / self.original_tokens * 100, 1)

    # Convenience formatted strings
    def fmt_original(self) -> str:
        return format_stat(self.original_tokens)

    def fmt_optimized(self) -> str:
        return format_stat(self.optimized_tokens)

    def fmt_saved(self) -> str:
        return format_stat(self.tokens_saved)

    def fmt_percent(self) -> str:
        return f"{self.percent_saved}%"


# ---------------------------------------------------------------------------
# Core optimization pipeline
# ---------------------------------------------------------------------------

# Patterns that represent common OCR / PDF artifacts
_OCR_ARTIFACTS: list[re.Pattern[str]] = [
    re.compile(r"\f"),                              # form-feed characters
    re.compile(r"[^\S\r\n]+$", re.MULTILINE),       # trailing whitespace per line
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"),   # control characters (keep \t \n \r)
]

# Page-number patterns (standalone numeric lines, "Page N of M", etc.)
_PAGE_NUMBER_RE = re.compile(
    r"^[ \t]*(?:Page\s+\d+\s+of\s+\d+|\d+\s*/\s*\d+|\-\s*\d+\s*\-|\d+)[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)

# Repeated horizontal rules / separators (more than one consecutive)
_MULTI_HR_RE = re.compile(r"(\n[-*_]{3,}\n){2,}", re.MULTILINE)

# Three or more consecutive blank lines → normalise to two
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")


def optimize_markdown(text: str) -> str:
    """Return a cleaned, de-duplicated, token-optimised Markdown string.

    Steps applied (in order):
    0. Unicode normalisation (NFKC) — converts ligatures, lookalikes, invisible chars.
    1. Strip OCR control-character artifacts.
    2. Remove page numbers.
    3. Remove duplicate blank lines (≥3 → 2).
    4. Remove repeated horizontal rules.
    5. Deduplicate repeated headings scoped per top-level section.
    6. Remove duplicate consecutive paragraphs / footer blobs.
    7. Normalize trailing whitespace per line.
    """
    if not text:
        return text

    # 0 – Unicode normalisation: ligatures (ﬁ→fi), non-breaking spaces, soft hyphens, zero-width
    result = unicodedata.normalize("NFKC", text)
    result = result.replace("\u00a0", " ")   # non-breaking space → regular space
    result = result.replace("\u00ad", "")    # soft hyphen → delete
    result = result.replace("\u200b", "")    # zero-width space → delete
    result = result.replace("\u200c", "")    # zero-width non-joiner → delete
    result = result.replace("\u200d", "")    # zero-width joiner → delete
    result = result.replace("\ufeff", "")    # BOM → delete

    # 1 – OCR artifacts
    for pat in _OCR_ARTIFACTS:
        result = pat.sub("", result)

    # 2 – Page numbers
    result = _PAGE_NUMBER_RE.sub("", result)

    # 3 – Excess blank lines
    result = _EXCESS_BLANK_RE.sub("\n\n", result)

    # 4 – Repeated horizontal rules
    result = _MULTI_HR_RE.sub("\n---\n", result)

    # 5 – Deduplicate headings (scoped per top-level section)
    result = _deduplicate_headings(result)

    # 6 – Deduplicate consecutive duplicate paragraphs / footers
    result = _deduplicate_paragraphs(result)

    # 7 – Final trailing-whitespace sweep + strip
    result = re.sub(r"[ \t]+$", "", result, flags=re.MULTILINE)
    result = result.strip()

    return result


# ---------------------------------------------------------------------------
# Private deduplication helpers
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)
_TOP_LEVEL_HEADING_RE = re.compile(r"^#\s+")


def _deduplicate_headings(text: str) -> str:
    """Remove exact duplicate heading lines, keeping the first occurrence.

    Scope resets at each top-level (H1) heading so that identical subheadings
    in different chapters (e.g. '## Summary') are preserved.
    """
    lines = text.splitlines(keepends=True)
    seen_headings: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Reset scope at every H1 so cross-chapter headings aren't dropped
        if _TOP_LEVEL_HEADING_RE.match(stripped):
            seen_headings.clear()

        if _HEADING_RE.match(stripped):
            if stripped in seen_headings:
                continue  # drop duplicate heading within this scope
            seen_headings.add(stripped)

        out.append(line)

    return "".join(out)


def _deduplicate_paragraphs(text: str) -> str:
    """Remove consecutive duplicate paragraph blocks."""
    paragraphs = re.split(r"\n\n+", text)
    out: list[str] = []
    prev: str = ""
    for para in paragraphs:
        normalised = para.strip()
        if normalised and normalised == prev:
            continue  # exact duplicate of previous paragraph
        out.append(para)
        prev = normalised
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Smart chunking
# ---------------------------------------------------------------------------

CHUNK_PRESETS: dict[str, int] = {
    "4K tokens": 4_000,
    "8K tokens": 8_000,
    "16K tokens": 16_000,
}

# Default overlap as a fraction of max_tokens (10%)
_DEFAULT_OVERLAP_RATIO: float = 0.10


def chunk_markdown(
    text: str,
    max_tokens: int,
    overlap_tokens: int | None = None,
) -> list[str]:
    """Split *text* into chunks of at most *max_tokens* tokens each.

    Strategy:
    - Split on heading boundaries (# / ##) first to preserve sections.
    - If a section is still too large, split on paragraph boundaries.
    - Optionally prepend the tail of the previous chunk (overlap) to each
      subsequent chunk so LLMs retain cross-boundary context.

    Args:
        text:           The Markdown string to split.
        max_tokens:     Hard upper bound on tokens per chunk.
        overlap_tokens: How many tokens from the end of chunk N to prepend to
                        chunk N+1. Defaults to 10 % of max_tokens. Pass 0 to
                        disable overlap entirely.

    Returns:
        A list of non-empty chunk strings.
    """
    if not text or max_tokens <= 0:
        return [text] if text else []

    if estimate_tokens(text) <= max_tokens:
        return [text]

    # Resolve overlap
    if overlap_tokens is None:
        overlap_tokens = max(0, int(max_tokens * _DEFAULT_OVERLAP_RATIO))

    raw_chunks: list[str] = _split_on_headings(text, max_tokens)
    raw_chunks = [c for c in raw_chunks if c.strip()]

    if overlap_tokens <= 0 or len(raw_chunks) < 2:
        return raw_chunks

    # Stitch overlap: tail of chunk[i-1] prepended to chunk[i]
    overlapped: list[str] = [raw_chunks[0]]
    for i in range(1, len(raw_chunks)):
        tail = _tail_tokens(raw_chunks[i - 1], overlap_tokens)
        if tail:
            overlapped.append(tail + "\n\n" + raw_chunks[i])
        else:
            overlapped.append(raw_chunks[i])

    return overlapped


# ---------------------------------------------------------------------------
# Overlap helper
# ---------------------------------------------------------------------------

def _tail_tokens(text: str, n_tokens: int) -> str:
    """Return roughly the last *n_tokens* tokens from *text* on paragraph boundaries."""
    paragraphs = text.split("\n\n")
    tail_parts: list[str] = []
    count = 0
    for para in reversed(paragraphs):
        t = estimate_tokens(para)
        if count + t > n_tokens:
            break
        tail_parts.insert(0, para)
        count += t
    return "\n\n".join(tail_parts)


# ---------------------------------------------------------------------------
# Internal split helpers
# ---------------------------------------------------------------------------

def _split_on_headings(text: str, max_tokens: int) -> list[str]:
    """Split at top-level heading (# or ##) boundaries."""
    heading_pat = re.compile(r"^#{1,2}\s+", re.MULTILINE)
    positions = [m.start() for m in heading_pat.finditer(text)]

    if not positions:
        return _split_on_paragraphs(text, max_tokens)

    segments: list[str] = []
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        segments.append(text[pos:end])

    preamble = text[: positions[0]].strip()

    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens: int = 0

    if preamble:
        current_parts.append(preamble)
        current_tokens += estimate_tokens(preamble)

    for seg in segments:
        seg_tokens = estimate_tokens(seg)
        if seg_tokens > max_tokens:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
                current_parts, current_tokens = [], 0
            chunks.extend(_split_on_paragraphs(seg, max_tokens))
        elif current_tokens + seg_tokens > max_tokens:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
            current_parts = [seg]
            current_tokens = seg_tokens
        else:
            current_parts.append(seg)
            current_tokens += seg_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


def _split_on_paragraphs(text: str, max_tokens: int) -> list[str]:
    """Fall-back: split on double-newline paragraph boundaries."""
    paragraphs = re.split(r"\n\n+", text)
    chunks: list[str] = []
    current_parts: list[str] = []
    current_tokens: int = 0

    for para in paragraphs:
        para_tokens = estimate_tokens(para)
        if current_tokens + para_tokens > max_tokens:
            if current_parts:
                chunks.append("\n\n".join(current_parts))
            current_parts = [para]
            current_tokens = para_tokens
        else:
            current_parts.append(para)
            current_tokens += para_tokens

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks

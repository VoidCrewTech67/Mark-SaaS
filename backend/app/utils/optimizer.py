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
    """Return roughly the last *n_tokens* tokens from *text*.

    Tries paragraph → sentence → line boundaries in that order. Falls back to
    a character-window slice for bodies (e.g. dense tables) that have none of
    the above. Always returns a non-empty string when the input is non-empty
    and n_tokens > 0 — production overlap relies on this.
    """
    if not text or n_tokens <= 0:
        return ""

    # Paragraph boundary
    paragraphs = text.split("\n\n")
    if len(paragraphs) > 1:
        tail_parts: list[str] = []
        count = 0
        for para in reversed(paragraphs):
            t = estimate_tokens(para)
            if count + t > n_tokens:
                break
            tail_parts.insert(0, para)
            count += t
        if tail_parts:
            return "\n\n".join(tail_parts)

    # Sentence boundary
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) > 1:
        out: list[str] = []
        count = 0
        for s in reversed(sentences):
            t = estimate_tokens(s)
            if count + t > n_tokens:
                break
            out.insert(0, s)
            count += t
        if out:
            return " ".join(out)

    # Line boundary
    lines = text.split("\n")
    if len(lines) > 1:
        out2: list[str] = []
        count = 0
        for ln in reversed(lines):
            t = estimate_tokens(ln)
            if count + t > n_tokens:
                break
            out2.insert(0, ln)
            count += t
        if out2:
            return "\n".join(out2)

    # Character-window fallback
    ratio = max(1, len(text) // max(1, estimate_tokens(text)))
    return text[-(n_tokens * ratio):]


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


# ---------------------------------------------------------------------------
# Structured chunking (RAG) — reuses the split helpers above but emits
# per-chunk metadata (section, token/word/char counts, tables, pages,
# source_file). The plain chunk_markdown() above is kept unchanged for
# backward compatibility.
# ---------------------------------------------------------------------------

# RAG defaults — only applied when caller passes None (i.e. user picked no preset)
DEFAULT_RAG_MAX_TOKENS: int = 800
DEFAULT_RAG_OVERLAP_TOKENS: int = 100

# Soft target band applied only when defaults are in use (None args).
# Caller-supplied max_tokens is respected as-is so explicit /api/chunk
# callers keep their existing behavior.
_TARGET_MIN_TOKENS: int = 200
_TARGET_MAX_TOKENS: int = 500
_HARD_MIN_TOKENS:  int = 100
_HARD_MAX_TOKENS:  int = 600

# Heading levels used to mark section boundaries (1–3 → captures subsections)
_SECTION_HEADING_PAT = re.compile(r"^(#{1,3})\s+(.*)$", re.MULTILINE)
_HEADING_LINE_PAT    = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)

# Page-break marker emitted by extractors (e.g. Docling with page_break_placeholder).
# Two forms are recognised: "<!-- page: N -->" carries an explicit page number,
# "<!-- page-break -->" just signals the next page (we increment).
_PAGE_MARKER_NUM_PAT = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)
_PAGE_MARKER_ANY_PAT = re.compile(r"<!--\s*page[-_ ]?break\s*-->", re.IGNORECASE)

# Junk artefacts produced by document extractors that we always strip.
_ARTIFACT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"<!--\s*image\s*-->", re.IGNORECASE),
    re.compile(r"<!--\s*formula-not-decoded\s*-->", re.IGNORECASE),
    re.compile(r"<!--\s*missing[\w-]*\s*-->", re.IGNORECASE),
    re.compile(r"<!--\s*no[\w-]*\s*-->", re.IGNORECASE),
]

# Markdown table detector — a header row followed by a `|---|---|` separator.
_TABLE_BLOCK_PAT = re.compile(
    r"(^\|.+\|\s*\n\|[\s:|\-]+\|\s*\n(?:\|.*\|\s*\n?)*)",
    re.MULTILINE,
)

# Inline section header pattern — research paper sections that appear glued to
# body text without a markdown heading prefix. Examples:
#   "1.Introduction", "3.1.ResidualLearning", "A.ObjectDetectionBaselines"
# Captures (number, title). Title must start with uppercase letter.
_INLINE_SECTION_PAT = re.compile(
    r"^(\d+(?:\.\d+){0,3}|[A-Z])\.([A-Z][A-Za-z][A-Za-z0-9 ]*?)(?=\s|$)",
    re.MULTILINE,
)

# Well-known unnumbered section titles in academic papers.
_NAMED_SECTION_TITLES = {
    "abstract", "introduction", "references", "acknowledgments",
    "acknowledgements", "appendix", "conclusion", "conclusions",
    "related work", "discussion", "experiments", "methods", "methodology",
}

# Reference list entry — bracketed citation marker at line start.
_REFERENCE_LINE_PAT = re.compile(r"^\s*\[\d+\]\s+\S", re.MULTILINE)

# Figure / table caption markers (with or without bold).
_FIGURE_CAPTION_PAT = re.compile(r"^(?:\*{0,2})(Figure|Fig\.?)\s*\d+", re.MULTILINE | re.IGNORECASE)
_TABLE_CAPTION_PAT  = re.compile(r"^(?:\*{0,2})Table\s*\d+",            re.MULTILINE | re.IGNORECASE)

# Equation markers — LaTeX block math or standalone equation refs.
_EQUATION_PAT = re.compile(r"(\$\$.+?\$\$|\\begin\{equation\}|\\\[.+?\\\])", re.DOTALL)

# Author-block heuristics — emails and affiliation-y tokens.
_EMAIL_PAT = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_AFFILIATION_TOKENS = re.compile(
    r"\b(University|Institute|Research|Laboratory|Department|School of|Microsoft|Google|Meta|Facebook|OpenAI|DeepMind|Stanford|MIT|Berkeley|CMU)\b",
    re.IGNORECASE,
)


def _promote_inline_section_headers(text: str) -> str:
    """Insert markdown headings where research-paper section headers appear inline.

    Real-world extractor output (e.g. Docling on multi-column PDFs) often glues
    section numbers to body text — "1.Introduction unsurprising) and then…".
    Without explicit headings, every chunk ends up with section=None.

    Heuristic:
    - At line start, match `\\d+(\\.\\d+)*\\.[A-Z][A-Za-z…]` or `[A-Z]\\.[A-Z][A-Za-z…]`.
    - Convert to `## <num> <title>` (or `### …` for subsections like 3.1).
    - Trailing prose on the same line is pushed to the next line.
    - Existing markdown headings are left untouched.
    """
    out: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            out.append(line)
            continue
        m = _INLINE_SECTION_PAT.match(line)
        if not m:
            out.append(line)
            continue
        num = m.group(1)
        title = m.group(2).strip()
        # Decide heading depth from number tier; letter prefix → appendix → ##
        depth = num.count(".") + 2          # "3" → 2 (##), "3.1" → 3 (###), "3.1.2" → 4
        depth = min(depth, 4)
        heading = "#" * depth + f" {num}. {title}"
        rest = line[m.end():].strip()
        out.append(heading)
        if rest:
            out.append(rest)
    return "\n".join(out)


def _classify_content_type(body: str, section: str | None) -> str:
    """Return one of: text|table|equation|figure_caption|reference|appendix."""
    sec = (section or "").lower()
    if sec.startswith("references") or _REFERENCE_LINE_PAT.search(body):
        # References dominate when ≥40 % of non-blank lines look like [N] entries.
        lines = [ln for ln in body.splitlines() if ln.strip()]
        ref_lines = len(_REFERENCE_LINE_PAT.findall(body))
        if lines and ref_lines / max(1, len(lines)) >= 0.4:
            return "reference"
    if sec.startswith("appendix") or re.match(r"^[A-Z]\.\s", sec):
        return "appendix"
    if _TABLE_BLOCK_PAT.search(body):
        return "table"
    if _EQUATION_PAT.search(body):
        return "equation"
    if _FIGURE_CAPTION_PAT.search(body) or _TABLE_CAPTION_PAT.search(body):
        # Caption-dominant only when caption text accounts for most of the body.
        if len(body) < 400:
            return "figure_caption"
    return "text"


def _table_embedding_text(body: str, section: str | None) -> tuple[str, str | None]:
    """Build (embedding_text, table_markdown) for a table-dominant chunk.

    Markdown tables embed poorly because pipe separators dilute semantic signal.
    We extract the largest table, build a prose summary describing its columns
    and row count, then concatenate with any surrounding prose so retrieval
    still surfaces the table on relevant queries.
    """
    matches = _TABLE_BLOCK_PAT.findall(body)
    if not matches:
        return body, None
    biggest = max(matches, key=len)
    lines = [ln for ln in biggest.strip().split("\n") if ln.strip().startswith("|")]
    header_cells: list[str] = []
    if lines:
        header_cells = [c.strip() for c in lines[0].strip("|").split("|") if c.strip()]
    cols = len(header_cells)
    data_rows = max(0, len(lines) - 2)
    sec_label = f" in section '{section}'" if section else ""
    if header_cells:
        summary = (
            f"Table{sec_label}: {data_rows} rows × {cols} columns. "
            f"Columns: {', '.join(header_cells)}."
        )
    else:
        summary = f"Table{sec_label}: {data_rows} rows × {cols} columns."
    # Prose surrounding the table (captions etc.) is high-value for retrieval.
    prose = _TABLE_BLOCK_PAT.sub("", body).strip()
    embedding_text = (prose + "\n\n" + summary).strip() if prose else summary
    return embedding_text, biggest.strip()


def _is_low_value_author_block(body: str) -> bool:
    """True if body is just authors / affiliations / emails (no real content)."""
    stripped = body.strip()
    if not stripped or estimate_tokens(stripped) > 80:
        return False
    has_email   = bool(_EMAIL_PAT.search(stripped))
    has_affil   = bool(_AFFILIATION_TOKENS.search(stripped))
    if not (has_email or has_affil):
        return False
    # Heuristic: short block dominated by capitalised names / orgs / emails.
    words = stripped.split()
    if not words:
        return False
    capped = sum(1 for w in words if w[:1].isupper())
    return capped / len(words) >= 0.5


def _strip_artifacts(text: str) -> str:
    """Remove extractor junk comments and collapse the whitespace they leave behind."""
    for pat in _ARTIFACT_PATTERNS:
        text = pat.sub("", text)
    # Collapse blank lines created by removed markers
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _strip_page_markers(text: str) -> tuple[str, int | None]:
    """Strip <!-- page: N --> / <!-- page-break --> markers.

    Returns (cleaned_text, first_page_number_seen_or_None).
    A bare page-break marker bumps an internal counter starting at 1.
    """
    first_page: int | None = None

    # Numbered markers carry authoritative page numbers
    m = _PAGE_MARKER_NUM_PAT.search(text)
    if m:
        try:
            first_page = int(m.group(1))
        except ValueError:
            first_page = None
    text = _PAGE_MARKER_NUM_PAT.sub("", text)

    # Bare page-break markers — caller's running counter handles real numbering
    text = _PAGE_MARKER_ANY_PAT.sub("", text)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text, first_page


def _strip_leading_heading(body: str, section_title: str | None) -> str:
    """Remove the leading heading line if it matches the section_title.

    Keeps lower-level headings (e.g. 3.1 under section "3") intact when they
    appear deeper in the body — only the first heading line is dropped.
    """
    lines = body.lstrip().split("\n")
    if not lines:
        return body
    first = lines[0].strip()
    if not first.startswith("#"):
        return body
    # Strip the leading "#### " markers and compare with section_title
    stripped = re.sub(r"^#{1,6}\s+", "", first).strip()
    if section_title and stripped == section_title.strip():
        return "\n".join(lines[1:]).lstrip()
    # No section title (preamble) — drop bare heading lines anyway so content
    # is prose-only. Section already carried in metadata.
    if section_title is None:
        return "\n".join(lines[1:]).lstrip()
    return body


def _detect_tables(body: str) -> tuple[bool, str | None]:
    """Return (has_table, summary).

    summary describes the largest detected table (rows × cols + header preview).
    Tables are left in the chunk content so retrieval can still surface them.
    """
    matches = _TABLE_BLOCK_PAT.findall(body)
    if not matches:
        return False, None

    biggest = max(matches, key=len)
    lines = [ln for ln in biggest.strip().split("\n") if ln.strip().startswith("|")]
    if len(lines) < 2:
        return True, "table (unparsed)"
    header_cells = [c.strip() for c in lines[0].strip("|").split("|") if c.strip()]
    # data rows = all rows except header (line 0) and separator (line 1)
    data_rows = max(0, len(lines) - 2)
    cols = len(header_cells) or len(lines[1].strip("|").split("|"))
    header_preview = ", ".join(header_cells[:6]) if header_cells else ""
    if header_preview:
        return True, f"table {data_rows} rows × {cols} cols (columns: {header_preview})"
    return True, f"table {data_rows} rows × {cols} cols"


def _section_segments(text: str) -> list[tuple[str | None, str]]:
    """Split text into (section_title, body) segments on #/##/### headings.

    Text before the first heading is returned with section=None (preamble).
    Document-type agnostic: a document with no headings yields a single
    (None, text) segment.
    """
    matches = list(_SECTION_HEADING_PAT.finditer(text))
    if not matches:
        return [(None, text)]

    segments: list[tuple[str | None, str]] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        segments.append((None, preamble))

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = m.group(2).strip() or None
        body = text[start:end].strip()
        if body:
            segments.append((title, body))

    return segments


def _walk_with_pages(text: str) -> list[tuple[int | None, str]]:
    """Split text on page markers, returning [(page_no, slice_text), ...].

    If no page markers are present, returns [(None, text)].
    """
    # Numbered markers take priority — they carry real page numbers.
    if _PAGE_MARKER_NUM_PAT.search(text):
        pat = _PAGE_MARKER_NUM_PAT
        cursor = 0
        out: list[tuple[int | None, str]] = []
        current_page: int | None = None
        for m in pat.finditer(text):
            chunk = text[cursor:m.start()]
            if chunk.strip():
                out.append((current_page, chunk))
            try:
                current_page = int(m.group(1))
            except ValueError:
                pass
            cursor = m.end()
        tail = text[cursor:]
        if tail.strip():
            out.append((current_page, tail))
        return out

    # Bare page-break markers: increment a counter, starting at 1.
    if _PAGE_MARKER_ANY_PAT.search(text):
        pat = _PAGE_MARKER_ANY_PAT
        cursor = 0
        out2: list[tuple[int | None, str]] = []
        page = 1
        for m in pat.finditer(text):
            chunk = text[cursor:m.start()]
            if chunk.strip():
                out2.append((page, chunk))
            page += 1
            cursor = m.end()
        tail = text[cursor:]
        if tail.strip():
            out2.append((page, tail))
        return out2

    return [(None, text)]


def _section_segments_with_pages(text: str) -> list[tuple[str | None, str, int | None]]:
    """Like _section_segments but tracks the page number each segment starts on."""
    slices = _walk_with_pages(text)
    segments: list[tuple[str | None, str, int | None]] = []
    for page, slice_text in slices:
        for section, body in _section_segments(slice_text):
            segments.append((section, body, page))
    return segments


# Heading walker that also tracks subsection (H3+) under the running H1/H2.
_ANY_HEADING_PAT = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)


def _section_segments_with_subsections(
    text: str,
) -> list[tuple[str | None, str | None, str, int | None]]:
    """Walk text into (section, subsection, body, page) tuples.

    - H1/H2 reset the running section; subsection cleared.
    - H3+ sets the running subsection; section sticks.
    - Page numbers come from page-marker walk.
    """
    slices = _walk_with_pages(text)
    out: list[tuple[str | None, str | None, str, int | None]] = []
    section: str | None = None
    subsection: str | None = None

    for page, slice_text in slices:
        matches = list(_ANY_HEADING_PAT.finditer(slice_text))
        if not matches:
            body = slice_text.strip()
            if body:
                out.append((section, subsection, body, page))
            continue

        preamble = slice_text[: matches[0].start()].strip()
        if preamble:
            out.append((section, subsection, preamble, page))

        for i, m in enumerate(matches):
            level = len(m.group(1))
            title = m.group(2).strip() or None
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(slice_text)
            body = slice_text[start:end].strip()
            if level <= 2:
                section = title
                subsection = None
            else:
                subsection = title
            if body:
                out.append((section, subsection, body, page))

    return out


def _enforce_size_bounds(
    pieces: list[tuple[str | None, str, int | None]],
    hard_max: int,
    hard_min: int,
) -> list[tuple[str | None, str, int | None]]:
    """Merge tiny same-section pieces and split oversized ones.

    Tiny rule: a piece with < hard_min tokens is merged into the previous
    piece when (a) the previous piece exists, (b) sections match, and
    (c) the merged result stays under hard_max.

    Oversize rule: a piece with > hard_max tokens is paragraph-split until
    every part fits.
    """
    # Split oversize first so all input to merging is bounded above.
    expanded: list[tuple[str | None, str, int | None]] = []
    for section, body, page in pieces:
        if estimate_tokens(body) <= hard_max:
            expanded.append((section, body, page))
            continue
        for part in _split_on_paragraphs(body, hard_max):
            if part.strip():
                expanded.append((section, part.strip(), page))

    # Merge tiny chunks forward — combine with previous if section matches.
    merged: list[tuple[str | None, str, int | None]] = []
    for section, body, page in expanded:
        if (
            merged
            and estimate_tokens(body) < hard_min
            and merged[-1][0] == section
            and estimate_tokens(merged[-1][1]) + estimate_tokens(body) <= hard_max
        ):
            prev_section, prev_body, prev_page = merged[-1]
            merged[-1] = (prev_section, prev_body + "\n\n" + body, prev_page)
        else:
            merged.append((section, body, page))

    # Try once more, this time merging tiny chunks into the NEXT piece — covers
    # leading tiny chunks that had no previous neighbour to absorb them.
    final: list[tuple[str | None, str, int | None]] = []
    i = 0
    while i < len(merged):
        section, body, page = merged[i]
        if (
            estimate_tokens(body) < hard_min
            and i + 1 < len(merged)
            and merged[i + 1][0] == section
            and estimate_tokens(body) + estimate_tokens(merged[i + 1][1]) <= hard_max
        ):
            next_section, next_body, next_page = merged[i + 1]
            final.append((section, body + "\n\n" + next_body, page or next_page))
            i += 2
        else:
            final.append((section, body, page))
            i += 1

    return final


def chunk_markdown_structured(
    text: str,
    max_tokens: int | None = None,
    overlap_tokens: int | None = None,
    *,
    source_file: str | None = None,
    document_type: str | None = None,
) -> list[dict]:
    """Split *text* into retrieval-oriented chunks with rich metadata.

    Pipeline:
    1. Strip extractor artefacts (`<!-- image -->`, `<!-- formula-not-decoded -->`, …).
    2. Walk page markers (`<!-- page: N -->` or `<!-- page-break -->`), assigning
       a starting page to every chunk; markers themselves are removed.
    3. Split on heading boundaries → one section per chunk. The section title
       is stored in metadata; the leading `## Title` line is stripped from
       chunk content so embeddings see prose only.
    4. Paragraph-split any section larger than the per-call hard ceiling.
    5. When defaults are in use, enforce the soft 200–500-token target band
       (hard floor 100, hard cap 600): tiny same-section pieces merge into
       neighbours, oversized ones split further.
    6. Apply cross-chunk overlap (tail of previous content) and emit metadata.

    Args:
        text:           Markdown to split.
        max_tokens:     Hard token bound per chunk. None → DEFAULT_RAG_MAX_TOKENS
                        and additionally activates the soft 200–500 band.
        overlap_tokens: Tokens repeated at boundaries. None → DEFAULT_RAG_OVERLAP_TOKENS.
        source_file:    Original filename, copied verbatim into every chunk.
        document_type:  Document-type label, copied verbatim into every chunk.

    Returns:
        List of chunk dicts. Required keys: chunk_id, index, section, content,
        token_count, word_count, char_count, overlap_prev_tokens, page_number,
        source_file, document_type, has_table, table_summary.
    """
    using_defaults = max_tokens is None or max_tokens <= 0
    if using_defaults:
        max_tokens = DEFAULT_RAG_MAX_TOKENS
    if overlap_tokens is None:
        overlap_tokens = DEFAULT_RAG_OVERLAP_TOKENS

    text = (text or "").strip()
    if not text:
        return []

    # 1. Artefact strip (page markers are handled in step 2 — keep them for now)
    text = _strip_artifacts(text)

    # 1b. Promote inline section headers (e.g. "3.1.ResidualLearning") so
    #     downstream walkers can split on them. Without this, garbled
    #     extractor output collapses to section=None everywhere.
    text = _promote_inline_section_headers(text)

    # 2 + 3. Section + subsection + page walk.
    raw_pieces: list[tuple[str | None, str | None, str, int | None]] = []
    for section, subsection, body, page in _section_segments_with_subsections(text):
        # Strip the leading heading line (it's already captured as metadata).
        body = _strip_leading_heading(body, subsection or section)
        body = body.strip()
        if not body:
            continue
        raw_pieces.append((section, subsection, body, page))

    if not raw_pieces:
        return []

    # 3b. Suppress low-value author / affiliation / email blocks — merge them
    #     into the next piece if same section, otherwise drop.
    cleaned: list[tuple[str | None, str | None, str, int | None]] = []
    pending_author_block: str | None = None
    for section, subsection, body, page in raw_pieces:
        if _is_low_value_author_block(body):
            pending_author_block = (pending_author_block + "\n\n" + body) if pending_author_block else body
            continue
        if pending_author_block and using_defaults:
            # Drop author block entirely under defaults — pure metadata noise.
            pending_author_block = None
        elif pending_author_block:
            body = pending_author_block + "\n\n" + body
            pending_author_block = None
        cleaned.append((section, subsection, body, page))
    raw_pieces = cleaned

    # 4. Force-split oversize sections against the per-call ceiling.
    bounded: list[tuple[str | None, str | None, str, int | None]] = []
    for section, subsection, body, page in raw_pieces:
        if estimate_tokens(body) <= max_tokens:
            bounded.append((section, subsection, body, page))
        else:
            for part in _force_split(body, max_tokens):
                if part.strip():
                    bounded.append((section, subsection, part.strip(), page))

    # 5. Size-band enforcement (always — production RAG requirement).
    bounded = _enforce_size_bounds_v2(
        bounded,
        hard_max=_HARD_MAX_TOKENS if using_defaults else max_tokens,
        hard_min=_HARD_MIN_TOKENS,
    )

    # 5b. Forward-fill section from previous chunk when a piece still lacks one
    #     (e.g. tail content after a section ended on a page break).
    last_section: str | None = None
    last_subsection: str | None = None
    propagated: list[tuple[str | None, str | None, str, int | None]] = []
    for section, subsection, body, page in bounded:
        if section:
            last_section = section
        elif last_section:
            section = last_section
        if subsection:
            last_subsection = subsection
        elif section != last_section:
            last_subsection = None
        propagated.append((section, subsection, body, page))
    bounded = propagated

    # 5c. Leading content with no section header gets labeled "Preamble" so the
    #     retrieval contract (section is never null) is upheld. If the preamble
    #     contains the word "Abstract" on its own line, prefer that.
    label_for_preamble: str | None = None
    if bounded and bounded[0][0] is None:
        first_body = bounded[0][2]
        if re.search(r"(?i)\babstract\b", first_body[:200]):
            label_for_preamble = "Abstract"
        else:
            label_for_preamble = "Preamble"
    if label_for_preamble:
        relabeled: list[tuple[str | None, str | None, str, int | None]] = []
        for section, subsection, body, page in bounded:
            if section is None:
                section = label_for_preamble
            relabeled.append((section, subsection, body, page))
        bounded = relabeled

    # 6. Apply overlap + emit metadata. Overlap is capped so the resulting
    #    chunk stays within hard_max (overlap eats into the body budget rather
    #    than blowing past the ceiling — production retrievers reject oversized
    #    chunks outright).
    chunks: list[dict] = []
    prev_body: str | None = None       # raw body of previous chunk (no overlap)
    ceiling = _HARD_MAX_TOKENS if using_defaults else max_tokens
    for idx, (section, subsection, body, page) in enumerate(bounded, start=1):
        overlap_used = 0
        content = body
        if prev_body and overlap_tokens > 0:
            body_tok = estimate_tokens(body)
            budget = max(0, min(overlap_tokens, ceiling - body_tok))
            if budget > 0:
                tail = _tail_tokens(prev_body, budget)
                # Skip overlap when the tail paragraph is already at the head
                # of the current body (deduplicate boundary repetition).
                if tail and tail.strip() and tail.strip() not in body:
                    overlap_used = estimate_tokens(tail)
                    content = tail + "\n\n" + body
        prev_body = body                # NOTE: store raw body, not body+overlap

        content_type = _classify_content_type(content, section)
        has_table = content_type == "table"
        table_summary: str | None = None
        table_markdown: str | None = None
        embedding_text = content
        if has_table:
            embedding_text, table_markdown = _table_embedding_text(content, section)
            _, table_summary = _detect_tables(content)
        elif _TABLE_BLOCK_PAT.search(content):
            # Table present but not dominant — still record summary.
            _, table_summary = _detect_tables(content)

        chunks.append({
            "chunk_id": f"chunk_{idx:03d}",
            "index": idx,
            "section": section,
            "subsection": subsection,
            "content": content,
            "content_type": content_type,
            "token_count": estimate_tokens(content),
            "word_count": len(content.split()),
            "char_count": len(content),
            "overlap_prev_tokens": overlap_used,
            "page_number": page,
            "source_file": source_file,
            "document_type": document_type,
            "has_table": has_table or table_markdown is not None or table_summary is not None,
            "table_summary": table_summary,
            "table_markdown": table_markdown,
            "embedding_text": embedding_text,
        })

    return chunks


def _enforce_size_bounds_v2(
    pieces: list[tuple[str | None, str | None, str, int | None]],
    hard_max: int,
    hard_min: int,
) -> list[tuple[str | None, str | None, str, int | None]]:
    """Merge tiny same-section pieces; split oversized ones.

    Same shape as _enforce_size_bounds but carries subsection through.
    Merging rules:
    - Tiny piece + previous piece if (a) sections match, (b) merged ≤ hard_max.
    - Subsection collapses to the previous one when merging crosses subsections.
    """
    expanded: list[tuple[str | None, str | None, str, int | None]] = []
    for section, subsection, body, page in pieces:
        if estimate_tokens(body) <= hard_max:
            expanded.append((section, subsection, body, page))
            continue
        for part in _force_split(body, hard_max):
            if part.strip():
                expanded.append((section, subsection, part.strip(), page))

    def _sections_compatible(a: str | None, b: str | None) -> bool:
        # Same section, or one side has no section yet (orphan preamble / tail).
        return a == b or a is None or b is None

    merged: list[tuple[str | None, str | None, str, int | None]] = []
    for section, subsection, body, page in expanded:
        if (
            merged
            and estimate_tokens(body) < hard_min
            and _sections_compatible(merged[-1][0], section)
            and estimate_tokens(merged[-1][2]) + estimate_tokens(body) <= hard_max
        ):
            p_sec, p_sub, p_body, p_page = merged[-1]
            merged[-1] = (p_sec or section, p_sub or subsection, p_body + "\n\n" + body, p_page)
        else:
            merged.append((section, subsection, body, page))

    final: list[tuple[str | None, str | None, str, int | None]] = []
    i = 0
    while i < len(merged):
        section, subsection, body, page = merged[i]
        if (
            estimate_tokens(body) < hard_min
            and i + 1 < len(merged)
            and _sections_compatible(section, merged[i + 1][0])
            and estimate_tokens(body) + estimate_tokens(merged[i + 1][2]) <= hard_max
        ):
            n_sec, n_sub, n_body, n_page = merged[i + 1]
            final.append((section or n_sec, subsection or n_sub, body + "\n\n" + n_body, page or n_page))
            i += 2
        else:
            final.append((section, subsection, body, page))
            i += 1

    return final


def _force_split(text: str, max_tokens: int) -> list[str]:
    """Recursive split: paragraphs → lines → sentences → hard token slice.

    Use when a body has no paragraph breaks (common for table-dominated chunks
    produced by PDF extractors that jam every cell onto one line group).
    """
    if estimate_tokens(text) <= max_tokens or not text.strip():
        return [text.strip()] if text.strip() else []

    # Try paragraph split first
    paras = re.split(r"\n\n+", text)
    if len(paras) > 1:
        out: list[str] = []
        for p in paras:
            out.extend(_force_split(p, max_tokens))
        return _coalesce(out, max_tokens)

    # Line-level split
    lines = text.split("\n")
    if len(lines) > 1:
        out2: list[str] = []
        for ln in lines:
            out2.extend(_force_split(ln, max_tokens))
        return _coalesce(out2, max_tokens)

    # Sentence split
    sents = re.split(r"(?<=[.!?])\s+", text)
    if len(sents) > 1:
        out3: list[str] = []
        for s in sents:
            out3.extend(_force_split(s, max_tokens))
        return _coalesce(out3, max_tokens)

    # Last resort: hard slice by char position scaled to tokens.
    avg_chars_per_token = max(1, len(text) // max(1, estimate_tokens(text)))
    window = max_tokens * avg_chars_per_token
    return [text[i:i + window] for i in range(0, len(text), window) if text[i:i + window].strip()]


def _coalesce(parts: list[str], max_tokens: int) -> list[str]:
    """Greedily merge consecutive parts up to max_tokens.

    Uses a 10% safety margin against BPE tokenizer drift: joining N parts can
    produce more tokens than the sum of estimate_tokens(part) because the BPE
    merges across boundaries shift. A 90% target keeps the joined output under
    max_tokens in practice.
    """
    target = max(1, int(max_tokens * 0.9))
    out: list[str] = []
    buf: list[str] = []
    buf_tok = 0
    for p in parts:
        if not p.strip():
            continue
        pt = estimate_tokens(p)
        if buf and buf_tok + pt > target:
            out.append("\n".join(buf).strip())
            buf, buf_tok = [], 0
        buf.append(p)
        buf_tok += pt
    if buf:
        out.append("\n".join(buf).strip())
    # Post-check: any output still over the hard cap (rare BPE outlier) gets
    # hard-sliced by character window so the ceiling holds.
    final: list[str] = []
    for s in out:
        if not s:
            continue
        if estimate_tokens(s) <= max_tokens:
            final.append(s)
            continue
        ratio = max(1, len(s) // max(1, estimate_tokens(s)))
        window = max(1, int(max_tokens * ratio * 0.9))
        for i in range(0, len(s), window):
            slice_ = s[i:i + window].strip()
            if slice_:
                final.append(slice_)
    return final


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

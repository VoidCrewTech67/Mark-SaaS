"""
optimizer/passes/paragraph_dedup.py – Global paragraph deduplication.

Algorithm
=========

Unlike simple consecutive-duplicate removal, this pass detects
duplicate paragraphs **across the entire document**, preserves the
first occurrence, and removes all subsequent copies.

Three matching modes are supported:

1. **Exact** — Raw text comparison via deterministic hashing.
   Complexity: O(n).

2. **Normalized** — Text is NFKC-normalised, lowercased, whitespace-
   collapsed, and punctuation-stripped before hashing.  Catches
   formatting variants.  Complexity: O(n).

3. **Fuzzy** — Two-stage approach:

   a. *SimHash fingerprinting* computes a 64-bit locality-sensitive
      hash from word trigrams.  Paragraphs whose Hamming distance
      is within ``max_hamming_distance`` are *candidates*.
   b. *SequenceMatcher* verifies candidates above the Hamming
      threshold.  Only pairs with ``ratio ≥ similarity_threshold``
      are flagged as duplicates.

   Expected complexity: O(n) for typical documents with few
   near-duplicates.  Worst case O(n²) when many paragraphs are
   near-similar.

Paragraph splitting
-------------------

The document is split at blank-line boundaries.  Fenced code
blocks (````` ``` … ``` `````) are treated as atomic, indivisible
units.  Heading paragraphs and code blocks are *protected* and
are never removed, even if duplicated.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Constants ─────────────────────────────────────────────────────────────────

_HASH_BITS = 64
_ATX_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
_SETEXT_UNDERLINE_RE = re.compile(r"^(?:={3,}|-{3,})\s*$")
_FENCED_CODE_RE = re.compile(r"^\s*```")
_EXCESS_BLANK_RE = re.compile(r"\n{3,}")
_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]", re.UNICODE)


# ── Internal data structures ─────────────────────────────────────────────────

@dataclass
class _Paragraph:
    """A block of text separated by blank lines."""
    index: int           # sequential paragraph number (0-based)
    text: str            # joined non-empty lines (for comparison)
    start_line: int      # 0-based line index in original doc (inclusive)
    end_line: int        # 0-based line index (exclusive)
    is_protected: bool   # heading or code block — never removed


@dataclass
class _DuplicateGroup:
    """A group of paragraphs with the same content."""
    first_index: int              # paragraph index of first occurrence
    first_line: int               # line number of first occurrence
    duplicate_indices: List[int]  # paragraph indices of later copies
    duplicate_lines: List[int]    # line numbers of later copies
    preview: str                  # truncated text for metrics


# ── Pass implementation ──────────────────────────────────────────────────────

@register_pass
class GlobalParagraphDeduplicationPass(OptimizerPass):
    """Detect and remove duplicate paragraphs across the entire document.

    Config params
    ~~~~~~~~~~~~~

    ======================== ================== ================================
    Param                    Default            Description
    ======================== ================== ================================
    mode                     ``"normalized"``   ``"exact"`` / ``"normalized"``
                                                / ``"fuzzy"``
    similarity_threshold     ``0.85``           Minimum SequenceMatcher ratio
                                                for fuzzy mode.
    min_paragraph_length     ``20``             Skip paragraphs shorter than
                                                this many characters.
    preserve_headings        ``True``           Never remove heading paragraphs.
    preserve_code_blocks     ``True``           Never remove code blocks.
    max_hamming_distance     ``12``             SimHash Hamming distance filter
                                                for fuzzy mode candidates.
    ======================== ================== ================================
    """

    # ── OptimizerPass interface ───────────────────────────────────────────

    @property
    def name(self) -> str:
        return "global_paragraph_deduplication"

    @property
    def description(self) -> str:
        return (
            "Detect and remove duplicate paragraphs across the entire "
            "document.  Preserves first occurrence, removes later copies."
        )

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=30,  # after section-removal passes
            params={
                "mode": "normalized",
                "similarity_threshold": 0.85,
                "min_paragraph_length": 20,
                "preserve_headings": True,
                "preserve_code_blocks": True,
                "max_hamming_distance": 12,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError

        p = config.params
        mode = p.get("mode", "normalized")
        if mode not in ("exact", "normalized", "fuzzy"):
            raise PassConfigError(
                self.name,
                f"mode must be 'exact', 'normalized', or 'fuzzy', "
                f"got {mode!r}",
            )
        threshold = p.get("similarity_threshold", 0.85)
        if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
            raise PassConfigError(
                self.name,
                f"similarity_threshold must be in (0, 1], got {threshold!r}",
            )
        min_len = p.get("min_paragraph_length", 20)
        if not isinstance(min_len, int) or min_len < 0:
            raise PassConfigError(
                self.name,
                f"min_paragraph_length must be a non-negative integer, "
                f"got {min_len!r}",
            )
        max_hd = p.get("max_hamming_distance", 12)
        if not isinstance(max_hd, int) or max_hd < 0:
            raise PassConfigError(
                self.name,
                f"max_hamming_distance must be a non-negative integer, "
                f"got {max_hd!r}",
            )

    # ── Main execution ────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        mode: str = p.get("mode", "normalized")

        if not ctx.content.strip():
            self._report_metrics(ctx, [], [], 0, 0, mode, 0.0)
            return ctx

        t_start = time.perf_counter()

        # ── Step 1: Split into paragraphs ─────────────────────────────────
        paragraphs = self._split_paragraphs(
            ctx.content,
            preserve_headings=p.get("preserve_headings", True),
            preserve_code_blocks=p.get("preserve_code_blocks", True),
        )

        if not paragraphs:
            self._report_metrics(ctx, [], [], 0, 0, mode, 0.0)
            return ctx

        min_len: int = p.get("min_paragraph_length", 20)

        # ── Step 2: Detect duplicates ─────────────────────────────────────
        if mode == "exact":
            to_remove, groups = self._detect_exact(paragraphs, min_len)
        elif mode == "normalized":
            to_remove, groups = self._detect_normalized(paragraphs, min_len)
        else:  # fuzzy
            threshold = p.get("similarity_threshold", 0.85)
            max_hd = p.get("max_hamming_distance", 12)
            to_remove, groups = self._detect_fuzzy(
                paragraphs, min_len, threshold, max_hd,
            )

        elapsed = time.perf_counter() - t_start
        protected = sum(1 for pa in paragraphs if pa.is_protected)

        if not to_remove:
            self._report_metrics(
                ctx, paragraphs, groups, protected, 0, mode, elapsed,
            )
            return ctx

        # ── Step 3: Remove duplicates ─────────────────────────────────────
        ctx.content = self._rebuild(ctx.content, paragraphs, to_remove)

        self._report_metrics(
            ctx, paragraphs, groups, protected, len(to_remove), mode,
            elapsed,
        )
        return ctx

    # ── Paragraph splitting ───────────────────────────────────────────────

    @classmethod
    def _split_paragraphs(
        cls,
        content: str,
        *,
        preserve_headings: bool = True,
        preserve_code_blocks: bool = True,
    ) -> List[_Paragraph]:
        """Split *content* into paragraph blocks.

        Fenced code blocks are treated as indivisible units.
        """
        lines = content.split("\n")
        paragraphs: List[_Paragraph] = []
        buf: List[str] = []
        buf_start = 0
        in_code = False
        idx = 0

        def _flush(end: int, *, is_code: bool = False) -> None:
            nonlocal idx
            if not buf:
                return
            text = "\n".join(buf)
            protected = False
            if is_code and preserve_code_blocks:
                protected = True
            elif preserve_headings and cls._is_heading(buf):
                protected = True
            paragraphs.append(_Paragraph(
                index=idx,
                text=text,
                start_line=buf_start,
                end_line=end,
                is_protected=protected,
            ))
            idx += 1

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Toggle code fences
            if _FENCED_CODE_RE.match(stripped):
                if not in_code:
                    _flush(i)
                    buf = [line]
                    buf_start = i
                    in_code = True
                else:
                    buf.append(line)
                    _flush(i + 1, is_code=True)
                    buf = []
                    in_code = False
                continue

            if in_code:
                buf.append(line)
                continue

            if stripped == "":
                _flush(i)
                buf = []
            else:
                if not buf:
                    buf_start = i
                buf.append(line)

        _flush(len(lines), is_code=in_code)
        return paragraphs

    @staticmethod
    def _is_heading(lines: List[str]) -> bool:
        """Check whether a paragraph block is a heading."""
        if not lines:
            return False
        first = lines[0].strip()
        if _ATX_HEADING_RE.match(first):
            return True
        if len(lines) == 2 and _SETEXT_UNDERLINE_RE.match(lines[1].strip()):
            return True
        return False

    # ── Duplicate detection: exact ────────────────────────────────────────

    @classmethod
    def _detect_exact(
        cls,
        paragraphs: List[_Paragraph],
        min_len: int,
    ) -> Tuple[Set[int], List[_DuplicateGroup]]:
        """Exact text comparison via deterministic hashing."""
        seen: Dict[int, int] = {}  # hash → first paragraph index
        to_remove: Set[int] = set()
        group_map: Dict[int, _DuplicateGroup] = {}  # first_idx → group

        for para in paragraphs:
            if para.is_protected or len(para.text) < min_len:
                continue

            h = _deterministic_hash(para.text)

            if h in seen:
                first_idx = seen[h]
                to_remove.add(para.index)
                if first_idx not in group_map:
                    first_para = paragraphs[first_idx]
                    group_map[first_idx] = _DuplicateGroup(
                        first_index=first_idx,
                        first_line=first_para.start_line,
                        duplicate_indices=[],
                        duplicate_lines=[],
                        preview=first_para.text[:100],
                    )
                group_map[first_idx].duplicate_indices.append(para.index)
                group_map[first_idx].duplicate_lines.append(para.start_line)
            else:
                seen[h] = para.index

        return to_remove, list(group_map.values())

    # ── Duplicate detection: normalized ───────────────────────────────────

    @classmethod
    def _detect_normalized(
        cls,
        paragraphs: List[_Paragraph],
        min_len: int,
    ) -> Tuple[Set[int], List[_DuplicateGroup]]:
        """Normalized text comparison — catches formatting variants."""
        seen: Dict[int, int] = {}
        to_remove: Set[int] = set()
        group_map: Dict[int, _DuplicateGroup] = {}

        for para in paragraphs:
            if para.is_protected or len(para.text) < min_len:
                continue

            norm = _normalize(para.text)
            h = _deterministic_hash(norm)

            if h in seen:
                first_idx = seen[h]
                to_remove.add(para.index)
                if first_idx not in group_map:
                    first_para = paragraphs[first_idx]
                    group_map[first_idx] = _DuplicateGroup(
                        first_index=first_idx,
                        first_line=first_para.start_line,
                        duplicate_indices=[],
                        duplicate_lines=[],
                        preview=first_para.text[:100],
                    )
                group_map[first_idx].duplicate_indices.append(para.index)
                group_map[first_idx].duplicate_lines.append(para.start_line)
            else:
                seen[h] = para.index

        return to_remove, list(group_map.values())

    # ── Duplicate detection: fuzzy ────────────────────────────────────────

    @classmethod
    def _detect_fuzzy(
        cls,
        paragraphs: List[_Paragraph],
        min_len: int,
        threshold: float,
        max_hamming: int,
    ) -> Tuple[Set[int], List[_DuplicateGroup]]:
        """Two-stage fuzzy matching: SimHash filter + SequenceMatcher.

        Stage 1: Normalised hash catches exact-after-normalisation
        duplicates in O(1).

        Stage 2: For remaining paragraphs, SimHash fingerprints are
        compared via Hamming distance.  Candidates within
        ``max_hamming`` bits are verified with ``SequenceMatcher``.
        """
        seen_norm: Dict[int, int] = {}  # norm_hash → first_idx
        fingerprints: List[Tuple[int, int, str]] = []  # (simhash, idx, norm)
        to_remove: Set[int] = set()
        group_map: Dict[int, _DuplicateGroup] = {}

        def _record_dup(first_idx: int, dup_para: _Paragraph) -> None:
            to_remove.add(dup_para.index)
            if first_idx not in group_map:
                first_para = paragraphs[first_idx]
                group_map[first_idx] = _DuplicateGroup(
                    first_index=first_idx,
                    first_line=first_para.start_line,
                    duplicate_indices=[],
                    duplicate_lines=[],
                    preview=first_para.text[:100],
                )
            group_map[first_idx].duplicate_indices.append(dup_para.index)
            group_map[first_idx].duplicate_lines.append(dup_para.start_line)

        for para in paragraphs:
            if para.is_protected or len(para.text) < min_len:
                continue

            norm = _normalize(para.text)
            nh = _deterministic_hash(norm)

            # Stage 1: exact normalised match
            if nh in seen_norm:
                _record_dup(seen_norm[nh], para)
                continue

            # Stage 2: SimHash candidate search
            sh = _simhash(norm)
            found = False
            for prev_sh, prev_idx, prev_norm in fingerprints:
                if _hamming_distance(sh, prev_sh) <= max_hamming:
                    ratio = SequenceMatcher(None, norm, prev_norm).ratio()
                    if ratio >= threshold:
                        _record_dup(prev_idx, para)
                        found = True
                        break

            if not found:
                seen_norm[nh] = para.index
                fingerprints.append((sh, para.index, norm))

        return to_remove, list(group_map.values())

    # ── Document reconstruction ───────────────────────────────────────────

    @staticmethod
    def _rebuild(
        content: str,
        paragraphs: List[_Paragraph],
        to_remove: Set[int],
    ) -> str:
        """Rebuild the document with duplicate paragraphs removed."""
        lines = content.split("\n")
        removed_lines: Set[int] = set()

        for para in paragraphs:
            if para.index in to_remove:
                for i in range(para.start_line, para.end_line):
                    removed_lines.add(i)

        result_lines = [
            line for i, line in enumerate(lines)
            if i not in removed_lines
        ]
        result = "\n".join(result_lines)
        result = _EXCESS_BLANK_RE.sub("\n\n", result)
        return result.strip()

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report_metrics(
        self,
        ctx: OptimizationContext,
        paragraphs: List[_Paragraph],
        groups: List[_DuplicateGroup],
        protected_count: int,
        removed_count: int,
        mode: str,
        elapsed_seconds: float,
    ) -> None:
        group_details = [
            {
                "first_line": g.first_line,
                "duplicate_lines": g.duplicate_lines,
                "copies": len(g.duplicate_indices),
                "preview": g.preview,
            }
            for g in groups
        ]

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "mode": mode,
            "paragraphs_scanned": len(paragraphs),
            "paragraphs_protected": protected_count,
            "duplicate_groups": len(groups),
            "total_duplicates_removed": removed_count,
            "elapsed_seconds": round(elapsed_seconds, 6),
            "groups": group_details,
        }


# ── Module-level helpers ─────────────────────────────────────────────────────


def _deterministic_hash(text: str) -> int:
    """Return a deterministic 64-bit hash of *text*."""
    digest = hashlib.md5(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "little")


def _normalize(text: str) -> str:
    """Normalise paragraph text for comparison."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = _WHITESPACE_RE.sub(" ", text)
    text = _NON_WORD_RE.sub("", text)
    return text.strip()


def _simhash(text: str, ngram_size: int = 3) -> int:
    """Compute a 64-bit SimHash from word n-grams.

    SimHash is a locality-sensitive hash: similar texts produce
    fingerprints with low Hamming distance.
    """
    words = text.split()
    if len(words) < ngram_size:
        return _deterministic_hash(text)

    v = [0] * _HASH_BITS
    for i in range(len(words) - ngram_size + 1):
        shingle = " ".join(words[i : i + ngram_size])
        h = _deterministic_hash(shingle)
        for bit in range(_HASH_BITS):
            if h & (1 << bit):
                v[bit] += 1
            else:
                v[bit] -= 1

    fingerprint = 0
    for bit in range(_HASH_BITS):
        if v[bit] > 0:
            fingerprint |= (1 << bit)
    return fingerprint


def _hamming_distance(a: int, b: int) -> int:
    """Hamming distance between two integers (popcount of XOR)."""
    return bin(a ^ b).count("1")

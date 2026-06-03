"""
optimizer/passes/ocr_cleanup.py – Repair OCR/PDF extraction artifacts.

Targets
=======

1. ``(cid:XXX)`` font-mapping artifacts → remove
2. Unicode normalization (NFKC) + ligature expansion
3. Broken Unicode (replacement chars, mojibake patterns)
4. Missing whitespace between merged words
5. Mid-sentence line breaks (unwrap)
6. Corrupted punctuation (double periods, spaced punctuation)

Protected zones: code blocks, inline code, equations ($$..$$, $...$).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Patterns ──────────────────────────────────────────────────────────────────

# (cid:NNN) — PDF font-mapping artifact
_CID_RE = re.compile(r"\(cid:\d+\)")

# Replacement character
_REPLACEMENT_CHAR = "\ufffd"

# Ligatures → expanded
_LIGATURE_MAP = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
    "\u0132": "IJ",
    "\u0133": "ij",
    "\u0152": "OE",
    "\u0153": "oe",
    "\u00c6": "AE",
    "\u00e6": "ae",
}

# Invisible/zero-width chars
_INVISIBLE_RE = re.compile(
    r"[\u200b\u200c\u200d\u2060\ufeff\u00ad\u034f\u2028\u2029]"
)

# Non-breaking space → regular
_NBSP = "\u00a0"

# Smart quotes → ASCII
_SMART_QUOTE_MAP = {
    "\u2018": "'",  # left single
    "\u2019": "'",  # right single
    "\u201c": '"',  # left double
    "\u201d": '"',  # right double
    "\u2013": "-",  # en-dash
    "\u2014": "--",  # em-dash
    "\u2026": "...",  # ellipsis
}

# Common word merge patterns (lowercase→Uppercase mid-word)
_LOWER_UPPER_RE = re.compile(r"([a-z])([A-Z][a-z])")

# Common OCR merged preposition+article combos
_MERGED_WORDS = re.compile(
    r"\b(of|in|on|at|to|by|and|the|for|with|from|that|this|which|where|when|have|been|will|can|are|was|were)"
    r"(the|a|an|is|of|in|on|to|and|or|be|it|as|at|by|if|we|do|no|up|so|he|my|us)\b",
    re.IGNORECASE,
)

# Mid-sentence line break: lowercase/comma at end, lowercase at start of next
_MID_SENTENCE_BREAK_RE = re.compile(
    r"([a-z,;])\s*\n\s*([a-z])"
)

# Corrupted punctuation
_DOUBLE_PERIOD_RE = re.compile(r"(?<!\.)\.\.(?!\.)")  # exactly 2 dots
_SPACED_PUNCT_RE = re.compile(r"\s+([.,;:!?])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

# Control chars (keep \t \n \r)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Protected zones
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_DISPLAY_MATH_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(?:[^$\n]|\\\$)+\$(?!\$)")


# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class OCRCleanupPass(OptimizerPass):
    """Detect and repair OCR/PDF extraction artifacts.

    Config params
    ~~~~~~~~~~~~~

    ============================ ============== ===============================
    Param                        Default        Description
    ============================ ============== ===============================
    remove_cid                   ``True``       Remove (cid:XXX) tokens.
    normalize_unicode            ``True``       NFKC + ligature expansion.
    fix_whitespace               ``True``       Reconstruct merged words.
    unwrap_lines                 ``True``       Join mid-sentence breaks.
    fix_punctuation              ``True``       Repair corrupted punctuation.
    remove_control_chars         ``True``       Strip control characters.
    normalize_quotes             ``False``      Smart quotes → ASCII.
    ============================ ============== ===============================
    """

    @property
    def name(self) -> str:
        return "ocr_cleanup"

    @property
    def description(self) -> str:
        return "Detect and repair OCR/PDF extraction artifacts."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=5,  # run very early
            params={
                "remove_cid": True,
                "normalize_unicode": True,
                "fix_whitespace": True,
                "unwrap_lines": True,
                "fix_punctuation": True,
                "remove_control_chars": True,
                "normalize_quotes": False,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        pass  # all params are booleans, no strict validation needed

    # ── Main ──────────────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        content = ctx.content
        metrics = _Metrics()

        if not content.strip():
            self._report(ctx, metrics)
            return ctx

        # Find protected zones
        protected = self._find_protected(content)

        # 1. (cid:XXX) removal
        if p.get("remove_cid", True):
            content, n = self._remove_cid(content, protected)
            metrics.cid_removed += n
            if n:
                protected = self._find_protected(content)

        # 2. Unicode normalization + ligatures
        if p.get("normalize_unicode", True):
            content, ligs, repl = self._normalize_unicode(content, protected)
            metrics.ligatures_fixed += ligs
            metrics.replacement_chars_removed += repl
            if ligs or repl:
                protected = self._find_protected(content)

        # 3. Control chars
        if p.get("remove_control_chars", True):
            content, n = self._remove_control_chars(content, protected)
            metrics.control_chars_removed += n
            if n:
                protected = self._find_protected(content)

        # 4. Smart quotes
        if p.get("normalize_quotes", False):
            content, n = self._normalize_quotes(content, protected)
            metrics.quotes_normalized += n
            if n:
                protected = self._find_protected(content)

        # 5. Fix whitespace (merged words)
        if p.get("fix_whitespace", True):
            content, n = self._fix_whitespace(content, protected)
            metrics.whitespace_fixed += n
            if n:
                protected = self._find_protected(content)

        # 6. Unwrap mid-sentence line breaks
        if p.get("unwrap_lines", True):
            content, n = self._unwrap_lines(content, protected)
            metrics.lines_unwrapped += n
            if n:
                protected = self._find_protected(content)

        # 7. Fix punctuation
        if p.get("fix_punctuation", True):
            content, n = self._fix_punctuation(content, protected)
            metrics.punctuation_fixed += n

        # Final: collapse multi-spaces
        content = _MULTI_SPACE_RE.sub(" ", content)

        ctx.content = content
        self._report(ctx, metrics)
        return ctx

    # ── Protected zones ───────────────────────────────────────────────────

    @staticmethod
    def _find_protected(content: str) -> List[Tuple[int, int]]:
        zones: List[Tuple[int, int]] = []
        for pattern in (_CODE_BLOCK_RE, _INLINE_CODE_RE,
                        _DISPLAY_MATH_RE, _INLINE_MATH_RE):
            for m in pattern.finditer(content):
                zones.append((m.start(), m.end()))
        zones.sort()
        return zones

    # ── (cid:XXX) ────────────────────────────────────────────────────────

    @staticmethod
    def _remove_cid(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        count = 0
        def _repl(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return ""
        result = _CID_RE.sub(_repl, content)
        return result, count

    # ── Unicode normalization ─────────────────────────────────────────────

    @staticmethod
    def _normalize_unicode(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int, int]:
        ligs = 0
        repl_removed = 0

        # Ligatures
        for lig, expansion in _LIGATURE_MAP.items():
            if lig in content:
                new = []
                i = 0
                for m in re.finditer(re.escape(lig), content):
                    if not _in_protected(m.start(), m.end(), protected):
                        new.append(content[i:m.start()])
                        new.append(expansion)
                        ligs += 1
                    else:
                        new.append(content[i:m.end()])
                    i = m.end()
                new.append(content[i:])
                content = "".join(new)

        # NFKC
        content = unicodedata.normalize("NFKC", content)

        # NBSP → space
        content = content.replace(_NBSP, " ")

        # Invisible chars
        content = _INVISIBLE_RE.sub("", content)

        # Replacement chars
        repl_removed = content.count(_REPLACEMENT_CHAR)
        content = content.replace(_REPLACEMENT_CHAR, "")

        return content, ligs, repl_removed

    # ── Control chars ─────────────────────────────────────────────────────

    @staticmethod
    def _remove_control_chars(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        count = 0
        def _repl(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return ""
        result = _CONTROL_RE.sub(_repl, content)
        return result, count

    # ── Smart quotes ──────────────────────────────────────────────────────

    @staticmethod
    def _normalize_quotes(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        count = 0
        for smart, ascii_ver in _SMART_QUOTE_MAP.items():
            if smart in content:
                new = []
                i = 0
                for m in re.finditer(re.escape(smart), content):
                    if not _in_protected(m.start(), m.end(), protected):
                        new.append(content[i:m.start()])
                        new.append(ascii_ver)
                        count += 1
                    else:
                        new.append(content[i:m.end()])
                    i = m.end()
                new.append(content[i:])
                content = "".join(new)
        return content, count

    # ── Whitespace (merged words) ─────────────────────────────────────────

    @staticmethod
    def _fix_whitespace(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        count = 0

        # Fix lowerUpper transitions (not in protected)
        def _repl_case(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return m.group(1) + " " + m.group(2)

        content = _LOWER_UPPER_RE.sub(_repl_case, content)

        # Fix common merged preposition+article combos
        def _repl_merged(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return m.group(1) + " " + m.group(2)

        content = _MERGED_WORDS.sub(_repl_merged, content)

        return content, count

    # ── Line unwrapping ───────────────────────────────────────────────────

    @staticmethod
    def _unwrap_lines(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        count = 0
        def _repl(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return m.group(1) + " " + m.group(2)
        content = _MID_SENTENCE_BREAK_RE.sub(_repl, content)
        return content, count

    # ── Punctuation repair ────────────────────────────────────────────────

    @staticmethod
    def _fix_punctuation(
        content: str, protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        count = 0

        # Double periods → single
        def _repl_dp(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return "."
        content = _DOUBLE_PERIOD_RE.sub(_repl_dp, content)

        # Space before punctuation
        def _repl_sp(m: re.Match) -> str:
            nonlocal count
            if _in_protected(m.start(), m.end(), protected):
                return m.group()
            count += 1
            return m.group(1)
        content = _SPACED_PUNCT_RE.sub(_repl_sp, content)

        return content, count

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(self, ctx: OptimizationContext, m: _Metrics) -> None:
        total = m.total_detected
        repaired = m.total_repaired
        confidence = 1.0 if total == 0 else round(repaired / total, 3)

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "artifacts_detected": total,
            "artifacts_repaired": repaired,
            "confidence_score": confidence,
            "cid_removed": m.cid_removed,
            "ligatures_fixed": m.ligatures_fixed,
            "replacement_chars_removed": m.replacement_chars_removed,
            "control_chars_removed": m.control_chars_removed,
            "quotes_normalized": m.quotes_normalized,
            "whitespace_fixed": m.whitespace_fixed,
            "lines_unwrapped": m.lines_unwrapped,
            "punctuation_fixed": m.punctuation_fixed,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

class _Metrics:
    __slots__ = (
        "cid_removed", "ligatures_fixed", "replacement_chars_removed",
        "control_chars_removed", "quotes_normalized", "whitespace_fixed",
        "lines_unwrapped", "punctuation_fixed",
    )

    def __init__(self) -> None:
        self.cid_removed = 0
        self.ligatures_fixed = 0
        self.replacement_chars_removed = 0
        self.control_chars_removed = 0
        self.quotes_normalized = 0
        self.whitespace_fixed = 0
        self.lines_unwrapped = 0
        self.punctuation_fixed = 0

    @property
    def total_detected(self) -> int:
        return (
            self.cid_removed + self.ligatures_fixed
            + self.replacement_chars_removed + self.control_chars_removed
            + self.quotes_normalized + self.whitespace_fixed
            + self.lines_unwrapped + self.punctuation_fixed
        )

    @property
    def total_repaired(self) -> int:
        return self.total_detected  # all detected = repaired


def _in_protected(
    start: int, end: int, zones: List[Tuple[int, int]],
) -> bool:
    for zs, ze in zones:
        if start < ze and end > zs:
            return True
    return False

"""
optimizer/passes/abbreviation_mining.py – Auto-detect repeated phrases → abbreviations.

Algorithm
=========

1. **Phrase extraction** — Scan for sequences of 2+ title-case words
   (allowing connectors: of/and/for/the/in/on/with/to/by/a/an).
   Count frequency of each unique phrase.

2. **Acronym generation** — Take first letter of each significant
   word (skip connectors).  ``Quantum Key Distribution → QKD``.

3. **Collision detection** — If two phrases yield the same acronym,
   keep the higher-frequency one.  Also check that the acronym
   doesn't already appear in the document as an existing term.

4. **Confidence scoring** — Score based on:
   - normalised frequency (50%)
   - word count sweetness (30%)  — 2–5 significant words optimal
   - acronym distinctness (20%) — unique letters, no collision

5. **Safe replacement** — First occurrence → ``Phrase (ACRONYM)``.
   Subsequent occurrences → ``ACRONYM``.
   Protected zones (code blocks, inline code, optionally headings)
   are never modified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Constants ─────────────────────────────────────────────────────────────────

_STOP_WORDS: Set[str] = {
    "of", "and", "for", "the", "in", "on", "with", "to", "by", "a", "an",
}

_CAP_WORD = r"[A-Z][a-zA-Z]*"
_CONNECTOR = r"(?:" + "|".join(_STOP_WORDS) + r")"
# Match: CapWord (optional_connector CapWord)+
_PHRASE_RE = re.compile(
    rf"\b({_CAP_WORD}(?:\s+(?:{_CONNECTOR}\s+)?{_CAP_WORD})+)\b"
)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")
_HEADING_RE = re.compile(r"^#{1,6}\s+.*$", re.MULTILINE)
_EXISTING_ABBR_RE = re.compile(r"\b[A-Z]{2,6}\b")


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class _AbbreviationCandidate:
    phrase: str
    acronym: str
    frequency: int
    confidence: float
    replacements_made: int = 0


# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class AbbreviationMiningPass(OptimizerPass):
    """Auto-detect repeated technical phrases and replace with abbreviations.

    Config params
    ~~~~~~~~~~~~~

    ======================== ================== ================================
    Param                    Default            Description
    ======================== ================== ================================
    min_frequency            ``3``              Min occurrences to abbreviate.
    min_words                ``2``              Min significant words in phrase.
    min_acronym_length       ``2``              Min acronym characters.
    max_acronym_length       ``6``              Max acronym characters.
    min_confidence           ``0.3``            Min confidence score to accept.
    protect_headings         ``True``           Don't replace inside headings.
    protect_code             ``True``           Don't replace inside code.
    intro_format             ``"{phrase} ({acronym})"``  First-occurrence format.
    ======================== ================== ================================
    """

    @property
    def name(self) -> str:
        return "abbreviation_mining"

    @property
    def description(self) -> str:
        return (
            "Detect repeated technical phrases and replace with "
            "auto-generated abbreviations."
        )

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=40,
            params={
                "min_frequency": 3,
                "min_words": 2,
                "min_acronym_length": 2,
                "max_acronym_length": 6,
                "min_confidence": 0.3,
                "protect_headings": True,
                "protect_code": True,
                "intro_format": "{phrase} ({acronym})",
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError
        p = config.params
        if not isinstance(p.get("min_frequency", 3), int) or p.get("min_frequency", 3) < 1:
            raise PassConfigError(self.name, "min_frequency must be positive int")
        if not isinstance(p.get("min_words", 2), int) or p.get("min_words", 2) < 2:
            raise PassConfigError(self.name, "min_words must be int >= 2")
        fmt = p.get("intro_format", "")
        if "{phrase}" not in fmt or "{acronym}" not in fmt:
            raise PassConfigError(
                self.name, "intro_format must contain {phrase} and {acronym}",
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
            self._report(ctx, [])
            return ctx

        min_freq: int = p.get("min_frequency", 3)
        min_words: int = p.get("min_words", 2)
        min_acr_len: int = p.get("min_acronym_length", 2)
        max_acr_len: int = p.get("max_acronym_length", 6)
        min_conf: float = p.get("min_confidence", 0.3)
        protect_headings: bool = p.get("protect_headings", True)
        protect_code: bool = p.get("protect_code", True)
        intro_fmt: str = p.get("intro_format", "{phrase} ({acronym})")

        # 1. Find protected zones
        protected = self._find_protected_zones(
            content, headings=protect_headings, code=protect_code,
        )

        # 2. Extract phrases + frequencies (outside protected zones)
        phrase_freq = self._count_phrases(content, protected, min_words)

        if not phrase_freq:
            self._report(ctx, [])
            return ctx

        # 3. Find existing abbreviations in doc
        existing_abbrs = set(_EXISTING_ABBR_RE.findall(content))

        # 4. Generate acronyms, detect collisions, score confidence
        candidates = self._build_candidates(
            phrase_freq, existing_abbrs,
            min_freq=min_freq,
            min_acr_len=min_acr_len,
            max_acr_len=max_acr_len,
            min_conf=min_conf,
        )

        if not candidates:
            self._report(ctx, [])
            return ctx

        # 5. Apply replacements (longest phrase first)
        candidates.sort(key=lambda c: len(c.phrase), reverse=True)

        for cand in candidates:
            content, n = self._replace_phrase(
                content, cand.phrase, cand.acronym, intro_fmt, protected,
            )
            cand.replacements_made = n
            # Recompute protected zones (content shifted)
            if n > 0:
                protected = self._find_protected_zones(
                    content, headings=protect_headings, code=protect_code,
                )

        ctx.content = content
        self._report(ctx, candidates)
        return ctx

    # ── Phrase extraction ─────────────────────────────────────────────────

    @staticmethod
    def _count_phrases(
        content: str,
        protected: List[Tuple[int, int]],
        min_words: int,
    ) -> Dict[str, int]:
        """Extract and count title-case phrases outside protected zones."""
        counts: Dict[str, int] = {}

        for m in _PHRASE_RE.finditer(content):
            phrase = m.group(1)
            start, end = m.start(), m.end()

            # Skip if inside protected zone
            if _in_protected(start, end, protected):
                continue

            # Count significant words
            sig_words = [w for w in phrase.split() if w.lower() not in _STOP_WORDS]
            if len(sig_words) < min_words:
                continue

            counts[phrase] = counts.get(phrase, 0) + 1

        return counts

    # ── Acronym generation ────────────────────────────────────────────────

    @staticmethod
    def generate_acronym(phrase: str) -> str:
        """Generate acronym from phrase, skipping stop words."""
        words = phrase.split()
        significant = [w for w in words if w.lower() not in _STOP_WORDS]
        return "".join(w[0].upper() for w in significant)

    # ── Candidate building ────────────────────────────────────────────────

    @classmethod
    def _build_candidates(
        cls,
        phrase_freq: Dict[str, int],
        existing_abbrs: Set[str],
        *,
        min_freq: int,
        min_acr_len: int,
        max_acr_len: int,
        min_conf: float,
    ) -> List[_AbbreviationCandidate]:
        """Build candidates with collision detection and confidence scoring."""
        max_freq = max(phrase_freq.values()) if phrase_freq else 1

        # Generate acronym for each phrase
        raw: List[Tuple[str, str, int]] = []  # (phrase, acronym, freq)
        for phrase, freq in phrase_freq.items():
            if freq < min_freq:
                continue
            acronym = cls.generate_acronym(phrase)
            if len(acronym) < min_acr_len or len(acronym) > max_acr_len:
                continue
            raw.append((phrase, acronym, freq))

        # Collision detection: keep highest-frequency phrase per acronym
        acronym_best: Dict[str, Tuple[str, int]] = {}
        for phrase, acronym, freq in raw:
            if acronym in acronym_best:
                if freq > acronym_best[acronym][1]:
                    acronym_best[acronym] = (phrase, freq)
            else:
                acronym_best[acronym] = (phrase, freq)

        # Build final candidates
        candidates: List[_AbbreviationCandidate] = []
        collisions = 0

        for phrase, acronym, freq in raw:
            best_phrase, _ = acronym_best[acronym]
            if best_phrase != phrase:
                collisions += 1
                continue  # lost collision

            # Skip if acronym already exists in doc as different meaning
            if acronym in existing_abbrs:
                continue

            confidence = cls._compute_confidence(phrase, freq, max_freq)
            if confidence < min_conf:
                continue

            candidates.append(_AbbreviationCandidate(
                phrase=phrase,
                acronym=acronym,
                frequency=freq,
                confidence=confidence,
            ))

        return candidates

    @staticmethod
    def _compute_confidence(phrase: str, frequency: int, max_freq: int) -> float:
        """Score 0–1 based on frequency and word count."""
        sig_words = [w for w in phrase.split() if w.lower() not in _STOP_WORDS]
        word_count = len(sig_words)

        # Frequency component (50%)
        freq_score = frequency / max_freq if max_freq > 0 else 0

        # Word count component (30%) — 2-5 words optimal
        word_score = min(1.0, word_count / 3)

        # Length savings component (20%) — longer phrases save more
        savings = len(phrase) - word_count  # chars saved per replacement
        savings_score = min(1.0, savings / 20)

        return round(freq_score * 0.5 + word_score * 0.3 + savings_score * 0.2, 3)

    # ── Replacement ───────────────────────────────────────────────────────

    @staticmethod
    def _replace_phrase(
        content: str,
        phrase: str,
        acronym: str,
        intro_format: str,
        protected: List[Tuple[int, int]],
    ) -> Tuple[str, int]:
        """Replace phrase occurrences. First → intro, rest → acronym.

        Returns (new_content, replacement_count).
        """
        # Find all occurrences
        positions: List[int] = []
        start = 0
        while True:
            idx = content.find(phrase, start)
            if idx == -1:
                break
            # Word boundary check
            if _at_word_boundary(content, idx, idx + len(phrase)):
                if not _in_protected(idx, idx + len(phrase), protected):
                    positions.append(idx)
            start = idx + 1

        if len(positions) < 2:
            return content, 0  # need intro + at least 1 replacement

        # Apply in reverse order to preserve positions
        replacements = 0
        for i in range(len(positions) - 1, -1, -1):
            pos = positions[i]
            end = pos + len(phrase)
            original = content[pos:end]

            if i == 0:
                # First occurrence: introduce
                repl = intro_format.format(phrase=original, acronym=acronym)
            else:
                repl = acronym
                replacements += 1

            content = content[:pos] + repl + content[end:]

        return content, replacements

    # ── Protected zones ───────────────────────────────────────────────────

    @staticmethod
    def _find_protected_zones(
        content: str,
        *,
        headings: bool = True,
        code: bool = True,
    ) -> List[Tuple[int, int]]:
        zones: List[Tuple[int, int]] = []
        if code:
            for m in _CODE_BLOCK_RE.finditer(content):
                zones.append((m.start(), m.end()))
            for m in _INLINE_CODE_RE.finditer(content):
                zones.append((m.start(), m.end()))
        if headings:
            for m in _HEADING_RE.finditer(content):
                zones.append((m.start(), m.end()))
        zones.sort()
        return zones

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(
        self,
        ctx: OptimizationContext,
        candidates: List[_AbbreviationCandidate],
    ) -> None:
        abbr_details = [
            {
                "phrase": c.phrase,
                "acronym": c.acronym,
                "frequency": c.frequency,
                "confidence": c.confidence,
                "replacements": c.replacements_made,
            }
            for c in candidates
        ]
        total_replacements = sum(c.replacements_made for c in candidates)

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "phrases_detected": len(candidates),
            "abbreviations_created": sum(
                1 for c in candidates if c.replacements_made > 0
            ),
            "total_replacements": total_replacements,
            "abbreviations": abbr_details,
        }


# ── Module-level helpers ─────────────────────────────────────────────────────


def _in_protected(
    start: int, end: int, zones: List[Tuple[int, int]],
) -> bool:
    for zs, ze in zones:
        if start < ze and end > zs:
            return True
    return False


def _at_word_boundary(content: str, start: int, end: int) -> bool:
    """Check that match is at word boundaries."""
    if start > 0 and content[start - 1].isalnum():
        return False
    if end < len(content) and content[end].isalnum():
        return False
    return True

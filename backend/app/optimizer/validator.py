"""
optimizer/validator.py – Semantic quality validation for optimization output.

Architecture
============

``SemanticQualityValidator`` compares original vs optimized docs across
four dimensions:

1. **Semantic score** — bag-of-words cosine similarity (lightweight).
   Optional sentence-transformers embedding similarity if available.
2. **Structure score** — heading/section/list preservation ratio.
3. **Equation score** — math expression retention ratio.
4. **Token reduction** — token savings percentage.

Produces a ``ValidationReport`` with scores + warnings.
Can reject optimizations below configurable thresholds.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.utils.token_counter import estimate_tokens


# ── Patterns for analysis ─────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_NUMBERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)

# Math patterns
_DISPLAY_MATH_RE = re.compile(r"\$\$.*?\$\$", re.DOTALL)
_INLINE_MATH_RE = re.compile(r"(?<!\$)\$(?!\$)(?:[^$\n\\]|\\.)+\$(?!\$)")
_LATEX_ENV_RE = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|math)\}.*?"
    r"\\end\{\1\}",
    re.DOTALL,
)
_BRACKET_MATH_RE = re.compile(r"\\\[.*?\\\]", re.DOTALL)
_PAREN_MATH_RE = re.compile(r"\\\(.*?\\\)", re.DOTALL)
_SCI_NOTATION_RE = re.compile(r"\b\d+\.?\d*[eE][+-]?\d+\b")

# Code blocks
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]+`")

# Word tokenizer (simple)
_WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    """Quality metrics for an optimization run."""

    semantic_score: float = 0.0        # 0..1 cosine similarity
    structure_score: float = 0.0       # 0..1 heading/list retention
    equation_score: float = 0.0        # 0..1 math retention
    token_reduction: float = 0.0       # 0..1 fraction saved
    original_tokens: int = 0
    optimized_tokens: int = 0
    warnings: List[str] = field(default_factory=list)
    passed: bool = True
    rejection_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "semanticScore": round(self.semantic_score, 4),
            "structureScore": round(self.structure_score, 4),
            "equationScore": round(self.equation_score, 4),
            "tokenReduction": round(self.token_reduction, 4),
            "originalTokens": self.original_tokens,
            "optimizedTokens": self.optimized_tokens,
            "warnings": self.warnings,
            "passed": self.passed,
            "rejectionReasons": self.rejection_reasons,
        }


@dataclass
class ValidationThresholds:
    """Minimum acceptable scores. Below any → reject."""

    min_semantic_score: float = 0.7
    min_structure_score: float = 0.5
    min_equation_score: float = 0.95  # equations must be preserved
    max_token_reduction: float = 0.80  # reject if >80% tokens removed (suspicious)

    def validate(self) -> None:
        for attr in ("min_semantic_score", "min_structure_score",
                     "min_equation_score", "max_token_reduction"):
            val = getattr(self, attr)
            if not 0.0 <= val <= 1.0:
                raise ValueError(f"{attr} must be 0..1, got {val}")


# ── Validator ─────────────────────────────────────────────────────────────────

class SemanticQualityValidator:
    """Compare original vs optimized document quality.

    Parameters
    ----------
    thresholds : ValidationThresholds, optional
        Min scores for each dimension. Below → rejection.
    use_embeddings : bool
        If True and sentence-transformers available, use embedding
        similarity for semantic_score (more accurate, slower).
    """

    def __init__(
        self,
        thresholds: ValidationThresholds | None = None,
        use_embeddings: bool = False,
    ) -> None:
        self._thresholds = thresholds or ValidationThresholds()
        self._thresholds.validate()
        self._use_embeddings = use_embeddings
        self._model = None  # lazy load

    def validate(
        self,
        original: str,
        optimized: str,
    ) -> ValidationReport:
        """Compare *original* and *optimized* documents.

        Returns a ``ValidationReport`` with scores and pass/fail.
        """
        report = ValidationReport()

        if not original.strip():
            report.semantic_score = 1.0
            report.structure_score = 1.0
            report.equation_score = 1.0
            report.passed = True
            return report

        # Token counts
        report.original_tokens = estimate_tokens(original)
        report.optimized_tokens = estimate_tokens(optimized)

        if report.original_tokens > 0:
            report.token_reduction = (
                (report.original_tokens - report.optimized_tokens)
                / report.original_tokens
            )
        else:
            report.token_reduction = 0.0

        # 1. Semantic score
        report.semantic_score = self._compute_semantic(original, optimized)

        # 2. Structure score
        report.structure_score = self._compute_structure(original, optimized)

        # 3. Equation score
        report.equation_score = self._compute_equation(original, optimized)

        # 4. Warnings
        report.warnings = self._generate_warnings(report, original, optimized)

        # 5. Threshold check
        self._apply_thresholds(report)

        return report

    # ── Semantic similarity ───────────────────────────────────────────────

    def _compute_semantic(self, original: str, optimized: str) -> float:
        if self._use_embeddings:
            score = self._embedding_similarity(original, optimized)
            if score is not None:
                return score
            # Fallback to bag-of-words

        return self._bow_cosine(original, optimized)

    @staticmethod
    def _bow_cosine(text_a: str, text_b: str) -> float:
        """Bag-of-words cosine similarity."""
        words_a = _WORD_RE.findall(text_a.lower())
        words_b = _WORD_RE.findall(text_b.lower())

        if not words_a and not words_b:
            return 1.0
        if not words_a or not words_b:
            return 0.0

        counter_a = Counter(words_a)
        counter_b = Counter(words_b)

        # Cosine similarity
        all_words = set(counter_a) | set(counter_b)
        dot = sum(counter_a.get(w, 0) * counter_b.get(w, 0) for w in all_words)
        mag_a = math.sqrt(sum(v ** 2 for v in counter_a.values()))
        mag_b = math.sqrt(sum(v ** 2 for v in counter_b.values()))

        if mag_a == 0 or mag_b == 0:
            return 0.0

        return dot / (mag_a * mag_b)

    def _embedding_similarity(
        self, text_a: str, text_b: str,
    ) -> Optional[float]:
        try:
            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer("all-MiniLM-L6-v2")

            embeddings = self._model.encode(
                [text_a[:5000], text_b[:5000]],  # truncate for speed
                normalize_embeddings=True,
            )
            similarity = float(embeddings[0] @ embeddings[1])
            return max(0.0, min(1.0, similarity))
        except Exception:
            return None

    # ── Structure score ───────────────────────────────────────────────────

    @staticmethod
    def _compute_structure(original: str, optimized: str) -> float:
        scores: List[float] = []

        # Heading retention
        orig_headings = set(_HEADING_RE.findall(original))
        opt_headings = set(_HEADING_RE.findall(optimized))

        if orig_headings:
            heading_retention = len(orig_headings & opt_headings) / len(orig_headings)
            scores.append(heading_retention)
        else:
            scores.append(1.0)

        # List item count ratio
        orig_lists = len(_LIST_ITEM_RE.findall(original)) + len(_NUMBERED_LIST_RE.findall(original))
        opt_lists = len(_LIST_ITEM_RE.findall(optimized)) + len(_NUMBERED_LIST_RE.findall(optimized))

        if orig_lists > 0:
            # Optimized can have MORE lists (table→list transform)
            scores.append(min(1.0, opt_lists / orig_lists))
        else:
            scores.append(1.0)

        # Code block retention
        orig_code = len(_CODE_BLOCK_RE.findall(original))
        opt_code = len(_CODE_BLOCK_RE.findall(optimized))

        if orig_code > 0:
            scores.append(min(1.0, opt_code / orig_code))
        else:
            scores.append(1.0)

        # Paragraph count ratio
        orig_paras = len([p for p in original.split("\n\n") if p.strip()])
        opt_paras = len([p for p in optimized.split("\n\n") if p.strip()])

        if orig_paras > 0:
            scores.append(min(1.0, opt_paras / orig_paras))
        else:
            scores.append(1.0)

        return sum(scores) / len(scores) if scores else 1.0

    # ── Equation score ────────────────────────────────────────────────────

    @staticmethod
    def _compute_equation(original: str, optimized: str) -> float:
        """Check what fraction of equations from original survive."""
        patterns = [
            _DISPLAY_MATH_RE, _INLINE_MATH_RE, _LATEX_ENV_RE,
            _BRACKET_MATH_RE, _PAREN_MATH_RE, _SCI_NOTATION_RE,
        ]

        orig_equations: List[str] = []
        for pat in patterns:
            orig_equations.extend(m.group() for m in pat.finditer(original))

        if not orig_equations:
            return 1.0  # no equations → perfect score

        found = 0
        for eq in orig_equations:
            if eq in optimized:
                found += 1

        return found / len(orig_equations)

    # ── Warnings ──────────────────────────────────────────────────────────

    @staticmethod
    def _generate_warnings(
        report: ValidationReport,
        original: str,
        optimized: str,
    ) -> List[str]:
        warnings: List[str] = []

        if report.token_reduction > 0.6:
            warnings.append(
                f"High token reduction ({report.token_reduction:.0%}). "
                f"Verify content preservation."
            )

        if report.semantic_score < 0.8:
            warnings.append(
                f"Low semantic similarity ({report.semantic_score:.2f}). "
                f"Content may have been significantly altered."
            )

        if report.equation_score < 1.0:
            missing = int((1 - report.equation_score) * 100)
            warnings.append(
                f"~{missing}% of equations were lost during optimization."
            )

        if report.structure_score < 0.7:
            warnings.append(
                f"Structure preservation low ({report.structure_score:.2f}). "
                f"Headings or lists may have been removed."
            )

        if not optimized.strip() and original.strip():
            warnings.append("Optimized output is empty!")

        return warnings

    # ── Threshold enforcement ─────────────────────────────────────────────

    def _apply_thresholds(self, report: ValidationReport) -> None:
        t = self._thresholds
        reasons: List[str] = []

        if report.semantic_score < t.min_semantic_score:
            reasons.append(
                f"semantic_score {report.semantic_score:.3f} "
                f"< min {t.min_semantic_score}"
            )

        if report.structure_score < t.min_structure_score:
            reasons.append(
                f"structure_score {report.structure_score:.3f} "
                f"< min {t.min_structure_score}"
            )

        if report.equation_score < t.min_equation_score:
            reasons.append(
                f"equation_score {report.equation_score:.3f} "
                f"< min {t.min_equation_score}"
            )

        if report.token_reduction > t.max_token_reduction:
            reasons.append(
                f"token_reduction {report.token_reduction:.3f} "
                f"> max {t.max_token_reduction}"
            )

        report.rejection_reasons = reasons
        report.passed = len(reasons) == 0

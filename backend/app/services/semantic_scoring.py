"""
services/semantic_scoring.py — Three-score semantic preservation analysis.

Score 1 — Semantic Preservation  (embedding-based bidirectional chunk recall)
Score 2 — Context Preservation   (structural/lexical, no embeddings needed)
Score 3 — Overall Preservation   (harmonic mean of scores 1 & 2)
"""

from __future__ import annotations

import hashlib
import logging
import math
import random
import re
from dataclasses import dataclass

from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_MODEL_NAME          = "all-MiniLM-L6-v2"
_SENT_CHUNK_SIZE     = 5          # sentences per chunk
_SENT_OVERLAP        = 2          # sentences of overlap (~50 %)
_LOW_SIM_THRESHOLD   = 0.75       # flag chunks below this score
_LARGE_DOC_CHARS     = 200_000    # ≈50 k tokens → trigger sampling
_SAMPLE_RATIO        = 0.30
_MODEL_CACHE: dict   = {}
_EMBED_CACHE: dict   = {}         # sha256(chunk) → np.ndarray

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PreservationIssue:
    severity: str   # "danger" | "warning" | "info"
    message:  str

    def to_dict(self) -> dict:
        return {"severity": self.severity, "message": self.message}


@dataclass
class LowSimChunk:
    original_text:    str
    best_match_score: float

    def to_dict(self) -> dict:
        return {
            "original_text":    self.original_text[:200],
            "best_match_score": round(self.best_match_score, 3),
        }


@dataclass
class SemanticScoreResult:
    semantic_preservation:  float
    semantic_loss:          float
    context_preservation:   float
    overall_preservation:   float
    context_breakdown:      dict
    issues:                 list
    low_similarity_chunks:  list
    method:                 str

    def to_dict(self) -> dict:
        return {
            "semantic_preservation": round(self.semantic_preservation, 2),
            "semantic_loss":         round(self.semantic_loss,         2),
            "context_preservation":  round(self.context_preservation,  2),
            "overall_preservation":  round(self.overall_preservation,  2),
            "context_breakdown":     {k: round(v, 2) for k, v in self.context_breakdown.items()},
            "issues":                [i.to_dict() for i in self.issues],
            "low_similarity_chunks": [c.to_dict() for c in self.low_similarity_chunks],
            "scoring_method":        self.method,
        }


# ── Main service ──────────────────────────────────────────────────────────────

class SemanticScoringService:
    """Stateless — call SemanticScoringService.score() directly."""

    @classmethod
    def score(cls, original: str, optimized: str) -> Optional[SemanticScoreResult]:
        original  = (original  or "").strip()
        optimized = (optimized or "").strip()

        if not original:
            return _trivial(100.0)
        if not optimized:
            return _trivial(0.0)
        if original == optimized:
            return _exact()

        # ── Step 1: Context (fast, no model) ──────────────────────────────────
        ctx_result = _context_score(original, optimized)

        # ── Step 2: Semantic (embeddings) ─────────────────────────────────────
        try:
            sem, low_chunks, method = cls._semantic_score(original, optimized)
        except ImportError as exc:
            logger.warning(
                "[semantic_scoring] sentence-transformers not available; using BoW fallback. "
                "Cause: %s", exc,
            )
            logger.debug("[semantic_scoring] ImportError traceback:", exc_info=True)
            sem, low_chunks, method = _bow_cosine(original, optimized), [], "bow"
        except Exception as exc:
            logger.warning("[semantic_scoring] Embedding scoring failed (%s); using BoW fallback", exc)
            logger.debug("[semantic_scoring] Full embedding failure traceback:", exc_info=True)
            sem, low_chunks, method = _bow_cosine(original, optimized), [], "bow"

        # ── Step 3: Harmonic mean ─────────────────────────────────────────────
        ctx = ctx_result["score"]
        overall = _harmonic(sem, ctx)

        all_issues = list(ctx_result["issues"])
        if low_chunks:
            all_issues.append(PreservationIssue(
                "warning",
                f"{len(low_chunks)} chunk(s) may have lost content "
                f"(similarity < {_LOW_SIM_THRESHOLD})",
            ))

        logger.info(
            "[semantic_scoring] sem=%.1f%% ctx=%.1f%% overall=%.1f%% method=%s",
            sem, ctx, overall, method,
        )

        return SemanticScoreResult(
            semantic_preservation  = round(sem,     2),
            semantic_loss          = round(100-sem,  2),
            context_preservation   = round(ctx,     2),
            overall_preservation   = round(overall, 2),
            context_breakdown      = ctx_result["breakdown"],
            issues                 = all_issues,
            low_similarity_chunks  = low_chunks,
            method                 = method,
        )

    # ── Embedding path ────────────────────────────────────────────────────────

    @classmethod
    def _semantic_score(
        cls, original: str, optimized: str,
    ) -> tuple[float, list, str]:
        model = cls._get_model()

        orig_chunks = _sentence_chunks(original)
        opt_chunks  = _sentence_chunks(optimized)

        if not orig_chunks or not opt_chunks:
            return 100.0, [], "embedding"

        orig_chunks = _maybe_sample(orig_chunks, original)

        orig_vecs = _encode_cached(model, orig_chunks)   # (N, D) L2-normalised
        opt_vecs  = _encode_cached(model, opt_chunks)    # (M, D) L2-normalised

        # Recall: each original chunk → best match in optimized set
        sim_matrix = orig_vecs @ opt_vecs.T              # (N, M)
        best_sims  = sim_matrix.max(axis=1)              # (N,)

        sem = float(np.clip(np.mean(best_sims) * 100, 0, 100))

        low = [
            LowSimChunk(orig_chunks[i], float(s))
            for i, s in enumerate(best_sims)
            if s < _LOW_SIM_THRESHOLD
        ]
        return sem, low, "embedding"

    @classmethod
    def _get_model(cls):
        if _MODEL_NAME not in _MODEL_CACHE:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415
            logger.info("[semantic_scoring] Loading '%s'…", _MODEL_NAME)
            _MODEL_CACHE[_MODEL_NAME] = SentenceTransformer(_MODEL_NAME)
        return _MODEL_CACHE[_MODEL_NAME]


# ── Context scoring (6 sub-metrics) ──────────────────────────────────────────

def _context_score(original: str, optimized: str) -> dict:
    results = [
        _score_sections(original, optimized),     # 25 %
        _score_tables  (original, optimized),     # 20 %
        _score_numerics(original, optimized),     # 20 %
        _score_code    (original, optimized),     # 10 %
        _score_images  (original, optimized),     # 10 %
        _score_entities(original, optimized),     # 15 %
    ]
    keys    = ["section_score","table_score","numeric_score","code_score","image_score","entity_score"]
    weights = [0.25, 0.20, 0.20, 0.10, 0.10, 0.15]

    breakdown: dict[str,float] = {}
    all_issues: list = []
    composite = 0.0

    for (score, issues), key, w in zip(results, keys, weights):
        breakdown[key] = round(score, 2)
        all_issues.extend(issues)
        composite += score * w

    return {"score": round(composite, 2), "breakdown": breakdown, "issues": all_issues}


# ── Sub-metric: sections ──────────────────────────────────────────────────────

_HEADING_RE = re.compile(r'^#{1,3}\s+(.+)$', re.MULTILINE)

def _score_sections(orig: str, opt: str) -> tuple[float, list]:
    orig_h = {h.strip().lower() for h in _HEADING_RE.findall(orig)}
    opt_h  = {h.strip().lower() for h in _HEADING_RE.findall(opt)}

    if not orig_h:
        return 100.0, [PreservationIssue("info", "No headings found — section check skipped")]

    missing = orig_h - opt_h
    score   = (len(orig_h) - len(missing)) / len(orig_h) * 100

    if not missing:
        return 100.0, [PreservationIssue("info", f"All {len(orig_h)} sections retained")]
    if len(missing) <= 3:
        return round(score, 2), [PreservationIssue(
            "warning", f"{len(missing)} section(s) missing: {', '.join(sorted(missing)[:3])}")]
    return round(score, 2), [PreservationIssue(
        "danger", f"{len(missing)}/{len(orig_h)} sections missing from optimized doc")]


# ── Sub-metric: tables ────────────────────────────────────────────────────────

def _table_rows(text: str) -> int:
    return sum(
        1 for ln in text.splitlines()
        if (s := ln.strip()) and s.startswith("|") and s.endswith("|") and len(s) > 2
    )

def _score_tables(orig: str, opt: str) -> tuple[float, list]:
    orig_n, opt_n = _table_rows(orig), _table_rows(opt)
    if orig_n == 0:
        return 100.0, []
    if opt_n >= orig_n:
        return 100.0, [PreservationIssue("info", f"All {orig_n} table rows retained")]
    score = opt_n / orig_n * 100
    sev   = "danger" if score < 50 else "warning"
    return round(score, 2), [PreservationIssue(
        sev, f"Table content reduced (original: {orig_n} rows, optimized: {opt_n} rows)")]


# ── Sub-metric: numerics ──────────────────────────────────────────────────────

_NUM_RE = re.compile(
    r'\b\d{1,3}(?:[,_]\d{3})*(?:\.\d+)?'
    r'(?:\s*(?:MB|GB|TB|KB|ms|μs|s|%|px|fps|Hz|GHz|MHz|dB|V|W|°C|°F))?\b'
)

def _score_numerics(orig: str, opt: str) -> tuple[float, list]:
    orig_nums = {n for n in _NUM_RE.findall(orig) if len(n) >= 3 or any(c.isalpha() for c in n)}
    opt_nums  = set(_NUM_RE.findall(opt))
    if not orig_nums:
        return 100.0, []
    missing = orig_nums - opt_nums
    if not missing:
        return 100.0, [PreservationIssue("info", f"All {len(orig_nums)} numeric values retained")]
    score  = max(0.0, (1 - len(missing) / len(orig_nums)) * 100)
    sample = ", ".join(sorted(missing)[:5])
    sev    = "danger" if len(missing) > len(orig_nums) * 0.3 else "warning"
    return round(score, 2), [PreservationIssue(
        sev, f"{len(missing)} numeric value(s) not found in optimized doc: {sample}")]


# ── Sub-metric: code blocks ───────────────────────────────────────────────────

def _code_blocks(text: str) -> int:
    return len(re.findall(r"```", text)) // 2

def _score_code(orig: str, opt: str) -> tuple[float, list]:
    orig_n, opt_n = _code_blocks(orig), _code_blocks(opt)
    if orig_n == 0:
        return 100.0, []
    if opt_n >= orig_n:
        return 100.0, [PreservationIssue("info", f"All {orig_n} code block(s) retained")]
    score = opt_n / orig_n * 100
    return round(score, 2), [PreservationIssue(
        "danger", f"{orig_n - opt_n} code block(s) removed (original: {orig_n}, optimized: {opt_n})")]


# ── Sub-metric: images ────────────────────────────────────────────────────────

_IMG_RE = re.compile(r'!\[.*?\]\(.*?\)|<img\b[^>]*/?>', re.IGNORECASE)

def _score_images(orig: str, opt: str) -> tuple[float, list]:
    orig_n, opt_n = len(_IMG_RE.findall(orig)), len(_IMG_RE.findall(opt))
    if orig_n == 0:
        return 100.0, []
    if opt_n >= orig_n:
        return 100.0, []
    score = opt_n / orig_n * 100
    return round(score, 2), [PreservationIssue(
        "warning", f"{orig_n - opt_n} image reference(s) removed")]


# ── Sub-metric: named entities ────────────────────────────────────────────────

_ENT_PATS = [
    re.compile(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+\b'),
    re.compile(r'\b[A-Z]{3,}\b'),
    re.compile(r'\bv?\d+\.\d+(?:\.\d+)*\b'),
]

def _entities(text: str) -> set:
    result: set = set()
    for p in _ENT_PATS:
        result.update(p.findall(text))
    return result

def _score_entities(orig: str, opt: str) -> tuple[float, list]:
    orig_e, opt_e = _entities(orig), _entities(opt)
    if not orig_e:
        return 100.0, []
    missing = orig_e - opt_e
    if not missing:
        return 100.0, [PreservationIssue("info", f"All {len(orig_e)} named entities retained")]
    score  = max(0.0, (1 - len(missing) / len(orig_e)) * 100)
    sample = ", ".join(sorted(missing)[:5])
    if len(missing) > len(orig_e) * 0.2:
        return round(score, 2), [PreservationIssue(
            "warning", f"{len(missing)} named entity/entities not found: {sample}")]
    return round(score, 2), []


# ── Helpers ───────────────────────────────────────────────────────────────────

_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')

def _sentence_chunks(text: str) -> list[str]:
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if len(s.strip()) > 15]
    if not sents:
        return [text[:1000]] if text.strip() else []
    step, chunks = max(1, _SENT_CHUNK_SIZE - _SENT_OVERLAP), []
    for i in range(0, len(sents), step):
        c = " ".join(sents[i : i + _SENT_CHUNK_SIZE])
        if c.strip():
            chunks.append(c)
    return chunks


def _maybe_sample(chunks: list[str], original: str) -> list[str]:
    if len(original) <= _LARGE_DOC_CHARS:
        return chunks
    n = len(chunks)
    if n <= 20:
        return chunks
    bnd    = max(1, int(n * 0.20))
    head   = chunks[:bnd]
    tail   = chunks[n - bnd :]
    mid    = chunks[bnd : n - bnd]
    k      = max(1, int(len(mid) * _SAMPLE_RATIO))
    sample = random.sample(mid, k)
    seen   = set(); result = []
    for c in head + sample + tail:
        if c not in seen:
            seen.add(c); result.append(c)
    return result


def _encode_cached(model, chunks: list[str]) -> np.ndarray:
    computed_idx, to_encode = [], []
    cached: list[Optional[np.ndarray]] = [None] * len(chunks)
    for i, c in enumerate(chunks):
        key = hashlib.sha256(c.encode()).hexdigest()
        if key in _EMBED_CACHE:
            cached[i] = _EMBED_CACHE[key]
        else:
            to_encode.append((i, c, key))
    if to_encode:
        texts = [t[1] for t in to_encode]
        vecs  = model.encode(texts, batch_size=64, show_progress_bar=False, normalize_embeddings=True)
        for j, (i, _, key) in enumerate(to_encode):
            _EMBED_CACHE[key] = vecs[j]
            cached[i] = vecs[j]
    return np.array(cached, dtype=np.float32)


def _harmonic(a: float, b: float) -> float:
    if a + b == 0:
        return 0.0
    return round(2 * a * b / (a + b), 2)


def _bow_cosine(original: str, optimized: str) -> float:
    def tok(t):
        return {w: c for w, c in
                __import__("collections").Counter(re.findall(r"\b\w+\b", t.lower())).items()}
    ca, cb = tok(original), tok(optimized)
    all_w  = set(ca) | set(cb)
    dot    = sum(ca.get(w,0)*cb.get(w,0) for w in all_w)
    ma     = math.sqrt(sum(v**2 for v in ca.values()))
    mb     = math.sqrt(sum(v**2 for v in cb.values()))
    if not ma or not mb:
        return 0.0
    return max(0.0, min(100.0, dot / (ma * mb) * 100))


def _trivial(preservation: float) -> SemanticScoreResult:
    loss = round(100.0 - preservation, 2)
    brd  = {k: preservation for k in
            ["section_score","table_score","numeric_score","code_score","image_score","entity_score"]}
    return SemanticScoreResult(
        semantic_preservation=preservation, semantic_loss=loss,
        context_preservation=preservation, overall_preservation=preservation,
        context_breakdown=brd, issues=[], low_similarity_chunks=[], method="trivial",
    )


def _exact() -> SemanticScoreResult:
    brd = {k: 100.0 for k in
           ["section_score","table_score","numeric_score","code_score","image_score","entity_score"]}
    return SemanticScoreResult(
        semantic_preservation=100.0, semantic_loss=0.0,
        context_preservation=100.0,  overall_preservation=100.0,
        context_breakdown=brd,
        issues=[PreservationIssue("info", "Documents are identical — no optimization applied")],
        low_similarity_chunks=[], method="exact",
    )


# ── Public label helpers ──────────────────────────────────────────────────────

def get_preservation_label(score: float) -> str:
    if score >= 98: return "Excellent"
    if score >= 95: return "Good"
    if score >= 90: return "Moderate"
    return "Significant Loss"

def get_preservation_emoji(score: float) -> str:
    if score >= 98: return "🟢"
    if score >= 95: return "🟡"
    if score >= 90: return "🟠"
    return "🔴"

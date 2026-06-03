"""
optimizer/passes/semantic_dedup.py – Semantic deduplication via embeddings.

Architecture
============

::

    ┌──────────────────┐
    │ 1. Split Paras   │  → list of Paragraph(text, line, protected)
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ 2. Embed          │  → numpy (N, D)  via SentenceTransformer
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ 3. Similarity     │  → cosine matrix or FAISS index
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ 4. Cluster        │  → groups of near-duplicate paragraphs
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ 5. Select Rep.    │  → keep best representative, remove rest
    └──────────────────┘

Dependencies
~~~~~~~~~~~~

Required:  ``sentence-transformers``, ``numpy``
Optional:  ``faiss-cpu`` (for large-doc acceleration)

If ``sentence-transformers`` is not installed the pass will
**skip gracefully** with a warning rather than crash.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass

logger = logging.getLogger(__name__)

# ── Protected-zone patterns ──────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(r"^```", re.MULTILINE)
_ATX_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_SETEXT_RE = re.compile(r"^[=-]{2,}\s*$", re.MULTILINE)


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass
class _Paragraph:
    text: str
    start_idx: int       # index in the split list
    is_protected: bool = False


@dataclass
class _DedupGroup:
    """A cluster of semantically equivalent paragraphs."""
    representative_idx: int
    duplicate_indices: List[int] = field(default_factory=list)
    similarity: float = 0.0
    preview: str = ""


# ── Lazy model cache ─────────────────────────────────────────────────────────

_MODEL_CACHE: Dict[str, Any] = {}


def _get_model(model_name: str) -> Any:
    """Load SentenceTransformer model (cached)."""
    if model_name not in _MODEL_CACHE:
        from sentence_transformers import SentenceTransformer
        _MODEL_CACHE[model_name] = SentenceTransformer(model_name)
    return _MODEL_CACHE[model_name]


# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class SemanticDeduplicationPass(OptimizerPass):
    """Detect and remove semantically equivalent paragraphs using embeddings.

    Config params
    ~~~~~~~~~~~~~

    ========================== =========================== ===================
    Param                      Default                     Description
    ========================== =========================== ===================
    model_name                 ``"all-MiniLM-L6-v2"``      SentenceTransformer
    similarity_threshold       ``0.85``                    Cosine threshold.
    min_paragraph_length       ``30``                      Skip shorter paras.
    preserve_headings          ``True``                    Protect headings.
    preserve_code_blocks       ``True``                    Protect code blocks.
    use_faiss                  ``False``                   Use FAISS indexing.
    batch_size                 ``32``                      Embed batch size.
    representative_strategy    ``"first"``                 "first" or "longest"
    ========================== =========================== ===================
    """

    @property
    def name(self) -> str:
        return "semantic_deduplication"

    @property
    def description(self) -> str:
        return "Remove semantically equivalent paragraphs using sentence embeddings."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=45,
            params={
                "model_name": "all-MiniLM-L6-v2",
                "similarity_threshold": 0.85,
                "min_paragraph_length": 30,
                "preserve_headings": True,
                "preserve_code_blocks": True,
                "use_faiss": False,
                "batch_size": 32,
                "representative_strategy": "first",
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError
        p = config.params
        thr = p.get("similarity_threshold", 0.85)
        if not isinstance(thr, (int, float)) or not (0 < thr <= 1):
            raise PassConfigError(
                self.name,
                f"similarity_threshold must be (0, 1], got {thr!r}",
            )
        strat = p.get("representative_strategy", "first")
        if strat not in ("first", "longest"):
            raise PassConfigError(
                self.name,
                f"representative_strategy must be 'first' or 'longest', got {strat!r}",
            )
        ml = p.get("min_paragraph_length", 30)
        if not isinstance(ml, int) or ml < 0:
            raise PassConfigError(
                self.name,
                f"min_paragraph_length must be non-negative int, got {ml!r}",
            )
        bs = p.get("batch_size", 32)
        if not isinstance(bs, int) or bs < 1:
            raise PassConfigError(
                self.name,
                f"batch_size must be positive int, got {bs!r}",
            )

    # ── Main ──────────────────────────────────────────────────────────────

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        t0 = time.perf_counter()
        p = config.params

        if not ctx.content.strip():
            self._report(ctx, [], [], 0, time.perf_counter() - t0)
            return ctx

        # Check dependency
        try:
            from sentence_transformers import SentenceTransformer  # noqa: F401
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; "
                "SemanticDeduplicationPass skipping.",
            )
            self._report(ctx, [], [], 0, time.perf_counter() - t0,
                         skipped_reason="sentence-transformers not installed")
            return ctx

        model_name: str = p.get("model_name", "all-MiniLM-L6-v2")
        threshold: float = p.get("similarity_threshold", 0.85)
        min_len: int = p.get("min_paragraph_length", 30)
        preserve_h: bool = p.get("preserve_headings", True)
        preserve_c: bool = p.get("preserve_code_blocks", True)
        use_faiss: bool = p.get("use_faiss", False)
        batch_size: int = p.get("batch_size", 32)
        strategy: str = p.get("representative_strategy", "first")

        # 1. Split into paragraphs
        paragraphs = self._split_paragraphs(
            ctx.content,
            preserve_headings=preserve_h,
            preserve_code=preserve_c,
        )

        if len(paragraphs) < 2:
            self._report(ctx, paragraphs, [], 0, time.perf_counter() - t0)
            return ctx

        # 2. Identify eligible paragraphs
        eligible_indices = [
            i for i, para in enumerate(paragraphs)
            if not para.is_protected and len(para.text.strip()) >= min_len
        ]

        if len(eligible_indices) < 2:
            self._report(ctx, paragraphs, [], 0, time.perf_counter() - t0)
            return ctx

        eligible_texts = [paragraphs[i].text for i in eligible_indices]

        # 3. Generate embeddings
        model = _get_model(model_name)
        embeddings = model.encode(
            eligible_texts,
            batch_size=batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        embeddings = np.array(embeddings, dtype=np.float32)

        # 4. Compute similarity & cluster
        if use_faiss and len(eligible_indices) > 50:
            groups = self._cluster_faiss(
                embeddings, eligible_indices, threshold,
            )
        else:
            groups = self._cluster_cosine(
                embeddings, eligible_indices, threshold,
            )

        if not groups:
            self._report(ctx, paragraphs, [], 0, time.perf_counter() - t0)
            return ctx

        # 5. Select representatives and mark removals
        remove_set: Set[int] = set()
        final_groups: List[_DedupGroup] = []

        for group_indices in groups:
            rep_idx = self._select_representative(
                group_indices, paragraphs, strategy,
            )
            dups = [i for i in group_indices if i != rep_idx]
            remove_set.update(dups)

            final_groups.append(_DedupGroup(
                representative_idx=rep_idx,
                duplicate_indices=dups,
                preview=paragraphs[rep_idx].text[:80],
            ))

        # 6. Rebuild document
        kept = [
            para.text for i, para in enumerate(paragraphs)
            if i not in remove_set
        ]
        ctx.content = "\n\n".join(kept)

        elapsed = time.perf_counter() - t0
        self._report(ctx, paragraphs, final_groups, len(remove_set), elapsed)
        return ctx

    # ── Paragraph splitting ───────────────────────────────────────────────

    @staticmethod
    def _split_paragraphs(
        content: str,
        *,
        preserve_headings: bool = True,
        preserve_code: bool = True,
    ) -> List[_Paragraph]:
        """Split document into paragraphs, marking protected ones."""
        # Handle fenced code blocks as atomic units
        parts: List[str] = []
        code_flags: List[bool] = []

        fence_positions = [m.start() for m in _CODE_FENCE_RE.finditer(content)]
        if len(fence_positions) >= 2 and preserve_code:
            last = 0
            i = 0
            while i + 1 < len(fence_positions):
                # Before fence
                before = content[last:fence_positions[i]]
                if before.strip():
                    for p in before.split("\n\n"):
                        if p.strip():
                            parts.append(p.strip())
                            code_flags.append(False)

                # Code block
                # Find end of closing fence line
                close_start = fence_positions[i + 1]
                close_end = content.find("\n", close_start)
                if close_end == -1:
                    close_end = len(content)
                block = content[fence_positions[i]:close_end]
                parts.append(block)
                code_flags.append(True)

                last = close_end
                i += 2

            # Remainder
            remainder = content[last:]
            if remainder.strip():
                for p in remainder.split("\n\n"):
                    if p.strip():
                        parts.append(p.strip())
                        code_flags.append(False)
        else:
            for p in content.split("\n\n"):
                if p.strip():
                    parts.append(p.strip())
                    code_flags.append(False)

        paragraphs: List[_Paragraph] = []
        for idx, (text, is_code) in enumerate(zip(parts, code_flags)):
            protected = is_code
            if not protected and preserve_headings:
                if _ATX_HEADING_RE.match(text):
                    protected = True
                elif "\n" in text:
                    lines = text.split("\n")
                    if len(lines) >= 2 and _SETEXT_RE.match(lines[-1]):
                        protected = True
            paragraphs.append(_Paragraph(
                text=text, start_idx=idx, is_protected=protected,
            ))

        return paragraphs

    # ── Cosine clustering ─────────────────────────────────────────────────

    @staticmethod
    def _cluster_cosine(
        embeddings: np.ndarray,
        eligible_indices: List[int],
        threshold: float,
    ) -> List[List[int]]:
        """Greedy clustering via cosine similarity matrix."""
        n = len(eligible_indices)
        # Embeddings already L2-normalised → dot product = cosine
        sim_matrix = embeddings @ embeddings.T

        visited: Set[int] = set()
        groups: List[List[int]] = []

        for i in range(n):
            if i in visited:
                continue
            cluster = [eligible_indices[i]]
            visited.add(i)

            for j in range(i + 1, n):
                if j in visited:
                    continue
                if sim_matrix[i, j] >= threshold:
                    cluster.append(eligible_indices[j])
                    visited.add(j)

            if len(cluster) > 1:
                groups.append(cluster)

        return groups

    # ── FAISS clustering ──────────────────────────────────────────────────

    @staticmethod
    def _cluster_faiss(
        embeddings: np.ndarray,
        eligible_indices: List[int],
        threshold: float,
    ) -> List[List[int]]:
        """FAISS-accelerated clustering for large documents."""
        try:
            import faiss
        except ImportError:
            logger.warning("faiss not installed; falling back to cosine.")
            return SemanticDeduplicationPass._cluster_cosine(
                embeddings, eligible_indices, threshold,
            )

        n, d = embeddings.shape
        index = faiss.IndexFlatIP(d)  # inner product = cosine for normalised
        index.add(embeddings)

        # Search each vector for neighbours above threshold
        # Use k = min(n, 50) to limit search
        k = min(n, 50)
        scores, indices = index.search(embeddings, k)

        visited: Set[int] = set()
        groups: List[List[int]] = []

        for i in range(n):
            if i in visited:
                continue
            cluster = [eligible_indices[i]]
            visited.add(i)

            for j_pos in range(1, k):  # skip self at position 0
                j = int(indices[i, j_pos])
                if j < 0 or j in visited:
                    continue
                if scores[i, j_pos] >= threshold:
                    cluster.append(eligible_indices[j])
                    visited.add(j)

            if len(cluster) > 1:
                groups.append(cluster)

        return groups

    # ── Representative selection ──────────────────────────────────────────

    @staticmethod
    def _select_representative(
        group_indices: List[int],
        paragraphs: List[_Paragraph],
        strategy: str,
    ) -> int:
        if strategy == "longest":
            return max(group_indices, key=lambda i: len(paragraphs[i].text))
        # "first" — lowest index = earliest in document
        return min(group_indices)

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(
        self,
        ctx: OptimizationContext,
        paragraphs: List[_Paragraph],
        groups: List[_DedupGroup],
        removed: int,
        elapsed: float,
        skipped_reason: str = "",
    ) -> None:
        group_details = [
            {
                "representative_idx": g.representative_idx,
                "duplicate_indices": g.duplicate_indices,
                "duplicates": len(g.duplicate_indices),
                "preview": g.preview,
            }
            for g in groups
        ]

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "paragraphs_scanned": len(paragraphs),
            "paragraphs_protected": sum(1 for p in paragraphs if p.is_protected),
            "duplicate_groups": len(groups),
            "total_duplicates_removed": removed,
            "elapsed_seconds": round(elapsed, 4),
            "groups": group_details,
            **({"skipped_reason": skipped_reason} if skipped_reason else {}),
        }

"""
Tests for SemanticDeduplicationPass.

Uses mock embeddings to avoid requiring GPU/model downloads.
Tests cover: clustering, representative selection, protected zones,
config validation, graceful degradation, statistics, pipeline integration,
and benchmarks.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from typing import List

import numpy as np
import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.semantic_dedup import (
    SemanticDeduplicationPass,
    _Paragraph,
    _MODEL_CACHE,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Mock Helpers ──────────────────────────────────────────────────────────────


def _make_mock_model(embeddings_map: dict[str, np.ndarray] | None = None):
    """Create mock SentenceTransformer model.

    If *embeddings_map* given, ``encode()`` returns vectors by matching
    input text prefixes.  Otherwise returns random unit vectors.
    """
    model = MagicMock()

    def _encode(texts: List[str], **kwargs):
        if embeddings_map:
            vecs = []
            for t in texts:
                matched = False
                for key, vec in embeddings_map.items():
                    if key in t:
                        vecs.append(vec)
                        matched = True
                        break
                if not matched:
                    # Random orthogonal vector
                    v = np.random.randn(384).astype(np.float32)
                    v /= np.linalg.norm(v)
                    vecs.append(v)
            return np.array(vecs, dtype=np.float32)
        else:
            n = len(texts)
            vecs = np.random.randn(n, 384).astype(np.float32)
            norms = np.linalg.norm(vecs, axis=1, keepdims=True)
            return vecs / norms

    model.encode = _encode
    return model


def _similar_vec(base: np.ndarray, noise: float = 0.05) -> np.ndarray:
    """Create a vector similar to *base* with small perturbation."""
    v = base + np.random.randn(*base.shape).astype(np.float32) * noise
    v /= np.linalg.norm(v)
    return v


# Create a fixed "semantic cluster" — two similar vectors + one different
np.random.seed(42)
_VEC_A = np.random.randn(384).astype(np.float32)
_VEC_A /= np.linalg.norm(_VEC_A)
_VEC_A_SIMILAR = _similar_vec(_VEC_A, noise=0.03)
_VEC_B = np.random.randn(384).astype(np.float32)
_VEC_B /= np.linalg.norm(_VEC_B)


@pytest.fixture(autouse=True)
def _clear_model_cache():
    _MODEL_CACHE.clear()
    yield
    _MODEL_CACHE.clear()


def _run(content: str, params: dict | None = None,
         embeddings_map: dict | None = None) -> tuple[str, dict]:
    p = SemanticDeduplicationPass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})

    mock_model = _make_mock_model(embeddings_map)

    with patch("app.optimizer.passes.semantic_dedup._get_model", return_value=mock_model):
        ctx = OptimizationContext(content=content, original_content=content)
        ctx = p.run(ctx, config)

    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


# ── Tests: Basic Deduplication ───────────────────────────────────────────────


class TestBasicDedup:

    def test_removes_semantic_duplicate(self):
        doc = (
            "BB84 was proposed by Bennett and Brassard in 1984 as a protocol.\n\n"
            "Some completely unrelated paragraph about different topic here.\n\n"
            "The BB84 protocol was introduced by Bennett and Brassard in 1984."
        )
        emap = {
            "BB84 was proposed": _VEC_A,
            "BB84 protocol was introduced": _VEC_A_SIMILAR,
            "unrelated": _VEC_B,
        }
        output, metrics = _run(doc, embeddings_map=emap)
        assert metrics["total_duplicates_removed"] == 1
        assert metrics["duplicate_groups"] == 1

    def test_preserves_unique_paragraphs(self):
        doc = (
            "First unique paragraph about quantum computing and qubits.\n\n"
            "Second unique paragraph about machine learning models.\n\n"
            "Third unique paragraph about database optimization techniques."
        )
        # Default mock returns random vectors → all different
        output, metrics = _run(doc)
        assert metrics["total_duplicates_removed"] == 0

    def test_preserves_representative(self):
        doc = (
            "BB84 was proposed by Bennett and Brassard in 1984 as a protocol.\n\n"
            "The BB84 protocol was introduced by Bennett and Brassard in 1984."
        )
        emap = {
            "BB84 was proposed": _VEC_A,
            "BB84 protocol was introduced": _VEC_A_SIMILAR,
        }
        output, metrics = _run(
            doc,
            params={"representative_strategy": "first"},
            embeddings_map=emap,
        )
        assert "BB84 was proposed" in output
        assert metrics["total_duplicates_removed"] == 1


# ── Tests: Representative Strategy ───────────────────────────────────────────


class TestRepresentativeStrategy:

    def test_first_strategy(self):
        doc = (
            "Short version of the concept.\n\n"
            "A much longer and more detailed version of the same concept here."
        )
        emap = {
            "Short version": _VEC_A,
            "longer and more detailed": _VEC_A_SIMILAR,
        }
        output, _ = _run(
            doc,
            params={"representative_strategy": "first"},
            embeddings_map=emap,
        )
        assert "Short version" in output

    def test_longest_strategy(self):
        doc = (
            "Short version of the concept.\n\n"
            "A much longer and more detailed version of the same concept here."
        )
        emap = {
            "Short version": _VEC_A,
            "longer and more detailed": _VEC_A_SIMILAR,
        }
        output, _ = _run(
            doc,
            params={"representative_strategy": "longest"},
            embeddings_map=emap,
        )
        assert "longer and more detailed" in output


# ── Tests: Protected Zones ───────────────────────────────────────────────────


class TestProtectedZones:

    def test_headings_protected(self):
        doc = (
            "# Introduction to the Topic\n\n"
            "Introduction to the Topic is covered in detail here below."
        )
        emap = {
            "Introduction to the Topic": _VEC_A,
        }
        output, metrics = _run(doc, embeddings_map=emap)
        assert "# Introduction" in output
        assert metrics["paragraphs_protected"] >= 1

    def test_code_blocks_protected(self):
        doc = (
            "```python\nprint('hello world')\n```\n\n"
            "Some paragraph with similar content to the code block here."
        )
        output, metrics = _run(doc)
        assert "```python" in output
        assert metrics["paragraphs_protected"] >= 1


# ── Tests: Min Length Filtering ───────────────────────────────────────────────


class TestMinLength:

    def test_short_paragraphs_skipped(self):
        doc = "Short.\n\nShort."
        output, metrics = _run(doc, params={"min_paragraph_length": 30})
        assert metrics["total_duplicates_removed"] == 0


# ── Tests: Cosine Clustering ────────────────────────────────────────────────


class TestCosineClustering:

    def test_cluster_similar(self):
        embeddings = np.array([_VEC_A, _VEC_A_SIMILAR, _VEC_B], dtype=np.float32)
        groups = SemanticDeduplicationPass._cluster_cosine(
            embeddings, [0, 1, 2], threshold=0.85,
        )
        # A and A_similar should cluster
        assert len(groups) >= 1
        found = False
        for g in groups:
            if 0 in g and 1 in g:
                found = True
        assert found

    def test_no_cluster_different(self):
        v1 = np.random.randn(384).astype(np.float32)
        v1 /= np.linalg.norm(v1)
        v2 = np.random.randn(384).astype(np.float32)
        v2 /= np.linalg.norm(v2)
        embeddings = np.array([v1, v2], dtype=np.float32)
        groups = SemanticDeduplicationPass._cluster_cosine(
            embeddings, [0, 1], threshold=0.99,
        )
        assert len(groups) == 0


# ── Tests: Paragraph Splitting ───────────────────────────────────────────────


class TestParagraphSplitting:

    def test_basic_split(self):
        doc = "Para one.\n\nPara two.\n\nPara three."
        paras = SemanticDeduplicationPass._split_paragraphs(doc)
        assert len(paras) == 3

    def test_code_block_atomic(self):
        doc = "Before.\n\n```\ncode\nhere\n```\n\nAfter."
        paras = SemanticDeduplicationPass._split_paragraphs(doc)
        code_paras = [p for p in paras if p.is_protected and "code" in p.text]
        assert len(code_paras) == 1

    def test_heading_protected(self):
        doc = "# Title\n\nBody."
        paras = SemanticDeduplicationPass._split_paragraphs(doc)
        heading = [p for p in paras if p.is_protected]
        assert len(heading) == 1

    def test_empty(self):
        paras = SemanticDeduplicationPass._split_paragraphs("")
        assert len(paras) == 0


# ── Tests: Edge Cases ────────────────────────────────────────────────────────


class TestEdgeCases:

    def test_empty_doc(self):
        output, metrics = _run("")
        assert output == ""
        assert metrics["total_duplicates_removed"] == 0

    def test_single_paragraph(self):
        output, metrics = _run(
            "Just one paragraph that is long enough for processing."
        )
        assert metrics["total_duplicates_removed"] == 0

    def test_all_protected(self):
        doc = "# Heading One\n\n# Heading Two\n\n# Heading Three"
        output, metrics = _run(doc)
        assert metrics["total_duplicates_removed"] == 0


# ── Tests: Graceful Degradation ──────────────────────────────────────────────


class TestGracefulDegradation:

    def test_missing_sentence_transformers(self):
        p = SemanticDeduplicationPass()
        config = p.default_config
        ctx = OptimizationContext(
            content="Para one long enough.\n\nPara two long enough.",
            original_content="Para one long enough.\n\nPara two long enough.",
        )

        with patch.dict("sys.modules", {"sentence_transformers": None}):
            with patch(
                "builtins.__import__",
                side_effect=lambda name, *a, **kw: (
                    (_ for _ in ()).throw(ImportError(name))
                    if name == "sentence_transformers"
                    else __builtins__.__import__(name, *a, **kw)  # type: ignore
                ),
            ):
                ctx = p.run(ctx, config)

        metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
        assert metrics.get("skipped_reason", "").startswith("sentence-transformers")


# ── Tests: Config Validation ─────────────────────────────────────────────────


class TestConfigValidation:

    def test_invalid_threshold(self):
        from app.optimizer.exceptions import PassConfigError
        p = SemanticDeduplicationPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"similarity_threshold": 1.5}))

    def test_invalid_strategy(self):
        from app.optimizer.exceptions import PassConfigError
        p = SemanticDeduplicationPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"representative_strategy": "nope"}))

    def test_invalid_min_length(self):
        from app.optimizer.exceptions import PassConfigError
        p = SemanticDeduplicationPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"min_paragraph_length": -1}))

    def test_invalid_batch_size(self):
        from app.optimizer.exceptions import PassConfigError
        p = SemanticDeduplicationPass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={"batch_size": 0}))


# ── Tests: Statistics ────────────────────────────────────────────────────────


class TestStatistics:

    def test_metrics_keys(self):
        doc = (
            "First paragraph about quantum computing and research.\n\n"
            "Second paragraph about different machine learning topic."
        )
        _, metrics = _run(doc)
        expected = {
            "paragraphs_scanned", "paragraphs_protected",
            "duplicate_groups", "total_duplicates_removed",
            "elapsed_seconds", "groups",
        }
        assert expected.issubset(set(metrics.keys()))

    def test_group_detail(self):
        doc = (
            "BB84 was proposed by Bennett and Brassard in 1984 as a protocol.\n\n"
            "Unrelated paragraph about something completely different here.\n\n"
            "The BB84 protocol was introduced by Bennett and Brassard in 1984."
        )
        emap = {
            "BB84 was proposed": _VEC_A,
            "BB84 protocol was introduced": _VEC_A_SIMILAR,
            "Unrelated": _VEC_B,
        }
        _, metrics = _run(doc, embeddings_map=emap)
        assert len(metrics["groups"]) >= 1
        g = metrics["groups"][0]
        assert "representative_idx" in g
        assert "duplicate_indices" in g
        assert "preview" in g


# ── Tests: Threshold Sensitivity ──────────────────────────────────────────────


class TestThreshold:

    def test_high_threshold_fewer_removals(self):
        doc = (
            "BB84 was proposed by Bennett and Brassard in 1984 as a protocol.\n\n"
            "Middle unique paragraph about something completely different.\n\n"
            "The BB84 protocol was introduced by Bennett and Brassard in 1984."
        )
        emap = {
            "BB84 was proposed": _VEC_A,
            "BB84 protocol was introduced": _VEC_A_SIMILAR,
            "Middle unique": _VEC_B,
        }
        _, m_low = _run(doc, params={"similarity_threshold": 0.7}, embeddings_map=emap)
        _, m_high = _run(doc, params={"similarity_threshold": 0.99}, embeddings_map=emap)
        assert m_low["total_duplicates_removed"] >= m_high["total_duplicates_removed"]


# ── Tests: Benchmark ──────────────────────────────────────────────────────────


class TestBenchmark:

    @pytest.mark.parametrize("n_paragraphs", [20, 50])
    def test_throughput(self, n_paragraphs):
        """Verify pass completes in reasonable time with mocked model."""
        import time

        paras = [
            f"Paragraph number {i} discusses topic {i % 5} in detail here."
            for i in range(n_paragraphs)
        ]
        doc = "\n\n".join(paras)

        t0 = time.perf_counter()
        _run(doc)
        elapsed = time.perf_counter() - t0

        assert elapsed < 5.0, f"Too slow: {elapsed:.3f}s for {n_paragraphs} paragraphs"


# ── Tests: Pipeline Integration ───────────────────────────────────────────────


class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(SemanticDeduplicationPass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["semantic_deduplication"],
            collect_statistics=True,
        )
        doc = (
            "BB84 was proposed by Bennett and Brassard in 1984 as a protocol.\n\n"
            "Unique paragraph about different topic and ideas completely.\n\n"
            "The BB84 protocol was introduced by Bennett and Brassard in 1984."
        )
        emap = {
            "BB84 was proposed": _VEC_A,
            "BB84 protocol was introduced": _VEC_A_SIMILAR,
            "Unique": _VEC_B,
        }
        mock_model = _make_mock_model(emap)

        with patch("app.optimizer.passes.semantic_dedup._get_model", return_value=mock_model):
            result = PipelineExecutor(registry=r, config=config).run(doc)

        assert result.success
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["total_duplicates_removed"] == 1

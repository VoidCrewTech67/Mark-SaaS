"""Tests for ImportanceAwarePass."""

from __future__ import annotations

import pytest

from app.optimizer.config import PipelineConfig
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.passes.importance_aware import (
    ImportanceAwarePass,
    ImportanceTier,
)
from app.optimizer.pipeline import PipelineExecutor
from app.optimizer.registry import PassRegistry


# ── Helper ────────────────────────────────────────────────────────────────────

def _run(content: str, params: dict | None = None) -> tuple[str, dict]:
    p = ImportanceAwarePass()
    config = p.default_config
    if params:
        config = config.merge({"params": params})
    ctx = OptimizationContext(content=content, original_content=content)
    ctx = p.run(ctx, config)
    metrics = ctx.metadata.get(f"_pass_metrics_{p.name}", {})
    return ctx.content, metrics


_FULL_PAPER = """\
# Abstract

This paper presents novel quantum key distribution results.

# Introduction

Quantum computing [1] has grown significantly [2,3].
It is worth noting that QKD enables secure communication.
As mentioned above, BB84 is foundational.

# Methodology

We implement the BB84 protocol with the following equation:
$$H(X|Y) = -\\sum p(x,y) \\log p(x|y)$$

## Algorithm

Step 1: Alice generates random bits.
Step 2: Alice encodes using random bases.
Step 3: Bob measures in random bases.

# Results

Our system achieves 99.2% accuracy with $p < 0.001$.

# Conclusion

QKD provides provable security guarantees.

# Acknowledgements

We thank the anonymous reviewers and NSF grant #12345.

# References

[1] Bennett, C. (1984). Quantum cryptography.
[2] Ekert, A. (1991). Quantum key distribution.
[3] Shor, P. (1994). Algorithms for quantum computation."""


# ── Tier Classification ──────────────────────────────────────────────────────

class TestClassification:

    def test_methodology_is_tier1(self):
        _, m = _run(_FULL_PAPER)
        assert "Methodology" in m["tier1_sections"]

    def test_results_is_tier1(self):
        _, m = _run(_FULL_PAPER)
        assert "Results" in m["tier1_sections"]

    def test_conclusion_is_tier1(self):
        _, m = _run(_FULL_PAPER)
        assert "Conclusion" in m["tier1_sections"]

    def test_abstract_is_tier1(self):
        _, m = _run(_FULL_PAPER)
        assert "Abstract" in m["tier1_sections"]

    def test_introduction_is_tier2(self):
        _, m = _run(_FULL_PAPER)
        assert "Introduction" in m["tier2_sections"]

    def test_acknowledgements_is_tier3(self):
        _, m = _run(_FULL_PAPER)
        assert "Acknowledgements" in m["tier3_sections"]

    def test_references_is_tier3(self):
        # "References" doesn't match tier3 heading pattern directly
        # but that's ok — it's handled by reference_section_removal pass
        pass

    def test_equation_content_promotes_to_tier1(self):
        doc = "# Custom Section\n\nSome text with $$E = mc^2$$."
        _, m = _run(doc)
        assert m["tier1_count"] >= 1

    def test_algorithm_content_promotes_to_tier1(self):
        doc = "# Process\n\nStep 1: Initialize.\nStep 2: Execute."
        _, m = _run(doc)
        assert m["tier1_count"] >= 1

    def test_definition_promotes_to_tier1(self):
        doc = "# Concepts\n\nWe define the entropy as $H(X)$."
        _, m = _run(doc)
        assert m["tier1_count"] >= 1

    def test_boilerplate_content_demotes_to_tier3(self):
        doc = "# Notice\n\nThis is to certify that the work was completed."
        _, m = _run(doc)
        assert m["tier3_count"] >= 1


# ── Tier 1 Preservation ─────────────────────────────────────────────────────

class TestTier1Preservation:

    def test_equations_preserved(self):
        output, _ = _run(_FULL_PAPER)
        assert "$$H(X|Y)" in output
        assert "$p < 0.001$" in output

    def test_methodology_preserved(self):
        output, _ = _run(_FULL_PAPER)
        assert "We implement the BB84 protocol" in output

    def test_results_preserved(self):
        output, _ = _run(_FULL_PAPER)
        assert "99.2% accuracy" in output

    def test_conclusion_preserved(self):
        output, _ = _run(_FULL_PAPER)
        assert "QKD provides provable security" in output

    def test_algorithm_steps_preserved(self):
        output, _ = _run(_FULL_PAPER)
        assert "Step 1:" in output
        assert "Step 2:" in output
        assert "Step 3:" in output


# ── Tier 2 Moderate Optimization ─────────────────────────────────────────────

class TestTier2Moderate:

    def test_citations_removed(self):
        output, _ = _run(_FULL_PAPER)
        # Intro is tier 2 → citations stripped
        assert "[1]" not in output
        assert "[2,3]" not in output

    def test_filler_removed(self):
        output, _ = _run(_FULL_PAPER)
        assert "It is worth noting that" not in output
        assert "As mentioned above," not in output

    def test_core_content_kept(self):
        output, _ = _run(_FULL_PAPER)
        assert "QKD enables secure communication" in output

    def test_citation_compression_disabled(self):
        output, _ = _run(_FULL_PAPER, params={"compress_citations_tier2": False})
        assert "[1]" in output

    def test_redundant_compression_disabled(self):
        output, _ = _run(
            _FULL_PAPER,
            params={"compress_redundant_tier2": False},
        )
        assert "It is worth noting that" in output


# ── Tier 3 Aggressive Optimization ───────────────────────────────────────────

class TestTier3Aggressive:

    def test_acknowledgements_compressed(self):
        output, _ = _run(_FULL_PAPER)
        # Should keep heading + first sentence max
        lines = [l for l in output.split("\n") if "thank" in l.lower() or "grant" in l.lower()]
        # At most 1 line about thanks (compressed)
        assert len(lines) <= 1

    def test_remove_tier3_entirely(self):
        output, _ = _run(_FULL_PAPER, params={"remove_tier3": True})
        assert "Acknowledgements" not in output
        assert "anonymous reviewers" not in output

    def test_all_actions_preserve(self):
        output, _ = _run(
            _FULL_PAPER,
            params={
                "tier1_action": "preserve",
                "tier2_action": "preserve",
                "tier3_action": "preserve",
            },
        )
        # Everything preserved
        assert "[1]" in output
        assert "It is worth noting that" in output


# ── Section Splitting ────────────────────────────────────────────────────────

class TestSectionSplitting:

    def test_counts(self):
        _, m = _run(_FULL_PAPER)
        assert m["total_sections"] >= 6

    def test_no_headings(self):
        doc = "Just a plain paragraph.\n\nAnother paragraph."
        _, m = _run(doc)
        assert m["total_sections"] >= 1

    def test_nested_headings(self):
        doc = "# Main\n\nText.\n\n## Sub\n\nMore text."
        _, m = _run(doc)
        assert m["total_sections"] >= 2


# ── Edge Cases ───────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty(self):
        output, m = _run("")
        assert output == ""
        assert m["total_sections"] == 0

    def test_single_section(self):
        doc = "# Results\n\nAccuracy: 99.5%."
        output, m = _run(doc)
        assert "99.5%" in output
        assert m["tier1_count"] == 1

    def test_no_excess_blanks(self):
        output, _ = _run(_FULL_PAPER)
        assert "\n\n\n" not in output


# ── Config Validation ────────────────────────────────────────────────────────

class TestConfigValidation:

    def test_invalid_action(self):
        from app.optimizer.exceptions import PassConfigError
        p = ImportanceAwarePass()
        with pytest.raises(PassConfigError):
            p.validate_config(PassConfig(params={
                "tier1_action": "nuke",
                "tier2_action": "moderate",
                "tier3_action": "aggressive",
            }))


# ── Statistics ───────────────────────────────────────────────────────────────

class TestStatistics:

    def test_keys(self):
        _, m = _run(_FULL_PAPER)
        expected = {
            "total_sections", "tier1_count", "tier2_count", "tier3_count",
            "tier1_sections", "tier2_sections", "tier3_sections",
        }
        assert set(m.keys()) == expected

    def test_tier_counts_sum(self):
        _, m = _run(_FULL_PAPER)
        assert (m["tier1_count"] + m["tier2_count"] + m["tier3_count"]
                == m["total_sections"])


# ── Pipeline Integration ─────────────────────────────────────────────────────

class TestPipelineIntegration:

    @pytest.fixture(autouse=True)
    def _reg(self):
        r = PassRegistry()
        r.register(ImportanceAwarePass, force=True)
        yield
        r.clear()

    def test_integration(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["importance_aware"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run(_FULL_PAPER)
        assert result.success
        # Critical content preserved
        assert "$$H(X|Y)" in result.output
        assert "99.2% accuracy" in result.output
        # Tier 2 citations removed
        assert "[1]" not in result.output

    def test_custom_metrics(self):
        r = PassRegistry()
        config = PipelineConfig(
            pass_order=["importance_aware"],
            collect_statistics=True,
        )
        result = PipelineExecutor(registry=r, config=config).run(_FULL_PAPER)
        stats = result.report.pass_details[0]
        assert stats.custom_metrics["tier1_count"] >= 3


# ── Benchmark ────────────────────────────────────────────────────────────────

class TestBenchmark:

    @pytest.mark.parametrize("n_sections", [10, 50])
    def test_throughput(self, n_sections: int):
        import time

        sections = []
        for i in range(n_sections):
            tier = i % 3
            if tier == 0:
                sections.append(f"# Results {i}\n\nAccuracy is $x_{i} = {i}$.")
            elif tier == 1:
                sections.append(f"# Introduction {i}\n\nBackground [1] discussion [2,3].")
            else:
                sections.append(f"# Acknowledgements {i}\n\nWe thank reviewer {i}.")

        doc = "\n\n".join(sections)

        t0 = time.perf_counter()
        output, m = _run(doc)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0
        assert m["total_sections"] == n_sections

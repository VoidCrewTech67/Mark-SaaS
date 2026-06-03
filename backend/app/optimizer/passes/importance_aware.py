"""
optimizer/passes/importance_aware.py – Tier-based importance-aware optimization.

Architecture
============

1. **Classify** — Split doc into sections, assign importance tiers.
2. **Apply** — Per-tier optimization rules:
   - Tier 1 (critical): preserve almost completely.
   - Tier 2 (moderate): light optimization.
   - Tier 3 (low-value): aggressive removal/compression.

Tier classification
~~~~~~~~~~~~~~~~~~~

**Tier 1** (preserve):
  - Equations, methodology, definitions, algorithms, results, conclusions,
    theorems, proofs, abstract.

**Tier 2** (moderate):
  - Introduction, background, literature review, discussion, explanations.

**Tier 3** (aggressive):
  - Boilerplate, certificates, page numbers, TOC, acknowledgements,
    funding, author bios, formatting artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Dict, List, Optional, Set, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass


# ── Tiers ─────────────────────────────────────────────────────────────────────

class ImportanceTier(IntEnum):
    CRITICAL = 1    # preserve almost fully
    MODERATE = 2    # light optimization
    LOW = 3         # aggressive optimization


# ── Classification patterns ───────────────────────────────────────────────────

_TIER1_HEADINGS = re.compile(
    r"(?:method(?:ology|s)?|result(?:s)?|conclusion(?:s)?|"
    r"definition(?:s)?|algorithm(?:s)?|theorem(?:s)?|proof(?:s)?|"
    r"abstract|finding(?:s)?|contribution(?:s)?|"
    r"experiment(?:s|al)?|evaluation|analysis|framework|"
    r"model(?:ing)?|implementation|architecture|design|"
    r"formula(?:tion)?|derivation|hypothesis|observation(?:s)?)",
    re.IGNORECASE,
)

_TIER2_HEADINGS = re.compile(
    r"(?:introduction|background|related\s+work|literature|"
    r"survey|review|discussion|overview|motivation|"
    r"preliminaries|notation|context|scope|objectives?|"
    r"summary|future\s+work|limitations?|comparison)",
    re.IGNORECASE,
)

_TIER3_HEADINGS = re.compile(
    r"(?:acknowledg(?:e)?ment(?:s)?|funding|"
    r"conflict\s+of\s+interest|ethics|author\s+contribution(?:s)?|"
    r"data\s+availability|declaration(?:s)?|"
    r"table\s+of\s+contents|contents|appendix|"
    r"bio(?:graph(?:y|ies))?|affiliation(?:s)?|"
    r"copyright|disclaimer|colophon)",
    re.IGNORECASE,
)

# Content-level tier 1 indicators
_EQUATION_INDICATOR = re.compile(
    r"\$\$|\\\[|\\\(|\\begin\{(?:equation|align|gather)\}|"
    r"\\frac|\\sum|\\int|\\prod",
)
_DEFINITION_INDICATOR = re.compile(
    r"(?:(?:we\s+)?define|definition\s*\d*[:.]|"
    r"let\s+\$|denote(?:d|s)?\s+(?:by|as))",
    re.IGNORECASE,
)
_ALGORITHM_INDICATOR = re.compile(
    r"(?:algorithm\s*\d*[:.]|step\s+\d+[:.]|"
    r"input\s*:|output\s*:|procedure|pseudocode)",
    re.IGNORECASE,
)

# Content-level tier 3 indicators
_BOILERPLATE_INDICATOR = re.compile(
    r"(?:this\s+is\s+to\s+certif|certificate\s+of|"
    r"evaluation\s+(?:sheet|form|rubric)|"
    r"score\s*:|grade\s*:|marks\s*:|"
    r"page\s+\d+\s+of\s+\d+|"
    r"all\s+rights\s+reserved|"
    r"printed\s+(?:on|in|by)|"
    r"©\s*\d{4}|"
    r"confidential\s+(?:document|report))",
    re.IGNORECASE,
)

# Heading detection
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Citations for tier 2 compression
_CITATION_RE = re.compile(r"\[[\d,;\s–-]+\]")

# Redundant phrases for tier 2 compression
_REDUNDANT_PHRASES = [
    (re.compile(r"\bIt\s+(?:is|should\s+be)\s+(?:noted|mentioned|observed)\s+that\b", re.IGNORECASE), ""),
    (re.compile(r"\bAs\s+(?:mentioned|stated|discussed)\s+(?:above|earlier|previously|before)\b,?\s*", re.IGNORECASE), ""),
    (re.compile(r"\bIn\s+this\s+(?:section|paper|work|study),?\s+we\b", re.IGNORECASE), "We"),
    (re.compile(r"\bIt\s+is\s+(?:important|worth)\s+(?:to\s+note|noting|mentioning)\s+that\b", re.IGNORECASE), ""),
    (re.compile(r"\bFor\s+the\s+sake\s+of\s+(?:completeness|clarity|brevity)\b,?\s*", re.IGNORECASE), ""),
]


# ── Data ──────────────────────────────────────────────────────────────────────

@dataclass
class _Section:
    heading: str
    heading_level: int
    content: str
    start_line: int
    end_line: int
    tier: ImportanceTier = ImportanceTier.MODERATE
    raw_lines: List[str] = field(default_factory=list)


# ── Pass ─────────────────────────────────────────────────────────────────────

@register_pass
class ImportanceAwarePass(OptimizerPass):
    """Optimize sections differently based on content importance.

    Config params
    ~~~~~~~~~~~~~

    ============================== ============ ==============================
    Param                          Default      Description
    ============================== ============ ==============================
    tier1_action                   ``"preserve"``   Tier 1 action.
    tier2_action                   ``"moderate"``   Tier 2 action.
    tier3_action                   ``"aggressive"`` Tier 3 action.
    remove_tier3                   ``False``    Remove tier 3 entirely.
    compress_citations_tier2       ``True``     Strip citations in tier 2.
    compress_redundant_tier2       ``True``     Strip filler phrases in tier 2.
    ============================== ============ ==============================
    """

    @property
    def name(self) -> str:
        return "importance_aware"

    @property
    def description(self) -> str:
        return "Importance-tiered document optimization."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=50,
            params={
                "tier1_action": "preserve",
                "tier2_action": "moderate",
                "tier3_action": "aggressive",
                "remove_tier3": False,
                "compress_citations_tier2": True,
                "compress_redundant_tier2": True,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        from app.optimizer.exceptions import PassConfigError
        p = config.params
        for key in ("tier1_action", "tier2_action", "tier3_action"):
            val = p.get(key, "")
            if val not in ("preserve", "moderate", "aggressive"):
                raise PassConfigError(
                    self.name,
                    f"{key} must be preserve/moderate/aggressive, got {val!r}",
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
            self._report(ctx, [], {})
            return ctx

        # 1. Split into sections
        sections = self._split_sections(content)

        # 2. Classify tiers
        for section in sections:
            section.tier = self._classify(section)

        # 3. Apply per-tier optimization
        action_map = {
            ImportanceTier.CRITICAL: p.get("tier1_action", "preserve"),
            ImportanceTier.MODERATE: p.get("tier2_action", "moderate"),
            ImportanceTier.LOW: p.get("tier3_action", "aggressive"),
        }

        output_parts: List[str] = []
        for section in sections:
            action = action_map[section.tier]
            optimized = self._apply_action(section, action, p)
            if optimized is not None:
                output_parts.append(optimized)

        ctx.content = "\n\n".join(output_parts).strip()
        ctx.content = re.sub(r"\n{3,}", "\n\n", ctx.content)

        self._report(ctx, sections, action_map)
        return ctx

    # ── Section splitting ─────────────────────────────────────────────────

    @staticmethod
    def _split_sections(content: str) -> List[_Section]:
        lines = content.split("\n")
        sections: List[_Section] = []
        current_heading = ""
        current_level = 0
        current_lines: List[str] = []
        current_start = 0

        for i, line in enumerate(lines):
            m = _HEADING_RE.match(line)
            if m:
                # Flush previous section
                if current_lines or current_heading:
                    sections.append(_Section(
                        heading=current_heading,
                        heading_level=current_level,
                        content="\n".join(current_lines),
                        start_line=current_start,
                        end_line=i,
                        raw_lines=list(current_lines),
                    ))
                current_heading = m.group(2).strip()
                current_level = len(m.group(1))
                current_lines = [line]
                current_start = i
            else:
                current_lines.append(line)

        # Last section
        if current_lines or current_heading:
            sections.append(_Section(
                heading=current_heading,
                heading_level=current_level,
                content="\n".join(current_lines),
                start_line=current_start,
                end_line=len(lines),
                raw_lines=list(current_lines),
            ))

        return sections

    # ── Classification ────────────────────────────────────────────────────

    @staticmethod
    def _classify(section: _Section) -> ImportanceTier:
        heading = section.heading
        content = section.content

        # Heading-based classification
        if heading:
            if _TIER1_HEADINGS.search(heading):
                return ImportanceTier.CRITICAL
            if _TIER3_HEADINGS.search(heading):
                return ImportanceTier.LOW
            if _TIER2_HEADINGS.search(heading):
                return ImportanceTier.MODERATE

        # Content-based classification
        if _EQUATION_INDICATOR.search(content):
            return ImportanceTier.CRITICAL
        if _DEFINITION_INDICATOR.search(content):
            return ImportanceTier.CRITICAL
        if _ALGORITHM_INDICATOR.search(content):
            return ImportanceTier.CRITICAL

        if _BOILERPLATE_INDICATOR.search(content):
            return ImportanceTier.LOW

        # Default
        return ImportanceTier.MODERATE

    # ── Per-tier actions ──────────────────────────────────────────────────

    def _apply_action(
        self,
        section: _Section,
        action: str,
        params: dict,
    ) -> Optional[str]:
        content = section.content

        if action == "preserve":
            return content

        if action == "aggressive":
            if params.get("remove_tier3", False):
                return None  # remove entirely
            # Strip most content, keep heading only
            return self._aggressive_compress(section)

        if action == "moderate":
            return self._moderate_compress(section, params)

        return content

    @staticmethod
    def _aggressive_compress(section: _Section) -> str:
        """Keep heading + first sentence only."""
        lines = section.content.split("\n")
        kept: List[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if _HEADING_RE.match(line):
                kept.append(line)
                continue
            # Keep first non-empty line as summary
            if not any(not _HEADING_RE.match(k) for k in kept if k.strip()):
                kept.append(line)
                break

        return "\n".join(kept) if kept else ""

    @staticmethod
    def _moderate_compress(section: _Section, params: dict) -> str:
        """Light optimization: strip citations, filler phrases."""
        content = section.content

        if params.get("compress_citations_tier2", True):
            content = _CITATION_RE.sub("", content)

        if params.get("compress_redundant_tier2", True):
            for pattern, replacement in _REDUNDANT_PHRASES:
                content = pattern.sub(replacement, content)

        # Collapse multi-spaces
        content = re.sub(r"  +", " ", content)
        content = re.sub(r" +\.", ".", content)
        content = re.sub(r"\n{3,}", "\n\n", content)

        return content

    # ── Metrics ───────────────────────────────────────────────────────────

    def _report(
        self,
        ctx: OptimizationContext,
        sections: List[_Section],
        action_map: dict,
    ) -> None:
        tier_counts = {1: 0, 2: 0, 3: 0}
        tier_sections: Dict[int, List[str]] = {1: [], 2: [], 3: []}

        for s in sections:
            tier_counts[s.tier] += 1
            if s.heading:
                tier_sections[s.tier].append(s.heading)

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "total_sections": len(sections),
            "tier1_count": tier_counts[1],
            "tier2_count": tier_counts[2],
            "tier3_count": tier_counts[3],
            "tier1_sections": tier_sections[1],
            "tier2_sections": tier_sections[2],
            "tier3_sections": tier_sections[3],
        }

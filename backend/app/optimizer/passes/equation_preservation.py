"""
optimizer/passes/equation_preservation.py – Extract/restore equations.

Architecture
============

Two-pass design:

1. ``EquationExtractionPass`` (priority=1, runs FIRST)
   - Detect all math/equation patterns
   - Replace with unique placeholders ``⟦EQ_NNN⟧``
   - Store mapping in ``ctx.metadata["_equation_map"]``

2. ``EquationRestorationPass`` (priority=99, runs LAST)
   - Read mapping from ``ctx.metadata["_equation_map"]``
   - Restore all placeholders → original equation text
   - Zero modification guarantee

Detected patterns
~~~~~~~~~~~~~~~~~

- Display math: ``$$...$$``
- Inline math: ``$...$``
- LaTeX environments: ``\\begin{equation}...\\end{equation}``, align, gather, etc.
- LaTeX commands in text: ``\\frac{}{}``, ``\\sum``, ``\\int``, etc.
- Scientific notation: ``1.5 × 10^3``, ``3.14e-5``, ``6.022 × 10²³``
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.optimizer.base import OptimizerPass
from app.optimizer.models import OptimizationContext, PassConfig
from app.optimizer.registry import register_pass

# ── Placeholder format ────────────────────────────────────────────────────────
# Use unusual Unicode brackets to avoid collision w/ any real content
_PLACEHOLDER_FMT = "\u27e6EQ_{idx:04d}\u27e7"  # ⟦EQ_0001⟧
_PLACEHOLDER_RE = re.compile(r"\u27e6EQ_(\d{4})\u27e7")

# ── Detection patterns (order matters: longest/greediest first) ───────────────

# LaTeX environments (display)
_LATEX_ENV_RE = re.compile(
    r"\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|"
    r"eqnarray\*?|displaymath|math|split|cases|array)\}"
    r".*?"
    r"\\end\{\1\}",
    re.DOTALL,
)

# Display math $$...$$
_DISPLAY_MATH_RE = re.compile(r"\$\$(?:[^$]|\\\$)+?\$\$", re.DOTALL)

# \[...\] display math
_BRACKET_DISPLAY_RE = re.compile(r"\\\[.*?\\\]", re.DOTALL)

# Inline math $...$ (not $$, not escaped \$, not empty)
_INLINE_MATH_RE = re.compile(
    r"(?<!\$)(?<!\\)\$(?!\$)(?:[^$\n\\]|\\.)+\$(?!\$)"
)

# \(...\) inline math
_PAREN_INLINE_RE = re.compile(r"\\\(.*?\\\)", re.DOTALL)

# Standalone LaTeX commands (common math commands not inside $...$)
_LATEX_CMD_RE = re.compile(
    r"\\(?:frac|sqrt|sum|prod|int|lim|log|ln|sin|cos|tan|exp|"
    r"partial|nabla|infty|alpha|beta|gamma|delta|epsilon|theta|"
    r"lambda|mu|sigma|omega|pi|phi|psi|rho|tau|chi|eta|zeta|"
    r"cdot|times|div|pm|mp|leq|geq|neq|approx|equiv|subset|"
    r"supset|cup|cap|forall|exists|in|notin|rightarrow|leftarrow|"
    r"Rightarrow|Leftarrow|vec|hat|bar|tilde|dot|ddot|"
    r"mathbb|mathcal|mathbf|mathrm|text|operatorname)"
    r"(?:\{[^}]*\}|\[[^\]]*\]|[_^]\{[^}]*\}|[_^]\S)*",
)

# Scientific notation: 1.5×10^3, 6.022e23, 3.14E-5, 1.5 × 10³
_SCI_NOTATION_RE = re.compile(
    r"\b\d+\.?\d*\s*[×x]\s*10\s*[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+\b"  # Unicode superscript
    r"|\b\d+\.?\d*\s*[×x]\s*10\s*\^\s*\{?[+-]?\d+\}?"   # 10^{-3} or 10^3
    r"|\b\d+\.?\d*[eE][+-]?\d+\b",                        # 3.14e-5
    re.UNICODE,
)

# Subscript/superscript patterns outside math: x₁, x², H₂O
_SUB_SUPER_RE = re.compile(
    r"[A-Za-z][₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+",
    re.UNICODE,
)

# All patterns in priority order
_ALL_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("latex_env", _LATEX_ENV_RE),
    ("display_math", _DISPLAY_MATH_RE),
    ("bracket_display", _BRACKET_DISPLAY_RE),
    ("inline_math", _INLINE_MATH_RE),
    ("paren_inline", _PAREN_INLINE_RE),
    ("latex_cmd", _LATEX_CMD_RE),
    ("sci_notation", _SCI_NOTATION_RE),
    ("sub_super", _SUB_SUPER_RE),
]

# Metadata key
_EQ_MAP_KEY = "_equation_map"
_EQ_TYPES_KEY = "_equation_types"


# ── Extraction Pass ──────────────────────────────────────────────────────────

@register_pass
class EquationExtractionPass(OptimizerPass):
    """Extract equations → placeholders before other passes run.

    Config params
    ~~~~~~~~~~~~~

    ======================== ============ ==============================
    Param                    Default      Description
    ======================== ============ ==============================
    detect_latex_env         ``True``     LaTeX environments
    detect_display_math      ``True``     $$...$$ blocks
    detect_inline_math       ``True``     $...$ inline
    detect_latex_commands    ``True``     Standalone \\frac, \\sum, etc.
    detect_sci_notation      ``True``     Scientific notation
    detect_sub_super         ``False``    Unicode sub/superscripts
    ======================== ============ ==============================
    """

    @property
    def name(self) -> str:
        return "equation_extraction"

    @property
    def description(self) -> str:
        return "Extract equations and replace with placeholders."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=1,  # run FIRST
            params={
                "detect_latex_env": True,
                "detect_display_math": True,
                "detect_inline_math": True,
                "detect_latex_commands": True,
                "detect_sci_notation": True,
                "detect_sub_super": False,
            },
        )

    def validate_config(self, config: PassConfig) -> None:
        pass  # all booleans

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        p = config.params
        content = ctx.content

        if not content.strip():
            self._report(ctx, {}, {})
            return ctx

        # Build active pattern list
        active: List[Tuple[str, re.Pattern]] = []
        param_map = {
            "latex_env": "detect_latex_env",
            "display_math": "detect_display_math",
            "bracket_display": "detect_display_math",
            "inline_math": "detect_inline_math",
            "paren_inline": "detect_inline_math",
            "latex_cmd": "detect_latex_commands",
            "sci_notation": "detect_sci_notation",
            "sub_super": "detect_sub_super",
        }
        for pat_name, pattern in _ALL_PATTERNS:
            cfg_key = param_map.get(pat_name, "")
            if p.get(cfg_key, True):
                active.append((pat_name, pattern))

        # Find all matches (non-overlapping, priority order)
        eq_map: Dict[str, str] = {}       # placeholder → original
        type_map: Dict[str, str] = {}     # placeholder → type
        occupied: List[Tuple[int, int]] = []  # occupied ranges
        idx = 0

        for pat_name, pattern in active:
            for m in pattern.finditer(content):
                start, end = m.start(), m.end()
                # Skip if overlaps w/ already-extracted region
                if _overlaps(start, end, occupied):
                    continue
                placeholder = _PLACEHOLDER_FMT.format(idx=idx)
                eq_map[placeholder] = m.group()
                type_map[placeholder] = pat_name
                occupied.append((start, end))
                idx += 1

        if not eq_map:
            self._report(ctx, {}, {})
            return ctx

        # Sort occupied by start desc → replace from end to preserve positions
        occupied_with_ph = sorted(
            zip(
                occupied,
                list(eq_map.keys())[:len(occupied)],
            ),
            key=lambda x: x[0][0],
            reverse=True,
        )

        for (start, end), placeholder in occupied_with_ph:
            content = content[:start] + placeholder + content[end:]

        ctx.content = content
        ctx.metadata[_EQ_MAP_KEY] = eq_map
        ctx.metadata[_EQ_TYPES_KEY] = type_map

        self._report(ctx, eq_map, type_map)
        return ctx

    def _report(
        self,
        ctx: OptimizationContext,
        eq_map: Dict[str, str],
        type_map: Dict[str, str],
    ) -> None:
        # Count by type
        type_counts: Dict[str, int] = {}
        for ph, t in type_map.items():
            type_counts[t] = type_counts.get(t, 0) + 1

        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "equations_extracted": len(eq_map),
            "by_type": type_counts,
        }


# ── Restoration Pass ─────────────────────────────────────────────────────────

@register_pass
class EquationRestorationPass(OptimizerPass):
    """Restore equations from placeholders after all other passes.

    Reads ``ctx.metadata["_equation_map"]`` and replaces every
    ``⟦EQ_NNNN⟧`` placeholder with the original equation text.
    Zero modification guaranteed.
    """

    @property
    def name(self) -> str:
        return "equation_restoration"

    @property
    def description(self) -> str:
        return "Restore equations from placeholders."

    @property
    def default_config(self) -> PassConfig:
        return PassConfig(
            enabled=True,
            priority=99,  # run LAST
            params={},
        )

    def validate_config(self, config: PassConfig) -> None:
        pass

    def run(
        self,
        ctx: OptimizationContext,
        config: PassConfig,
    ) -> OptimizationContext:
        eq_map: Dict[str, str] = ctx.metadata.get(_EQ_MAP_KEY, {})

        if not eq_map:
            self._report(ctx, 0, 0)
            return ctx

        content = ctx.content
        restored = 0
        orphaned = 0

        for placeholder, original in eq_map.items():
            if placeholder in content:
                content = content.replace(placeholder, original)
                restored += 1
            else:
                orphaned += 1

        ctx.content = content
        self._report(ctx, restored, orphaned)
        return ctx

    def _report(
        self,
        ctx: OptimizationContext,
        restored: int,
        orphaned: int,
    ) -> None:
        ctx.metadata[f"_pass_metrics_{self.name}"] = {
            "equations_restored": restored,
            "orphaned_placeholders": orphaned,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _overlaps(
    start: int, end: int, ranges: List[Tuple[int, int]],
) -> bool:
    for rs, re_ in ranges:
        if start < re_ and end > rs:
            return True
    return False

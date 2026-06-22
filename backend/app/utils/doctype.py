"""
utils/doctype.py — Lightweight content-based document-type detection.

Used to enrich RAG responses with a human-meaningful ``document_type``
(e.g. "resume", "documentation", "contract"). Heuristics only — no ML.
Falls back to "general_document". Document-type agnostic by design: every
branch is optional and the default is always safe.
"""

from __future__ import annotations

import re


def _has_any(text: str, terms: list[str]) -> int:
    """Count how many of *terms* appear in *text* (already lowercased)."""
    return sum(1 for t in terms if t in text)


def detect_document_type(
    markdown: str,
    original_name: str = "",
    *,
    requested_type: str | None = None,
) -> str:
    """Return a lightweight document_type label.

    Args:
        markdown:       Extracted/optimized markdown.
        original_name:  Source filename (extension is a strong signal).
        requested_type: The user-selected type ("research_paper" wins if set,
                        since it is an explicit choice).

    Returns one of (heuristic-only; low confidence → "generic"):
        research_paper, documentation, report, resume, contract, manual, generic.
    """
    # Explicit user intent for research_paper is authoritative.
    if requested_type == "research_paper":
        return "research_paper"

    text = (markdown or "").lower()
    head = text[:4000]  # most signals live near the top

    # Resume / CV
    if (
        _has_any(head, ["curriculum vitae", "résumé", "resume"])
        or (
            _has_any(text, ["work experience", "professional experience", "employment"])
            and _has_any(text, ["education", "skills", "certifications"]) >= 2
        )
    ):
        return "resume"

    # Contract / legal
    if _has_any(text, [
        "this agreement", "hereby agree", "terms and conditions",
        "the parties", "shall not", "governing law", "in witness whereof",
    ]) >= 2:
        return "contract"

    # Research paper
    if (
        "abstract" in head
        and _has_any(text, ["references", "bibliography", "et al", "doi:"]) >= 1
    ):
        return "research_paper"

    # Documentation
    if (
        text.count("```") >= 4
        or _has_any(head, ["installation", "getting started", "quick start", "api reference", "usage"]) >= 2
    ):
        return "documentation"

    # Manual / guide
    if _has_any(text, ["user manual", "user guide", "instruction manual"]) or len(
        re.findall(r"^\s*step\s+\d+", text, re.MULTILINE)
    ) >= 3:
        return "manual"

    # Report
    if _has_any(text, [
        "executive summary", "quarterly report", "annual report",
        "fiscal year", "key findings",
    ]) >= 1:
        return "report"

    # Low confidence → generic
    return "generic"

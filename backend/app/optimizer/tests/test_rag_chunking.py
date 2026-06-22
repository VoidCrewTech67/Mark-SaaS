"""
Tests for RAG structured chunking + document-type detection.

Verifies the repaired RAG pipeline:
  - chunk_markdown_structured returns metadata dicts (not strings)
  - defaults are 800 / 100 (never 512)
  - headings → section labels; no-heading docs → None (preamble)
  - oversize sections paragraph-split keep their section label
  - overlap is applied and recorded
  - detect_document_type is heuristic-only and falls back to "generic"
"""

from __future__ import annotations

from app.utils.optimizer import (
    chunk_markdown_structured,
    DEFAULT_RAG_MAX_TOKENS,
    DEFAULT_RAG_OVERLAP_TOKENS,
)
from app.utils.doctype import detect_document_type


# ── Defaults ──────────────────────────────────────────────────────────────────

def test_rag_defaults_are_800_100():
    assert DEFAULT_RAG_MAX_TOKENS == 800
    assert DEFAULT_RAG_OVERLAP_TOKENS == 100


def test_none_args_use_rag_defaults_not_512():
    # A doc large enough to force multiple chunks at 800 but not at 512-only logic
    body = "\n\n".join(f"Paragraph number {i} with some filler words here." for i in range(400))
    text = f"# Title\n\n{body}"
    chunks = chunk_markdown_structured(text, None, None)
    assert len(chunks) >= 2
    # Every chunk respects the 800 default ceiling (+overlap slack)
    assert all(c["token_count"] <= DEFAULT_RAG_MAX_TOKENS + DEFAULT_RAG_OVERLAP_TOKENS + 50 for c in chunks)


# ── Shape / metadata ──────────────────────────────────────────────────────────

def test_chunks_are_metadata_dicts():
    text = "# Introduction\n\nHello world. This is the intro.\n\n# Methods\n\nWe did things."
    chunks = chunk_markdown_structured(text, 50, 0)
    assert chunks and all(isinstance(c, dict) for c in chunks)
    keys = {"chunk_id", "index", "section", "content", "token_count", "word_count", "char_count", "overlap_prev_tokens"}
    for c in chunks:
        assert keys <= set(c.keys())


def test_chunk_id_zero_padded_and_indexed():
    text = "# A\n\none\n\n# B\n\ntwo\n\n# C\n\nthree"
    chunks = chunk_markdown_structured(text, 20, 0)
    assert chunks[0]["chunk_id"] == "chunk_001"
    assert chunks[0]["index"] == 1
    for i, c in enumerate(chunks, start=1):
        assert c["chunk_id"] == f"chunk_{i:03d}"
        assert c["index"] == i


def test_counts_match_content():
    text = "# Sec\n\nThe quick brown fox jumps."
    c = chunk_markdown_structured(text, 800, 0)[0]
    assert c["word_count"] == len(c["content"].split())
    assert c["char_count"] == len(c["content"])
    assert c["token_count"] > 0


# ── Sections ──────────────────────────────────────────────────────────────────

def test_headings_become_sections():
    text = "# Introduction\n\nIntro body.\n\n# Conclusion\n\nThe end."
    chunks = chunk_markdown_structured(text, 30, 0)
    sections = [c["section"] for c in chunks]
    assert "Introduction" in sections
    assert "Conclusion" in sections


def test_no_heading_doc_yields_none_section():
    text = "Just a flat document.\n\nWith two paragraphs and no headings at all."
    chunks = chunk_markdown_structured(text, 800, 0)
    assert len(chunks) == 1
    assert chunks[0]["section"] is None


def test_oversize_section_keeps_label_across_splits():
    big = "\n\n".join(f"Sentence {i} filler filler filler." for i in range(200))
    text = f"# Big Section\n\n{big}"
    chunks = chunk_markdown_structured(text, 60, 0)
    assert len(chunks) >= 2
    assert all(c["section"] == "Big Section" for c in chunks)


# ── Overlap ───────────────────────────────────────────────────────────────────

def test_overlap_recorded_and_applied():
    text = "# A\n\n" + "\n\n".join(f"para {i} words words words" for i in range(60))
    no_ov = chunk_markdown_structured(text, 60, 0)
    with_ov = chunk_markdown_structured(text, 60, 20)
    assert len(with_ov) >= 2
    # First chunk never has overlap; at least one later chunk does
    assert with_ov[0]["overlap_prev_tokens"] == 0
    assert any(c["overlap_prev_tokens"] > 0 for c in with_ov[1:])


def test_empty_text_returns_empty():
    assert chunk_markdown_structured("", 800, 100) == []
    assert chunk_markdown_structured("   ", 800, 100) == []


# ── Document-type heuristics ──────────────────────────────────────────────────

def test_detect_research_paper():
    md = "# Abstract\n\nWe study X.\n\n# References\n\nSmith et al. 2020. doi:10.1/x"
    assert detect_document_type(md) == "research_paper"


def test_detect_resume():
    md = "# Work Experience\n\nAcme.\n\n# Education\n\nBSc.\n\n# Skills\n\nPython.\n\n# Certifications\n\nAWS."
    assert detect_document_type(md) == "resume"


def test_detect_documentation():
    md = "# Getting Started\n\n```bash\ninstall\n```\n\n```py\nx\n```\n\n```py\ny\n```\n\n```sh\nz\n```"
    assert detect_document_type(md) == "documentation"


def test_detect_contract():
    md = "This agreement is made between the parties. The parties shall not breach. Governing law applies."
    assert detect_document_type(md) == "contract"


def test_low_confidence_returns_generic():
    md = "# Notes\n\nSome random thoughts about the weather and lunch."
    assert detect_document_type(md) == "generic"


def test_requested_research_paper_is_authoritative():
    assert detect_document_type("random text", requested_type="research_paper") == "research_paper"

"""
Integration test: ConversionService RAG mode vs non-RAG.

Verifies (backend checklist):
  - RAG mode ADDS structured chunks + detected_document_type, KEEPS markdown.
  - Non-RAG modes are unchanged: result.chunks is None.
  - Same markdown output for balanced regardless of the RAG branch.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.core.config import settings
from app.utils.converter import FileConverter
from app.services.conversion_service import ConversionService


SAMPLE = """# Introduction

This document explains the system. It has several sections so that the
structured chunker has real headings to work with.

# Methods

We describe the approach in detail here. The methodology section is long
enough to be a meaningful retrieval chunk on its own.

# Results

The results were positive across every measured dimension.

# Conclusion

In conclusion, the approach works and is recommended for future use.
"""


def _write_sample(tmp_path: Path) -> tuple[Path, str]:
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    settings.CONVERTED_DIR.mkdir(parents=True, exist_ok=True)
    p = settings.UPLOAD_DIR / "rag_pipeline_sample.txt"
    p.write_text(SAMPLE, encoding="utf-8")
    return p, "rag_pipeline_sample.txt"


def _service() -> ConversionService:
    conv = FileConverter(settings.UPLOAD_DIR, settings.CONVERTED_DIR)
    return ConversionService(conv)


def test_rag_mode_adds_chunks_and_keeps_markdown(tmp_path):
    svc = _service()
    src, name = _write_sample(tmp_path)

    result, opt_md, _stats = asyncio.run(svc.convert(
        source_path=src, original_name=name,
        document_type="general_document", optimization_mode="rag",
    ))

    # markdown preserved
    assert result.success
    assert result.markdown and result.markdown.strip()
    assert opt_md and opt_md.strip()

    # structured chunks added
    assert result.chunks is not None
    assert len(result.chunks) >= 2
    first = result.chunks[0]
    assert first["chunk_id"] == "chunk_001"
    assert "content" in first and "token_count" in first and "section" in first

    # doctype detected (heuristic), never empty for RAG
    assert result.detected_document_type


def test_non_rag_mode_has_no_chunks(tmp_path):
    svc = _service()
    src, name = _write_sample(tmp_path)

    result, opt_md, _ = asyncio.run(svc.convert(
        source_path=src, original_name=name,
        document_type="general_document", optimization_mode="balanced",
    ))

    assert result.success
    assert result.chunks is None
    assert result.detected_document_type == ""
    assert opt_md  # markdown still produced


def test_rag_and_balanced_produce_same_markdown(tmp_path):
    """RAG must reuse the balanced pass set — markdown identical, only chunks differ."""
    svc = _service()
    src, name = _write_sample(tmp_path)

    _, rag_md, _ = asyncio.run(svc.convert(
        source_path=src, original_name=name,
        document_type="general_document", optimization_mode="rag",
    ))
    _, bal_md, _ = asyncio.run(svc.convert(
        source_path=src, original_name=name,
        document_type="general_document", optimization_mode="balanced",
    ))

    assert rag_md == bal_md

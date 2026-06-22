"""
services/docling_service.py — Lazy Docling wrapper for research paper extraction.

Docling's DocumentConverter is heavy (loads ML models). This service uses a
class-level singleton so the converter is instantiated only on first use,
avoiding any startup cost when research_paper mode is never requested.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Class-level cache — shared across all instances / calls
_CONVERTER_CACHE: dict = {}


class DoclingService:
    """Converts documents (primarily PDFs) to Markdown using Docling."""

    @classmethod
    def _get_converter(cls):
        """Lazy-load the Docling DocumentConverter on first use."""
        if "converter" not in _CONVERTER_CACHE:
            logger.info("[docling_service] Loading Docling DocumentConverter (first use)…")
            try:
                from docling.document_converter import DocumentConverter
                _CONVERTER_CACHE["converter"] = DocumentConverter()
                logger.info("[docling_service] Docling DocumentConverter ready.")
            except ImportError as exc:
                logger.error(
                    "[docling_service] Docling is not installed. "
                    "Install with: pip install docling"
                )
                raise ImportError(
                    "Docling is required for research_paper mode. "
                    "Install with: pip install docling"
                ) from exc
        return _CONVERTER_CACHE["converter"]

    async def convert(self, source_path: Path) -> str:
        """Convert a document to Markdown using Docling.

        Args:
            source_path: Path to the source file (typically a PDF).

        Returns:
            Extracted Markdown string.

        Raises:
            ImportError: If docling is not installed.
            RuntimeError: If conversion fails.
        """
        loop = asyncio.get_event_loop()
        converter = self._get_converter()

        def _do_convert() -> str:
            logger.info("[docling_service] Converting '%s'…", source_path.name)
            result = converter.convert(str(source_path))
            # Try to embed page-break markers so the RAG chunker can attach
            # page_number metadata. Newer Docling supports page_break_placeholder;
            # older versions fall back to plain export_to_markdown().
            try:
                md = result.document.export_to_markdown(
                    page_break_placeholder="<!-- page-break -->",
                )
            except TypeError:
                md = result.document.export_to_markdown()
            logger.info(
                "[docling_service] Done: %d chars extracted from '%s'",
                len(md), source_path.name,
            )
            return md

        try:
            return await loop.run_in_executor(None, _do_convert)
        except Exception as exc:
            logger.exception(
                "[docling_service] Conversion failed for '%s': %s",
                source_path.name, exc,
            )
            raise RuntimeError(
                f"Docling conversion failed for '{source_path.name}': {exc}"
            ) from exc

"""
services/extractors.py — Unified extraction interface.

Provides a common ABC for document extractors and two implementations:
  - MarkItDownExtractor: wraps FileConverter + OCR fallback
  - DoclingExtractor:    wraps DoclingService (lazy singleton), falls back to MarkItDown

Both return an ExtractionResult dataclass. The optimizer layer downstream
never needs to know which extractor produced the markdown.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.utils.token_counter import estimate_tokens

logger = logging.getLogger(__name__)


# ── Extraction result ─────────────────────────────────────────────────────────

@dataclass
class ExtractionResult:
    """Extractor-agnostic output container."""

    markdown: str
    extractor: str            # "markitdown" | "docling"
    success: bool
    error: Optional[str] = None
    duration_s: float = 0.0
    ocr_used: bool = False
    ocr_warning: str = ""
    embedded_images_ocr_count: int = 0
    file_size_bytes: int = 0
    token_count: int = 0      # estimated tokens in raw markdown

    def __post_init__(self) -> None:
        if self.token_count == 0 and self.markdown:
            self.token_count = estimate_tokens(self.markdown)


# ── Abstract base ─────────────────────────────────────────────────────────────

class Extractor(ABC):
    """Common interface for all document extractors."""

    name: str = "base"

    @abstractmethod
    async def extract(
        self,
        file_path: Path,
        original_name: str,
        **kwargs,
    ) -> ExtractionResult:
        """Extract markdown from a document.

        Args:
            file_path: Path to the source file on disk.
            original_name: User-visible filename.
            **kwargs: Extractor-specific options.

        Returns:
            ExtractionResult with markdown + metadata.
        """
        ...


# ── MarkItDown extractor ─────────────────────────────────────────────────────

class MarkItDownExtractor(Extractor):
    """Wraps the existing FileConverter + OCR fallback pipeline."""

    name = "markitdown"

    def __init__(self, converter) -> None:
        """
        Args:
            converter: An instance of app.utils.converter.FileConverter.
        """
        self._converter = converter

    async def extract(
        self,
        file_path: Path,
        original_name: str,
        *,
        embedded_ocr_mode: str = "Smart (Recommended)",
        **kwargs,
    ) -> ExtractionResult:
        loop = asyncio.get_event_loop()
        start = time.perf_counter()

        logger.info(
            "[markitdown_extractor] Extracting '%s' (ocr_mode=%s)",
            original_name, embedded_ocr_mode,
        )

        # Step 1: MarkItDown conversion
        result = await loop.run_in_executor(
            None,
            lambda: self._converter.convert(
                file_path, original_name, embedded_ocr_mode,
            ),
        )

        if not result.success:
            return ExtractionResult(
                markdown="",
                extractor=self.name,
                success=False,
                error=result.error,
                duration_s=time.perf_counter() - start,
                file_size_bytes=result.file_size_bytes,
            )

        # Step 2: Whole-document OCR fallback
        from app.utils.ocr_handler import needs_ocr_fallback, run_ocr

        ocr_used = result.ocr_used
        ocr_warning = result.ocr_warning or ""

        if needs_ocr_fallback(result.markdown, file_path):
            logger.info(
                "[markitdown_extractor] OCR fallback triggered for '%s'",
                original_name,
            )
            ocr_text, ocr_warn = await loop.run_in_executor(
                None, lambda: run_ocr(file_path),
            )
            if ocr_text:
                result.markdown = ocr_text
                ocr_used = True
                result._compute_stats()
            if ocr_warn:
                ocr_warning = ocr_warn

        duration = time.perf_counter() - start
        md = result.markdown or ""

        logger.info(
            "[markitdown_extractor] Done: '%s' → %d chars, %d tokens in %.2fs",
            original_name, len(md), estimate_tokens(md), duration,
        )

        return ExtractionResult(
            markdown=md,
            extractor=self.name,
            success=True,
            duration_s=duration,
            ocr_used=ocr_used,
            ocr_warning=ocr_warning,
            embedded_images_ocr_count=result.embedded_images_ocr_count,
            file_size_bytes=result.file_size_bytes,
        )


# ── Docling extractor ────────────────────────────────────────────────────────

class DoclingExtractor(Extractor):
    """Wraps DoclingService. Falls back to MarkItDown on failure."""

    name = "docling"

    def __init__(self, markitdown_fallback: MarkItDownExtractor) -> None:
        self._fallback = markitdown_fallback

    async def extract(
        self,
        file_path: Path,
        original_name: str,
        **kwargs,
    ) -> ExtractionResult:
        start = time.perf_counter()

        logger.info(
            "[docling_extractor] Extracting '%s' via Docling", original_name,
        )

        try:
            from app.services.docling_service import DoclingService
            docling_svc = DoclingService()
            md = await docling_svc.convert(file_path)

            duration = time.perf_counter() - start
            logger.info(
                "[docling_extractor] Done: '%s' → %d chars, %d tokens in %.2fs",
                original_name, len(md), estimate_tokens(md), duration,
            )

            return ExtractionResult(
                markdown=md,
                extractor=self.name,
                success=True,
                duration_s=duration,
                file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            )

        except (ImportError, RuntimeError) as exc:
            logger.warning(
                "[docling_extractor] Docling unavailable/failed for '%s': %s. "
                "Falling back to MarkItDown.",
                original_name, exc,
            )
            result = await self._fallback.extract(
                file_path, original_name, **kwargs,
            )
            # Mark that we fell back but still report the actual extractor used
            result.extractor = f"docling→markitdown"
            return result


# ── Factory ───────────────────────────────────────────────────────────────────

def get_extractor(
    document_type: str,
    converter,
    *,
    extractor_override: Optional[str] = None,
) -> Extractor:
    """Return the appropriate extractor for the given document_type.

    Args:
        document_type: 'research_paper' or 'general_document'.
        converter: FileConverter instance (needed for MarkItDown).
        extractor_override: Force a specific extractor ('markitdown' | 'docling').

    Returns:
        An Extractor instance.
    """
    mit = MarkItDownExtractor(converter)

    # Explicit override takes precedence
    if extractor_override == "docling":
        return DoclingExtractor(markitdown_fallback=mit)
    if extractor_override == "markitdown":
        return mit

    # Default: research_paper → docling, general → markitdown
    if document_type == "research_paper":
        return DoclingExtractor(markitdown_fallback=mit)
    return mit

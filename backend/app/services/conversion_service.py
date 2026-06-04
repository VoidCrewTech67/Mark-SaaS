"""
services/conversion_service.py

Unified conversion pipeline: Extractor → Optimizer → Output.

The service:
  1. Selects an extractor based on document_type (or explicit override).
  2. Extracts raw markdown (extractor-agnostic).
  3. Optimizes using the universal optimizer with mode-based passes.
  4. Returns (ConversionResult, optimized_markdown, OptimizationStats).

Both MarkItDown and Docling extracted markdown flows through the exact
same optimization pipeline. The optimizer never knows which extractor
produced the markdown.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.utils.converter import FileConverter, ConversionResult
from app.utils.optimizer import OptimizationStats

logger = logging.getLogger(__name__)


class ConversionService:
    """Orchestrates the unified Extractor → Optimizer pipeline."""

    def __init__(self, converter: FileConverter) -> None:
        self._converter = converter

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def convert(
        self,
        source_path: Path,
        original_name: str,
        document_type: str = "general_document",
        optimization_mode: str | None = None,
        embedded_ocr_mode: str = "Smart (Recommended)",
        extractor_override: str | None = None,
    ) -> tuple[ConversionResult, str, Optional[OptimizationStats]]:
        """Run the full pipeline asynchronously.

        Args:
            source_path: Path to the uploaded file on disk.
            original_name: User-visible filename.
            document_type: 'research_paper' or 'general_document'.
            optimization_mode: 'safe'|'balanced'|'aggressive'|'rag'. Default: 'balanced'.
            embedded_ocr_mode: OCR mode (only used by MarkItDown extractor).
            extractor_override: Force 'markitdown' or 'docling' regardless of document_type.

        Returns:
            (ConversionResult, optimized_markdown, OptimizationStats)
        """
        # ── 1. Select extractor ─────────────────────────────────────────
        from app.services.extractors import get_extractor

        extractor = get_extractor(
            document_type=document_type,
            converter=self._converter,
            extractor_override=extractor_override,
        )

        logger.info(
            "[conversion_service] Pipeline: extractor=%s, mode=%s, doc_type=%s, file='%s'",
            extractor.name, optimization_mode or "balanced",
            document_type, original_name,
        )

        # ── 2. Extract → raw markdown ───────────────────────────────────
        extraction = await extractor.extract(
            file_path=source_path,
            original_name=original_name,
            embedded_ocr_mode=embedded_ocr_mode,
        )

        # Build ConversionResult from extraction
        result = ConversionResult(
            source_path=source_path,
            source_name=original_name,
            success=extraction.success,
            error=extraction.error,
            markdown=extraction.markdown,
            duration_s=extraction.duration_s,
            file_size_bytes=extraction.file_size_bytes,
            ocr_used=extraction.ocr_used,
            ocr_warning=extraction.ocr_warning,
            embedded_images_ocr_count=extraction.embedded_images_ocr_count,
        )
        if result.success:
            result._compute_stats()

        if not extraction.success:
            logger.warning(
                "[conversion_service] Extraction failed for '%s': %s",
                original_name, extraction.error,
            )
            return result, "", None

        # ── 3. Optimize (mode-based, extractor-agnostic) ────────────────
        mode = optimization_mode or "balanced"

        from app.services.optimization_service import OptimizationService
        opt_svc = OptimizationService()

        opt_md, opt_stats = await opt_svc.optimize(extraction.markdown, mode=mode)

        logger.info(
            "[conversion_service] Done: '%s' extractor=%s mode=%s "
            "saved %d tokens (%.1f%%)",
            original_name, extraction.extractor, mode,
            opt_stats.tokens_saved, opt_stats.percent_saved,
        )

        return result, opt_md, opt_stats

    # ------------------------------------------------------------------
    # Passthrough helpers (expose converter internals cleanly)
    # ------------------------------------------------------------------

    def is_supported(self, filename: str) -> bool:
        return self._converter.is_supported(filename)

    async def save_upload(self, filename: str, data: bytes) -> tuple[Path, str]:
        """Save upload bytes to disk asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._converter.save_upload(filename, data)
        )

    async def cleanup_files(self, paths: list[Path]) -> None:
        """Delete files from disk asynchronously."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, lambda: self._converter.cleanup_session_files(paths)
        )

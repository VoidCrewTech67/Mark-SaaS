"""
services/conversion_service.py

Thin async wrapper around FileConverter + OCR fallback + Markdown optimization.

The service:
  1. Calls FileConverter.convert() (sync, CPU-bound) via run_in_executor.
  2. Applies the whole-document OCR fallback if MarkItDown output is too short.
  3. Runs Markdown optimization.
  4. Returns (ConversionResult, optimized_markdown, OptimizationStats).

All sync work is dispatched to the default thread-pool executor so the
FastAPI event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from app.utils.converter import FileConverter, ConversionResult
from app.utils.ocr_handler import needs_ocr_fallback, run_ocr
from app.utils.optimizer import optimize_markdown, OptimizationStats

logger = logging.getLogger(__name__)


class ConversionService:
    """Orchestrates the full conversion pipeline asynchronously."""

    def __init__(self, converter: FileConverter) -> None:
        self._converter = converter

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def convert(
        self,
        source_path: Path,
        original_name: str,
        embedded_ocr_mode: str = "Smart (Recommended)",
    ) -> tuple[ConversionResult, str, Optional[OptimizationStats]]:
        """Run the full pipeline asynchronously.

        Returns:
            (result, optimized_markdown, opt_stats)
            optimized_markdown and opt_stats are empty/None on failure.
        """
        loop = asyncio.get_event_loop()

        # ── Step 1: MarkItDown + embedded OCR (sync → thread pool) ──────
        logger.info("[conversion_service] Starting convert for '%s'", original_name)
        result: ConversionResult = await loop.run_in_executor(
            None,
            lambda: self._converter.convert(
                source_path, original_name, embedded_ocr_mode
            ),
        )

        if not result.success:
            logger.warning(
                "[conversion_service] Conversion failed for '%s': %s",
                original_name, result.error,
            )
            return result, "", None

        # ── Step 2: Whole-document OCR fallback ─────────────────────────
        if needs_ocr_fallback(result.markdown, source_path):
            logger.info(
                "[conversion_service] OCR fallback triggered for '%s'", original_name
            )
            ocr_text, ocr_warning = await loop.run_in_executor(
                None, lambda: run_ocr(source_path)
            )
            if ocr_text:
                result.markdown = ocr_text
                result.ocr_used = True
                result._compute_stats()
                logger.info(
                    "[conversion_service] OCR fallback succeeded: %d chars", len(ocr_text)
                )
            if ocr_warning:
                result.ocr_warning = ocr_warning

        # ── Step 3: Markdown optimization ───────────────────────────────
        opt_md: str = await loop.run_in_executor(
            None, lambda: optimize_markdown(result.markdown)
        )
        opt_stats = OptimizationStats(
            original_text=result.markdown,
            optimized_text=opt_md,
        )
        logger.info(
            "[conversion_service] Optimization saved %d tokens (%.1f%%) for '%s'",
            opt_stats.tokens_saved, opt_stats.percent_saved, original_name,
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

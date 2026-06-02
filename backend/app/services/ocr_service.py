"""
services/ocr_service.py

Thin async wrapper exposing OCR capabilities for the API layer.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.utils.ocr_handler import (
    warm_up_reader,
    run_ocr,
    needs_ocr_fallback,
    ocr_available,
    pdf_ocr_available,
    OCR_AVAILABLE,
)

logger = logging.getLogger(__name__)


class OCRService:
    """Async facade over ocr_handler functions."""

    async def warm_up(self) -> None:
        """Pre-load EasyOCR weights in a thread so startup is non-blocking."""
        if not OCR_AVAILABLE:
            logger.info("[ocr_service] OCR not available — skipping warm-up.")
            return
        logger.info("[ocr_service] Warming up EasyOCR reader…")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, warm_up_reader)
        logger.info("[ocr_service] EasyOCR reader warm-up complete.")

    async def run_ocr(self, path: Path) -> tuple[str, str]:
        """Run whole-document OCR asynchronously."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: run_ocr(path))

    def is_ocr_available(self) -> bool:
        return ocr_available()

    def is_pdf_ocr_available(self) -> bool:
        return pdf_ocr_available()

    def needs_fallback(self, text: str, path: Path) -> bool:
        return needs_ocr_fallback(text, path)

"""
services/zip_service.py

Async wrapper around zip_handler for the API layer.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Sequence

from app.utils.zip_handler import build_zip, build_zip_from_strings

logger = logging.getLogger(__name__)


class ZipService:
    """Async facade over zip_handler functions."""

    async def build_zip_from_paths(
        self, paths: Sequence[Path]
    ) -> tuple[bytes, list[str]]:
        """Build a ZIP from on-disk .md files asynchronously.

        Returns (zip_bytes, skipped_filenames).
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: build_zip(paths)
        )

    async def build_zip_from_strings(
        self, items: Sequence[tuple[str, str]]
    ) -> bytes:
        """Build a ZIP from (filename, content) pairs asynchronously.

        Returns raw ZIP bytes ready for a StreamingResponse.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: build_zip_from_strings(items)
        )

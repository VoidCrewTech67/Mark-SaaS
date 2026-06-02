"""
services/chunking_service.py

Async wrapper around optimizer.chunk_markdown for the API layer.
"""

from __future__ import annotations

import asyncio
import logging

from app.utils.optimizer import chunk_markdown

logger = logging.getLogger(__name__)


class ChunkingService:
    """Async facade over chunk_markdown."""

    async def chunk(
        self,
        text: str,
        max_tokens: int,
        overlap_tokens: int | None = None,
    ) -> list[str]:
        """Split *text* into token-bounded chunks asynchronously.

        Args:
            text:           Markdown source to split.
            max_tokens:     Hard token limit per chunk.
            overlap_tokens: Tokens to repeat at chunk boundaries. None → 10%.

        Returns:
            List of chunk strings (at least one element).
        """
        loop = asyncio.get_event_loop()
        chunks: list[str] = await loop.run_in_executor(
            None,
            lambda: chunk_markdown(text, max_tokens, overlap_tokens),
        )
        logger.info(
            "[chunking_service] Produced %d chunk(s) (max=%d tokens, overlap=%s)",
            len(chunks), max_tokens, overlap_tokens,
        )
        return chunks

"""
services/chunking_service.py

Async wrapper around optimizer.chunk_markdown for the API layer.
"""

from __future__ import annotations

import asyncio
import logging

from app.utils.optimizer import chunk_markdown, chunk_markdown_structured

logger = logging.getLogger(__name__)


class ChunkingService:
    """Async facade over chunk_markdown / chunk_markdown_structured."""

    async def chunk_structured(
        self,
        text: str,
        max_tokens: int | None = None,
        overlap_tokens: int | None = None,
        *,
        source_file: str | None = None,
        document_type: str | None = None,
    ) -> list[dict]:
        """Split *text* into retrieval-oriented chunks with metadata.

        Shared by /api/convert (RAG mode) and /api/chunk so both paths use
        one structured chunking implementation.

        Args:
            text:           Markdown source to split.
            max_tokens:     Hard token limit. None → RAG default (800).
            overlap_tokens: Boundary overlap. None → RAG default (100).
            source_file:    Original filename, copied into every chunk's metadata.
            document_type:  Heuristic label, copied into every chunk's metadata.

        Returns:
            List of chunk dicts (chunk_id, index, section, content,
            token_count, word_count, char_count, overlap_prev_tokens,
            page_number, source_file, document_type, has_table, table_summary).
        """
        loop = asyncio.get_event_loop()
        chunks: list[dict] = await loop.run_in_executor(
            None,
            lambda: chunk_markdown_structured(
                text, max_tokens, overlap_tokens,
                source_file=source_file,
                document_type=document_type,
            ),
        )
        logger.info(
            "[chunking_service] Produced %d structured chunk(s) (max=%s, overlap=%s)",
            len(chunks), max_tokens, overlap_tokens,
        )
        return chunks

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

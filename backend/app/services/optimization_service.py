"""
services/optimization_service.py

Async wrapper around optimizer.py for the API layer.
"""

from __future__ import annotations

import asyncio
import logging

from app.utils.optimizer import optimize_markdown, OptimizationStats

logger = logging.getLogger(__name__)


class OptimizationService:
    """Async facade over optimizer functions."""

    async def optimize(self, markdown: str) -> tuple[str, OptimizationStats]:
        """Run the full optimization pipeline asynchronously.

        Returns (optimized_markdown, stats).
        """
        loop = asyncio.get_event_loop()
        opt_md: str = await loop.run_in_executor(
            None, lambda: optimize_markdown(markdown)
        )
        stats = OptimizationStats(original_text=markdown, optimized_text=opt_md)
        logger.info(
            "[optimization_service] Saved %d tokens (%.1f%%)",
            stats.tokens_saved, stats.percent_saved,
        )
        return opt_md, stats

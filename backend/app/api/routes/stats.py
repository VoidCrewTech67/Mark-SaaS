"""
api/routes/stats.py

GET /api/stats/{id} — return conversion statistics for a given file_id.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.services import get_result_registry
from app.models.responses import StatsResponse, OptimizationStatsResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/stats/{file_id}",
    response_model=StatsResponse,
    summary="Get conversion statistics for a file",
    description=(
        "Returns character count, word count, token estimate, file size, "
        "duration, OCR status, and optimization savings for the given file_id."
    ),
)
async def get_stats(
    file_id: str,
    result_registry: dict = Depends(get_result_registry),
) -> StatsResponse:
    entry = result_registry.get(file_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No stats available for file_id '{file_id}'. "
                "The file may not have been converted yet, or the result has expired."
            ),
        )

    result = entry.get("result")
    if not result:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Corrupt registry entry for file_id '{file_id}'.",
        )

    opt_stats = entry.get("opt_stats")
    opt_stats_response: OptimizationStatsResponse | None = None
    if opt_stats is not None:
        opt_stats_response = OptimizationStatsResponse(
            original_tokens=opt_stats.original_tokens,
            optimized_tokens=opt_stats.optimized_tokens,
            tokens_saved=opt_stats.tokens_saved,
            percent_saved=opt_stats.percent_saved,
        )

    logger.debug("[stats] Returning stats for file_id=%s", file_id)

    return StatsResponse(
        file_id=file_id,
        source_name=result.source_name,
        char_count=result.char_count,
        word_count=result.word_count,
        token_estimate=result.token_estimate,
        file_size_bytes=result.file_size_bytes,
        duration_s=result.duration_s,
        ocr_used=result.ocr_used,
        ocr_warning=result.ocr_warning,
        embedded_images_ocr_count=result.embedded_images_ocr_count,
        optimization_stats=opt_stats_response,
    )

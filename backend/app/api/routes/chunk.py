"""
api/routes/chunk.py

POST /api/chunk — split a converted file's Markdown into token-bounded chunks.

The endpoint:
  1. Looks up file_id in result_registry (file must be converted first).
  2. Selects optimized or raw Markdown based on the request flag.
  3. Calls ChunkingService.chunk() asynchronously.
  4. Stores chunks back into result_registry[file_id]["chunks"] for download.
  5. Returns the chunks inline plus metadata.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.services import (
    get_chunking_service,
    get_result_registry,
)
from app.models.requests import ChunkRequest
from app.models.responses import ChunkResponse
from app.services.chunking_service import ChunkingService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/chunk",
    response_model=ChunkResponse,
    summary="Split a converted document into token-bounded chunks",
    description=(
        "The file must be converted first via POST /api/convert. "
        "Chunks are returned inline and also stored for GET /api/download-zip/{id}."
    ),
)
async def chunk_document(
    body: ChunkRequest,
    svc: ChunkingService = Depends(get_chunking_service),
    result_registry: dict = Depends(get_result_registry),
) -> ChunkResponse:
    # ── Validate file_id exists and is converted ─────────────────────────────
    entry = result_registry.get(body.file_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No conversion result found for file_id '{body.file_id}'. "
                "Convert the file first via POST /api/convert."
            ),
        )

    result = entry.get("result")
    if not result or not result.success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conversion for file_id '{body.file_id}' did not succeed — cannot chunk.",
        )

    # ── Choose source text ───────────────────────────────────────────────────
    optimized_md: str = entry.get("optimized_markdown", "")
    if body.use_optimized and optimized_md:
        source_text = optimized_md
        source_label = "optimized"
    else:
        source_text = result.markdown
        source_label = "raw"

    logger.info(
        "[chunk] Chunking file_id=%s (%s), max_tokens=%d, overlap=%s",
        body.file_id, source_label, body.max_tokens, body.overlap_tokens,
    )

    # ── Run chunking ─────────────────────────────────────────────────────────
    chunks = await svc.chunk(source_text, body.max_tokens, body.overlap_tokens)

    # Resolve actual overlap used (mirrors chunk_markdown default logic)
    actual_overlap = (
        body.overlap_tokens
        if body.overlap_tokens is not None
        else max(0, int(body.max_tokens * 0.10))
    )

    # ── Persist chunks for download endpoint ─────────────────────────────────
    entry["chunks"] = chunks
    entry["chunk_source_name"] = entry.get("original_name", body.file_id)

    logger.info(
        "[chunk] Produced %d chunk(s) for file_id=%s", len(chunks), body.file_id
    )

    return ChunkResponse(
        file_id=body.file_id,
        chunks=chunks,
        chunk_count=len(chunks),
        max_tokens=body.max_tokens,
        overlap_tokens=actual_overlap,
        source=source_label,
    )

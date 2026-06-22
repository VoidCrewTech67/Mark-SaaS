"""
api/routes/convert.py

POST /api/convert       — single file conversion
POST /api/convert/batch — multi-file conversion

Both endpoints:
  1. Look up the file_id in the upload_registry.
  2. Delegate to ConversionService.convert() (async, non-blocking).
  3. Store the result in result_registry for later retrieval.
  4. Return a ConversionResponse with markdown + optimization stats.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies.services import (
    get_conversion_service,
    get_upload_registry,
    get_result_registry,
)
from app.models.requests import ConvertRequest, BatchConvertRequest
from app.models.responses import (
    ConversionResponse,
    BatchConversionResponse,
    OptimizationStatsResponse,
    ChunkMeta,
)
from app.services.conversion_service import ConversionService

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _lookup_upload(file_id: str, upload_registry: dict) -> dict:
    """Raise 404 if file_id is not in the registry."""
    meta = upload_registry.get(file_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"file_id '{file_id}' not found. Upload the file first via POST /api/upload.",
        )
    return meta


async def _run_single_conversion(
    file_id: str,
    document_type: str,
    optimization_mode: str | None,
    embedded_ocr_mode: str,
    upload_registry: dict,
    result_registry: dict,
    svc: ConversionService,
    extractor_override: str | None = None,
    chunk_max_tokens: int | None = None,
    chunk_overlap_tokens: int | None = None,
) -> ConversionResponse:
    """Core logic shared by single and batch convert."""
    meta = _lookup_upload(file_id, upload_registry)
    source_path: Path = meta["path"]
    original_name: str = meta["original_name"]

    if not source_path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Uploaded file for file_id '{file_id}' has been deleted (TTL expired).",
        )

    logger.info(
        "[convert] Starting conversion — file_id=%s, name='%s', doc_type=%s, mode=%s",
        file_id, original_name, document_type, optimization_mode,
    )

    result, opt_md, opt_stats = await svc.convert(
        source_path=source_path,
        original_name=original_name,
        document_type=document_type,
        optimization_mode=optimization_mode,
        embedded_ocr_mode=embedded_ocr_mode,
        extractor_override=extractor_override,
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
    )

    # ── Build optimization stats response ───────────────────────────────────
    opt_stats_response: OptimizationStatsResponse | None = None
    if opt_stats is not None:
        opt_stats_response = OptimizationStatsResponse(
            original_tokens       = opt_stats.original_tokens,
            optimized_tokens      = opt_stats.optimized_tokens,
            tokens_saved          = opt_stats.tokens_saved,
            percent_saved         = opt_stats.percent_saved,
            semantic_preservation = opt_stats.semantic_preservation,
            semantic_loss         = opt_stats.semantic_loss,
            context_preservation  = opt_stats.context_preservation,
            overall_preservation  = opt_stats.overall_preservation,
            scoring_method        = opt_stats.scoring_method,
            context_breakdown     = opt_stats.context_breakdown,
            issues                = opt_stats.issues,
        )

    # ── Build RAG structured-chunk response (additive — markdown preserved) ──
    rag_chunks: list[ChunkMeta] | None = None
    if result.success and result.chunks:
        rag_chunks = [ChunkMeta(**c) for c in result.chunks]

    # ── Persist in result registry for /stats and /download ─────────────────
    # RAG chunks (dicts) stored so /api/download-zip can build the archive.
    result_registry[file_id] = {
        "result": result,
        "optimized_markdown": opt_md,
        "opt_stats": opt_stats,
        "original_name": original_name,
        "chunks": result.chunks if result.chunks else None,
    }

    logger.info(
        "[convert] Done — file_id=%s, success=%s, duration=%.2fs",
        file_id, result.success, result.duration_s,
    )

    # ── Determine which extractor was used ───────────────────────────────────
    # Report the REAL extractor (set by the extractor layer, e.g.
    # "docling→markitdown" when Docling failed and fell back). Falls back to
    # the requested one only if the result didn't record it.
    extractor_name = result.extractor or extractor_override or (
        "docling" if document_type == "research_paper" else "markitdown"
    )

    return ConversionResponse(
        file_id=file_id,
        source_name=result.source_name,
        success=result.success,
        error=result.error if not result.success else None,
        document_type=document_type,
        optimization_mode=optimization_mode or "balanced",
        extractor=extractor_name,
        markdown=result.markdown if result.success else None,
        optimized_markdown=opt_md if result.success and opt_md else None,
        duration_s=result.duration_s,
        ocr_used=result.ocr_used,
        ocr_warning=result.ocr_warning,
        embedded_images_ocr_count=result.embedded_images_ocr_count,
        char_count=result.char_count,
        word_count=result.word_count,
        token_estimate=result.token_estimate,
        file_size_bytes=result.file_size_bytes,
        optimization_stats=opt_stats_response,
        # RAG-only fields (None/0 for other modes → backward compatible)
        mode="rag" if rag_chunks is not None else None,
        detected_document_type=result.detected_document_type or None,
        chunk_count=len(rag_chunks) if rag_chunks else 0,
        chunks=rag_chunks,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/convert",
    response_model=ConversionResponse,
    summary="Convert a single uploaded file to Markdown",
    description=(
        "Runs the full pipeline: MarkItDown → embedded image OCR → "
        "OCR fallback → Markdown optimization. "
        "Returns the raw and optimized Markdown plus statistics."
    ),
)
async def convert_single(
    body: ConvertRequest,
    svc: ConversionService = Depends(get_conversion_service),
    upload_registry: dict = Depends(get_upload_registry),
    result_registry: dict = Depends(get_result_registry),
) -> ConversionResponse:
    return await _run_single_conversion(
        file_id=body.file_id,
        document_type=body.document_type,
        optimization_mode=body.optimization_mode,
        embedded_ocr_mode=body.embedded_ocr_mode,
        upload_registry=upload_registry,
        result_registry=result_registry,
        svc=svc,
        extractor_override=body.extractor_override,
        chunk_max_tokens=body.chunk_max_tokens,
        chunk_overlap_tokens=body.chunk_overlap_tokens,
    )


@router.post(
    "/convert/batch",
    response_model=BatchConversionResponse,
    summary="Convert multiple uploaded files to Markdown",
    description=(
        "Processes each file sequentially (EasyOCR is a singleton CPU resource). "
        "Returns a list of ConversionResponse objects in the same order as the request."
    ),
)
async def convert_batch(
    body: BatchConvertRequest,
    svc: ConversionService = Depends(get_conversion_service),
    upload_registry: dict = Depends(get_upload_registry),
    result_registry: dict = Depends(get_result_registry),
) -> BatchConversionResponse:
    results: list[ConversionResponse] = []

    for item in body.items:
        try:
            response = await _run_single_conversion(
                file_id=item.file_id,
                document_type=item.document_type,
                optimization_mode=item.optimization_mode,
                embedded_ocr_mode=item.embedded_ocr_mode,
                upload_registry=upload_registry,
                result_registry=result_registry,
                svc=svc,
                extractor_override=item.extractor_override,
                chunk_max_tokens=item.chunk_max_tokens,
                chunk_overlap_tokens=item.chunk_overlap_tokens,
            )
        except HTTPException as exc:
            # Surface per-file errors without aborting the whole batch
            response = ConversionResponse(
                file_id=item.file_id,
                source_name=upload_registry.get(item.file_id, {}).get("original_name", item.file_id),
                success=False,
                error=exc.detail,
            )
        results.append(response)

    succeeded = sum(1 for r in results if r.success)
    return BatchConversionResponse(
        results=results,
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
    )

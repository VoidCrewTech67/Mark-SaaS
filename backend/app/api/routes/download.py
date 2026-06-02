"""
api/routes/download.py

GET /api/download/{id}      — download the converted .md file
GET /api/download-zip/{id}  — download chunks as a ZIP (requires prior /api/chunk call)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies.services import (
    get_result_registry,
    get_zip_service,
)
from app.core.config import settings
from app.services.zip_service import ZipService

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get(
    "/download/{file_id}",
    summary="Download the converted Markdown file",
    description=(
        "Returns the raw `.md` file produced by the conversion pipeline. "
        "The file must exist in the converted/ directory (not yet expired)."
    ),
    responses={
        200: {"content": {"text/markdown": {}}, "description": "Markdown file download"},
        404: {"description": "file_id not found or file expired"},
    },
)
async def download_markdown(
    file_id: str,
    result_registry: dict = Depends(get_result_registry),
) -> Response:
    # ── Validate file_id ─────────────────────────────────────────────────────
    entry = result_registry.get(file_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No conversion result for file_id '{file_id}'.",
        )

    result = entry.get("result")
    if not result or not result.success:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Conversion for file_id '{file_id}' did not succeed — nothing to download.",
        )

    # ── Locate the .md file on disk ──────────────────────────────────────────
    md_path: Path = settings.CONVERTED_DIR / f"{file_id}.md"
    if not md_path.exists():
        # File may have been cleaned up; fall back to in-memory markdown
        markdown_content = result.markdown
        if not markdown_content:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=f"Converted file for '{file_id}' has been deleted (TTL expired).",
            )
        logger.warning(
            "[download] .md file missing from disk for file_id=%s — serving from memory",
            file_id,
        )
    else:
        markdown_content = md_path.read_text(encoding="utf-8")

    # ── Build safe download filename ─────────────────────────────────────────
    original_name = entry.get("original_name", file_id)
    safe_stem = Path(original_name).stem
    download_filename = f"{safe_stem}.md"

    logger.info("[download] Serving '%s' for file_id=%s", download_filename, file_id)

    return Response(
        content=markdown_content.encode("utf-8"),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{download_filename}"',
        },
    )


@router.get(
    "/download-zip/{file_id}",
    summary="Download chunks as a ZIP archive",
    description=(
        "Returns a ZIP containing all chunks produced by POST /api/chunk. "
        "Each chunk is saved as `{stem}_chunk_001.md`, `{stem}_chunk_002.md`, …"
    ),
    responses={
        200: {"content": {"application/zip": {}}, "description": "ZIP archive of chunks"},
        404: {"description": "file_id not found or no chunks generated yet"},
    },
)
async def download_zip(
    file_id: str,
    result_registry: dict = Depends(get_result_registry),
    zip_svc: ZipService = Depends(get_zip_service),
) -> Response:
    # ── Validate ─────────────────────────────────────────────────────────────
    entry = result_registry.get(file_id)
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No result for file_id '{file_id}'.",
        )

    chunks: list[str] | None = entry.get("chunks")
    if not chunks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No chunks found for file_id '{file_id}'. "
                "Call POST /api/chunk first to generate chunks."
            ),
        )

    # ── Build ZIP from in-memory strings ─────────────────────────────────────
    original_name = entry.get("original_name", file_id)
    stem = Path(original_name).stem

    chunk_items = [
        (f"{stem}_chunk_{i + 1:03d}.md", chunk)
        for i, chunk in enumerate(chunks)
    ]

    zip_bytes = await zip_svc.build_zip_from_strings(chunk_items)
    zip_filename = f"{stem}_chunks.zip"

    logger.info(
        "[download-zip] Serving %d chunks as '%s' for file_id=%s",
        len(chunks), zip_filename, file_id,
    )

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_filename}"',
        },
    )

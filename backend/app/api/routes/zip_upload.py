"""
api/routes/zip_upload.py

POST /api/upload-zip — accept a ZIP file, extract supported documents,
convert each to Markdown, and merge into a single combined output.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.api.dependencies.services import (
    get_conversion_service,
    get_result_registry,
    get_upload_registry,
)
from app.core.config import settings
from app.services.conversion_service import ConversionService

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
_MAX_FILES_IN_ZIP = 1000  # safety cap


# ── Response model ────────────────────────────────────────────────────────────

from pydantic import BaseModel, Field


class ZipFileEntry(BaseModel):
    """Per-file result within the ZIP."""
    filename: str
    success: bool
    error: Optional[str] = None
    char_count: int = 0
    word_count: int = 0
    token_estimate: int = 0


class ZipUploadResponse(BaseModel):
    """Response for POST /api/upload-zip."""
    file_id: str = Field(description="ID for the merged result.")
    total_files: int
    succeeded: int
    failed: int
    skipped: int
    files: List[ZipFileEntry]
    merged_token_estimate: int = 0
    merged_char_count: int = 0


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post(
    "/upload-zip",
    response_model=ZipUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP and merge all documents into a single Markdown",
    description=(
        "Accepts a ZIP file containing multiple documents (PDF, DOCX, TXT, etc.). "
        "Extracts each supported file, converts it to Markdown, and merges all "
        "results into a single combined Markdown output. "
        f"Maximum ZIP size: {settings.MAX_UPLOAD_SIZE_MB} MB. "
        f"Maximum files inside ZIP: {_MAX_FILES_IN_ZIP}."
    ),
)
async def upload_zip(
    file: UploadFile = File(..., description="A ZIP file containing documents."),
    svc: ConversionService = Depends(get_conversion_service),
    upload_registry: dict = Depends(get_upload_registry),
    result_registry: dict = Depends(get_result_registry),
) -> ZipUploadResponse:
    # ── Validate ──────────────────────────────────────────────────────────
    content = await file.read()

    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"ZIP file is too large ({len(content) / 1024 / 1024:.1f} MB). "
                f"Maximum allowed: {settings.MAX_UPLOAD_SIZE_MB} MB."
            ),
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    # Verify it's a valid ZIP
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is not a valid ZIP archive.",
        )

    # ── Extract and filter ────────────────────────────────────────────────
    supported_exts = svc._converter.SUPPORTED_EXTENSIONS - {".zip"}  # no nested zips
    entries = [
        info for info in zf.infolist()
        if not info.is_dir()
        and not info.filename.startswith("__MACOSX")
        and not Path(info.filename).name.startswith(".")
        and Path(info.filename).suffix.lower() in supported_exts
    ]

    if not entries:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ZIP contains no supported files.",
        )

    if len(entries) > _MAX_FILES_IN_ZIP:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"ZIP contains {len(entries)} files. "
                f"Maximum allowed: {_MAX_FILES_IN_ZIP}."
            ),
        )

    skipped_count = sum(
        1 for info in zf.infolist()
        if not info.is_dir()
        and not info.filename.startswith("__MACOSX")
        and not Path(info.filename).name.startswith(".")
        and Path(info.filename).suffix.lower() not in supported_exts
    )

    logger.info(
        "[zip-upload] ZIP '%s' contains %d supported files, %d skipped",
        file.filename, len(entries), skipped_count,
    )

    # ── Convert each file ─────────────────────────────────────────────────
    merged_parts: List[str] = []
    file_results: List[ZipFileEntry] = []
    succeeded = 0

    # Sort by path for consistent ordering
    entries.sort(key=lambda e: e.filename)

    for info in entries:
        original_name = Path(info.filename).name
        file_data = zf.read(info.filename)

        # Save to uploads/ with UUID
        loop = asyncio.get_event_loop()
        uuid_path, _ = await loop.run_in_executor(
            None, lambda fn=original_name, fd=file_data: svc._converter.save_upload(fn, fd)
        )

        try:
            result, opt_md, opt_stats = await svc.convert(
                source_path=uuid_path,
                original_name=original_name,
                embedded_ocr_mode="Smart (Recommended)",
            )

            if result.success:
                # Use optimized markdown if available, otherwise raw
                md_content = opt_md or result.markdown

                # Add file header + content
                merged_parts.append(
                    f"---\n\n"
                    f"# 📄 {original_name}\n\n"
                    f"{md_content.strip()}\n"
                )

                file_results.append(ZipFileEntry(
                    filename=info.filename,
                    success=True,
                    char_count=result.char_count,
                    word_count=result.word_count,
                    token_estimate=result.token_estimate,
                ))
                succeeded += 1
            else:
                file_results.append(ZipFileEntry(
                    filename=info.filename,
                    success=False,
                    error=result.error,
                ))
        except Exception as exc:
            logger.exception("[zip-upload] Failed to convert '%s'", original_name)
            file_results.append(ZipFileEntry(
                filename=info.filename,
                success=False,
                error=str(exc),
            ))

    zf.close()

    # ── Merge into single markdown ────────────────────────────────────────
    merged_markdown = "\n\n".join(merged_parts).strip()

    if not merged_markdown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="All files in the ZIP failed to convert.",
        )

    # Compute merged stats
    from app.utils.token_counter import estimate_tokens, count_chars
    merged_tokens = estimate_tokens(merged_markdown)
    merged_chars = count_chars(merged_markdown)

    # ── Persist merged result ─────────────────────────────────────────────
    merged_id = uuid.uuid4().hex
    merged_path = svc._converter.converted_dir / f"{merged_id}.md"
    merged_path.write_text(merged_markdown, encoding="utf-8")

    # Register so /api/download and /api/stats can find it
    from app.utils.converter import ConversionResult
    merged_result = ConversionResult(
        source_path=merged_path,
        source_name=file.filename or "merged.zip",
        output_path=merged_path,
        markdown=merged_markdown,
        success=True,
        file_size_bytes=len(content),
    )

    result_registry[merged_id] = {
        "result": merged_result,
        "optimized_markdown": merged_markdown,
        "opt_stats": None,
        "original_name": file.filename or "merged.zip",
    }

    upload_registry[merged_id] = {
        "path": merged_path,
        "original_name": file.filename or "merged.zip",
        "uploaded_at": time.time(),
    }

    logger.info(
        "[zip-upload] Done: %d/%d succeeded, merged=%d tokens, id=%s",
        succeeded, len(entries), merged_tokens, merged_id,
    )

    return ZipUploadResponse(
        file_id=merged_id,
        total_files=len(entries),
        succeeded=succeeded,
        failed=len(entries) - succeeded,
        skipped=skipped_count,
        files=file_results,
        merged_token_estimate=merged_tokens,
        merged_char_count=merged_chars,
    )

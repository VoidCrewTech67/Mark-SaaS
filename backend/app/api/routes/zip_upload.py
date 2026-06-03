"""
api/routes/zip_upload.py

POST /api/upload-zip — extract a ZIP, convert each supported file
independently, and return a list of individual results.

Each file gets its own file_id so it can be downloaded, chunked,
and displayed exactly like a regular single-file upload.
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
from pydantic import BaseModel, Field

from app.api.dependencies.services import (
    get_conversion_service,
    get_result_registry,
    get_upload_registry,
)
from app.core.config import settings
from app.services.conversion_service import ConversionService
from app.utils.converter import ConversionResult

router = APIRouter()
logger = logging.getLogger(__name__)

_MAX_BYTES = 500 * 1024 * 1024  # 500 MB for ZIP uploads (overrides global single-file limit)
_MAX_FILES_IN_ZIP = 1000  # safety cap


# ── Response models ───────────────────────────────────────────────────────────

class ZipFileResult(BaseModel):
    """Per-file result — mirrors a normal /api/convert response."""
    file_id: str
    filename: str               # original filename inside the ZIP
    success: bool
    error: Optional[str] = None
    markdown: Optional[str] = None
    optimized_markdown: Optional[str] = None
    token_estimate: int = 0
    char_count: int = 0
    word_count: int = 0
    duration_s: float = 0.0
    ocr_used: bool = False
    embedded_images_ocr_count: int = 0
    optimization_stats: Optional[dict] = None


class ZipUploadResponse(BaseModel):
    """Response for POST /api/upload-zip."""
    zip_filename: str
    total_files: int
    succeeded: int
    failed: int
    skipped: int
    files: List[ZipFileResult]


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post(
    "/upload-zip",
    response_model=ZipUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a ZIP — convert each file independently",
    description=(
        "Accepts a ZIP file. Extracts each supported document, converts it "
        "to Markdown independently, registers each result individually, and "
        "returns a list of per-file results. Behaves identically to uploading "
        "multiple files manually."
    ),
)
async def upload_zip(
    file: UploadFile = File(..., description="A ZIP file containing documents."),
    svc: ConversionService = Depends(get_conversion_service),
    upload_registry: dict = Depends(get_upload_registry),
    result_registry: dict = Depends(get_result_registry),
) -> ZipUploadResponse:

    # ── Read + validate ───────────────────────────────────────────────────
    content = await file.read()
    zip_filename = file.filename or "archive.zip"

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"ZIP is too large ({len(content)/1024/1024:.1f} MB). "
                f"Maximum ZIP size: 500 MB."
            ),
        )

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Not a valid ZIP archive.")

    # ── Filter to supported files ─────────────────────────────────────────
    supported_exts = svc._converter.SUPPORTED_EXTENSIONS - {".zip"}

    all_members = [
        info for info in zf.infolist()
        if not info.is_dir()
        and not info.filename.startswith("__MACOSX")
        and not Path(info.filename).name.startswith(".")
    ]

    to_convert = [
        info for info in all_members
        if Path(info.filename).suffix.lower() in supported_exts
    ]
    skipped_count = len(all_members) - len(to_convert)

    if not to_convert:
        raise HTTPException(status_code=400, detail="ZIP contains no supported files.")

    if len(to_convert) > _MAX_FILES_IN_ZIP:
        raise HTTPException(
            status_code=400,
            detail=f"ZIP contains {len(to_convert)} files; max is {_MAX_FILES_IN_ZIP}.",
        )

    to_convert.sort(key=lambda e: e.filename)  # stable ordering

    logger.info(
        "[zip-upload] '%s' — %d to convert, %d skipped",
        zip_filename, len(to_convert), skipped_count,
    )

    # ── Convert each file independently ──────────────────────────────────
    file_results: List[ZipFileResult] = []
    succeeded = 0
    loop = asyncio.get_event_loop()

    for info in to_convert:
        original_name = Path(info.filename).name
        file_data = zf.read(info.filename)
        file_id = uuid.uuid4().hex

        # Save to uploads/ with its own UUID
        try:
            uuid_path, _ = await loop.run_in_executor(
                None,
                lambda fn=original_name, fd=file_data: svc._converter.save_upload(fn, fd),
            )
        except Exception as exc:
            logger.warning("[zip-upload] Could not save '%s': %s", original_name, exc)
            file_results.append(ZipFileResult(
                file_id=file_id, filename=info.filename,
                success=False, error=f"Save failed: {exc}",
            ))
            continue

        # Register in upload_registry so cleanup knows about it
        upload_registry[file_id] = {
            "path": uuid_path,
            "original_name": original_name,
            "uploaded_at": time.time(),
        }

        # Convert
        try:
            result, opt_md, opt_stats = await svc.convert(
                source_path=uuid_path,
                original_name=original_name,
                embedded_ocr_mode="Smart (Recommended)",
            )
        except Exception as exc:
            logger.exception("[zip-upload] Conversion failed for '%s'", original_name)
            file_results.append(ZipFileResult(
                file_id=file_id, filename=info.filename,
                success=False, error=str(exc),
            ))
            continue

        if not result.success:
            file_results.append(ZipFileResult(
                file_id=file_id, filename=info.filename,
                success=False, error=result.error or "Conversion failed",
            ))
            continue

        # Persist individual .md file
        md_content = opt_md or result.markdown or ""
        md_path = svc._converter.converted_dir / f"{file_id}.md"
        try:
            md_path.write_text(md_content, encoding="utf-8")
        except OSError as exc:
            logger.warning("[zip-upload] Could not write md for '%s': %s", original_name, exc)

        # Register in result_registry (same structure as /api/convert)
        result_registry[file_id] = {
            "result": result,
            "optimized_markdown": opt_md,
            "opt_stats": opt_stats,
            "original_name": original_name,
        }

        # Also update the upload_registry path with the saved uuid_path
        upload_registry[file_id]["path"] = uuid_path

        opt_stats_dict = None
        if opt_stats:
            try:
                opt_stats_dict = opt_stats if isinstance(opt_stats, dict) else opt_stats.dict()
            except Exception:
                opt_stats_dict = None

        file_results.append(ZipFileResult(
            file_id=file_id,
            filename=info.filename,
            success=True,
            markdown=result.markdown,
            optimized_markdown=opt_md,
            token_estimate=result.token_estimate,
            char_count=result.char_count,
            word_count=result.word_count,
            duration_s=getattr(result, "duration_s", 0.0),
            ocr_used=getattr(result, "ocr_used", False),
            embedded_images_ocr_count=getattr(result, "embedded_images_ocr_count", 0),
            optimization_stats=opt_stats_dict,
        ))
        succeeded += 1
        logger.info("[zip-upload] ✓ '%s' → %d tokens", original_name, result.token_estimate)

    zf.close()

    if succeeded == 0:
        raise HTTPException(
            status_code=422,
            detail="All files in the ZIP failed to convert.",
        )

    logger.info(
        "[zip-upload] Done: %d/%d succeeded, %d failed",
        succeeded, len(to_convert), len(to_convert) - succeeded,
    )

    return ZipUploadResponse(
        zip_filename=zip_filename,
        total_files=len(to_convert),
        succeeded=succeeded,
        failed=len(to_convert) - succeeded,
        skipped=skipped_count,
        files=file_results,
    )

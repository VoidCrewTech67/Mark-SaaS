"""
api/routes/upload.py

POST /api/upload — receive a file via multipart/form-data, save it with a
UUID filename, and return a file_id for use in subsequent API calls.
"""

from __future__ import annotations

import time
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.api.dependencies.services import (
    get_conversion_service,
    get_upload_registry,
)
from app.models.responses import UploadResponse
from app.services.conversion_service import ConversionService
from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

# Maximum file size enforced here *before* saving to disk.
_MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file for conversion",
    description=(
        "Accepts a single file via multipart/form-data. "
        f"Maximum size: {settings.MAX_UPLOAD_SIZE_MB} MB. "
        "Returns a `file_id` that must be passed to `/api/convert`."
    ),
)
async def upload_file(
    file: UploadFile = File(..., description="The document to convert."),
    svc: ConversionService = Depends(get_conversion_service),
    upload_registry: dict = Depends(get_upload_registry),
) -> UploadResponse:
    # ── Read content ────────────────────────────────────────────────────────
    content = await file.read()

    if len(content) > _MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File '{file.filename}' is too large "
                f"({len(content) / 1024 / 1024:.1f} MB). "
                f"Maximum allowed: {settings.MAX_UPLOAD_SIZE_MB} MB."
            ),
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    original_name = file.filename or "unknown"
    is_supported = svc.is_supported(original_name)

    # ── Persist to uploads/ with UUID filename ───────────────────────────────
    uuid_path, _ = await svc.save_upload(original_name, content)
    file_id = uuid_path.stem  # UUID hex string, no extension

    # ── Register in memory ───────────────────────────────────────────────────
    upload_registry[file_id] = {
        "path": uuid_path,
        "original_name": original_name,
        "uploaded_at": time.time(),
    }

    logger.info(
        "[upload] Saved '%s' -> file_id=%s (%d bytes, supported=%s)",
        original_name, file_id, len(content), is_supported,
    )

    return UploadResponse(
        file_id=file_id,
        original_name=original_name,
        size_bytes=len(content),
        supported=is_supported,
    )

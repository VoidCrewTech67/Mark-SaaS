"""
models/requests.py – Pydantic request bodies for all API endpoints.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ── Upload ────────────────────────────────────────────────────────────────────
# Upload uses multipart/form-data (UploadFile), so there is no JSON body model.


# ── Convert ───────────────────────────────────────────────────────────────────

class ConvertRequest(BaseModel):
    """Body for POST /api/convert (single file)."""

    file_id: str = Field(
        description="The file_id returned by POST /api/upload."
    )
    embedded_ocr_mode: Literal["Disabled", "Smart (Recommended)", "Aggressive"] = Field(
        default="Smart (Recommended)",
        description=(
            "Disabled: skip embedded-image OCR (fastest). "
            "Smart: filter decorative images automatically. "
            "Aggressive: OCR every embedded image."
        ),
    )


class BatchConvertItem(BaseModel):
    """A single item inside a batch convert request."""

    file_id: str
    embedded_ocr_mode: Literal["Disabled", "Smart (Recommended)", "Aggressive"] = "Smart (Recommended)"


class BatchConvertRequest(BaseModel):
    """Body for POST /api/convert/batch."""

    items: List[BatchConvertItem] = Field(
        min_length=1,
        max_length=20,
        description="List of files to convert (max 20 per batch).",
    )


# ── Chunk ─────────────────────────────────────────────────────────────────────

class ChunkRequest(BaseModel):
    """Body for POST /api/chunk."""

    file_id: str = Field(
        description="The file_id of a previously converted file."
    )
    max_tokens: int = Field(
        default=8000,
        gt=0,
        le=128000,
        description="Hard upper bound on tokens per chunk.",
    )
    overlap_tokens: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Tokens from the end of chunk N prepended to chunk N+1. "
            "Defaults to 10 %% of max_tokens when None."
        ),
    )
    use_optimized: bool = Field(
        default=True,
        description="Chunk the optimized Markdown if available; otherwise use raw.",
    )

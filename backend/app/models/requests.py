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
    document_type: Literal["research_paper", "general_document"] = Field(
        default="general_document",
        description=(
            "research_paper: use Docling for extraction + universal optimization. "
            "general_document: use MarkItDown + universal optimization."
        ),
    )
    optimization_mode: Optional[Literal["safe", "balanced", "aggressive", "rag"]] = Field(
        default=None,
        description=(
            "Optimization mode (works for both document types). "
            "safe: cleanup only (5-10%% reduction). "
            "balanced: remove references/boilerplate + dedup (15-40%%). Default. "
            "aggressive: maximum reduction (30-60%%). "
            "rag: balanced + structured output for retrieval. "
            "Defaults to 'balanced' when omitted."
        ),
    )
    embedded_ocr_mode: Literal["Disabled", "Smart (Recommended)", "Aggressive"] = Field(
        default="Smart (Recommended)",
        description=(
            "Embedded image OCR mode (used by MarkItDown extractor). "
            "Disabled: skip embedded-image OCR (fastest). "
            "Smart: filter decorative images automatically. "
            "Aggressive: OCR every embedded image."
        ),
    )
    extractor_override: Optional[Literal["markitdown", "docling"]] = Field(
        default=None,
        description=(
            "Force a specific extractor regardless of document_type. "
            "None: auto-select based on document_type."
        ),
    )


class BatchConvertItem(BaseModel):
    """A single item inside a batch convert request."""

    file_id: str
    document_type: Literal["research_paper", "general_document"] = "general_document"
    optimization_mode: Optional[Literal["safe", "balanced", "aggressive", "rag"]] = None
    embedded_ocr_mode: Literal["Disabled", "Smart (Recommended)", "Aggressive"] = "Smart (Recommended)"
    extractor_override: Optional[Literal["markitdown", "docling"]] = None


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

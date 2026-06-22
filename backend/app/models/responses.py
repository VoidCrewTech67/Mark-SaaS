"""
models/responses.py – Pydantic response schemas for all API endpoints.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    ocr_available: bool
    pdf_ocr_available: bool
    token_backend: str
    version: str
    app_name: str


# ── Upload ────────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    file_id: str = Field(description="Opaque ID to pass to /api/convert.")
    original_name: str
    size_bytes: int
    supported: bool = Field(
        description="Whether the file extension is supported for conversion."
    )


# ── Optimization ─────────────────────────────────────────────────────────────

class OptimizationStatsResponse(BaseModel):
    original_tokens:  int
    optimized_tokens: int
    tokens_saved:     int
    percent_saved:    float
    # Semantic scores (None when scoring was skipped)
    semantic_preservation: Optional[float] = None
    semantic_loss:         Optional[float] = None
    context_preservation:  Optional[float] = None
    overall_preservation:  Optional[float] = None
    scoring_method:        Optional[str]   = None
    context_breakdown:     Optional[dict]  = None
    issues:                Optional[list]  = None


# ── Chunk metadata (shared by RAG convert + /api/chunk) ───────────────────────

class ChunkMeta(BaseModel):
    chunk_id: str                       # "chunk_001"
    index: int                          # 1-based
    section: Optional[str] = None       # nearest heading; None for preamble/no-heading
    content: str
    token_count: int = 0
    word_count: int = 0
    char_count: int = 0
    overlap_prev_tokens: int = 0        # tokens carried over from previous chunk
    # Extended metadata — None when extractor does not provide the signal
    page_number: Optional[int] = None       # 1-based, when known from extractor
    source_file: Optional[str] = None       # original filename
    document_type: Optional[str] = None     # heuristic label
    has_table: bool = False                 # at least one markdown table inside
    table_summary: Optional[str] = None     # human-readable table description


# ── Conversion ───────────────────────────────────────────────────────────────

class ConversionResponse(BaseModel):
    file_id: str
    source_name: str
    success: bool
    error: Optional[str] = None

    # Pipeline metadata
    document_type: str = "general_document"
    optimization_mode: Optional[str] = None
    extractor: str = "markitdown"  # "markitdown" | "docling" | "docling→markitdown"

    # Content (only set on success)
    markdown: Optional[str] = None
    optimized_markdown: Optional[str] = None

    # Timing
    duration_s: float = 0.0

    # OCR metadata
    ocr_used: bool = False
    ocr_warning: str = ""
    embedded_images_ocr_count: int = 0

    # Text statistics
    char_count: int = 0
    word_count: int = 0
    token_estimate: int = 0
    file_size_bytes: int = 0

    # Optimization stats
    optimization_stats: Optional[OptimizationStatsResponse] = None

    # ── RAG mode only (None/0 for all other modes) ───────────────────────────
    mode: Optional[str] = None                    # "rag" when structured output present
    detected_document_type: Optional[str] = None  # heuristic label (research_paper, resume, …, generic)
    chunk_count: int = 0
    chunks: Optional[List[ChunkMeta]] = None      # retrieval-ready chunks


class BatchConversionResponse(BaseModel):
    results: List[ConversionResponse]
    total: int
    succeeded: int
    failed: int


# ── Chunks ────────────────────────────────────────────────────────────────────

class ChunkResponse(BaseModel):
    file_id: str
    chunks: List[ChunkMeta]
    chunk_count: int
    max_tokens: int
    overlap_tokens: int
    document_type: Optional[str] = None
    source: str = Field(
        description="'optimized' or 'raw' — which markdown was chunked."
    )


# ── Stats ─────────────────────────────────────────────────────────────────────

class StatsResponse(BaseModel):
    file_id: str
    source_name: str
    char_count: int = 0
    word_count: int = 0
    token_estimate: int = 0
    file_size_bytes: int = 0
    duration_s: float = 0.0
    ocr_used: bool = False
    ocr_warning: str = ""
    embedded_images_ocr_count: int = 0
    optimization_stats: Optional[OptimizationStatsResponse] = None


# ── Error ─────────────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None

"""
api/dependencies/services.py

FastAPI dependency functions that pull service singletons from app.state.

Usage:
    from app.api.dependencies.services import get_conversion_service

    @router.post("/convert")
    async def convert(
        body: ConvertRequest,
        svc: ConversionService = Depends(get_conversion_service),
    ):
        ...
"""

from __future__ import annotations

from fastapi import Request

from app.services.conversion_service import ConversionService
from app.services.ocr_service import OCRService
from app.services.optimization_service import OptimizationService
from app.services.chunking_service import ChunkingService
from app.services.zip_service import ZipService


def get_conversion_service(request: Request) -> ConversionService:
    return request.app.state.conversion_service


def get_ocr_service(request: Request) -> OCRService:
    return request.app.state.ocr_service


def get_optimization_service(request: Request) -> OptimizationService:
    return request.app.state.optimization_service


def get_chunking_service(request: Request) -> ChunkingService:
    return request.app.state.chunking_service


def get_zip_service(request: Request) -> ZipService:
    return request.app.state.zip_service


def get_upload_registry(request: Request) -> dict:
    """Returns the in-memory upload metadata registry (file_id → meta dict)."""
    return request.app.state.upload_registry


def get_result_registry(request: Request) -> dict:
    """Returns the in-memory conversion result registry (file_id → result dict)."""
    return request.app.state.result_registry

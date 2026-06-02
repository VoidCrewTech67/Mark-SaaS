"""
api/routes/health.py

GET /api/health — liveness + capability check.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.models.responses import HealthResponse
from app.utils.ocr_handler import ocr_available, pdf_ocr_available
from app.utils.token_counter import TOKEN_BACKEND
from app.core.config import settings

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description=(
        "Returns the current liveness status of the API, together with "
        "capability flags for OCR and the active token-counting backend."
    ),
)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        ocr_available=ocr_available(),
        pdf_ocr_available=pdf_ocr_available(),
        token_backend=TOKEN_BACKEND,
        version=settings.APP_VERSION,
        app_name=settings.APP_NAME,
    )

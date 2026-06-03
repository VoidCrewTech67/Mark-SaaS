"""
app/main.py – FastAPI application factory.

Lifecycle:
  1. lifespan startup:
     - Setup logging
     - Ensure upload/converted directories exist
     - Initialise all service singletons on app.state
     - Warm up EasyOCR model (async, non-blocking — runs in thread pool)
     - Start background cleanup task
  2. Request handling via mounted routers.
  3. lifespan shutdown:
     - Cancel cleanup task

Deployment:
  uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.log_config import setup_logging

# ── Services ────────────────────────────────────────────────────────────────
from app.services.cleanup_service import run_cleanup_loop
from app.services.chunking_service import ChunkingService
from app.services.conversion_service import ConversionService
from app.services.ocr_service import OCRService
from app.services.optimization_service import OptimizationService
from app.services.zip_service import ZipService

# ── Utils (converter needs configured dirs) ──────────────────────────────────
from app.utils.converter import FileConverter

# ── Routers ──────────────────────────────────────────────────────────────────
from app.api.routes import health, upload, convert, chunk, download, stats, zip_upload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ── Startup ──────────────────────────────────────────────────────────────
    setup_logging(debug=settings.DEBUG)
    logger.info("=" * 60)
    logger.info("%s v%s — starting up", settings.APP_NAME, settings.APP_VERSION)
    logger.info("=" * 60)

    # Ensure temp directories exist
    settings.ensure_dirs()
    logger.info(
        "Directories — uploads: %s | converted: %s",
        settings.UPLOAD_DIR, settings.CONVERTED_DIR,
    )

    # ── In-memory registries ─────────────────────────────────────────────────
    # file_id → {path, original_name, uploaded_at}
    app.state.upload_registry: dict = {}
    # file_id → {result, optimized_markdown, opt_stats, chunks, ...}
    app.state.result_registry: dict = {}

    # ── Service singletons ───────────────────────────────────────────────────
    converter = FileConverter(settings.UPLOAD_DIR, settings.CONVERTED_DIR)
    app.state.conversion_service = ConversionService(converter)
    app.state.ocr_service = OCRService()
    app.state.optimization_service = OptimizationService()
    app.state.chunking_service = ChunkingService()
    app.state.zip_service = ZipService()

    logger.info("Service singletons initialised.")

    # ── Warm up EasyOCR (async, non-blocking) ────────────────────────────────
    if settings.OCR_WARM_UP_ON_STARTUP:
        logger.info("Warming up EasyOCR reader (background)…")
        # Fire-and-forget: warm-up completes while server is already accepting
        # requests. OCR requests arriving before warm-up is done will trigger
        # the lazy initialiser on first use — still correct behaviour.
        asyncio.create_task(app.state.ocr_service.warm_up())

    # ── Background cleanup task ───────────────────────────────────────────────
    cleanup_task = asyncio.create_task(
        run_cleanup_loop(app.state.upload_registry, app.state.result_registry)
    )
    logger.info(
        "Cleanup task started (interval=%ds, TTL=%ds).",
        settings.CLEANUP_INTERVAL_SECONDS, settings.FILE_TTL_SECONDS,
    )

    logger.info("Startup complete — ready to accept requests.")

    yield  # ← application runs here

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down…")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Production-ready REST API for converting documents to AI-ready Markdown "
            "using Microsoft MarkItDown, EasyOCR, and smart optimization/chunking pipelines."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global exception handler ─────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled exception for %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An unexpected server error occurred.", "code": "INTERNAL_ERROR"},
        )

    # ── Routers ──────────────────────────────────────────────────────────────
    prefix = "/api"
    app.include_router(health.router,   prefix=prefix, tags=["Health"])
    app.include_router(upload.router,   prefix=prefix, tags=["Upload"])
    app.include_router(convert.router,  prefix=prefix, tags=["Convert"])
    app.include_router(chunk.router,    prefix=prefix, tags=["Chunk"])
    app.include_router(download.router, prefix=prefix, tags=["Download"])
    app.include_router(stats.router,    prefix=prefix, tags=["Stats"])
    app.include_router(zip_upload.router, prefix=prefix, tags=["ZIP Upload"])

    return app


app = create_app()

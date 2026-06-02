"""
core/config.py – Application settings via pydantic-settings.

All values can be overridden through environment variables or a .env file.
Pydantic-settings automatically reads UPPER_CASE env vars and maps them to
the field names (case-insensitive).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application metadata ─────────────────────────────────────────────────
    APP_NAME: str = "MarkItDown Converter API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # ── Server ───────────────────────────────────────────────────────────────
    PORT: int = 8000
    HOST: str = "0.0.0.0"

    # ── Storage directories ───────────────────────────────────────────────────
    # Relative paths are resolved from the working directory (backend/).
    UPLOAD_DIR: Path = Path("uploads")
    CONVERTED_DIR: Path = Path("converted")

    # ── Upload limits ─────────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 150  # 150 MB hard limit per file

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins.
    # Override in production with your Vercel deployment URL.
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3000",
    ]

    # ── File cleanup ─────────────────────────────────────────────────────────
    # How often the background cleanup task runs (seconds).
    CLEANUP_INTERVAL_SECONDS: int = 1800  # 30 minutes
    # How long files are kept before deletion (seconds).
    FILE_TTL_SECONDS: int = 7200  # 2 hours

    # ── Conversion timeouts ───────────────────────────────────────────────────
    MARKITDOWN_TIMEOUT_S: int = 120  # wall-clock limit per MarkItDown call
    OCR_IMAGE_TIMEOUT_S: int = 60   # wall-clock limit per image OCR call

    # ── OCR ──────────────────────────────────────────────────────────────────
    OCR_WARM_UP_ON_STARTUP: bool = True  # pre-load EasyOCR weights in lifespan

    @field_validator("UPLOAD_DIR", "CONVERTED_DIR", mode="before")
    @classmethod
    def _resolve_path(cls, v: str | Path) -> Path:
        return Path(v)

    def ensure_dirs(self) -> None:
        """Create upload and converted directories if they do not exist."""
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.CONVERTED_DIR.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import this everywhere.
settings = Settings()

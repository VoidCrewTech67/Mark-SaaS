"""
services/cleanup_service.py

Background asyncio task that deletes temporary files older than FILE_TTL_SECONDS.

Design
------
- Runs as a daemon coroutine started in the FastAPI lifespan.
- Iterates ``app.state.upload_registry`` every CLEANUP_INTERVAL_SECONDS.
- Removes both the uploaded file and the converted .md artefact.
- Purges the corresponding entries from upload_registry and result_registry.
- Also scans the uploads/ and converted/ directories for orphan files
  (files not in the registry, e.g. from a previous server run).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


async def run_cleanup_loop(
    upload_registry: dict,
    result_registry: dict,
) -> None:
    """Long-running background task — call with asyncio.create_task()."""
    logger.info(
        "[cleanup_service] Started — interval=%ds, TTL=%ds",
        settings.CLEANUP_INTERVAL_SECONDS, settings.FILE_TTL_SECONDS,
    )
    while True:
        await asyncio.sleep(settings.CLEANUP_INTERVAL_SECONDS)
        await _cleanup_registered(upload_registry, result_registry)
        await _cleanup_orphans()


async def _cleanup_registered(
    upload_registry: dict,
    result_registry: dict,
) -> None:
    """Delete all files that have exceeded the TTL."""
    now = time.time()
    expired_ids = [
        fid
        for fid, meta in upload_registry.items()
        if now - meta.get("uploaded_at", now) > settings.FILE_TTL_SECONDS
    ]

    if not expired_ids:
        return

    logger.info("[cleanup_service] Expiring %d registered file(s)…", len(expired_ids))

    for fid in expired_ids:
        meta = upload_registry.pop(fid, {})
        result_registry.pop(fid, None)

        # Delete upload file
        upload_path: Path | None = meta.get("path")
        if upload_path and upload_path.exists():
            try:
                upload_path.unlink(missing_ok=True)
                logger.debug("[cleanup_service] Deleted upload: %s", upload_path.name)
            except OSError as exc:
                logger.warning("[cleanup_service] Could not delete %s: %s", upload_path, exc)

        # Delete converted .md file (stem matches UUID)
        converted_path = settings.CONVERTED_DIR / f"{fid}.md"
        if converted_path.exists():
            try:
                converted_path.unlink(missing_ok=True)
                logger.debug("[cleanup_service] Deleted converted: %s", converted_path.name)
            except OSError as exc:
                logger.warning("[cleanup_service] Could not delete %s: %s", converted_path, exc)

    logger.info("[cleanup_service] Expired %d file(s).", len(expired_ids))


async def _cleanup_orphans() -> None:
    """Remove files in uploads/ and converted/ that are older than FILE_TTL_SECONDS.

    These may be left over from a server restart between upload and conversion.
    """
    cutoff = time.time() - settings.FILE_TTL_SECONDS
    count = 0

    for directory in (settings.UPLOAD_DIR, settings.CONVERTED_DIR):
        if not directory.exists():
            continue
        for fpath in directory.iterdir():
            if fpath.is_file() and fpath.stat().st_mtime < cutoff:
                try:
                    fpath.unlink(missing_ok=True)
                    count += 1
                    logger.debug("[cleanup_service] Removed orphan: %s", fpath.name)
                except OSError:
                    pass

    if count:
        logger.info("[cleanup_service] Removed %d orphan file(s).", count)

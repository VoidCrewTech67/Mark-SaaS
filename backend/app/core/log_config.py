"""
core/log_config.py – Structured logging configuration.

Call ``setup_logging()`` once at application startup (in main.py lifespan).
Uses a format compatible with Render's log aggregation.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(debug: bool = False) -> None:
    """Configure root logger with a clean, structured format.

    - INFO level by default; DEBUG when ``debug=True``.
    - Timestamps in ISO-8601 format.
    - Log lines go to stdout (Render ships stdout to its log dashboard).
    - Uvicorn's own loggers are left at their defaults so request logs
      remain separate from application logs.
    """
    level = logging.DEBUG if debug else logging.INFO

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Reduce noise from third-party libraries
    for noisy in ("PIL", "easyocr", "torch", "urllib3", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("markitdown").setLevel(logging.WARNING)

    logging.info("[log_config] Logging initialised — level=%s", logging.getLevelName(level))

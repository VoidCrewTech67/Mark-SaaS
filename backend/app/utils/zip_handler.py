"""
zip_handler.py – Bundles multiple converted Markdown files into a single ZIP.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Sequence


def build_zip(md_paths: Sequence[Path]) -> tuple[bytes, list[str]]:
    """Create an in-memory ZIP archive containing every path in *md_paths*.

    Returns:
        (zip_bytes, skipped_names) – zip_bytes is raw bytes ready for a
        FastAPI StreamingResponse; skipped_names lists any files that were
        missing on disk so the caller can warn the client.
    """
    skipped: list[str] = []
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in md_paths:
            if path.exists():
                zf.write(path, arcname=path.name)
            else:
                skipped.append(path.name)
    buffer.seek(0)
    return buffer.read(), skipped


def build_zip_from_strings(items: Sequence[tuple[str, str]]) -> bytes:
    """Create a ZIP from (filename, content) string pairs.

    Useful when the caller has the Markdown text in memory but the file
    might not have been written to disk yet.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename, content in items:
            zf.writestr(filename, content.encode("utf-8"))
    buffer.seek(0)
    return buffer.read()

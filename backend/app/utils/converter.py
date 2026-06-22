"""
converter.py – Wraps Microsoft MarkItDown and manages file-level conversion.

Security:
  - UUID-based internal filenames prevent collisions & path traversal.
  - ``save_upload`` returns a UUID-named path; original name is stored separately.
  - ``cleanup_session_files`` robustly removes both upload and converted artefacts.

Token accuracy:
  - ``_compute_stats`` delegates to token_counter.estimate_tokens so the token
    figure is consistent everywhere.

Embedded-image OCR:
  - After MarkItDown conversion, ``convert()`` calls image_extractor.extract_images()
    to pull every embedded image from the document.
  - Each extracted image is OCR'd via ocr_handler.ocr_extracted_images().
  - Non-empty OCR results are appended to the Markdown as structured blocks.
  - Duplicate images are skipped via SHA-256 caching inside ocr_handler.
  - The whole-document OCR fallback (run_ocr) is unchanged.

Reliability:
  - MarkItDown conversion is wrapped with a configurable wall-clock timeout
    (_MARKITDOWN_TIMEOUT_S) via concurrent.futures so a hanging file type
    cannot freeze the server indefinitely.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from markitdown import MarkItDown

from app.utils.token_counter import estimate_tokens, count_words, count_chars

logger = logging.getLogger(__name__)

# Wall-clock limit for a single MarkItDown conversion call.
_MARKITDOWN_TIMEOUT_S: int = 120  # seconds


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConversionResult:
    """Holds the outcome of a single file conversion."""

    source_path: Path           # UUID-named path on disk
    source_name: str = ""       # original user-visible filename
    output_path: Optional[Path] = None
    markdown: str = ""
    success: bool = False
    error: str = ""
    duration_s: float = 0.0
    file_size_bytes: int = 0
    extractor: str = ""         # actual extractor used (e.g. "docling", "docling→markitdown")

    # RAG mode only — populated by ConversionService when mode == "rag"
    chunks: Optional[list] = None              # list[dict] of structured chunks
    detected_document_type: str = ""           # heuristic label for RAG responses

    # OCR metadata
    ocr_used: bool = False
    ocr_warning: str = ""
    embedded_images_ocr_count: int = 0  # how many embedded images yielded OCR text

    # Derived stats (populated after conversion)
    char_count: int = field(default=0, init=False)
    word_count: int = field(default=0, init=False)
    token_estimate: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not self.source_name:
            self.source_name = self.source_path.name
        self._compute_stats()

    def _compute_stats(self) -> None:
        """Populate char/word/token counts from current self.markdown."""
        self.char_count = count_chars(self.markdown)
        self.word_count = count_words(self.markdown)
        self.token_estimate = estimate_tokens(self.markdown)


# ---------------------------------------------------------------------------
# Merge helper
# ---------------------------------------------------------------------------

def _build_ocr_block(ocr_result: "ImageOCRResult") -> str:  # type: ignore[name-defined]
    """Format a single embedded-image OCR result as a Markdown block."""
    label = ocr_result.position_label or "Embedded Image"
    return (
        f"\n\n### Extracted Image Text ({label})\n\n"
        f"```\n{ocr_result.text}\n```\n"
    )


def _merge_ocr_into_markdown(base_md: str, ocr_results: list) -> str:
    """Append OCR blocks for each embedded image after the main content."""
    if not ocr_results:
        return base_md

    blocks: list[str] = [base_md.rstrip()]
    blocks.append("\n\n---\n\n## Embedded Image Content\n")
    for r in ocr_results:
        blocks.append(_build_ocr_block(r))

    return "".join(blocks)


# ---------------------------------------------------------------------------
# Converter class
# ---------------------------------------------------------------------------

class FileConverter:
    """Thin wrapper around MarkItDown that adds path management and error handling.

    Unlike the original Streamlit version, upload_dir and converted_dir are
    injected via the constructor (from app.core.config.settings) rather than
    being hardcoded to tmp/ paths.
    """

    SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
        {
            ".pdf", ".docx", ".doc", ".pptx", ".ppt",
            ".xlsx", ".xls", ".csv",
            ".html", ".htm",
            ".txt", ".md", ".rst",
            ".json", ".xml",
            ".zip",
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
            ".mp3", ".wav", ".ogg",
            ".epub",
        }
    )

    def __init__(self, upload_dir: Path, converted_dir: Path) -> None:
        self.upload_dir = upload_dir
        self.converted_dir = converted_dir
        self._md = MarkItDown()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def convert(
        self,
        source_path: Path,
        original_name: str = "",
        embedded_ocr_mode: str = "Smart (Recommended)",
    ) -> ConversionResult:
        """Convert *source_path* to Markdown and write the .md file."""
        display_name = original_name or source_path.name
        result = ConversionResult(
            source_path=source_path,
            source_name=display_name,
            file_size_bytes=source_path.stat().st_size if source_path.exists() else 0,
        )

        start = time.perf_counter()
        try:
            # ── Step 1: MarkItDown conversion (with timeout) ───────────
            logger.info("[converter] Step 1: MarkItDown converting '%s'…", display_name)
            markdown_text = self._convert_with_timeout(source_path)
            logger.info(
                "[converter] Step 1 done: %d chars extracted from '%s'",
                len(markdown_text), display_name,
            )

            # ── Step 2: Embedded-image extraction + OCR ────────────────
            image_exts = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"}
            if source_path.suffix.lower() not in image_exts:
                logger.info(
                    "[converter] Step 2: embedded OCR (mode=%s) for '%s'…",
                    embedded_ocr_mode, display_name,
                )
                embedded_ocr = self._run_embedded_image_ocr(source_path, embedded_ocr_mode)
                if embedded_ocr:
                    markdown_text = _merge_ocr_into_markdown(markdown_text, embedded_ocr)
                    result.embedded_images_ocr_count = len(embedded_ocr)
                    logger.info(
                        "[converter] Step 2 done: %d image(s) contributed OCR text",
                        len(embedded_ocr),
                    )
                else:
                    logger.info("[converter] Step 2 done: no embedded OCR text kept")
            else:
                logger.info("[converter] Step 2 skipped: direct image upload")

            # ── Step 3: Persist ────────────────────────────────────────
            output_path = self._output_path(source_path)
            output_path.write_text(markdown_text, encoding="utf-8")
            logger.info("[converter] Step 3: persisted -> %s", output_path.name)

            result.markdown = markdown_text
            result.output_path = output_path
            result.success = True

        except Exception as exc:  # noqa: BLE001
            logger.exception("[converter] Conversion failed for '%s': %s", display_name, exc)
            result.error = str(exc)
            result.success = False
        finally:
            result.duration_s = time.perf_counter() - start
            result._compute_stats()
            logger.info(
                "[converter] Finished '%s' in %.2fs — success=%s",
                display_name, result.duration_s, result.success,
            )

        return result

    def save_upload(self, filename: str, data: bytes) -> tuple[Path, str]:
        """Persist raw upload bytes with a UUID filename.

        Returns:
            (uuid_path, original_name)
        """
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(filename).suffix.lower()
        unique_name = f"{uuid.uuid4().hex}{suffix}"
        dest = self.upload_dir / unique_name
        dest.write_bytes(data)
        return dest, filename

    def is_supported(self, filename: str) -> bool:
        return Path(filename).suffix.lower() in self.SUPPORTED_EXTENSIONS

    def cleanup_session_files(
        self, paths: list[Path], *, remove_converted: bool = True
    ) -> None:
        """Delete uploaded / converted files from disk."""
        for p in paths:
            if p and p.exists():
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        if remove_converted:
            converted_stem_map = {
                p.stem: p for p in self.converted_dir.glob("*.md")
            }
            for path in paths:
                md_path = converted_stem_map.get(path.stem)
                if md_path and md_path.exists():
                    try:
                        md_path.unlink(missing_ok=True)
                    except OSError:
                        pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _output_path(self, source_path: Path) -> Path:
        self.converted_dir.mkdir(parents=True, exist_ok=True)
        return self.converted_dir / (source_path.stem + ".md")

    def _convert_with_timeout(self, source_path: Path) -> str:
        """Run MarkItDown conversion in a thread with a wall-clock timeout."""
        def _do_convert() -> str:
            md_result = self._md.convert(str(source_path))
            return md_result.text_content or ""

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_convert)
            try:
                return future.result(timeout=_MARKITDOWN_TIMEOUT_S)
            except FuturesTimeoutError:
                msg = (
                    f"MarkItDown conversion timed out after {_MARKITDOWN_TIMEOUT_S}s "
                    f"for '{source_path.name}'. The file may be too large or complex."
                )
                logger.error("[converter] %s", msg)
                raise RuntimeError(msg)

    def _run_embedded_image_ocr(self, source_path: Path, mode: str) -> list:
        """Extract embedded images and OCR them.  Returns list[ImageOCRResult]."""
        if mode == "Disabled":
            logger.info("[converter] Embedded OCR disabled — skipping")
            return []
        try:
            from app.utils.image_extractor import extract_images
            from app.utils.ocr_handler import ocr_extracted_images, OCR_AVAILABLE

            if not OCR_AVAILABLE:
                logger.info("[converter] OCR not available — skipping embedded OCR")
                return []

            images = extract_images(source_path)
            logger.info(
                "[converter] Extracted %d image(s) from '%s'",
                len(images), source_path.name,
            )
            if not images:
                return []

            return ocr_extracted_images(images, mode)
        except Exception:
            logger.exception(
                "[converter] Embedded-image OCR pipeline failed for '%s'", source_path.name
            )
            return []

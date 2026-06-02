"""
ocr_handler.py – OCR fallback + embedded-image OCR for all document types.

Strategy
--------
1. Fallback OCR  – caller invokes ``run_ocr(path)`` when MarkItDown output
   is empty/too short.  Unchanged from previous version.
2. Embedded-image OCR  – caller invokes ``ocr_extracted_images(images)``
   with a list of ``ExtractedImage`` objects (from image_extractor.py).
   Returns ``list[ImageOCRResult]`` keeping position context.

Performance
-----------
- SHA-256-keyed cache: identical image bytes are OCR'd exactly once per
  process lifetime, regardless of which document they appear in.
- EasyOCR reader is a lazily-initialised module-level singleton.
- ``warm_up_reader()`` is called in FastAPI's lifespan startup event so the
  model is loaded once off the hot conversion path.
- Per-image timeout via ``concurrent.futures`` prevents a single stuck
  image from freezing the entire pipeline.

Dependencies (optional – gracefully degraded if absent):
  - easyocr
  - Pillow
  - pdf2image  (+ poppler on PATH)

No Tesseract dependency.
"""

from __future__ import annotations

import logging
import re
import string
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Availability flags
# ---------------------------------------------------------------------------

try:
    import easyocr  # type: ignore
    _EASYOCR_OK = True
except ImportError:
    _EASYOCR_OK = False

try:
    from PIL import Image  # type: ignore
    import numpy as np  # type: ignore
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

try:
    from pdf2image import convert_from_path  # type: ignore
    _PDF2IMAGE_OK = True
except ImportError:
    _PDF2IMAGE_OK = False


# ---------------------------------------------------------------------------
# EasyOCR reader – lazily initialised module-level singleton
# ---------------------------------------------------------------------------

_reader: "easyocr.Reader | None" = None  # type: ignore[name-defined]


def _get_reader() -> "easyocr.Reader":  # type: ignore[name-defined]
    """Return (and initialise) the EasyOCR reader singleton.

    GPU detection is automatic: uses CUDA/MPS when available, falls back
    to CPU gracefully without printing PyTorch warnings.
    """
    global _reader
    if _reader is None:
        import warnings
        # Suppress the DataLoader pin_memory warning that fires on CPU-only machines.
        warnings.filterwarnings("ignore", message=".*pin_memory.*")

        try:
            import torch
            has_gpu = torch.cuda.is_available() or torch.backends.mps.is_available()
        except Exception:
            has_gpu = False

        logger.info("[ocr_handler] Initialising EasyOCR reader (gpu=%s)…", has_gpu)
        _reader = easyocr.Reader(["en"], gpu=has_gpu)
        logger.info("[ocr_handler] EasyOCR reader ready.")
    return _reader


def warm_up_reader() -> None:
    """Pre-load EasyOCR model weights.

    Call this once at app startup (in FastAPI lifespan) so the 100 MB model
    download/load happens off the hot conversion path.
    """
    if not OCR_AVAILABLE:
        logger.info("[ocr_handler] OCR not available – skipping warm-up.")
        return
    _get_reader()


# ---------------------------------------------------------------------------
# SHA-256 cache – avoid re-OCR-ing identical images
# ---------------------------------------------------------------------------

# Maps sha256(image_bytes) → ocr_text (or "" for blank)
_ocr_cache: dict[str, str] = {}

# Per-image OCR timeout in seconds.  Prevents a single corrupt image from
# hanging the entire pipeline indefinitely on CPU.
_OCR_IMAGE_TIMEOUT_S: int = 60


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

OCR_AVAILABLE: bool = _EASYOCR_OK and _PIL_OK

# Minimum characters below which we consider MarkItDown output "empty"
_MIN_MEANINGFUL_CHARS: int = 80

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
)

# DPI for PDF → image rendering.
_PDF_RENDER_DPI: int = 300

# Maximum pixel dimension (width or height) fed to EasyOCR.
MAX_OCR_DIMENSION: int = 1024


def ocr_available() -> bool:
    return OCR_AVAILABLE


def pdf_ocr_available() -> bool:
    return OCR_AVAILABLE and _PDF2IMAGE_OK


def needs_ocr_fallback(text: str, source_path: Path) -> bool:
    """Decide whether OCR fallback should be attempted."""
    suffix = source_path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return True
    if len(text.strip()) < _MIN_MEANINGFUL_CHARS:
        return True
    return False


def run_ocr(source_path: Path) -> tuple[str, str]:
    """Run OCR on *source_path* and return (ocr_text, warning_message).

    This is the whole-document fallback OCR path.
    """
    if not OCR_AVAILABLE:
        return "", "easyocr / Pillow not installed – OCR unavailable."

    suffix = source_path.suffix.lower()
    logger.info("[ocr_handler] run_ocr -> %s", source_path.name)

    try:
        if suffix == ".pdf":
            return _ocr_pdf(source_path)
        elif suffix in IMAGE_EXTENSIONS:
            return _ocr_image(source_path)
        else:
            return "", f"OCR not supported for '{suffix}' files."
    except Exception as exc:  # noqa: BLE001
        logger.exception("[ocr_handler] OCR failed for %s", source_path)
        return "", f"OCR error: {exc}"


# ---------------------------------------------------------------------------
# Embedded-image OCR
# ---------------------------------------------------------------------------

@dataclass
class ImageOCRResult:
    """OCR result for a single extracted embedded image."""

    position_label: str   # e.g. "Page 2", "Slide 3", "Paragraph 5"
    source_name: str      # internal name/ref hint
    text: str             # OCR output (stripped); empty → skip
    from_cache: bool = False


# Rule 1 thresholds
MIN_IMAGE_AREA: int = 50000          # pixels²; skip images smaller than this
MAX_ASPECT_RATIO: float = 8.0        # skip wide banners / dividers
MIN_ASPECT_RATIO: float = 0.15       # skip tall slivers

# Rule 2 threshold
MIN_OCR_CHARS: int = 40              # minimum meaningful characters after OCR

# Rule 4 thresholds
MAX_REPEATED_WORD_COUNT: int = 4     # skip if any word repeats more than this
MAX_COORD_COUNT: int = 3             # skip if more than this many coordinate-like tokens
MIN_WORD_LENGTH_FOR_REPEAT: int = 2  # only count words longer than this for repetition check


def ocr_extracted_images(
    images: "list",  # list[ExtractedImage] – avoid circular import with string hint
    mode: str = "Smart (Recommended)",
) -> list[ImageOCRResult]:
    """OCR a list of ExtractedImage objects returned by image_extractor.py.

    - Skips images with empty OCR text.
    - Uses SHA-256 cache to avoid re-processing duplicate images.
    - Applies Smart OCR filters if mode is "Smart (Recommended)".
    - Enforces a per-image timeout (_OCR_IMAGE_TIMEOUT_S) so a single
      stuck image cannot freeze the pipeline.
    - Returns only results with non-empty text.
    """
    if not OCR_AVAILABLE:
        return []

    results: list[ImageOCRResult] = []
    total = len(images)
    logger.info("[ocr_handler] ocr_extracted_images: %d image(s), mode=%s", total, mode)

    for idx, img in enumerate(images, start=1):
        logger.info(
            "[ocr_handler] Processing image %d/%d — %s (%s)",
            idx, total, img.source_name, img.position_label,
        )

        if mode == "Smart (Recommended)":
            # Rule 1: Skip images that are too small or have extreme aspect ratios
            import io
            try:
                buf = io.BytesIO(img.data)
                pil_img = Image.open(buf)
                w, h = pil_img.size
                if h == 0 or w == 0:
                    logger.debug("[ocr_handler]   Rule 1: zero-dim image — skipped")
                    continue
                if w * h < MIN_IMAGE_AREA:
                    logger.debug("[ocr_handler]   Rule 1: too small (%dx%d) — skipped", w, h)
                    continue
                aspect_ratio = w / h
                if aspect_ratio > MAX_ASPECT_RATIO or aspect_ratio < MIN_ASPECT_RATIO:
                    logger.debug("[ocr_handler]   Rule 1: aspect ratio %.2f — skipped", aspect_ratio)
                    continue
            except Exception:
                pass  # If we can't inspect the image, allow it to proceed to OCR.

        img_hash = img.sha256

        # Cache hit — no OCR needed.
        if img_hash in _ocr_cache:
            text = _ocr_cache[img_hash]
            from_cache = True
            logger.debug("[ocr_handler]   Cache hit for %s", img.source_name)
        else:
            from_cache = False
            text = _ocr_bytes_with_timeout(img.data, img.source_name)
            _ocr_cache[img_hash] = text

        if not text:
            logger.debug("[ocr_handler]   Empty OCR result — skipped")
            continue

        if mode == "Smart (Recommended)":
            # Rule 2: Discard results with too few characters to be meaningful.
            if len(text) < MIN_OCR_CHARS:
                logger.debug("[ocr_handler]   Rule 2: too few chars (%d) — skipped", len(text))
                continue

            lines = text.split("\n")
            words = text.split()
            char_count = len(text)

            # Rule 3: Logo detection
            if len(words) < 5 and char_count < 60:
                is_mostly_title = (
                    sum(1 for w in words if w.istitle() or w.isupper())
                    / max(1, len(words))
                ) > 0.5
                has_punct = any(c in string.punctuation for c in text)
                if is_mostly_title and not has_punct:
                    logger.debug("[ocr_handler]   Rule 3: logo heuristic — skipped")
                    continue

            # Rule 4: Screenshot / map noise detection.
            line_count = len(lines)
            avg_words_per_line = len(words) / max(1, line_count)
            is_noise = False

            if line_count > 15 and avg_words_per_line < 3:
                is_noise = True

            word_counts = Counter(w.lower() for w in words if len(w) > MIN_WORD_LENGTH_FOR_REPEAT)
            if any(count > MAX_REPEATED_WORD_COUNT for count in word_counts.values()):
                is_noise = True

            coord_pattern = r'\b\d{1,3}\.\d{3,}\b'
            coords = re.findall(coord_pattern, text)
            if len(coords) > MAX_COORD_COUNT:
                is_noise = True

            if is_noise:
                logger.debug("[ocr_handler]   Rule 4: noise detected — skipped")
                continue

        logger.info("[ocr_handler]   Accepted: %d chars from %s", len(text), img.source_name)
        results.append(
            ImageOCRResult(
                position_label=img.position_label,
                source_name=img.source_name,
                text=text,
                from_cache=from_cache,
            )
        )

    logger.info("[ocr_handler] ocr_extracted_images done: %d result(s) kept", len(results))
    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _resize_for_ocr(img: "Image.Image") -> "Image.Image":  # type: ignore[name-defined]
    """Downscale large images before OCR to reduce CPU processing time."""
    if max(img.width, img.height) > MAX_OCR_DIMENSION:
        img = img.copy()
        img.thumbnail((MAX_OCR_DIMENSION, MAX_OCR_DIMENSION), Image.LANCZOS)
        logger.debug(
            "[ocr_handler] _resize_for_ocr: downscaled to %dx%d",
            img.width, img.height,
        )
    return img


def _run_easyocr_on_image(img: "Image.Image") -> str:  # type: ignore[name-defined]
    """Run EasyOCR on a PIL Image and return the joined text."""
    img_array = np.array(img.convert("RGB"))
    reader = _get_reader()
    results = reader.readtext(img_array, detail=0, paragraph=False)
    return "\n".join(results).strip()


def _ocr_bytes(data: bytes) -> str:
    """OCR raw image bytes.  Used by the embedded-image path."""
    import io
    buf = io.BytesIO(data)
    img = Image.open(buf)
    img = _resize_for_ocr(img)
    return _run_easyocr_on_image(img)


def _ocr_bytes_with_timeout(data: bytes, source_name: str) -> str:
    """Run ``_ocr_bytes`` with a wall-clock timeout."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_ocr_bytes, data)
        try:
            return future.result(timeout=_OCR_IMAGE_TIMEOUT_S)
        except FuturesTimeoutError:
            logger.warning(
                "[ocr_handler] OCR timed out after %ds for image '%s' — skipping.",
                _OCR_IMAGE_TIMEOUT_S, source_name,
            )
            return ""
        except Exception as exc:
            logger.warning("[ocr_handler] OCR error for '%s': %s", source_name, exc)
            return ""


def _ocr_image(path: Path) -> tuple[str, str]:
    if not _PIL_OK:
        return "", "Pillow not installed."
    logger.info("[ocr_handler] _ocr_image -> %s", path.name)
    img = Image.open(path)
    text = _run_easyocr_on_image(img)
    return text, ""


def _ocr_pdf(path: Path) -> tuple[str, str]:
    """OCR a PDF by rendering each page to an image then running EasyOCR."""
    if not _PDF2IMAGE_OK:
        return "", (
            "pdf2image not installed (or poppler missing from PATH). "
            "Install poppler: apt-get install -y poppler-utils"
        )

    logger.info("[ocr_handler] _ocr_pdf -> %s", path.name)
    pages = convert_from_path(str(path), dpi=_PDF_RENDER_DPI)
    parts: list[str] = []
    for i, page_img in enumerate(pages, start=1):
        logger.info("[ocr_handler]   PDF page %d/%d", i, len(pages))
        page_img = _resize_for_ocr(page_img)
        page_text = _run_easyocr_on_image(page_img)
        if page_text:
            parts.append(f"<!-- Page {i} -->\n{page_text}")

    return "\n\n".join(parts), ""

"""
token_counter.py – Lightweight token estimation utilities.

Uses tiktoken (cl100k_base) when available for accurate BPE token counts
compatible with GPT-4 and Claude. Falls back to a character-based heuristic
(chars / 4) when tiktoken is not installed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Backend selection (import-time, never crashes)
# ---------------------------------------------------------------------------

try:
    import tiktoken as _tiktoken
    _enc = _tiktoken.get_encoding("cl100k_base")

    def estimate_tokens(text: str) -> int:
        """Return the exact BPE token count via tiktoken (cl100k_base)."""
        if not text:
            return 0
        return len(_enc.encode(text))

    TOKEN_BACKEND: str = "tiktoken"

except ImportError:
    def estimate_tokens(text: str) -> int:  # type: ignore[misc]
        """Estimate token count using the chars/4 heuristic (GPT-family average)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    TOKEN_BACKEND: str = "heuristic"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def count_words(text: str) -> int:
    """Return a simple whitespace-split word count."""
    return len(text.split()) if text else 0


def count_chars(text: str) -> int:
    """Return the total character count (including whitespace)."""
    return len(text)


def format_stat(value: int) -> str:
    """Format an integer stat with comma thousands separators."""
    return f"{value:,}"

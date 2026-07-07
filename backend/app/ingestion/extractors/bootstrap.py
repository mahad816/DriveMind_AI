"""Register built-in extractors for supported Drive MIME types."""

from __future__ import annotations

from app.ingestion.extractors.plain_text import register_plain_text_extractors

_bootstrapped = False


def register_builtin_extractors() -> None:
    """Register all extractors shipped with the ingestion pipeline."""
    global _bootstrapped
    if _bootstrapped:
        return
    register_plain_text_extractors()
    _bootstrapped = True


def reset_builtin_extractors() -> None:
    """Clear bootstrap state. Intended for tests only."""
    global _bootstrapped
    _bootstrapped = False

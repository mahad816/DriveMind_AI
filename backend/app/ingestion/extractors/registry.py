"""MIME-type registry mapping supported files to text extractors."""

from __future__ import annotations

from app.ingestion.extractors.base import TextExtractor, UnsupportedMimeTypeError

_EXTRACTORS: dict[str, TextExtractor] = {}


def register_extractor(mime_type: str, extractor: TextExtractor) -> None:
    """Register an extractor for a MIME type."""
    if not mime_type:
        raise ValueError("mime_type must be non-empty")
    _EXTRACTORS[mime_type] = extractor


def get_extractor(mime_type: str) -> TextExtractor:
    """Return the extractor registered for ``mime_type``."""
    try:
        return _EXTRACTORS[mime_type]
    except KeyError as exc:
        raise UnsupportedMimeTypeError(
            f"No extractor registered for MIME type: {mime_type}"
        ) from exc


def registered_mime_types() -> frozenset[str]:
    """Return MIME types with a registered extractor."""
    return frozenset(_EXTRACTORS)


def clear_extractors() -> None:
    """Remove all registered extractors. Intended for tests only."""
    _EXTRACTORS.clear()

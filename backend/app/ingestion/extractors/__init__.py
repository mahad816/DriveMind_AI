"""File-type-specific text extractors (PDF, DOCX, OCR, etc.)."""

from app.ingestion.extractors.base import (
    ExtractionError,
    ExtractionResult,
    TextExtractor,
    UnsupportedMimeTypeError,
)
from app.ingestion.extractors.registry import (
    clear_extractors,
    get_extractor,
    register_extractor,
    registered_mime_types,
)

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "TextExtractor",
    "UnsupportedMimeTypeError",
    "clear_extractors",
    "get_extractor",
    "register_extractor",
    "registered_mime_types",
]

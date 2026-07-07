"""Shared types and errors for file-type text extractors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ExtractionResult:
    """Normalized output from a file-type-specific text extractor."""

    text: str
    page_count: int | None = None
    metadata: dict[str, object] = field(default_factory=dict)


class ExtractionError(Exception):
    """Base error raised when text extraction fails."""


class UnsupportedMimeTypeError(ExtractionError):
    """Raised when no extractor is registered for a MIME type."""


class TextExtractor(Protocol):
    """Protocol implemented by each supported file-type extractor."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        """Extract normalized plain text from raw file bytes."""
        ...

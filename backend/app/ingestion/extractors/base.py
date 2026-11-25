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
    """Text extraction failed.

    Raised directly it is positively the DOCUMENT's own failure (unreadable, malformed, empty, too large, unsupported).
    ``failure_class`` is the structured cause recorded on indexing jobs; the subclasses below override it. Classification
    is by type, never by message text.
    """

    failure_class: str = "document"


class ExtractionEnvironmentError(ExtractionError):
    """The extractor could not run for a reason that is not about this document (missing engine, resource exhaustion)."""

    def __init__(self, message: str, *, failure_class: str = "infrastructure") -> None:
        super().__init__(message)
        self.failure_class = failure_class


class UnclassifiedExtractionError(ExtractionError):
    """An unexpected fault at an extractor's catch-all boundary: nothing establishes it is the document's fault."""

    failure_class = "unknown"


def classify_unexpected(exc: BaseException, message: str) -> ExtractionError:
    """Wrap an unexpected exception from a catch-all boundary, by exception type only."""
    if isinstance(exc, ImportError):
        return ExtractionEnvironmentError(message, failure_class="configuration")
    if isinstance(
        exc, (OSError, MemoryError, RecursionError)
    ):  # OSError includes timeouts and disk errors
        return ExtractionEnvironmentError(message)
    return UnclassifiedExtractionError(message)


class UnsupportedMimeTypeError(ExtractionError):
    """Raised when no extractor is registered for a MIME type."""


class TextExtractor(Protocol):
    """Protocol implemented by each supported file-type extractor."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        """Extract normalized plain text from raw file bytes."""
        ...

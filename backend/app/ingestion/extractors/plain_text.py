"""Plain-text extraction for TXT files (and the plain-text export fallback of large Google Docs)."""

from __future__ import annotations

from app.connectors.google_drive.constants import TXT_MIME
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
from app.ingestion.extractors.registry import register_extractor


def decode_plain_text_bytes(data: bytes) -> str:
    """Decode bytes as UTF-8, falling back to Latin-1 for legacy text files."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def normalize_extracted_text(text: str) -> str:
    """Normalize line endings, drop NUL characters and trim trailing whitespace per line.

    NUL (U+0000) is dropped because PostgreSQL text columns cannot store it. Math-heavy PDFs
    emit it for large brackets, and one such character made the whole document unstorable.
    """
    normalized = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


class PlainTextExtractor:
    """Extract normalized plain text from UTF-8 or Latin-1 encoded bytes."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != TXT_MIME:
            raise ExtractionError(f"PlainTextExtractor does not support MIME type: {mime_type}")

        text = normalize_extracted_text(decode_plain_text_bytes(data))
        return ExtractionResult(
            text=text,
            page_count=None,
            metadata={
                "extractor": "plain_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_plain_text_extractors() -> None:
    """Register the plain-text extractor for the TXT MIME type."""
    register_extractor(TXT_MIME, PlainTextExtractor())

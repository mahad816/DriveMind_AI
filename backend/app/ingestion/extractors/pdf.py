"""PDF text extraction for born-digital PDF files (no OCR fallback)."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.connectors.google_drive.constants import PDF_MIME
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor


def extract_pdf_text(data: bytes) -> tuple[str, int]:
    """Extract normalized text and page count from PDF bytes."""
    if not data:
        raise ExtractionError("PDF file is empty")

    try:
        reader = PdfReader(BytesIO(data))
    except PdfReadError as exc:
        raise ExtractionError("Failed to read PDF content") from exc

    if reader.is_encrypted:
        decrypt_result = reader.decrypt("")
        if decrypt_result == 0:
            raise ExtractionError("PDF is encrypted and cannot be decrypted without a password")

    page_texts: list[str] = []
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            page_texts.append(page_text)

    combined = "\n\n".join(page_texts)
    return normalize_extracted_text(combined), len(reader.pages)


class PdfTextExtractor:
    """Extract text from born-digital PDFs using pypdf."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != PDF_MIME:
            raise ExtractionError(f"PdfTextExtractor does not support MIME type: {mime_type}")

        try:
            text, page_count = extract_pdf_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract text from PDF: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=page_count,
            metadata={
                "extractor": "pdf_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_pdf_extractor() -> None:
    """Register the PDF text extractor for application/pdf."""
    register_extractor(PDF_MIME, PdfTextExtractor())

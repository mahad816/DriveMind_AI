"""DOCX text extraction using python-docx."""

from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError

from app.connectors.google_drive.constants import DOCX_MIME
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor


def extract_docx_text(data: bytes) -> str:
    """Extract normalized paragraph text from DOCX bytes."""
    if not data:
        raise ExtractionError("DOCX file is empty")

    try:
        document = Document(BytesIO(data))
    except (PackageNotFoundError, BadZipFile, ValueError) as exc:
        raise ExtractionError("Failed to read DOCX content") from exc

    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    return normalize_extracted_text("\n".join(paragraphs))


class DocxTextExtractor:
    """Extract paragraph text from DOCX files using python-docx."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type != DOCX_MIME:
            raise ExtractionError(f"DocxTextExtractor does not support MIME type: {mime_type}")

        try:
            text = extract_docx_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract text from DOCX: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=None,
            metadata={
                "extractor": "docx_text",
                "source_mime_type": mime_type,
                "filename": filename,
            },
        )


def register_docx_extractor() -> None:
    """Register the DOCX text extractor for Word document MIME type."""
    register_extractor(DOCX_MIME, DocxTextExtractor())

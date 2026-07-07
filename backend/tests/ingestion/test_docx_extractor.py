"""Tests for DOCX text extraction."""

from __future__ import annotations

from collections.abc import Generator
from io import BytesIO

import pytest
from docx import Document

from app.connectors.google_drive.constants import (
    DOCX_MIME,
    GOOGLE_DOC_MIME,
    PDF_MIME,
    TXT_MIME,
)
from app.ingestion.extractors import (
    DocxTextExtractor,
    clear_extractors,
    get_extractor,
    register_builtin_extractors,
    register_docx_extractor,
    registered_mime_types,
    reset_builtin_extractors,
)
from app.ingestion.extractors.base import ExtractionError
from app.ingestion.extractors.docx import extract_docx_text


def _docx_bytes(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _fresh_registry() -> Generator[None, None, None]:
    clear_extractors()
    reset_builtin_extractors()
    register_docx_extractor()
    yield
    clear_extractors()
    reset_builtin_extractors()


def test_extract_docx_text_reads_paragraphs() -> None:
    text = extract_docx_text(_docx_bytes("Intro paragraph", "Details paragraph"))
    assert text == "Intro paragraph\nDetails paragraph"


def test_extract_docx_text_normalizes_trailing_whitespace() -> None:
    text = extract_docx_text(_docx_bytes("Heading  ", "Body line  "))
    assert text == "Heading\nBody line"


def test_extract_docx_text_returns_empty_string_for_blank_document() -> None:
    assert extract_docx_text(_docx_bytes()) == ""


def test_extract_docx_text_rejects_empty_bytes() -> None:
    with pytest.raises(ExtractionError, match="DOCX file is empty"):
        extract_docx_text(b"")


def test_extract_docx_text_raises_for_invalid_bytes() -> None:
    with pytest.raises(ExtractionError, match="Failed to read DOCX content"):
        extract_docx_text(b"not-a-docx")


def test_docx_extractor_returns_metadata() -> None:
    extractor = DocxTextExtractor()
    result = extractor.extract(
        _docx_bytes("Resume summary"),
        mime_type=DOCX_MIME,
        filename="resume.docx",
    )

    assert result.text == "Resume summary"
    assert result.page_count is None
    assert result.metadata["extractor"] == "docx_text"
    assert result.metadata["source_mime_type"] == DOCX_MIME
    assert result.metadata["filename"] == "resume.docx"


def test_docx_extractor_rejects_non_docx_mime_type() -> None:
    extractor = DocxTextExtractor()
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        extractor.extract(_docx_bytes("hello"), mime_type=PDF_MIME, filename="file.pdf")


def test_builtin_registration_includes_plain_pdf_and_docx_extractors() -> None:
    clear_extractors()
    reset_builtin_extractors()
    register_builtin_extractors()

    registered = registered_mime_types()
    assert registered == frozenset({TXT_MIME, GOOGLE_DOC_MIME, PDF_MIME, DOCX_MIME})

    docx_result = get_extractor(DOCX_MIME).extract(
        _docx_bytes("DriveMind DOCX test"),
        mime_type=DOCX_MIME,
        filename="notes.docx",
    )
    assert docx_result.text == "DriveMind DOCX test"

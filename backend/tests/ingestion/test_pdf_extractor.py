"""Tests for PDF text-only extraction."""

from __future__ import annotations

from collections.abc import Generator
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from pypdf import PdfWriter
from pypdf.errors import PdfReadError

from app.connectors.google_drive.constants import PDF_MIME, TXT_MIME
from app.ingestion.extractors import (
    PdfTextExtractor,
    clear_extractors,
    get_extractor,
    register_builtin_extractors,
    register_pdf_extractor,
    reset_builtin_extractors,
)
from app.ingestion.extractors.base import ExtractionError
from app.ingestion.extractors.pdf import extract_pdf_text


def _blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _fresh_registry() -> Generator[None, None, None]:
    clear_extractors()
    reset_builtin_extractors()
    register_pdf_extractor()
    yield
    clear_extractors()
    reset_builtin_extractors()


def test_extract_pdf_text_from_blank_pdf_returns_empty_text() -> None:
    text, page_count = extract_pdf_text(_blank_pdf_bytes())
    assert text == ""
    assert page_count == 1


def test_extract_pdf_text_rejects_empty_bytes() -> None:
    with pytest.raises(ExtractionError, match="PDF file is empty"):
        extract_pdf_text(b"")


@patch("app.ingestion.extractors.pdf.PdfReader")
def test_extract_pdf_text_joins_multi_page_content(mock_reader_cls: MagicMock) -> None:
    first_page = MagicMock()
    first_page.extract_text.return_value = "Page one  "
    second_page = MagicMock()
    second_page.extract_text.return_value = "Page two"
    mock_reader = MagicMock()
    mock_reader.is_encrypted = False
    mock_reader.pages = [first_page, second_page]
    mock_reader_cls.return_value = mock_reader

    text, page_count = extract_pdf_text(b"%PDF-1.4 fake")

    assert text == "Page one\n\nPage two"
    assert page_count == 2


@patch("app.ingestion.extractors.pdf.PdfReader")
def test_extract_pdf_text_raises_for_encrypted_pdf(mock_reader_cls: MagicMock) -> None:
    mock_reader = MagicMock()
    mock_reader.is_encrypted = True
    mock_reader.decrypt.return_value = 0
    mock_reader_cls.return_value = mock_reader

    with pytest.raises(ExtractionError, match="encrypted and cannot be decrypted"):
        extract_pdf_text(b"%PDF-1.4 encrypted")


@patch("app.ingestion.extractors.pdf.PdfReader", side_effect=PdfReadError("corrupt"))
def test_extract_pdf_text_raises_for_invalid_pdf(_mock_reader_cls: MagicMock) -> None:
    with pytest.raises(ExtractionError, match="Failed to read PDF content"):
        extract_pdf_text(b"not-a-pdf")


def test_pdf_extractor_returns_metadata_and_page_count() -> None:
    extractor = PdfTextExtractor()
    result = extractor.extract(_blank_pdf_bytes(), mime_type=PDF_MIME, filename="resume.pdf")

    assert result.text == ""
    assert result.page_count == 1
    assert result.metadata["extractor"] == "pdf_text"
    assert result.metadata["filename"] == "resume.pdf"


def test_pdf_extractor_rejects_non_pdf_mime_type() -> None:
    extractor = PdfTextExtractor()
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        extractor.extract(b"hello", mime_type=TXT_MIME, filename="notes.txt")


def test_builtin_registration_exposes_pdf_extractor() -> None:
    clear_extractors()
    reset_builtin_extractors()
    register_builtin_extractors()

    result = get_extractor(PDF_MIME).extract(
        _blank_pdf_bytes(),
        mime_type=PDF_MIME,
        filename="sample.pdf",
    )
    assert result.page_count == 1

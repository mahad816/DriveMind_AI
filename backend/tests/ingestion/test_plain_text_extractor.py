"""Tests for plain-text and Google Docs export extractors."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.connectors.google_drive.constants import GOOGLE_DOC_MIME, PDF_MIME, TXT_MIME
from app.ingestion.extractors import (
    PlainTextExtractor,
    clear_extractors,
    get_extractor,
    register_builtin_extractors,
    register_plain_text_extractors,
    reset_builtin_extractors,
)
from app.ingestion.extractors.base import ExtractionError


@pytest.fixture(autouse=True)
def _fresh_registry() -> Generator[None, None, None]:
    clear_extractors()
    reset_builtin_extractors()
    register_plain_text_extractors()
    yield
    clear_extractors()
    reset_builtin_extractors()


def test_decode_plain_text_bytes_handles_utf8() -> None:
    from app.ingestion.extractors.plain_text import decode_plain_text_bytes

    assert decode_plain_text_bytes("hello world".encode()) == "hello world"


def test_decode_plain_text_bytes_strips_utf8_bom() -> None:
    from app.ingestion.extractors.plain_text import decode_plain_text_bytes

    assert decode_plain_text_bytes("\ufeffnotes".encode()) == "notes"


def test_decode_plain_text_bytes_falls_back_to_latin1() -> None:
    from app.ingestion.extractors.plain_text import decode_plain_text_bytes

    raw = b"caf\xe9"
    assert decode_plain_text_bytes(raw) == "café"


def test_normalize_extracted_text_unifies_line_endings() -> None:
    from app.ingestion.extractors.plain_text import normalize_extracted_text

    assert normalize_extracted_text("line one\r\nline two\rline three\n") == (
        "line one\nline two\nline three"
    )


def test_normalize_extracted_text_strips_trailing_line_whitespace() -> None:
    from app.ingestion.extractors.plain_text import normalize_extracted_text

    assert normalize_extracted_text("alpha   \nbeta\t") == "alpha\nbeta"


def test_extract_txt_file_returns_normalized_text() -> None:
    extractor = PlainTextExtractor()
    result = extractor.extract(
        b"Title  \r\n\r\nBody line  \r\n",
        mime_type=TXT_MIME,
        filename="notes.txt",
    )

    assert result.text == "Title\n\nBody line"
    assert result.page_count is None
    assert result.metadata["extractor"] == "plain_text"
    assert result.metadata["source_mime_type"] == TXT_MIME


def test_extract_google_doc_export_bytes() -> None:
    extractor = PlainTextExtractor()
    result = extractor.extract(
        b"Google Doc export\r\nSecond paragraph",
        mime_type=GOOGLE_DOC_MIME,
        filename="meeting-notes",
    )

    assert result.text == "Google Doc export\nSecond paragraph"
    assert result.metadata["source_mime_type"] == GOOGLE_DOC_MIME


def test_extract_empty_txt_file_returns_empty_string() -> None:
    extractor = PlainTextExtractor()
    result = extractor.extract(b"", mime_type=TXT_MIME, filename="empty.txt")
    assert result.text == ""


def test_extract_rejects_unsupported_mime_type() -> None:
    extractor = PlainTextExtractor()
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        extractor.extract(b"%PDF", mime_type=PDF_MIME, filename="file.pdf")


def test_builtin_registration_exposes_txt_and_google_doc_extractors() -> None:
    clear_extractors()
    reset_builtin_extractors()
    register_builtin_extractors()

    txt_result = get_extractor(TXT_MIME).extract(
        b"hello txt",
        mime_type=TXT_MIME,
        filename="a.txt",
    )
    doc_result = get_extractor(GOOGLE_DOC_MIME).extract(
        b"hello doc",
        mime_type=GOOGLE_DOC_MIME,
        filename="a-doc",
    )

    assert txt_result.text == "hello txt"
    assert doc_result.text == "hello doc"

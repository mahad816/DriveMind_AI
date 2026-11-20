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
from app.ingestion.extractors.base import ExtractionError, UnsupportedMimeTypeError


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


def test_a_google_doc_type_is_not_read_as_plain_text() -> None:
    """Google Docs arrive as DOCX bytes; reading those as text would store zip garbage."""
    extractor = PlainTextExtractor()
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        extractor.extract(b"PK\x03\x04", mime_type=GOOGLE_DOC_MIME, filename="notes")


def test_extract_empty_txt_file_returns_empty_string() -> None:
    extractor = PlainTextExtractor()
    result = extractor.extract(b"", mime_type=TXT_MIME, filename="empty.txt")
    assert result.text == ""


def test_extract_rejects_unsupported_mime_type() -> None:
    extractor = PlainTextExtractor()
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        extractor.extract(b"%PDF", mime_type=PDF_MIME, filename="file.pdf")


def test_builtin_registration_exposes_the_txt_extractor_but_not_one_for_google_docs() -> None:
    clear_extractors()
    reset_builtin_extractors()
    register_builtin_extractors()

    txt_result = get_extractor(TXT_MIME).extract(
        b"hello txt",
        mime_type=TXT_MIME,
        filename="a.txt",
    )

    assert txt_result.text == "hello txt"
    with pytest.raises(UnsupportedMimeTypeError):
        get_extractor(GOOGLE_DOC_MIME)


def test_normalize_extracted_text_drops_nul_but_keeps_everything_else() -> None:
    """PostgreSQL cannot store U+0000; the surrounding text must be left exactly as it was."""
    from app.ingestion.extractors.plain_text import normalize_extracted_text

    assert normalize_extracted_text("p(i) \x00x\x00 + 1\r\nnext\x00") == "p(i) x + 1\nnext"
    assert normalize_extracted_text("keep \x01 this\ttab") == "keep \x01 this\ttab"
    assert "\x00" not in normalize_extracted_text("\x00\x00")


def test_plain_text_extractor_result_never_contains_nul() -> None:
    result = PlainTextExtractor().extract(b"before\x00after", mime_type=TXT_MIME, filename="a.txt")
    assert result.text == "beforeafter"


def test_normalization_keeps_a_line_that_holds_only_a_form_feed_but_trims_other_trailing_space():
    """PDF text separates pages with a form-feed line; plain rstrip would erase it (and shift offsets)."""
    from app.ingestion.extractors.plain_text import normalize_extracted_text

    assert normalize_extracted_text("page one  \n\f\npage two \t\n") == "page one\n\f\npage two"
    assert normalize_extracted_text("a\n \f \nb") == "a\n\f\nb"
    assert normalize_extracted_text("a\n\f\n\f\nb") == "a\n\f\n\f\nb"
    assert normalize_extracted_text("a  \n   \nb") == "a\n\nb"  # ordinary blank lines are unchanged
    once = normalize_extracted_text("x\n\f\ny")
    assert normalize_extracted_text(once) == once  # the chunker normalizes again: must be stable

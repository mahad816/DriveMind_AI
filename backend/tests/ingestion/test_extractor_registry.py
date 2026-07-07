"""Tests for MIME-type extractor registry."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from app.connectors.google_drive.constants import PDF_MIME, TXT_MIME
from app.ingestion.extractors import (
    ExtractionResult,
    UnsupportedMimeTypeError,
    clear_extractors,
    get_extractor,
    register_extractor,
    registered_mime_types,
)


class _FakeExtractor:
    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        return ExtractionResult(text=data.decode("utf-8"), page_count=None)


@pytest.fixture(autouse=True)
def _reset_registry() -> Generator[None, None, None]:
    clear_extractors()
    yield
    clear_extractors()


def test_get_extractor_raises_for_unregistered_mime() -> None:
    with pytest.raises(UnsupportedMimeTypeError, match="No extractor registered"):
        get_extractor(PDF_MIME)


def test_register_and_get_extractor() -> None:
    extractor = _FakeExtractor()
    register_extractor(TXT_MIME, extractor)

    assert get_extractor(TXT_MIME) is extractor
    assert registered_mime_types() == frozenset({TXT_MIME})


def test_register_extractor_rejects_empty_mime_type() -> None:
    with pytest.raises(ValueError, match="mime_type must be non-empty"):
        register_extractor("", _FakeExtractor())


def test_last_registration_wins_for_duplicate_mime_type() -> None:
    first = _FakeExtractor()
    second = _FakeExtractor()

    register_extractor(TXT_MIME, first)
    register_extractor(TXT_MIME, second)

    assert get_extractor(TXT_MIME) is second

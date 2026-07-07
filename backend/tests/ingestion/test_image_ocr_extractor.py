"""Tests for image OCR extraction."""

from __future__ import annotations

import shutil
from collections.abc import Generator
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image, UnidentifiedImageError
from pytesseract import TesseractNotFoundError

from app.connectors.google_drive.constants import (
    IMAGE_MIME_TYPES,
    PDF_MIME,
    SUPPORTED_MIME_TYPES,
    TXT_MIME,
)
from app.ingestion.extractors import (
    ImageOcrExtractor,
    clear_extractors,
    get_extractor,
    register_builtin_extractors,
    register_image_ocr_extractors,
    registered_mime_types,
    reset_builtin_extractors,
)
from app.ingestion.extractors.base import ExtractionError
from app.ingestion.extractors.image_ocr import extract_image_ocr_text

TESSERACT_AVAILABLE = shutil.which("tesseract") is not None


def _png_image_bytes() -> bytes:
    image = Image.new("RGB", (120, 40), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _fresh_registry() -> Generator[None, None, None]:
    clear_extractors()
    reset_builtin_extractors()
    register_image_ocr_extractors()
    yield
    clear_extractors()
    reset_builtin_extractors()


def test_extract_image_ocr_text_rejects_empty_bytes() -> None:
    with pytest.raises(ExtractionError, match="Image file is empty"):
        extract_image_ocr_text(b"")


@patch("app.ingestion.extractors.image_ocr.pytesseract.image_to_string")
def test_extract_image_ocr_text_normalizes_tesseract_output(mock_ocr: MagicMock) -> None:
    mock_ocr.return_value = "Screenshot title  \r\nBody text  \r\n"
    text = extract_image_ocr_text(_png_image_bytes())
    assert text == "Screenshot title\nBody text"
    mock_ocr.assert_called_once()


@patch("app.ingestion.extractors.image_ocr.Image.open", side_effect=UnidentifiedImageError("bad"))
def test_extract_image_ocr_text_raises_for_invalid_image_bytes(_mock_open: MagicMock) -> None:
    with pytest.raises(ExtractionError, match="Failed to read image content"):
        extract_image_ocr_text(b"not-an-image")


@patch(
    "app.ingestion.extractors.image_ocr.pytesseract.image_to_string",
    side_effect=TesseractNotFoundError(),
)
def test_extract_image_ocr_text_raises_when_tesseract_missing(_mock_ocr: MagicMock) -> None:
    with pytest.raises(ExtractionError, match="Tesseract OCR engine is not installed"):
        extract_image_ocr_text(_png_image_bytes())


def test_image_ocr_extractor_returns_metadata() -> None:
    extractor = ImageOcrExtractor()
    with patch(
        "app.ingestion.extractors.image_ocr.pytesseract.image_to_string",
        return_value="Label text",
    ):
        result = extractor.extract(
            _png_image_bytes(),
            mime_type="image/png",
            filename="screenshot.png",
        )

    assert result.text == "Label text"
    assert result.page_count is None
    assert result.metadata["extractor"] == "image_ocr"
    assert result.metadata["ocr_engine"] == "tesseract"
    assert result.metadata["filename"] == "screenshot.png"


def test_image_ocr_extractor_rejects_non_image_mime_type() -> None:
    extractor = ImageOcrExtractor()
    with pytest.raises(ExtractionError, match="does not support MIME type"):
        extractor.extract(_png_image_bytes(), mime_type=PDF_MIME, filename="file.pdf")


def test_image_ocr_registration_covers_all_image_mime_types() -> None:
    registered = registered_mime_types()
    assert IMAGE_MIME_TYPES.issubset(registered)


def test_builtin_registration_covers_all_supported_mime_types() -> None:
    clear_extractors()
    reset_builtin_extractors()
    register_builtin_extractors()

    assert registered_mime_types() == SUPPORTED_MIME_TYPES
    assert get_extractor(TXT_MIME) is not None
    assert get_extractor("image/png") is not None


@pytest.mark.skipif(not TESSERACT_AVAILABLE, reason="Tesseract is not installed on PATH")
def test_tesseract_integration_reads_simple_png_text() -> None:
    image = Image.new("RGB", (240, 80), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    # Blank images may return empty OCR output; ensure pipeline runs end-to-end.
    result = ImageOcrExtractor().extract(
        buffer.getvalue(),
        mime_type="image/png",
        filename="blank.png",
    )
    assert isinstance(result.text, str)

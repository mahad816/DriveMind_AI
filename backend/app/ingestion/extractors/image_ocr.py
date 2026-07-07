"""Image OCR text extraction using Tesseract via pytesseract."""

from __future__ import annotations

from io import BytesIO

import pytesseract
from PIL import Image, UnidentifiedImageError
from pytesseract import TesseractNotFoundError

from app.connectors.google_drive.constants import IMAGE_MIME_TYPES
from app.ingestion.extractors.base import ExtractionError, ExtractionResult
from app.ingestion.extractors.plain_text import normalize_extracted_text
from app.ingestion.extractors.registry import register_extractor


def extract_image_ocr_text(data: bytes) -> str:
    """Extract normalized text from image bytes using Tesseract OCR."""
    if not data:
        raise ExtractionError("Image file is empty")

    try:
        with Image.open(BytesIO(data)) as image:
            rgb_image = image.convert("RGB")
            ocr_text = pytesseract.image_to_string(rgb_image)
    except UnidentifiedImageError as exc:
        raise ExtractionError("Failed to read image content") from exc
    except TesseractNotFoundError as exc:
        raise ExtractionError(
            "Tesseract OCR engine is not installed or not available on PATH"
        ) from exc

    return normalize_extracted_text(ocr_text)


class ImageOcrExtractor:
    """Extract text from supported image formats using Tesseract OCR."""

    def extract(self, data: bytes, *, mime_type: str, filename: str) -> ExtractionResult:
        if mime_type not in IMAGE_MIME_TYPES:
            raise ExtractionError(f"ImageOcrExtractor does not support MIME type: {mime_type}")

        try:
            text = extract_image_ocr_text(data)
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Failed to extract text from image: {filename}") from exc

        return ExtractionResult(
            text=text,
            page_count=None,
            metadata={
                "extractor": "image_ocr",
                "source_mime_type": mime_type,
                "filename": filename,
                "ocr_engine": "tesseract",
            },
        )


def register_image_ocr_extractors() -> None:
    """Register the image OCR extractor for all supported image MIME types."""
    extractor = ImageOcrExtractor()
    for mime_type in IMAGE_MIME_TYPES:
        register_extractor(mime_type, extractor)

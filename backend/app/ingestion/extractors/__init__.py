"""File-type-specific text extractors (PDF, DOCX, OCR, etc.)."""

from app.ingestion.extractors.base import (
    ExtractionError,
    ExtractionResult,
    TextExtractor,
    UnsupportedMimeTypeError,
)
from app.ingestion.extractors.bootstrap import register_builtin_extractors, reset_builtin_extractors
from app.ingestion.extractors.docx import (
    DocxTextExtractor,
    extract_docx_text,
    register_docx_extractor,
)
from app.ingestion.extractors.image_ocr import (
    ImageOcrExtractor,
    extract_image_ocr_text,
    register_image_ocr_extractors,
)
from app.ingestion.extractors.pdf import (
    PdfTextExtractor,
    extract_pdf_text,
    register_pdf_extractor,
)
from app.ingestion.extractors.plain_text import (
    PlainTextExtractor,
    decode_plain_text_bytes,
    normalize_extracted_text,
    register_plain_text_extractors,
)
from app.ingestion.extractors.registry import (
    clear_extractors,
    get_extractor,
    register_extractor,
    registered_mime_types,
)

register_builtin_extractors()

__all__ = [
    "DocxTextExtractor",
    "ExtractionError",
    "ExtractionResult",
    "PdfTextExtractor",
    "ImageOcrExtractor",
    "PlainTextExtractor",
    "TextExtractor",
    "UnsupportedMimeTypeError",
    "clear_extractors",
    "decode_plain_text_bytes",
    "extract_docx_text",
    "extract_image_ocr_text",
    "extract_pdf_text",
    "get_extractor",
    "normalize_extracted_text",
    "register_builtin_extractors",
    "register_docx_extractor",
    "register_extractor",
    "register_image_ocr_extractors",
    "register_pdf_extractor",
    "register_plain_text_extractors",
    "registered_mime_types",
    "reset_builtin_extractors",
]

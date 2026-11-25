"""Typed failure classes at every extractor exception boundary (Checkpoint A).

A queue may move past a failed document only when the failure is positively the document's own. These tests inject
faults at each boundary and assert the class by exception TYPE, never by message text. Container-free.
"""

import io

import pytest
from PIL import Image
from pytesseract import TesseractNotFoundError

from app.connectors.google_drive.constants import (
    CSV_MIME,
    DOCX_MIME,
    PDF_MIME,
    PPTX_MIME,
    XLSX_MIME,
)
from app.ingestion.extractors import ExtractionError, UnsupportedMimeTypeError, get_extractor
from app.ingestion.extractors.csv_text import CsvTextExtractor
from app.ingestion.extractors.docx import DocxTextExtractor
from app.ingestion.extractors.image_ocr import ImageOcrExtractor
from app.ingestion.extractors.pdf import PdfTextExtractor
from app.ingestion.extractors.pptx import PptxTextExtractor
from app.ingestion.extractors.xlsx import XlsxTextExtractor
from app.services.indexing_failure_class import FAILURE_CLASSES, from_exception

PNG = io.BytesIO()
Image.new("RGB", (4, 4)).save(PNG, "PNG")
PNG_BYTES = PNG.getvalue()

# (extractor, mime, module that holds the inner function the extractor calls, that function's name, input bytes)
BOUNDARIES = [
    pytest.param(PdfTextExtractor(), PDF_MIME, "pdf", "extract_pdf_text", b"%PDF-1.4 x", id="pdf"),
    pytest.param(DocxTextExtractor(), DOCX_MIME, "docx", "extract_docx_text", b"PK x", id="docx"),
    pytest.param(PptxTextExtractor(), PPTX_MIME, "pptx", "extract_pptx_text", b"PK x", id="pptx"),
    pytest.param(XlsxTextExtractor(), XLSX_MIME, "xlsx", "extract_xlsx_text", b"PK x", id="xlsx"),
    pytest.param(CsvTextExtractor(), CSV_MIME, "csv_text", "extract_csv_text", b"a,b", id="csv"),
    pytest.param(
        ImageOcrExtractor(),
        "image/png",
        "image_ocr",
        "extract_image_ocr_text",
        PNG_BYTES,
        id="image",
    ),
]


def failure_of(extractor, mime, data):
    with pytest.raises(
        ExtractionError
    ) as caught:  # still an ExtractionError: existing callers keep working
        extractor.extract(data, mime_type=mime, filename="synthetic")
    return from_exception(caught.value)


def test_missing_tesseract_is_configuration_not_document(monkeypatch):
    # The reviewer's confirmed reproduction.
    def missing(_image):
        raise TesseractNotFoundError()

    monkeypatch.setattr("pytesseract.image_to_string", missing)
    assert failure_of(ImageOcrExtractor(), "image/png", PNG_BYTES) == "configuration"


@pytest.mark.parametrize(
    "fault,expected",
    [
        (OSError("disk"), "infrastructure"),
        (MemoryError(), "infrastructure"),
        (TimeoutError(), "infrastructure"),
        (ImportError("missing optional dependency"), "configuration"),
        (RuntimeError("anything else"), "unknown"),
        (KeyError("x"), "unknown"),
    ],
    ids=[
        "oserror",
        "memoryerror",
        "timeout",
        "import-error",
        "unexpected-runtime",
        "unexpected-key",
    ],
)
@pytest.mark.parametrize("extractor,mime,module,inner,data", BOUNDARIES)
def test_an_unexpected_fault_at_any_boundary_is_never_a_document_failure(
    monkeypatch, extractor, mime, module, inner, data, fault, expected
):
    def boom(*_args, **_kwargs):
        raise fault

    monkeypatch.setattr(f"app.ingestion.extractors.{module}.{inner}", boom)
    assert failure_of(extractor, mime, data) == expected


def test_xlsx_oserror_inside_the_workbook_reader_is_infrastructure(monkeypatch):
    # These two catches used to fold OSError into "Failed to read XLSX content" (a document failure).
    def boom(*_args, **_kwargs):
        raise OSError("no space left")

    monkeypatch.setattr("app.ingestion.extractors.xlsx.load_workbook", boom)
    from zipfile import ZipFile

    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("x", "y")
    assert failure_of(XlsxTextExtractor(), XLSX_MIME, buffer.getvalue()) == "infrastructure"


@pytest.mark.parametrize(
    "extractor,mime,data",
    [
        pytest.param(PdfTextExtractor(), PDF_MIME, b"not a pdf at all", id="pdf-malformed"),
        pytest.param(PdfTextExtractor(), PDF_MIME, b"", id="pdf-empty"),
        pytest.param(DocxTextExtractor(), DOCX_MIME, b"not a zip", id="docx-malformed"),
        pytest.param(DocxTextExtractor(), DOCX_MIME, b"", id="docx-empty"),
        pytest.param(PptxTextExtractor(), PPTX_MIME, b"not a zip", id="pptx-malformed"),
        pytest.param(XlsxTextExtractor(), XLSX_MIME, b"not a zip", id="xlsx-malformed"),
        pytest.param(XlsxTextExtractor(), XLSX_MIME, b"", id="xlsx-empty"),
        pytest.param(ImageOcrExtractor(), "image/png", b"not an image", id="image-malformed"),
        pytest.param(ImageOcrExtractor(), "image/png", b"", id="image-empty"),
    ],
)
def test_malformed_or_empty_content_is_positively_a_document_failure(extractor, mime, data):
    assert failure_of(extractor, mime, data) == "document"


def test_an_unsupported_format_is_a_document_failure():
    with pytest.raises(UnsupportedMimeTypeError) as caught:
        get_extractor("application/x-synthetic-unsupported")
    assert from_exception(caught.value) == "document"


def test_every_class_an_extractor_can_report_is_in_the_public_vocabulary(monkeypatch):
    for fault in (OSError(), ImportError(), RuntimeError()):
        monkeypatch.setattr(
            "app.ingestion.extractors.pdf.extract_pdf_text",
            lambda *_a, _f=fault, **_k: (_ for _ in ()).throw(_f),
        )
        assert failure_of(PdfTextExtractor(), PDF_MIME, b"%PDF x") in FAILURE_CLASSES

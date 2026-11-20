"""Constants for the read-only Google Drive connector."""

from __future__ import annotations

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
GOOGLE_SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

PDF_MIME = "application/pdf"
TXT_MIME = "text/plain"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV_MIME = "text/csv"
MARKDOWN_MIME = "text/markdown"

IMAGE_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/webp",
        "image/gif",
        "image/tiff",
        "image/bmp",
    }
)

# Supported source file types (Google Docs, Slides and Sheets, PDF, TXT, Markdown, CSV, DOCX, PPTX, XLSX,
# images for OCR).
SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        GOOGLE_DOC_MIME,
        GOOGLE_SLIDES_MIME,
        GOOGLE_SHEETS_MIME,
        PDF_MIME,
        TXT_MIME,
        MARKDOWN_MIME,
        CSV_MIME,
        DOCX_MIME,
        PPTX_MIME,
        XLSX_MIME,
    }
    | set(IMAGE_MIME_TYPES)
)

# Google-native files cannot be downloaded, only exported. Docs, Slides and Sheets are exported in the
# Office format so tables, headings, lists, speaker notes and every sheet survive (the plain-text and
# CSV exports drop them). Google refuses exports over about 10 MB; a simpler export of the same file
# is then used instead of failing it.
GOOGLE_EXPORT_MIME: dict[str, str] = {
    GOOGLE_DOC_MIME: DOCX_MIME,
    GOOGLE_SLIDES_MIME: PPTX_MIME,
    GOOGLE_SHEETS_MIME: XLSX_MIME,
}
GOOGLE_DOC_EXPORT_MIME = GOOGLE_EXPORT_MIME[GOOGLE_DOC_MIME]
GOOGLE_TEXT_EXPORT_MIME = "text/plain"
# The simpler export per Google type. Sheets cannot export as plain text; CSV holds the first sheet only
# (Google's export table: https://developers.google.com/workspace/drive/api/guides/ref-export-formats).
GOOGLE_FALLBACK_EXPORT_MIME: dict[str, str] = {
    GOOGLE_DOC_MIME: GOOGLE_TEXT_EXPORT_MIME,
    GOOGLE_SLIDES_MIME: GOOGLE_TEXT_EXPORT_MIME,
    GOOGLE_SHEETS_MIME: CSV_MIME,
}

# Fields requested from the Drive API for each file. Kept minimal and read-only.
FILE_FIELDS = (
    "id, name, mimeType, modifiedTime, createdTime, size, "
    "parents, trashed, webViewLink, md5Checksum"
)
LIST_FILES_FIELDS = f"nextPageToken, files({FILE_FIELDS})"
CHANGE_LIST_FIELDS = (
    f"nextPageToken, newStartPageToken, changes(removed, fileId, file({FILE_FIELDS}))"
)

# Exclude folders and trashed files from listings by default.
DEFAULT_LIST_QUERY = f"mimeType != '{GOOGLE_FOLDER_MIME}' and trashed = false"

DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000


def is_supported_mime_type(mime_type: str | None) -> bool:
    """Return True when a MIME type is in the MVP-supported set."""
    if not mime_type:
        return False
    return mime_type in SUPPORTED_MIME_TYPES


def requires_export(mime_type: str) -> bool:
    """Return True when Drive export_media is required instead of get_media."""
    return mime_type in GOOGLE_EXPORT_MIME


def output_content_mime_type(source_mime_type: str) -> str:
    """Return the usual MIME type of bytes produced when reading a supported file.

    A Google Doc normally arrives as DOCX, a Google Slides file as PPTX and a Google Sheet as XLSX;
    ``GoogleDriveClient.get_file_content_with_type`` reports the type that was really returned when
    the plain-text fallback had to be used.
    """
    return GOOGLE_EXPORT_MIME.get(source_mime_type, source_mime_type)

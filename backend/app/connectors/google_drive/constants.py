"""Constants for the read-only Google Drive connector."""

from __future__ import annotations

GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_FOLDER_MIME = "application/vnd.google-apps.folder"

PDF_MIME = "application/pdf"
TXT_MIME = "text/plain"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

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

# MVP-supported source file types (Google Docs, PDF, TXT, DOCX, images for OCR).
SUPPORTED_MIME_TYPES: frozenset[str] = frozenset(
    {
        GOOGLE_DOC_MIME,
        PDF_MIME,
        TXT_MIME,
        DOCX_MIME,
    }
    | set(IMAGE_MIME_TYPES)
)

# Default export target when reading Google Docs content for ingestion.
GOOGLE_DOC_EXPORT_MIME = "text/plain"

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
    return mime_type == GOOGLE_DOC_MIME


def output_content_mime_type(source_mime_type: str) -> str:
    """Return the MIME type of bytes produced when reading a supported file."""
    if source_mime_type == GOOGLE_DOC_MIME:
        return GOOGLE_DOC_EXPORT_MIME
    return source_mime_type

"""Hash helpers for extracted document text."""

from __future__ import annotations

import hashlib


def compute_extracted_text_hash(text: str) -> str:
    """Return a stable SHA-256 hex digest for normalized extracted text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

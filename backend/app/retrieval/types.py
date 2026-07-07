"""Shared retrieval result types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by retrieval with Postgres text and Qdrant score."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    drive_file_id: uuid.UUID
    filename: str
    mime_type: str
    modified_at: datetime
    chunk_index: int
    text: str
    score: float

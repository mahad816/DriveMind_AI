"""Shared retrieval result types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

RetrievalSource = Literal["vector", "keyword", "metadata", "hybrid"]


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk returned by retrieval with text and retrieval scores."""

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    drive_file_id: uuid.UUID
    filename: str
    mime_type: str
    modified_at: datetime
    chunk_index: int
    text: str
    score: float
    primary_source: RetrievalSource = "vector"
    source_scores: dict[RetrievalSource, float] = field(default_factory=dict)
    fusion_score: float | None = None

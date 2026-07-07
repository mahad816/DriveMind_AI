"""Embedding provider factory helpers."""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingService
from app.embeddings.openai_service import OpenAIEmbeddingService


def get_embedding_service(settings: Settings | None = None) -> EmbeddingService:
    """Return the configured embedding provider for the MVP."""
    return OpenAIEmbeddingService(settings=settings or get_settings())

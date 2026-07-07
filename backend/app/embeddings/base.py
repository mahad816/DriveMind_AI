"""Shared types and errors for embedding providers."""

from __future__ import annotations

from typing import Protocol


class EmbeddingError(Exception):
    """Base error raised when embedding generation fails."""


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when embedding provider settings are missing or invalid."""


class EmbeddingService(Protocol):
    """Protocol implemented by embedding providers."""

    @property
    def model_name(self) -> str:
        """Return the configured embedding model identifier."""
        ...

    @property
    def embedding_dimension(self) -> int:
        """Return the vector dimension produced by this model."""
        ...

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple text inputs and return vectors in the same order."""
        ...

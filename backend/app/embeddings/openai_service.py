"""OpenAI embedding provider."""

from __future__ import annotations

from openai import APIError, AsyncOpenAI

from app.core.config import Settings, get_settings
from app.embeddings.base import EmbeddingConfigurationError, EmbeddingError

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_BATCH_SIZE = 100

_EMBEDDING_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def resolve_embedding_dimension(model_name: str) -> int:
    """Return the vector dimension for a supported embedding model."""
    dimension = _EMBEDDING_DIMENSIONS.get(model_name)
    if dimension is None:
        supported = ", ".join(sorted(_EMBEDDING_DIMENSIONS))
        raise EmbeddingConfigurationError(
            f"Unsupported embedding model '{model_name}'. Supported models: {supported}"
        )
    return dimension


class OpenAIEmbeddingService:
    """Generate embeddings via the OpenAI embeddings API."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: AsyncOpenAI | None = None,
        batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE,
    ) -> None:
        self.settings = settings or get_settings()
        self.batch_size = batch_size
        self._client = client

    @property
    def model_name(self) -> str:
        return self.settings.embedding_model or DEFAULT_EMBEDDING_MODEL

    @property
    def embedding_dimension(self) -> int:
        return resolve_embedding_dimension(self.model_name)

    def _get_client(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        if not self.settings.openai_api_key:
            raise EmbeddingConfigurationError("OPENAI_API_KEY is not configured")
        return AsyncOpenAI(api_key=self.settings.openai_api_key)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in deterministic input order."""
        if not texts:
            return []

        for index, text in enumerate(texts):
            if not text.strip():
                raise EmbeddingError(f"Cannot embed empty text at index {index}")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        client = self._get_client()
        try:
            response = await client.embeddings.create(
                input=texts,
                model=self.model_name,
            )
        except APIError as exc:
            raise EmbeddingError(f"OpenAI embedding request failed: {exc}") from exc

        ordered = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in ordered]

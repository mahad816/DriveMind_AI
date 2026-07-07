"""Embedding generation and vector store integration."""

from app.embeddings.base import (
    EmbeddingConfigurationError,
    EmbeddingError,
    EmbeddingService,
)
from app.embeddings.factory import get_embedding_service
from app.embeddings.openai_service import (
    DEFAULT_EMBEDDING_BATCH_SIZE,
    DEFAULT_EMBEDDING_MODEL,
    OpenAIEmbeddingService,
    resolve_embedding_dimension,
)
from app.embeddings.vector_store import (
    DEFAULT_QDRANT_COLLECTION,
    QdrantVectorStore,
    VectorPoint,
    VectorStoreError,
)

__all__ = [
    "DEFAULT_EMBEDDING_BATCH_SIZE",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_QDRANT_COLLECTION",
    "EmbeddingConfigurationError",
    "EmbeddingError",
    "EmbeddingService",
    "OpenAIEmbeddingService",
    "QdrantVectorStore",
    "VectorPoint",
    "VectorStoreError",
    "get_embedding_service",
    "resolve_embedding_dimension",
]

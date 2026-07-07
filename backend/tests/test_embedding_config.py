"""Tests for embedding-related settings."""

from app.core.config import Settings
from app.embeddings.openai_service import DEFAULT_EMBEDDING_MODEL
from app.embeddings.vector_store import DEFAULT_QDRANT_COLLECTION


def test_settings_include_embedding_fields() -> None:
    """Settings model should expose OpenAI embedding env fields."""
    settings = Settings(
        openai_api_key="sk-test-key",
        embedding_model="text-embedding-3-large",
    )
    assert settings.openai_api_key == "sk-test-key"
    assert settings.embedding_model == "text-embedding-3-large"


def test_settings_embedding_defaults() -> None:
    """Embedding field defaults should match the MVP OpenAI model."""
    fields = Settings.model_fields
    assert fields["openai_api_key"].default == ""
    assert fields["embedding_model"].default == DEFAULT_EMBEDDING_MODEL


def test_settings_include_qdrant_fields() -> None:
    """Settings model should expose Qdrant connection env fields."""
    settings = Settings(
        qdrant_host="qdrant.local",
        qdrant_port=7333,
        qdrant_collection="custom_chunks",
    )
    assert settings.qdrant_host == "qdrant.local"
    assert settings.qdrant_port == 7333
    assert settings.qdrant_collection == "custom_chunks"


def test_settings_qdrant_defaults() -> None:
    """Qdrant field defaults should match local docker-compose values."""
    fields = Settings.model_fields
    assert fields["qdrant_host"].default == "localhost"
    assert fields["qdrant_port"].default == 6333
    assert fields["qdrant_collection"].default == DEFAULT_QDRANT_COLLECTION
    assert fields["qdrant_upsert_batch_size"].default == 100


def test_settings_retrieval_defaults() -> None:
    """Retrieval field defaults should match Phase 6 MVP tuning."""
    fields = Settings.model_fields
    assert fields["retrieval_top_k"].default == 8
    assert fields["retrieval_score_threshold"].default == 0.35


def test_settings_chat_defaults() -> None:
    """Chat and RAG field defaults should match Phase 6 MVP tuning."""
    fields = Settings.model_fields
    assert fields["chat_model"].default == "gpt-4o-mini"
    assert fields["rag_max_context_chars"].default == 12000

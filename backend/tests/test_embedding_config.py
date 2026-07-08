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
    """Retrieval defaults should match the Phase 7 hybrid baseline."""
    fields = Settings.model_fields
    assert fields["hybrid_retrieval_enabled"].default is True
    assert fields["retrieval_candidate_k"].default == 24
    assert fields["retrieval_top_k"].default == 8
    assert fields["retrieval_score_threshold"].default == 0.35
    assert fields["hybrid_rrf_k"].default == 60
    assert fields["hybrid_weight_vector"].default == 0.5
    assert fields["hybrid_weight_keyword"].default == 0.3
    assert fields["hybrid_weight_metadata"].default == 0.2
    assert fields["evidence_min_fusion_score"].default == 0.15
    assert fields["fts_language"].default == "english"


def test_settings_chat_defaults() -> None:
    """Chat and RAG field defaults should match Phase 6 MVP tuning."""
    fields = Settings.model_fields
    assert fields["chat_model"].default == "gpt-4o-mini"
    assert fields["rag_max_context_chars"].default == 12000


def test_settings_accepts_custom_rag_env_values() -> None:
    """Chat and retrieval settings should load from environment overrides."""
    settings = Settings(
        chat_model="gpt-4o",
        rag_max_context_chars=8000,
        hybrid_retrieval_enabled=False,
        retrieval_candidate_k=32,
        retrieval_top_k=12,
        retrieval_score_threshold=0.25,
        hybrid_rrf_k=40,
        hybrid_weight_vector=0.4,
        hybrid_weight_keyword=0.4,
        hybrid_weight_metadata=0.2,
        evidence_min_fusion_score=0.2,
        fts_language="simple",
    )
    assert settings.chat_model == "gpt-4o"
    assert settings.rag_max_context_chars == 8000
    assert settings.hybrid_retrieval_enabled is False
    assert settings.retrieval_candidate_k == 32
    assert settings.retrieval_top_k == 12
    assert settings.retrieval_score_threshold == 0.25
    assert settings.hybrid_rrf_k == 40
    assert settings.hybrid_weight_vector == 0.4
    assert settings.hybrid_weight_keyword == 0.4
    assert settings.hybrid_weight_metadata == 0.2
    assert settings.evidence_min_fusion_score == 0.2
    assert settings.fts_language == "simple"

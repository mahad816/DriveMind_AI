"""Tests for embedding-related settings."""

from app.core.config import Settings
from app.embeddings.openai_service import DEFAULT_EMBEDDING_MODEL


def test_settings_include_embedding_fields() -> None:
    """Settings model should expose OpenAI embedding env fields."""
    settings = Settings(
        openai_api_key="sk-test-key",
        embedding_model="text-embedding-3-large",
    )
    assert settings.openai_api_key == "sk-test-key"
    assert settings.embedding_model == "text-embedding-3-large"


def test_settings_embedding_defaults() -> None:
    """Embedding settings should default to the MVP OpenAI model."""
    settings = Settings()
    assert settings.openai_api_key == ""
    assert settings.embedding_model == DEFAULT_EMBEDDING_MODEL

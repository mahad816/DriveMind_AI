"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime settings for the backend service."""

    app_name: str = "DriveMind AI"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"
    # Storage isolation is provided by a dedicated demo environment, never by user ID alone.
    demo_mode: bool = False
    # Validate only when resolving demo identity; normal mode does not require this value.
    demo_user_id: str = ""
    demo_chat_max_question_chars: int = Field(default=4000, ge=1)
    demo_chat_max_body_bytes: int = Field(default=131072, ge=1)
    demo_chat_concurrency: int = Field(default=2, ge=1)
    demo_chat_rate_limit: int = Field(default=20, ge=1, le=10000)
    demo_chat_rate_window_seconds: int = Field(default=60, ge=1)

    # Backend-only explicit authorization plus an offline nonsecret target fingerprint.
    indexing_enabled: bool = False
    indexing_activation_target: str = ""
    indexing_database_schema: str = "public"
    indexing_poll_seconds: float = Field(default=1.0, ge=0.05, le=30, allow_inf_nan=False)
    indexing_classifier_seconds: float = Field(default=5.0, ge=0.05, le=60, allow_inf_nan=False)
    indexing_dependency_seconds: float = Field(default=5.0, ge=0.05, le=60, allow_inf_nan=False)
    indexing_dependency_timeout: float = Field(default=5.0, ge=0.05, le=30, allow_inf_nan=False)
    indexing_startup_timeout: float = Field(default=30.0, ge=0.05, le=60, allow_inf_nan=False)
    indexing_drain_seconds: float = Field(default=20.0, ge=0.01, le=60, allow_inf_nan=False)
    indexing_cleanup_seconds: float = Field(default=5.0, ge=0.01, le=60, allow_inf_nan=False)

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://drivemind:drivemind@localhost:5432/drivemind"

    # Inactive until same-origin callback registration and authorization rollout are reviewed.
    google_application_sessions_enabled: bool = False
    google_session_redirect_uri: str = ""
    # Optional, backend-only; parsed only when the inactive crypto component is invoked.
    google_credential_encryption_keyring: SecretStr | None = Field(
        default=None, repr=False, exclude=True
    )
    google_credential_encryption_active_key_id: str = Field(default="", repr=False, exclude=True)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    google_drive_scopes: str = "https://www.googleapis.com/auth/drive.readonly"

    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "drivemind_chunks"
    qdrant_upsert_batch_size: int = 100

    hybrid_retrieval_enabled: bool = True
    retrieval_candidate_k: int = 24
    retrieval_top_k: int = 8
    retrieval_score_threshold: float = 0.35
    hybrid_rrf_k: int = 60
    hybrid_weight_vector: float = 0.5
    hybrid_weight_keyword: float = 0.3
    hybrid_weight_metadata: float = 0.2
    evidence_min_fusion_score: float = 0.15
    fts_language: str = "english"
    rag_max_context_chars: int = 12000

    tool_rag_agent_enabled: bool = False
    agent_graph_enabled: bool = False
    agent_max_rewrite_attempts: int = 2

    frontend_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=(
            str(REPO_ROOT / ".env"),
            str(BACKEND_ROOT / ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=True,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings to avoid reloading env repeatedly."""
    return Settings()

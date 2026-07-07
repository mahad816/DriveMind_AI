"""Application configuration loaded from environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    """Runtime settings for the backend service."""

    app_name: str = "DriveMind AI"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://drivemind:drivemind@localhost:5432/drivemind"

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    google_drive_scopes: str = "https://www.googleapis.com/auth/drive.readonly"

    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"

    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "drivemind_chunks"
    qdrant_upsert_batch_size: int = 100

    retrieval_top_k: int = 8
    retrieval_score_threshold: float = 0.35
    rag_max_context_chars: int = 12000

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

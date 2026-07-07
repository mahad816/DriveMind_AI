"""Tests for Google OAuth token model (Phase 3 Milestone 1)."""

from app.db.base import Base
from app.db.models import GoogleOAuthToken


def test_google_oauth_token_table_is_registered() -> None:
    """OAuth token table should be present in SQLAlchemy metadata."""
    assert "google_oauth_tokens" in Base.metadata.tables


def test_google_oauth_token_has_unique_user_constraint() -> None:
    """Each user should have at most one OAuth token row (MVP single-user design)."""
    table = GoogleOAuthToken.__table__
    unique_columns = {col.name for col in table.columns if col.unique}
    assert "user_id" in unique_columns

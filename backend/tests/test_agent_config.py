"""Tests for LangGraph agent settings."""

from app.core.config import Settings


def test_settings_agent_defaults() -> None:
    """Agent graph flags should default to safe Phase 7 fallback values."""
    fields = Settings.model_fields
    assert fields["agent_graph_enabled"].default is False
    assert fields["agent_max_rewrite_attempts"].default == 2


def test_settings_accepts_custom_agent_env_values() -> None:
    """Agent settings should load from environment overrides."""
    settings = Settings(
        agent_graph_enabled=True,
        agent_max_rewrite_attempts=3,
    )
    assert settings.agent_graph_enabled is True
    assert settings.agent_max_rewrite_attempts == 3

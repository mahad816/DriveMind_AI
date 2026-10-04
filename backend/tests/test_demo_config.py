"""Tests for the explicit backend demo-mode configuration foundation."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def ignore_local_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep configuration tests independent of local credentials and demo flags."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("DEMO_USER_ID", raising=False)


def test_demo_mode_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)

    assert Settings.model_fields["demo_mode"].default is False
    assert Settings().demo_mode is False


@pytest.mark.parametrize("value, expected", [("true", True), ("false", False)])
def test_demo_mode_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: bool
) -> None:
    monkeypatch.setenv("DEMO_MODE", value)

    assert Settings().demo_mode is expected


def test_invalid_demo_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "invalid-mode")

    with pytest.raises(ValidationError) as exc_info:
        Settings()

    assert exc_info.value.errors()[0]["loc"] == ("demo_mode",)


def test_demo_flag_does_not_replace_normal_configuration() -> None:
    normal = Settings(
        demo_mode=False,
        database_url="postgresql+asyncpg://test:test@localhost/test",
        qdrant_collection="test_chunks",
        google_client_id="test-client",
        google_client_secret="test-secret",
    )
    demo = Settings(**{**normal.model_dump(), "demo_mode": True})

    normal_values = normal.model_dump()
    demo_values = demo.model_dump()
    assert normal_values.pop("demo_mode") is False
    assert demo_values.pop("demo_mode") is True
    assert demo_values == normal_values


def test_demo_identity_configuration_is_optional_and_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().demo_user_id == ""
    monkeypatch.setenv("DEMO_USER_ID", "00000000-0000-4000-8000-000000000001")

    assert Settings().demo_user_id == "00000000-0000-4000-8000-000000000001"


def test_demo_identity_validation_is_deferred_until_resolution() -> None:
    assert Settings(demo_mode=False, demo_user_id="invalid-id").demo_user_id == "invalid-id"
    assert Settings(demo_mode=True).demo_user_id == ""

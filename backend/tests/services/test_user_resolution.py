"""Focused tests for active-user resolution without demo OAuth or owner fallback."""

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.db.models.google_oauth_token import GoogleOAuthToken
from app.db.models.user import User
from app.services.user_resolution import DemoIdentityError, resolve_active_user

DEMO_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


@pytest.fixture(autouse=True)
def isolate_demo_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("DEMO_USER_ID", raising=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("demo_user_id", ["", "invalid-unused-id"])
async def test_normal_mode_preserves_first_oauth_token_resolution(demo_user_id: str) -> None:
    db = AsyncMock()
    owner = User(id=OWNER_ID, email="owner@example.test", google_id="normal-user")
    db.scalar.return_value = GoogleOAuthToken(user_id=OWNER_ID, access_token="test-token")
    db.get.return_value = owner

    result = await resolve_active_user(db, Settings(demo_mode=False, demo_user_id=demo_user_id))

    assert result is owner
    db.scalar.assert_awaited_once()
    statement = db.scalar.await_args.args[0]
    assert "google_oauth_tokens" in str(statement)
    assert statement.compile().params["param_1"] == 1
    db.get.assert_awaited_once_with(User, OWNER_ID)


@pytest.mark.asyncio
async def test_normal_explicit_user_needs_no_oauth_token() -> None:
    db = AsyncMock()
    user = User(id=OWNER_ID, email="user@example.test", google_id="explicit-user")
    db.get.return_value = user

    assert await resolve_active_user(db, Settings(demo_mode=False), OWNER_ID) is user
    db.get.assert_awaited_once_with(User, OWNER_ID)
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "explicit, token_exists, message",
    [
        (True, False, "User not found"),
        (False, False, "No Google Drive connection found. Complete OAuth first."),
        (False, True, "Connected Google account has no user record"),
    ],
)
async def test_normal_errors_are_preserved(
    explicit: bool, token_exists: bool, message: str
) -> None:
    db = AsyncMock()
    db.get.return_value = None
    db.scalar.return_value = (
        GoogleOAuthToken(user_id=OWNER_ID, access_token="test-token") if token_exists else None
    )

    with pytest.raises(ValueError) as exc_info:
        await resolve_active_user(db, Settings(demo_mode=False), OWNER_ID if explicit else None)

    assert str(exc_info.value) == message
    if explicit:
        db.scalar.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("requested_id", [None, DEMO_ID])
async def test_demo_resolves_only_designated_user_without_oauth(
    requested_id: uuid.UUID | None,
) -> None:
    db = AsyncMock()
    demo_user = User(id=DEMO_ID, email="demo@example.test", google_id="demo-identity")
    db.get.return_value = demo_user
    db.scalar.side_effect = AssertionError("Demo must not query OAuth or first-user fallback")

    result = await resolve_active_user(
        db, Settings(demo_mode=True, demo_user_id=str(DEMO_ID)), requested_id
    )

    assert result is demo_user
    db.get.assert_awaited_once_with(User, DEMO_ID)
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_id", ["", "   ", "invalid-id"])
@pytest.mark.parametrize("requested_id", [None, OWNER_ID])
async def test_missing_or_invalid_demo_identity_cannot_fall_back(
    configured_id: str, requested_id: uuid.UUID | None
) -> None:
    db = AsyncMock()

    with pytest.raises(DemoIdentityError, match="Demo identity unavailable") as exc_info:
        await resolve_active_user(
            db, Settings(demo_mode=True, demo_user_id=configured_id), requested_id
        )

    assert "invalid-id" not in str(exc_info.value)
    db.get.assert_not_awaited()
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonexistent_demo_identity_cannot_fall_back() -> None:
    db = AsyncMock()
    db.get.return_value = None

    with pytest.raises(DemoIdentityError, match="configured demo User does not exist"):
        await resolve_active_user(db, Settings(demo_mode=True, demo_user_id=str(DEMO_ID)))

    db.get.assert_awaited_once_with(User, DEMO_ID)
    db.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_owner_id_cannot_override_demo_identity() -> None:
    db = AsyncMock()

    with pytest.raises(DemoIdentityError, match="requested user differs from demo user"):
        await resolve_active_user(db, Settings(demo_mode=True, demo_user_id=str(DEMO_ID)), OWNER_ID)

    db.get.assert_not_awaited()
    db.scalar.assert_not_awaited()

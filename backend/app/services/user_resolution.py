"""Active user resolution for normal mode and explicit OAuth-free demo identity."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.user import User


class DemoIdentityError(ValueError):
    """Demo identity is unavailable or misconfigured; normal fallback is forbidden."""


async def resolve_active_user(
    db: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID | None = None,
) -> User:
    """Resolve the configured demo user, or the explicitly named owner in normal mode.

    Normal mode never infers an owner: a missing or non-UUID ``user_id`` raises ``ValueError``
    before any database read. This selects an identity; it does not provide corpus or
    multi-user isolation. Demo storage must be isolated independently.
    """
    if settings.demo_mode:
        configured_id = settings.demo_user_id.strip()
        if not configured_id:
            raise DemoIdentityError("Demo identity unavailable: DEMO_USER_ID is required")
        try:
            demo_user_id = uuid.UUID(configured_id)
        except ValueError as exc:
            raise DemoIdentityError(
                "Demo identity unavailable: DEMO_USER_ID must be a UUID"
            ) from exc
        if user_id is not None and user_id != demo_user_id:
            raise DemoIdentityError(
                "Demo identity unavailable: requested user differs from demo user"
            )
        user = await db.get(User, demo_user_id)
        if user is None:
            raise DemoIdentityError(
                "Demo identity unavailable: configured demo User does not exist"
            )
        return user

    if not isinstance(user_id, uuid.UUID):
        raise ValueError("An explicit corpus owner is required")
    user = await db.get(User, user_id)
    if user is None:
        raise ValueError("User not found")
    return user

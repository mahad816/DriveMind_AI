"""Shared API dependencies for runtime operation boundaries."""

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings


def require_normal_mode(settings: Settings = Depends(get_settings)) -> None:
    """Reject setup and indexing operations in the public demo runtime."""
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation is unavailable in public demo mode.",
        )

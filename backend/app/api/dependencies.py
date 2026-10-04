"""Shared API dependencies for runtime operation boundaries."""

from fastapi import Depends, HTTPException, status

from app.core.config import Settings, get_settings
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.demo.service import DemoCorpusService


def require_normal_mode(settings: Settings = Depends(get_settings)) -> None:
    """Reject setup and indexing operations in the public demo runtime."""
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation is unavailable in public demo mode.",
        )


async def require_demo_index(
    settings: Settings = Depends(get_settings), db: AsyncSession = Depends(get_db)
) -> None:
    """Do not serve globally retrieved evidence from unapproved or incomplete demo storage."""
    if not settings.demo_mode:
        return
    try:
        ready = await DemoCorpusService(db, settings).is_ready()
    except Exception:
        ready = False
    if not ready:
        raise HTTPException(status_code=503, detail="The sample knowledge base is unavailable.")

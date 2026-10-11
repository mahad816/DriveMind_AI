"""Shared API dependencies for runtime operation boundaries."""

from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from app.core.config import Settings, get_settings
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.demo.service import DemoCorpusService
from app.api.session_dependencies import require_application_principal, require_session_mutation
from app.services.application_session_service import ApplicationSessionService


def require_normal_mode(settings: Settings = Depends(get_settings)) -> None:
    """Reject setup and indexing operations in the public demo runtime."""
    if settings.demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This operation is unavailable in public demo mode.",
        )


async def require_index_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    _normal: None = Depends(require_normal_mode),
) -> UUID:
    """Verify identity before mutation protection, keeping unauthenticated errors 401."""
    service = ApplicationSessionService(db, settings)
    await require_application_principal(request, service)
    principal = await require_session_mutation(request, service)
    if settings.demo_user_id and str(principal.corpus_user_id) == settings.demo_user_id:
        raise HTTPException(401, "A normal Google account session is required.")
    return principal.corpus_user_id


async def require_demo_index(
    request: Request, settings: Settings = Depends(get_settings), db: AsyncSession = Depends(get_db)
) -> None:
    """Do not serve globally retrieved evidence from unapproved or incomplete demo storage."""
    if not settings.demo_mode:
        return
    try:
        ready = await DemoCorpusService(
            db, settings, readiness_client=request.app.state.demo_readiness_client
        ).is_ready()
    except Exception:
        ready = False
    if not ready:
        raise HTTPException(status_code=503, detail="The sample knowledge base is unavailable.")


async def require_resource_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    _demo_admission: None = Depends(require_demo_index),
) -> UUID:
    """Authorize a private read, or an admitted anonymous synthetic-corpus read."""
    if settings.demo_mode:
        # Admission verified the configured identity and the entire isolated corpus.
        try:
            return UUID(settings.demo_user_id)
        except ValueError:
            raise HTTPException(503, "The sample knowledge base is unavailable.") from None

    principal = await require_application_principal(
        request, ApplicationSessionService(db, settings)
    )
    return principal.corpus_user_id

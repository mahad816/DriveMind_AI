"""Reusable dependencies, deliberately NOT attached to any current route."""

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.security.principal import ApplicationPrincipal
from app.security.session_helpers import (
    InvalidApplicationSession,
    InvalidSessionRequest,
    SessionSecurityConfigurationError,
    SessionStoreUnavailable,
    session_cookie_policy,
    verify_origin,
)
from app.services.application_session_service import ApplicationSessionService


def get_application_session_service(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ApplicationSessionService:
    return ApplicationSessionService(db, settings)


def _safe_error(error: Exception) -> HTTPException:
    if isinstance(error, InvalidApplicationSession):
        return HTTPException(401, str(error))
    if isinstance(error, InvalidSessionRequest):
        return HTTPException(403, str(error))
    return HTTPException(503, "Application sessions are temporarily unavailable.")


async def require_application_principal(
    request: Request,
    service: ApplicationSessionService = Depends(get_application_session_service),
) -> ApplicationPrincipal:
    try:
        policy = session_cookie_policy(service.settings)
        return await service.resolve_principal(request.cookies.get(policy.name))
    except (
        InvalidApplicationSession,
        SessionStoreUnavailable,
        SessionSecurityConfigurationError,
    ) as exc:
        raise _safe_error(exc) from None


async def require_session_mutation(
    request: Request,
    service: ApplicationSessionService = Depends(get_application_session_service),
) -> ApplicationPrincipal:
    try:
        origins = request.headers.getlist("origin")
        if len(origins) != 1:
            raise InvalidSessionRequest()
        verify_origin(origins[0], service.settings)
        policy = session_cookie_policy(service.settings)
        csrf_tokens = request.headers.getlist("x-csrf-token")
        if len(csrf_tokens) != 1:
            raise InvalidSessionRequest()
        return await service.verify_csrf(request.cookies.get(policy.name), csrf_tokens[0])
    except (
        InvalidApplicationSession,
        InvalidSessionRequest,
        SessionStoreUnavailable,
        SessionSecurityConfigurationError,
    ) as exc:
        raise _safe_error(exc) from None

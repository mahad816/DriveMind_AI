"""Inactive-by-default session login endpoints; existing private APIs are untouched."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.session_dependencies import require_application_principal, require_session_mutation
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.security.principal import ApplicationPrincipal
from app.security.session_helpers import (
    InvalidApplicationSession,
    InvalidSessionRequest,
    SessionSecurityConfigurationError,
    SessionStoreUnavailable,
    clear_session_cookie,
    session_cookie_policy,
    set_session_cookie,
    verify_origin,
)
from app.services.application_session_service import ApplicationSessionService
from app.services.google_session_auth_service import (
    GoogleAuthIntent,
    GoogleLoginRejected,
    GoogleSessionAuthService,
    validate_session_login_configuration,
)


def require_session_login_enabled(settings: Settings = Depends(get_settings)) -> None:
    if not settings.google_application_sessions_enabled:
        raise HTTPException(404, "Not found")
    if settings.demo_mode:
        raise HTTPException(403, "Google login is unavailable in demo mode.")
    try:
        validate_session_login_configuration(settings)
    except SessionSecurityConfigurationError:
        raise HTTPException(503, "Application login is not configured.") from None


router = APIRouter(prefix="/auth/session", dependencies=[Depends(require_session_login_enabled)])


def get_google_session_service(
    db: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> GoogleSessionAuthService:
    return GoogleSessionAuthService(db, settings)


def _uncached(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"
    return response


def _binding_cookie(
    response: Response,
    settings: Settings,
    *,
    value: str,
    expires: datetime | None = None,
    max_age: int | None = None,
) -> None:
    # Binding uses the same host-only policy as the shared application credential.
    policy = session_cookie_policy(settings)
    response.set_cookie(
        policy.name + "-oauth",
        httponly=True,
        secure=policy.secure,
        samesite="lax",
        path="/",
        value=value,
        expires=expires,
        max_age=max_age,
    )


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (SessionStoreUnavailable, SQLAlchemyError)):
        return HTTPException(503, "Application login is temporarily unavailable.")
    if isinstance(exc, InvalidSessionRequest):
        return HTTPException(403, str(exc))
    if isinstance(exc, InvalidApplicationSession):
        return HTTPException(401, str(exc))
    return HTTPException(400, "Google login could not be verified. Please start again.")


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    intent: GoogleAuthIntent


@router.post("/google")
async def start_google_login(
    request: Request,
    body: LoginRequest,
    service: GoogleSessionAuthService = Depends(get_google_session_service),
) -> Response:
    try:
        origins = request.headers.getlist("origin")
        if len(origins) != 1 or request.headers.getlist("x-drivemind-auth") != ["1"]:
            raise InvalidSessionRequest()
        verify_origin(origins[0], service.settings)
        if body.intent == GoogleAuthIntent.CONNECT_DRIVE:
            await require_session_mutation(
                request, ApplicationSessionService(service.db, service.settings)
            )
        policy = session_cookie_policy(service.settings)
        started = await service.start(body.intent, request.cookies.get(policy.name))
        response = JSONResponse({"authorization_url": started.authorization_url})
        _binding_cookie(
            response,
            service.settings,
            value=started.browser_binding.get_secret_value(),
            expires=started.expires_at,
        )
        return _uncached(response)
    except (
        InvalidApplicationSession,
        InvalidSessionRequest,
        GoogleLoginRejected,
        SessionStoreUnavailable,
        SQLAlchemyError,
    ) as exc:
        raise _error(exc) from None


@router.get("/google/callback")
async def google_session_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    service: GoogleSessionAuthService = Depends(get_google_session_service),
) -> Response:
    policy = session_cookie_policy(service.settings)
    try:
        issued = await service.callback(
            code=code or "",
            state=state,
            binding=request.cookies.get(policy.name + "-oauth"),
            credential=request.cookies.get(policy.name),
        )
    except (
        InvalidApplicationSession,
        GoogleLoginRejected,
        SessionStoreUnavailable,
        SQLAlchemyError,
    ) as exc:
        # Public responses never include token errors, provider payloads or credentials.
        failure = _error(exc)
        error_response = JSONResponse({"detail": failure.detail}, status_code=failure.status_code)
        _binding_cookie(error_response, service.settings, value="", max_age=0)
        return _uncached(error_response)
    response = Response(
        status_code=303,
        headers={"Location": service.settings.frontend_url.rstrip("/") + "/settings?login=success"},
    )
    set_session_cookie(
        response,
        credential=issued.credential,
        expires_at=issued.expires_at,
        settings=service.settings,
    )
    _binding_cookie(response, service.settings, value="", max_age=0)
    return _uncached(response)


@router.get("")
async def inspect_session(
    request: Request,
    principal: ApplicationPrincipal = Depends(require_application_principal),
    service: GoogleSessionAuthService = Depends(get_google_session_service),
) -> Response:
    try:
        policy = session_cookie_policy(service.settings)
        token = await ApplicationSessionService(service.db, service.settings).csrf_token(
            request.cookies.get(policy.name)
        )
        return _uncached(
            JSONResponse(
                {
                    "kind": principal.kind,
                    "user_id": str(principal.authenticated_user_id),
                    "csrf_token": token.get_secret_value(),
                }
            )
        )
    except (InvalidApplicationSession, SessionStoreUnavailable) as exc:
        raise _error(exc) from None


@router.post("/logout")
async def logout(
    request: Request,
    principal: ApplicationPrincipal = Depends(require_session_mutation),
    service: GoogleSessionAuthService = Depends(get_google_session_service),
) -> Response:
    try:
        policy = session_cookie_policy(service.settings)
        if not await ApplicationSessionService(service.db, service.settings).revoke(
            request.cookies.get(policy.name)
        ):
            raise InvalidApplicationSession()
        await service.db.commit()
    except (InvalidApplicationSession, SessionStoreUnavailable, SQLAlchemyError) as exc:
        await service.db.rollback()
        raise _error(exc) from None
    response = Response(status_code=204)
    clear_session_cookie(response, settings=service.settings)
    return _uncached(response)

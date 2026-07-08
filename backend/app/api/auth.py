"""Google OAuth authentication routes."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.google_oauth_service import GoogleOAuthService

router = APIRouter(prefix="/auth")


def get_oauth_service(db: AsyncSession = Depends(get_db)) -> GoogleOAuthService:
    """Dependency provider for Google OAuth service."""
    return GoogleOAuthService(db=db)


def _wants_json_response(request: Request) -> bool:
    """Return True when the caller explicitly requests a JSON payload."""
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def _frontend_settings_url(settings: Settings, **query: str) -> str:
    """Build a frontend settings URL with optional query parameters."""
    base = settings.frontend_url.rstrip("/")
    if not query:
        return f"{base}/settings"
    return f"{base}/settings?{urlencode(query)}"


@router.get("/google", summary="Start Google OAuth login")
async def google_login(
    service: GoogleOAuthService = Depends(get_oauth_service),
) -> RedirectResponse:
    """Redirect user to Google OAuth consent screen."""
    try:
        authorization_url = await service.create_authorization_url()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return RedirectResponse(url=authorization_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get(
    "/google/callback",
    summary="Google OAuth callback",
    response_model=None,
)
async def google_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service: GoogleOAuthService = Depends(get_oauth_service),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse | dict[str, str]:
    """Handle Google OAuth callback and persist tokens."""
    if not code:
        if _wants_json_response(request):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing OAuth authorization code",
            )
        return RedirectResponse(
            url=_frontend_settings_url(settings, error="missing_oauth_code"),
            status_code=status.HTTP_302_FOUND,
        )

    try:
        result = await service.handle_callback(code=code, state=state)
    except ValueError as exc:
        if _wants_json_response(request):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        return RedirectResponse(
            url=_frontend_settings_url(settings, error=str(exc)),
            status_code=status.HTTP_302_FOUND,
        )

    payload = {
        "status": "ok",
        "message": "Google Drive connected successfully",
        "user_id": str(result.user_id),
        "email": result.email,
    }
    if _wants_json_response(request):
        return payload

    return RedirectResponse(
        url=_frontend_settings_url(
            settings,
            connected="true",
            email=result.email,
        ),
        status_code=status.HTTP_302_FOUND,
    )

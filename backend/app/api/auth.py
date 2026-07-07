"""Google OAuth authentication routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services.google_oauth_service import GoogleOAuthService

router = APIRouter(prefix="/auth")


def get_oauth_service(db: AsyncSession = Depends(get_db)) -> GoogleOAuthService:
    """Dependency provider for Google OAuth service."""
    return GoogleOAuthService(db=db)


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


@router.get("/google/callback", summary="Google OAuth callback")
async def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    service: GoogleOAuthService = Depends(get_oauth_service),
) -> dict[str, str]:
    """Handle Google OAuth callback and persist tokens."""
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing OAuth authorization code",
        )
    try:
        result = await service.handle_callback(code=code, state=state)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {
        "status": "ok",
        "message": "Google Drive connected successfully",
        "user_id": str(result.user_id),
        "email": result.email,
    }

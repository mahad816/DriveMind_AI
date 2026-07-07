"""Health check endpoints."""

from fastapi import APIRouter, HTTPException, status

from app.db.session import check_db_connection

router = APIRouter(prefix="/health")


@router.get("", summary="Liveness check")
async def health_check() -> dict[str, str]:
    """Simple liveness endpoint used by orchestration and monitoring."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness check")
async def readiness_check() -> dict[str, str]:
    """Readiness endpoint that verifies database connectivity."""
    is_connected = await check_db_connection()
    if not is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not reachable",
        )
    return {"status": "ok", "database": "connected"}

"""Health check endpoints."""

from fastapi import APIRouter, HTTPException, Request, status

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


@router.get("/indexing", summary="Indexing executor diagnostic state")
async def indexing_health(request: Request) -> dict[str, str]:
    """Separate from chat/general readiness; no job, claim or worker identifiers."""
    supervisor = getattr(request.app.state, "indexing_supervisor", None)
    result = {
        "status": supervisor.health.lower() if supervisor is not None else "inactive",
        "admission": "available"
        if supervisor is not None
        and supervisor.healthy
        and getattr(request.app.state, "indexing_admission_ready", False) is True
        else "closed",
    }
    reason = (
        supervisor.failure_reason
        if supervisor is not None
        else getattr(request.app.state, "indexing_activation_error", None)
    )
    if reason is not None:
        result["reason"] = reason
    return result

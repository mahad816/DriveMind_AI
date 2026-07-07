"""Health check endpoints."""

from fastapi import APIRouter

router = APIRouter(prefix="/health")


@router.get("", summary="Liveness check")
async def health_check() -> dict[str, str]:
    """Simple liveness endpoint used by orchestration and monitoring."""
    return {"status": "ok"}

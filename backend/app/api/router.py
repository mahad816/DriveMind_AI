"""API router aggregation for versioned endpoints."""

from fastapi import APIRouter

from app.api.health import router as health_router

router = APIRouter()
router.include_router(health_router, tags=["health"])

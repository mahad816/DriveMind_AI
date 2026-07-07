"""API router aggregation for versioned endpoints."""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.health import router as health_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(auth_router, tags=["auth"])

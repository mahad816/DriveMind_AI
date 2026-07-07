"""API router aggregation for versioned endpoints."""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.index import router as index_router
from app.api.sources import router as sources_router

router = APIRouter()
router.include_router(health_router, tags=["health"])
router.include_router(auth_router, tags=["auth"])
router.include_router(index_router, tags=["index"])
router.include_router(files_router, tags=["files"])
router.include_router(chat_router, tags=["chat"])
router.include_router(sources_router, tags=["sources"])

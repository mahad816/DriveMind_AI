"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from sqlalchemy import text

from app.api.router import router as api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine

logger = logging.getLogger(__name__)


async def _cleanup_stuck_jobs() -> None:
    """Mark any RUNNING jobs left over from a previous process as FAILED.

    Background tasks that were interrupted by a server restart never get the
    chance to update their own status, so they stay RUNNING forever.  Polling
    clients will wait on them indefinitely unless we clean them up at startup.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            text(
                "UPDATE indexing_jobs"
                " SET status = 'FAILED',"
                "     error  = 'Server restarted while job was running',"
                "     completed_at = now()"
                " WHERE status = 'RUNNING' AND completed_at IS NULL"
            )
        )
        await db.commit()
        if result.rowcount:
            logger.warning("Cleaned up %d stuck RUNNING job(s) on startup", result.rowcount)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize application-level resources during startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    await _cleanup_stuck_jobs()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Application factory for uvicorn and tests."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()

"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.router import router as api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine
from app.core.public_safety import DemoChatBodyLimit, DemoChatLimits, PUBLIC_ERROR

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
        cleaned = int(getattr(result, "rowcount", 0) or 0)
        if cleaned:
            logger.warning("Cleaned up %d stuck RUNNING job(s) on startup", cleaned)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize application-level resources during startup."""
    settings = get_settings()
    configure_logging(settings.log_level)
    # Demo indexing is offline; public runtime startup must not mutate index jobs.
    if not settings.demo_mode:
        await _cleanup_stuck_jobs()
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Application factory for uvicorn and tests."""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug and not settings.demo_mode,
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    app.state.demo_chat_limits = DemoChatLimits()
    app.add_middleware(DemoChatBodyLimit)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled API failure", exc_info=exc)
        return JSONResponse(status_code=500, content={"detail": PUBLIC_ERROR})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        current = get_settings()
        if not current.demo_mode and current.debug:
            return await request_validation_exception_handler(request, exc)
        # Never echo submitted secrets or entire oversized input into public errors.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
                    for error in exc.errors()
                ]
            },
        )

    return app


app = create_app()

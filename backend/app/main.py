"""FastAPI application entrypoint."""

import asyncio
import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.router import router as api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal, engine, google_refresh_lifecycle
from app.demo.readiness_client import DemoReadinessClient
from app.core.public_safety import (
    public_error_detail,
    DemoChatBodyLimit,
    DemoChatLimits,
    PUBLIC_ERROR,
)

from app.services.indexing_lifecycle import DisposableIndexingRuntime, IndexingSupervisor
from app.services.indexing_runtime import (
    NormalIndexingRuntime,
    create_normal_runtime,
    IndexingActivationError,
)

logger = logging.getLogger(__name__)


async def _cleanup_stuck_jobs() -> None:
    """Clean historical unmanaged RUNNING jobs only.

    Background tasks that were interrupted by a server restart never get the
    chance to update their own status, so they stay RUNNING forever.  Polling
    clients will wait on them indefinitely unless we clean them up at startup.
    Managed claims may belong to another live process; 4E3 owns their recovery.
    """
    async with SessionLocal() as db:
        result = await db.execute(
            text(
                "UPDATE indexing_jobs"
                " SET status = 'FAILED',"
                "     error  = 'Server restarted while job was running',"
                "     completed_at = now()"
                " WHERE status = 'RUNNING' AND completed_at IS NULL AND operation IS NULL"
            )
        )
        await db.commit()
        cleaned = int(getattr(result, "rowcount", 0) or 0)
        if cleaned:
            logger.warning("Cleaned up %d stuck RUNNING job(s) on startup", cleaned)


@asynccontextmanager
async def lifespan(
    app: FastAPI,
    *,
    runtime: DisposableIndexingRuntime | NormalIndexingRuntime | None = None,
    configuration: Settings | None = None,
    sessions: async_sessionmaker[AsyncSession] | None = None,
) -> AsyncIterator[None]:
    """Initialize application-level resources during startup."""
    if runtime is not None and not isinstance(runtime, DisposableIndexingRuntime):
        raise ValueError("Only validated disposable runtimes may be injected")
    settings = runtime.worker.settings if runtime else configuration or get_settings()
    if runtime is not None or settings.indexing_enabled:
        if app.state.indexing_lifecycle_started:
            raise RuntimeError("Indexing application lifecycle cannot start twice")
        app.state.indexing_lifecycle_started = True
    app.state.indexing_admission_ready = False
    supervisor = None
    configure_logging(settings.log_level)
    try:
        if settings.indexing_enabled and runtime is None:
            try:
                async with asyncio.timeout(settings.indexing_startup_timeout):
                    runtime = await create_normal_runtime(
                        sessions if sessions is not None else SessionLocal,
                        app.state.google_refresh_lifecycle,
                        settings,
                    )
            except IndexingActivationError as exc:
                app.state.indexing_activation_error = exc.code
                raise
            except TimeoutError:
                app.state.indexing_activation_error = "STARTUP_VALIDATION_TIMEOUT"
                raise IndexingActivationError("STARTUP_VALIDATION_TIMEOUT") from None
        # Demo indexing is offline; public runtime startup must not mutate index jobs.
        if not settings.demo_mode:
            if runtime is None:
                await _cleanup_stuck_jobs()
            else:
                supervisor = IndexingSupervisor(runtime)
                app.state.indexing_supervisor = supervisor
                await supervisor.start()
                app.state.indexing_admission_ready = True
        yield
    finally:
        app.state.indexing_admission_ready = False
        try:
            if runtime is None:
                await app.state.google_refresh_lifecycle.shutdown_and_dispose(engine.dispose)
            else:
                if supervisor is not None:
                    supervisor.begin_shutdown()

                async def finish() -> None:
                    if supervisor is not None:
                        await supervisor.wait_closed()
                    await app.state.google_refresh_lifecycle.shutdown_and_dispose(
                        runtime.engine.dispose
                    )

                # Strong application ownership survives cancellation or the bounded
                # lifespan deadline. SQL cleanup must finish before engine disposal.
                task = asyncio.create_task(finish(), name="indexing-resource-disposal")
                app.state.indexing_disposal_task = task

                def observed(done: asyncio.Task[None]) -> None:
                    if done.cancelled() or done.exception() is not None:
                        logger.error("Indexing resource cleanup is incomplete.")

                task.add_done_callback(observed)
                done, _ = await asyncio.wait(
                    [task], timeout=runtime.drain_seconds + runtime.cleanup_seconds
                )
                if task in done:
                    await asyncio.shield(task)
                else:
                    logger.warning("Indexing cleanup is deferred; database remains available.")
        finally:
            await app.state.demo_readiness_client.close()


def create_app(*, indexing_test_runtime: DisposableIndexingRuntime | None = None) -> FastAPI:
    """Application factory for uvicorn and tests."""
    if indexing_test_runtime is not None and not isinstance(
        indexing_test_runtime, DisposableIndexingRuntime
    ):
        raise ValueError("Only validated disposable runtimes may be injected")
    settings = get_settings()
    if (indexing_test_runtime is not None or settings.indexing_enabled) and settings.demo_mode:
        raise ValueError("Demo applications cannot activate a normal indexing lifecycle")
    # Runtime authority is captured by code/configuration, never read from app.state.
    normal_sessions = SessionLocal

    @asynccontextmanager
    async def owned_lifespan(application: FastAPI) -> AsyncIterator[None]:
        async with lifespan(
            application,
            runtime=indexing_test_runtime,
            configuration=settings,
            sessions=normal_sessions,
        ):
            yield

    app = FastAPI(
        title=settings.app_name,
        debug=False,  # Starlette debug tracebacks can contain credentials.
        lifespan=owned_lifespan,
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    app.state.demo_chat_limits = DemoChatLimits()
    app.state.demo_readiness_client = DemoReadinessClient()
    app.state.google_refresh_lifecycle = (
        indexing_test_runtime.refresh if indexing_test_runtime else google_refresh_lifecycle
    )
    app.state.indexing_test_runtime = (
        indexing_test_runtime  # Diagnostic only; not activation authority.
    )
    app.state.indexing_activation_error = None
    app.state.indexing_lifecycle_started = False
    app.state.indexing_supervisor = None
    app.state.indexing_disposal_task = None
    if indexing_test_runtime is not None:
        from app.db.session import get_db

        async def indexing_database() -> AsyncIterator[AsyncSession]:
            async with indexing_test_runtime.worker.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = indexing_database
        app.dependency_overrides[get_settings] = lambda: indexing_test_runtime.worker.settings
    # Default closed. Explicit normal target validation and both executor
    # handshakes must finish before this becomes true.
    app.state.indexing_admission_ready = False
    app.add_middleware(DemoChatBodyLimit)

    @app.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception) -> JSONResponse:
        public_error_detail(exc)
        return JSONResponse(status_code=500, content={"detail": PUBLIC_ERROR})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        current = get_settings()
        if (
            not current.demo_mode
            and current.debug
            and not request.url.path.startswith(f"{current.api_prefix}/auth")
        ):
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

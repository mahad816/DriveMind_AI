"""Bounded single-process demo chat admission and public error handling."""

import logging
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send, Message

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
PUBLIC_ERROR = "The service is temporarily unavailable. Please try again later."


def public_error_detail(exc: Exception) -> str:
    """Keep diagnostics in logs, not visitor-facing exception responses."""
    settings = get_settings()
    if settings.demo_mode or not settings.debug:
        logger.error("API operation failed", exc_info=exc)
        return PUBLIC_ERROR
    return str(exc)


class DemoChatLimits:
    """No waiting queue or visitor map; admission is atomic within one event loop."""

    def __init__(self) -> None:
        self.active = 0
        self.admitted: deque[float] = deque()

    @asynccontextmanager
    async def execution(self, settings: Settings) -> AsyncIterator[None]:
        if not settings.demo_mode:
            yield
            return
        now = monotonic()
        while self.admitted and self.admitted[0] <= now - settings.demo_chat_rate_window_seconds:
            self.admitted.popleft()
        if self.active >= settings.demo_chat_concurrency:
            raise HTTPException(429, "The demo is busy. Please try again shortly.")
        if len(self.admitted) >= settings.demo_chat_rate_limit:
            raise HTTPException(
                429,
                "The demo request limit was reached. Please try again shortly.",
                headers={"Retry-After": str(settings.demo_chat_rate_window_seconds)},
            )
        self.admitted.append(now)
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1


class DemoChatBodyLimit:
    """Bound chat bytes before FastAPI parses JSON, including chunked requests."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = get_settings()
        if (
            not settings.demo_mode
            or scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"].rstrip("/") != f"{settings.api_prefix}/chat"
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            data = message.get("body", b"")
            if len(body) + len(data) > settings.demo_chat_max_body_bytes:
                await JSONResponse({"detail": "Chat request is too large."}, status_code=413)(
                    scope, receive, send
                )
                return
            body.extend(data)
            if not message.get("more_body", False):
                break

        delivered = False

        async def bounded_receive() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, bounded_receive, send)

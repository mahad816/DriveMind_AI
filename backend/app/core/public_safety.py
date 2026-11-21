"""Bounded single-process demo chat admission and public error handling."""

import logging
import re
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic

from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send, Message

from app.core.config import Settings, get_settings

from app.core.credential_diagnostics import log_safe_failure

logger = logging.getLogger(__name__)
PUBLIC_ERROR = "The service is temporarily unavailable. Please try again later."
# Owner-mode request-body caps (M0-SEC ticket 06). The largest legal POST /chat request is 8 history
# turns of 8000 characters plus a 4000-character question, under about 170 KiB even with every
# character escaped; a legal turn request is a 4000-character question plus two small fields.
CHAT_MAX_BODY_BYTES = 512 * 1024
TURN_MAX_BODY_BYTES = 64 * 1024


def public_error_detail(exc: Exception) -> str:
    """Never expose provider or database details, including in debug mode."""
    log_safe_failure(logger, "API operation", exc)
    return PUBLIC_ERROR


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


class ChatBodyLimit:
    """Bound request bytes before FastAPI parses JSON, including chunked requests.

    Demo mode caps ``POST /chat`` at its own configured size. Owner mode caps ``POST /chat`` at
    ``CHAT_MAX_BODY_BYTES`` and turn creation and streaming (``/conversations/<id>/turns[/stream]``,
    a path with an identifier in it) at ``TURN_MAX_BODY_BYTES``. It is middleware, so a 413 can
    precede the 401 of a request that is both oversized and unauthenticated.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    @staticmethod
    def limit_for(settings: Settings, scope: Scope) -> int | None:
        if scope["type"] != "http" or scope["method"] != "POST":
            return None
        path = scope["path"].rstrip("/")
        prefix = settings.api_prefix
        if path == f"{prefix}/chat":
            return settings.demo_chat_max_body_bytes if settings.demo_mode else CHAT_MAX_BODY_BYTES
        if not settings.demo_mode and re.fullmatch(
            rf"{re.escape(prefix)}/conversations/[^/]+/turns(?:/stream)?", path
        ):
            return TURN_MAX_BODY_BYTES
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self.limit_for(get_settings(), scope)
        if limit is None:
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            data = message.get("body", b"")
            if len(body) + len(data) > limit:
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

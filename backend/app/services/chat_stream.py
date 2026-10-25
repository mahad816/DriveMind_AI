"""Request-local, bounded public events. Never serialize agent state or tool payloads."""

import asyncio
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextvars import ContextVar

import anyio

from app.services.conversation_service import ConversationSessionExpired

StreamSink = Callable[[str, dict[str, object]], Awaitable[None]]
stream_sink: ContextVar[StreamSink | None] = ContextVar("chat_stream_sink", default=None)


async def emit(event: str, data: dict[str, object]) -> None:
    sink = stream_sink.get()
    if sink is not None:
        await sink(event, data)


def provisional_text(text: str) -> str:
    """Withhold the trailing token and all citation/identifier syntax across chunks.

    Plain text only: links, source handles and incomplete markers cannot become
    clickable/verified sources. Final rendering always uses canonical validation.
    """
    text = text[: max(text.rfind(" "), text.rfind("\n"), text.rfind("\t")) + 1]
    text = re.sub(r"\[[^\]]*(?:\]|$)", "", text)
    text = re.sub(r"\b(?:file|source|evidence)_\w*\b", "", text, flags=re.I)
    text = re.sub(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", "", text, flags=re.I)
    return text


async def event_stream(operation: Callable[[], Awaitable[None]]) -> AsyncIterator[str]:
    """One request-owned producer; bounded backpressure, heartbeats and cancellation.

    Disconnect cancels and joins generation, allowing its existing durable cleanup
    to finish. Never reconnect/replay model generation automatically.
    """
    queue: asyncio.Queue[tuple[str, dict[str, object]] | None] = asyncio.Queue(maxsize=16)

    async def send(event: str, data: dict[str, object]) -> None:
        await queue.put((event, data))

    async def produce() -> None:
        token = stream_sink.set(send)
        try:
            await operation()
        except asyncio.CancelledError:
            raise
        except ConversationSessionExpired:
            await send(
                "error",
                {
                    "code": "SESSION_EXPIRED",
                    "message": "Your session expired. Sign in again to continue.",
                },
            )
        except Exception:
            await send(
                "error",
                {
                    "message": "The response could not be verified. Reconcile the saved attempt before trying again."
                },
            )
        finally:
            stream_sink.reset(token)
        await queue.put(None)

    task = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=10)
            except TimeoutError:
                yield ": keep-alive\n\n"
                continue
            if item is None:
                break
            event, data = item
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"
    finally:
        if not task.done():
            task.cancel()
        # Starlette's disconnect cancellation must not interrupt terminal cleanup.
        with anyio.CancelScope(shield=True):
            try:
                await task
            except asyncio.CancelledError:
                pass

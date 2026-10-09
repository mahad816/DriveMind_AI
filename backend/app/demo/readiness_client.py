"""Application-owned transport for demo verification, never a readiness cache."""

import asyncio

from qdrant_client import AsyncQdrantClient

from app.core.config import Settings
from app.embeddings.qdrant_connection import create_qdrant_client


class DemoReadinessClient:
    """One lazy client per application/event loop; requests only borrow it."""

    def __init__(self) -> None:
        self._client: AsyncQdrantClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._configuration: tuple[str, str, str, int, str] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def get(self, settings: Settings) -> AsyncQdrantClient:
        loop = asyncio.get_running_loop()
        if self._loop is not None and self._loop is not loop:
            raise RuntimeError("Demo readiness client belongs to another event loop")
        self._loop = loop
        configuration = (
            settings.qdrant_url,
            settings.qdrant_api_key,
            settings.qdrant_host,
            settings.qdrant_port,
            settings.qdrant_collection,
        )
        async with self._lock:
            if self._closed:
                raise RuntimeError("Demo readiness client is closed")
            if self._configuration is not None and self._configuration != configuration:
                raise RuntimeError("Demo readiness client configuration changed")
            if self._client is None:
                # The SDK factory is synchronous; assignment completes before another borrower.
                self._client = create_qdrant_client(settings)
                self._configuration = configuration
            return self._client

    async def close(self) -> None:
        """Close once at shutdown, after requests have finished."""
        if self._loop is not None and self._loop is not asyncio.get_running_loop():
            raise RuntimeError("Demo readiness client belongs to another event loop")
        async with self._lock:
            if not self._closed:
                self._closed = True
                if self._client is not None:
                    await self._client.close()

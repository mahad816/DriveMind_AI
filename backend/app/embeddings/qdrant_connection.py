"""Shared local or authenticated HTTPS Qdrant connection configuration, and the managed client."""

import asyncio
import logging
import threading
import weakref
from urllib.parse import urlsplit

from qdrant_client import AsyncQdrantClient

from app.core.config import Settings

logger = logging.getLogger(__name__)


def create_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    """Prefer an explicit URL; never fall back when URL configuration is invalid."""
    url = settings.qdrant_url.strip()
    key = settings.qdrant_api_key.strip()
    if not url:
        if key:
            raise ValueError("QDRANT_API_KEY requires an HTTPS QDRANT_URL")
        return AsyncQdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)

    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme in ("http", "https")
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() for char in url)
        )
        # Accessing port also validates malformed or out-of-range ports.
        _ = parsed.port
    except ValueError:
        raise ValueError("QDRANT_URL is invalid") from None
    if not valid:
        raise ValueError(
            "QDRANT_URL must be an HTTP(S) URL without credentials, query, or fragment"
        )
    if key:
        if parsed.scheme != "https":
            raise ValueError("QDRANT_API_KEY requires an HTTPS QDRANT_URL")
        return AsyncQdrantClient(url=url, port=None, api_key=key)
    # No implicit 6333 port: use the explicit URL port or the scheme's default.
    return AsyncQdrantClient(url=url, port=None)


# One client (one HTTP connection pool) per event loop and connection configuration, shared by every vector store
# that was not given a client. An AsyncQdrantClient belongs to the loop it first runs on, so it is looked up by the
# running loop and is never handed to another one. The loop is held weakly: a finished loop takes its client entry
# with it. Building a client is synchronous, so two tasks of one loop cannot both build one; the lock guards the
# registry against other threads running their own loops.
_clients: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str, str, int], AsyncQdrantClient]]" = weakref.WeakKeyDictionary()
_clients_lock = threading.Lock()


def shared_qdrant_client(settings: Settings) -> AsyncQdrantClient:
    """The managed client for the running event loop, created on first use.

    Without a running loop there is nothing safe to share with, so a fresh unmanaged client is returned (the
    behaviour before the client was managed). A construction failure raises as before and caches nothing.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return create_qdrant_client(settings)
    key = (
        settings.qdrant_url.strip(),
        settings.qdrant_api_key.strip(),
        settings.qdrant_host,
        settings.qdrant_port,
    )
    with _clients_lock:
        per_loop = _clients.setdefault(loop, {})
        client = per_loop.get(key)
        if client is None:
            client = create_qdrant_client(settings)
            per_loop[key] = client
        return client


async def close_shared_qdrant_clients() -> None:
    """Close the running loop's managed clients, at application shutdown.

    Every client is attempted even if one fails to close; the first failure is raised afterwards. The entries are
    removed first, so nothing closed is ever handed out again (a later search builds a new client). Clients of other
    loops are left to the loop that owns them.
    """
    loop = asyncio.get_running_loop()
    with _clients_lock:
        clients = list(_clients.pop(loop, {}).values())
    first_failure: Exception | None = None
    for client in clients:
        try:
            await client.close()
        except Exception as exc:
            logger.warning("A Qdrant client did not close cleanly (%s).", type(exc).__name__)
            first_failure = first_failure or exc
    if first_failure is not None:
        raise first_failure

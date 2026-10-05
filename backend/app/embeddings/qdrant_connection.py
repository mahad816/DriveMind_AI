"""Shared local or authenticated HTTPS Qdrant connection configuration."""

from urllib.parse import urlsplit

from qdrant_client import AsyncQdrantClient

from app.core.config import Settings


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

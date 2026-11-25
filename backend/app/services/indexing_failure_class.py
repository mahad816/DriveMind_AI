"""Structured failure classes for terminal indexing jobs.

A client may move past a failed document only when the backend positively recorded DOCUMENT: the failure is
specific to this document's own content. Every other value, and a missing value (older rows, startup cleanup,
admission or recovery paths), means "do not assume the next document will behave differently", so a client
must pause. Classes come from exception types and structured codes, never from message text.
"""

from __future__ import annotations

DOCUMENT = (
    "document"  # the document's own content could not be read (corrupt, unreadable, unsupported)
)
INFRASTRUCTURE = "infrastructure"  # worker crash, interruption, heartbeat or lease loss
PROVIDER = (
    "provider"  # embedding, vector store or Drive provider fault (outage, throttling, rejection)
)
AUTHENTICATION = "authentication"  # grant expired or needs reauthorization
CONFIGURATION = "configuration"  # deployment misconfiguration
UNKNOWN = "unknown"  # a failure nobody classified

FAILURE_CLASSES = frozenset(
    {DOCUMENT, INFRASTRUCTURE, PROVIDER, AUTHENTICATION, CONFIGURATION, UNKNOWN}
)

_FROM_CATEGORY = {
    "authentication_expired": AUTHENTICATION,
    "reauthorization_required": AUTHENTICATION,
    "temporary_provider_failure": PROVIDER,
    "configuration_error": CONFIGURATION,
}


def from_exception(exc: BaseException) -> str:
    """Document only for extraction failures. Everything else follows the existing structured category."""
    from app.core.credential_diagnostics import failure_category
    from app.ingestion.extractors import ExtractionError

    if isinstance(exc, ExtractionError):
        # Typed by the extractor itself: a plain ExtractionError is the document's own failure, the subclasses
        # (environment fault, unexpected fault) carry their own class. Anything outside the vocabulary is unknown.
        cause = getattr(exc, "failure_class", UNKNOWN)
        return cause if cause in FAILURE_CLASSES else UNKNOWN
    return _FROM_CATEGORY.get(failure_category(exc) if isinstance(exc, Exception) else "", UNKNOWN)


def merge(current: str | None, new: str) -> str:
    """A job that failed several files for different reasons is not specific to any one of them."""
    return new if current in (None, new) else UNKNOWN

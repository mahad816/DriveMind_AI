"""Marks the moment a question's first paid provider request is about to be sent.

The paid-question quota (``app.services.paid_question_quota``) counts an attempt only when paid
provider execution began. ``PaidExecutionMarker`` is a tiny mutable holder installed for one
attempt; ``mark_paid_started()`` is called at each provider-request chokepoint, before the request
is sent, so a timeout, cancellation or provider error during the request still counts and an SDK
retry inside one request cannot count twice. Nothing is recorded about calls, tokens or prices.

The ContextVar holds a reference to the holder, not a flag. Parallel retrievers and graph nodes run
in child tasks (``asyncio.ensure_future``) that copy the context at creation, so a change they make
to the ContextVar itself would never reach the parent; mutating the shared holder does.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar


class PaidExecutionMarker:
    """Set once, never cleared: a provider request began for this attempt."""

    def __init__(self) -> None:
        self.started = False

    def mark(self) -> None:
        self.started = True


_marker: ContextVar[PaidExecutionMarker | None] = ContextVar("paid_execution_marker", default=None)


def mark_paid_started() -> None:
    """Record that a provider request is about to be sent; a no-op without an installed marker."""
    marker = _marker.get()
    if marker is not None:
        marker.mark()


@contextmanager
def install_marker(marker: PaidExecutionMarker) -> Iterator[PaidExecutionMarker]:
    """Install ``marker`` for the current task and the child tasks it creates inside the block.

    Call it inside the work function itself (inside ``run()`` for a stream), never in a route
    function: a task created after the route returns would not inherit a route-level change.
    """
    token = _marker.set(marker)
    try:
        yield marker
    finally:
        try:
            _marker.reset(token)
        except ValueError:
            # Closed from another context (a stream torn down by the server): the holder stays
            # valid and the original exit path must not be replaced by this error.
            _marker.set(None)

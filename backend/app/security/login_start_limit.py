"""Global, process-local request limit for the unauthenticated login-start endpoint (KI-032).

``POST /auth/session/google`` with intent ``LOGIN`` needs no session, so there is no Owner to key a
limit on, and per-IP limiting cannot work while proxy headers are disabled. The limit is therefore
one sliding window for the whole process. Properties, all deliberate:

* Process-local and in memory: it resets on restart and each worker has its own window. Growth of
  the pending-state table is bounded by the prune in ``GoogleSessionAuthService.start``, so a lost
  window only loosens a limit whose purpose is to keep that growth small.
* A sustained flood above the limit can delay the Owner's own login (they receive 429 too). It can
  read or change nothing. A per-IP or edge limit is an M9 deployment decision.
* Rejected requests are not recorded, so a flood does not extend its own lockout beyond one window.
* Memory is bounded by the limit: at most ``limit`` timestamps are held.
* Check and record run with no ``await`` between them, so admission is atomic within one event loop.
* It deliberately mirrors the small deque window of ``DemoChatLimits`` instead of sharing code with it,
  to keep this ticket out of the demo path.
"""

import math
from collections import deque
from collections.abc import Callable
from time import monotonic

from fastapi import HTTPException

from app.core.config import Settings


class LoginStartLimiter:
    def __init__(self, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._admitted: deque[float] = deque()

    def admit(self, settings: Settings) -> None:
        """Record one request, or raise 429 with ``Retry-After`` when the window is full."""
        now = self._clock()
        window = settings.google_login_start_rate_window_seconds
        while self._admitted and self._admitted[0] <= now - window:
            self._admitted.popleft()
        if len(self._admitted) >= settings.google_login_start_rate_limit:
            retry_after = max(1, math.ceil(self._admitted[0] + window - now))
            raise HTTPException(
                429,
                "Too many sign-in attempts. Please try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )
        self._admitted.append(now)


login_start_limiter = LoginStartLimiter()

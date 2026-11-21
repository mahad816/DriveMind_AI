# 07: Stop login attempts from growing the database without limit (KI-032)

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** Expired Google login attempts are deleted when a new login starts, and the unauthenticated login-start endpoint has a small global request limit. Security implication (Owner decision D4-3): an unauthenticated request can create one stored row per call while sessions are enabled, with no data exposure. Storage implication: unbounded table growth.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** implemented and committed locally (2026-11-21); reviews recorded in Comments; not pushed

## Scope

- When a login starts, delete expired pending login states (existing expiry column; no schema change). A still-valid state of another browser is never deleted.
- A global (not per-Owner, not per-IP) request limit on the login-start endpoint, with a generous configurable default. It is a small process-local counter, independent of the paid-question ledger: there is no Owner to key on before sign-in, growth is already bounded by the prune, and this keeps the ticket free of the quota work. Over the limit: 429 with a retry hint, before any state row is written.
- Record the trade-off in the setting's documentation: with proxy headers disabled a per-IP limit cannot work, so a sustained flood can delay the Owner's own login but can read or change nothing; the counter resets on restart; per-IP or edge limiting is an M9 deployment decision.
- Remove the strict marker from the KI-032 test; move KI-032 to Fixed with both implications and the trade-off.

## Out of scope

Per-IP limiting, a background sweeper, a database-backed counter, schema or migration, the callback, state lifetime or PKCE, the allow-list.

## Inspect

`docs/KNOWN_ISSUES.md` KI-032; `tests/known_issues/test_ki032_pending_login_state_growth.py`; `backend/app/services/google_session_auth_service.py` (`start`, `_consume`); `google_oauth_service.py` (`_cleanup_expired_pending_states`, legacy); `backend/app/api/google_session_auth.py`; `backend/app/core/public_safety.py` (demo limiter as a style reference).

## Deliverables

Prune, limit, tests, registry move; `## Comments` with documentation items for ticket 09.

## Needs

Disposable PostgreSQL. No network.

- [x] The KI-032 strict test fails today for its registered reason and passes after the fix with its marker removed; the passing guard (a valid attempt survives another login start) still passes.
- [x] After the limit is exceeded, further login-start requests get 429 and write no row (row count asserted); after the window they work again (injected clock).
- [x] Statuses with the flag off (404), in demo mode (403) and when unconfigured (503) are unchanged; the route inventory passes.
- [x] Normal login (start then callback) still works end to end; no existing test needs more than the default or a manual reset.
- [x] No migration or schema change in this ticket.
- [x] KI-032 appears under Fixed with both implications and the lockout trade-off.

## Comments

**Where things are.** `app/security/login_start_limit.py` (`LoginStartLimiter`, process singleton `login_start_limiter`); dependency `get_login_start_limiter` and the `limiter.admit(...)` call in `app/api/google_session_auth.py`; `_prune_expired_states` and `_PRUNE_BATCH` in `google_session_auth_service.py`; settings `google_login_start_rate_limit` and `google_login_start_rate_window_seconds` in `config.py` (comment holds the trade-off). Tests: `tests/security/test_login_start_limit.py`, `tests/known_issues/test_ki032_pending_login_state_growth.py`.

**Decisions taken while building.**
- The limit counts only LOGIN starts, after the Origin and `X-DriveMind-Auth` checks, so requests that would be refused with 403 cannot use up the budget, and the authenticated `CONNECT_DRIVE` start is not blocked by a flood. The flag-off 404, demo 403 and unconfigured 503 come from the router dependency and still win over a 429.
- Rejected requests are not recorded, so a flood extends its own lockout by nothing beyond one window. Memory is at most `limit` timestamps.
- Prune runs inside the start transaction (one commit with the insert), deletes at most 500 expired rows (`SKIP LOCKED`) and covers legacy rows with no binding too (`_consume` already refuses all expired rows). A prune failure is a 503 and stores nothing; it is not swallowed, because a silent failure would hide the growth this ticket exists to stop.
- Defaults: 30 per 60 s (settings accept 1 to 10000 per window of at least 1 s). No existing test needed a reset or a different value.

**Reviews (2026-11-21).** Two independent read-only reviews (standards and maintainability; spec, correctness and security): no blocking findings. Fixed: the vacuous concurrent-limiter test was replaced by a flood test, the CONNECT_DRIVE test renamed to what it proves (a refused request uses no budget; the code skips the limiter for that intent, no positive authenticated test), unused `reset()` removed, config comment shortened to point at the limiter docstring, stale KI-032 test docstring marked historical. Accepted, not changed: a start that then fails with 503 still uses a slot; `Retry-After` is the earliest the oldest slot frees, and a sustained flood refills the window at once; the prune has no `expires_at` index (no schema change allowed; the 500-row batch bounds the cost; M9/M10 note); the limiter duplicates the small deque window of `DemoChatLimits` on purpose; the audit and v1 product definition still describe KI-032 as open (dated records; ticket 09 to update `drivemind-v1-product-definition.md` line 353).

**For ticket 09 documentation.** Add `GOOGLE_LOGIN_START_RATE_LIMIT` and `GOOGLE_LOGIN_START_RATE_WINDOW_SECONDS` to `.env.example` and the operating guide with the trade-off (global, process-local, resets on restart, can delay the Owner's own login, cannot read or change anything). Add a note to `backend/app/security/README.md` (current-status block). Add to the M9 row: per-IP or edge limiting for the login start, and re-check the limiter before running more than one worker (each worker has its own window).

**Verification (2026-11-21).** Disposable PostgreSQL, no `OPENAI_API_KEY`. Before the fix the strict KI-032 test failed for its registered reason and the guard passed. After: `tests/security/test_login_start_limit.py` and `tests/known_issues/test_ki032_...` pass; `tests/security tests/test_auth_google.py tests/db tests/known_issues`: 934 passed, 377 skipped, 6 xfailed. `ruff check`, `ruff format --check`, `mypy app` clean; `basedpyright` clean on `app` and the two test files. No migration or schema change.

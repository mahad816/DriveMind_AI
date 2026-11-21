# 07: Stop login attempts from growing the database without limit (KI-032)

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** Expired Google login attempts are deleted when a new login starts, and the unauthenticated login-start endpoint has a small global request limit. Security implication (Owner decision D4-3): an unauthenticated request can create one stored row per call while sessions are enabled, with no data exposure. Storage implication: unbounded table growth.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** open

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

- [ ] The KI-032 strict test fails today for its registered reason and passes after the fix with its marker removed; the passing guard (a valid attempt survives another login start) still passes.
- [ ] After the limit is exceeded, further login-start requests get 429 and write no row (row count asserted); after the window they work again (injected clock).
- [ ] Statuses with the flag off (404), in demo mode (403) and when unconfigured (503) are unchanged; the route inventory passes.
- [ ] Normal login (start then callback) still works end to end; no existing test needs more than the default or a manual reset.
- [ ] No migration or schema change in this ticket.
- [ ] KI-032 appears under Fixed with both implications and the lockout trade-off.

## Comments

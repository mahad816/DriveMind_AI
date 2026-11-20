# 04: Authentication and access-control audit (A2, part 2)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner has a verified inventory of how every mounted route is authenticated, how sessions and demo mode bound access, how stored Google credentials are protected, whether logs can leak sensitive data, what abuse protection exists for Owner-mode requests, and which legacy authentication routes exist but are unmounted, with confirmed and unverified behavior clearly separated.
**Blocked by:** None (can start immediately). Ticket 01's hosted session-flag and demo-mode values are a soft input: if unread, they stay `Unverified`. Any new test that needs the database waits for ticket 02, as in ticket 03.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Inventory mounted routes: authentication dependency, demo-mode behavior, and behavior when `GOOGLE_APPLICATION_SESSIONS_ENABLED` is off.
- Identify defined-but-unmounted routers (including the legacy Google authorization router that stores tokens) and whether anything else can reach them.
- Inspect session handling and the demo-mode access boundary (what a Visitor can and cannot reach).
- Check whether stored Google credentials are encrypted at rest by default and what happens when encryption is not configured; read the scope of the existing encrypted-only-credentials test.
- Inspect logging for exposure of tokens, authorization codes or File content.
- Record what rate limiting or abuse protection exists for Owner-mode requests (the demo limiter is separate). Recommend only; the v1 spec's security-triage decision stays with the Owner.
- Report each result as Verified, Defect, Unverified or Future, with evidence type.
- Escalation applies as in ticket 03: a reachable vulnerability found here is reported to the Owner immediately.
- Tests: only where a deterministic, meaningful test is possible (protective tests pass today; defect tests are strict expected failures with a registry entry).

## Out of scope

The six first-credential fallbacks and their callers (ticket 03). Fixing anything, removing the legacy router, building Disconnect/Revoke (M7), building or choosing rate limits, exploiting the hosted app.

## Inspect

`backend/app/api/` (`router.py`, `dependencies.py`, `session_dependencies.py`, `google_session_auth.py`, `auth.py`, `chat.py`, `conversations.py`, `files.py`, `index.py`, `sources.py`, `health.py`), `backend/app/security/` (`principal.py`, `google_credential_crypto.py`, `session_helpers.py`, README), `backend/app/core/config.py`, `backend/app/main.py`, logging setup and log call sites, demo-limiter code, `backend/tests/security/` (notably `test_encrypted_only_credentials.py`, `test_google_credential_crypto.py`, `test_credential_diagnostics.py`).

## Deliverables

`## Findings` in this ticket: route inventory table, unmounted-router list, encryption behavior (default and unconfigured), logging review, rate-limit/abuse-protection summary with a recommendation, Verified/Unverified list, any proposed M0-SEC items for ticket 09 to merge.

## Needs

No paid APIs. No live infrastructure. Local Docker only for any database-backed test, after ticket 02.

- [ ] Every mounted route is listed with its authentication dependency, demo-mode behavior and session-flag-off behavior.
- [ ] Unmounted routers are identified, with whether anything can reach them, and the search method is stated.
- [ ] Session and demo-mode access boundaries are described with code pointers.
- [ ] Encryption-at-rest default and the unconfigured-encryption behavior are answered with evidence; the encrypted-only test's scope is stated.
- [ ] The logging review states what was searched and whether tokens, authorization codes or File content can be logged.
- [ ] Existing Owner-mode rate limiting/abuse protection is recorded (or "none found" with the search method) with a recommendation, not a decision.
- [ ] Confirmed and unverified behavior are separated; any reachable vulnerability was reported to the Owner when found, with the time recorded.
- [ ] Any added test is deterministic, free of paid API calls and meaningful. No application code changed.

## Comments

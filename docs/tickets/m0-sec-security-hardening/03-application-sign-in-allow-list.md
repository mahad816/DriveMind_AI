# 03: Application-level sign-in allow-list

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** Only Google accounts the Owner has listed can sign in or keep using a session. Everyone else gets the same generic refusal as any other failed login and never holds a usable session. Removing an address ends its access on its next request. DriveMind stays a private single-Owner beta with no public registration (Owner decisions D4-1 and the 2026-11-21 approval).
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** open

## Scope

- A new configuration value holding the permitted verified Google e-mail addresses (environment, comma-separated, trimmed, case-insensitive, blank entries ignored). It is documented next to the other settings and in the example environment file with an invented address. No real address is committed anywhere.
- Matching is by the verified e-mail returned by Google's token verification (not the userinfo profile), not by Google subject; record this in the setting's documentation (an e-mail change on the Google side changes who matches).
- One check in the Google login completion path, after Google's identity verification (ID token, nonce, verified e-mail, subject) and before any user lookup or creation or session issuance. Both login intents pass through the same call site.
- Fail closed: in normal mode an unset or empty list means nobody can complete a sign-in.
- A refused account gets the same response, status and timing class as the existing generic login rejection (`GoogleLoginRejected`). It creates no `users`, `application_sessions` or credential row. Its address is not written to any log or response.
- **Removal denies protected operations immediately.** The same allow-list check runs where an authenticated request resolves its session to the stored user row (the principal resolution used by every private route), for Google-account sessions in normal mode. An unlisted or unset-list address gets 401 on its next request on every private route. The check is stateless (the session row is not rewritten), so re-adding an address within an old session's remaining lifetime (7 days at most) reactivates that session unless it was explicitly revoked; state this in the setting's documentation, together with how a session is explicitly revoked (logout, below).
- **Logout still revokes.** Logout resolves its session through the same CSRF verification, which would now answer 401 for a removed address and leave the session row alive. Give the logout route (only) a resolution path that checks everything it checks today (valid unexpired session cookie, exactly one matching `Origin`, session-bound CSRF token) but skips the allow-list, and that only revokes: it never returns a principal that any other route accepts. A removed address can therefore end its own session, and gains no access to any protected operation and no weaker CSRF protection. Verify first that the resolution step has the stored e-mail available; if it does not, report before adding a query.
- Limitation, documented: the CSRF token is read through the session-inspection endpoint, which passes through the allow-list check, so a removed address cannot fetch a fresh token; logout works for a client that already holds one, otherwise the session ends by expiry. The token endpoint is not exempted (smallest change).
- **Deferred, recorded here and in the spec, not described as a security guarantee:** (a) a conversation turn already running when an address is removed keeps running and may publish its result within its bounded execution window (publication checks the session row, not the allow-list); (b) indexing jobs already queued for a removed account are not cancelled, because the worker acts on a stored owner and has no session (the indexing worker is not started by the application today); the per-job allow-list check is assigned to M6, the first milestone that runs Preparation jobs through the worker, and verified again at the M9 gate; (c) the stored e-mail is refreshed only at sign-in, so a Google-side e-mail change is not seen until the next sign-in (residual risk).
- Demo mode is unaffected (its session endpoints already answer 403).

## Out of scope

Roles, invitations, domain rules, a user cap, admin screens, changing Google consent-screen settings (Owner dashboard, M9), sign-up or any public onboarding.

## Inspect

`docs/tickets/m0-system-audit/04-auth-and-access-control-audit.md` ("Sign-up gate", Owner decision 1); `backend/app/services/google_session_auth_service.py` (the callback, near the user upsert); `google_oauth_service.py` (`_upsert_user`); `backend/app/core/config.py`; `.env.example`; `tests/security/test_google_session_auth.py`, `test_google_session_postgres.py`, `test_session_security.py`, `test_two_user_rag_end_to_end.py`.

## Deliverables

Setting, check, tests; `## Comments` with the documentation items for ticket 09 (`docs/guides/GOOGLE_OAUTH.md` wording: the allow-list is the authorization model and the test-user list is an outer control).

## Needs

Disposable PostgreSQL. Fake Google identity as the existing tests do. No network.

- [ ] Tests written first fail today: an unlisted verified account gets a user row and a session, and a session of a no-longer-listed address still works.
- [ ] Unlisted verified account: no `users`, `application_sessions` or credential row is created; the response equals the existing generic rejection; the address appears in no captured log line or response body.
- [ ] Unset list and empty list: every completion is refused, no rows created.
- [ ] A listed account signs in as before, with any letter case in the list or in the Google claim; a returning user (matching Google subject) still resolves to the same user row.
- [ ] Logout regression: for a removed address with a valid session, `GET` and mutating protected routes answer 401, while logout with a valid `Origin` and CSRF token succeeds and revokes the session row (a later request is 401 even after the address is re-added); logout with a missing or wrong `Origin` or CSRF token, or with an invalid cookie, is refused as today; the logout resolution path is not usable as a principal by any other route (route inventory dependency check).
- [ ] Re-adding a removed address whose session was not revoked restores access (documented behavior).
- [ ] Revocation: with a valid session for a listed address, removing it from the list (or unsetting the list) makes the next request 401 on every private route class in the route inventory (conversations, files, index, sources, chat, session inspection), and on mutations; a demo-mode session is unaffected.
- [ ] The Drive-connect intent is covered: an unlisted account cannot get a credential stored.
- [ ] An unverified e-mail is still rejected (existing behavior preserved).
- [ ] Two-owner isolation tests (`test_two_user_rag_end_to_end.py`, `test_private_read_authorization.py`) pass; test fixtures that sign in set the list explicitly, nothing relies on a global default.
- [ ] Because an unset list now denies every session, one shared test helper (fixture) sets the list; the ticket's `## Comments` lists every existing test file that creates a session or completes a sign-in and that it uses the helper. No test depends on a default.
- [ ] The route inventory (48 tests) passes; it is updated only for the logout route's changed dependency and the new allow-list dependency, and the update is named in the ticket's `## Comments`. Static checks no worse than the baseline.

## Comments

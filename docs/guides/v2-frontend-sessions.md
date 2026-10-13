# V2 frontend application sessions (4F1A)

Normal pages bootstrap `GET /api/v1/auth/session`. Only a validated
`GOOGLE_ACCOUNT` response with a User UUID authorizes mounting private UI.
Drive grant connectivity remains a separate state. Inspection is uncached;
CSRF material is used in memory and is never persisted or placed in URLs.

Sign-in posts `{ "intent": "LOGIN" }` to `/auth/session/google` with
`X-DriveMind-Auth: 1`. Connect/reconnect posts `CONNECT_DRIVE` with that header
and freshly inspected, owner-matched `X-CSRF-Token`. Both receive an
`authorization_url` for browser navigation. Only HTTPS accounts.google.com
URLs are accepted. Origin, state, browser binding, verified Google identity,
HttpOnly/Secure/SameSite cookies and grant ownership remain backend authority.
The callback's `login=success` is a hint; session inspection determines identity.
Legacy `connected`, `email` and editable owner hints never establish identity.

Logout inspects current owner/CSRF and posts `/auth/session/logout`. Private UI
is unmounted before waiting. Failed logout never claims server revocation;
content remains hidden until explicit session verification. Private API 401s
invalidate local session state. Late responses from a previous session epoch
are discarded, and focus/periodic inspection can detect changed cookie identity.
Polling and preparation stop at known session changes rather than continuing
under the next account. A 404/503 session endpoint fails closed without legacy
OAuth fallback. Authentication requests have a 15-second transport deadline.

## Temporary history boundary

Normal AppShell routes use a memory-only chat and navigation without the legacy
conversation list. Even `/chat/<old-id>` does not mount the saved-history client.
Requests contain the question, not legacy conversation IDs or stored history.
Messages and citations disappear on logout, expiry or account remount. Existing
localStorage records are neither read/adopted nor deleted. Normal saved-history,
history follow-ups and durable conversation reopening await 4F2 ownership and
migration policy. Anonymous demo keeps its existing isolated history path and
never bootstraps a normal application session.

## Configuration and remaining work

Use the existing same-origin `/api/v1` Next.js rewrite and approved backend
session-login configuration. The Google session callback must be on the
cookie-owning frontend origin at `/api/v1/auth/session/google/callback`.
The browser supplies Origin and cookies; JavaScript never creates session cookies.
Provider cancellation/verification failures retain the backend's existing safe
callback error responses. Returning to the frontend permits session verification
and sign-in retry; this phase does not redesign backend failure redirects.

4F1B removes `/auth/google` and `/auth/google/callback` from application routing;
both now return 404 in normal and demo modes. Shared provider helpers and existing
grants/state rows are preserved. The old router module is retained internally
but is not mounted. There is no redirect or authentication fallback.

Existing Google registrations pointing to `/api/v1/auth/google/callback` are
obsolete and cannot complete login. Before separately authorized deployment,
register `/api/v1/auth/session/google/callback` on the cookie-owning frontend
origin and set the existing `GOOGLE_SESSION_REDIRECT_URI` accordingly. The legacy
`GOOGLE_REDIRECT_URI` field remains for internal compatibility; V2 explicitly
uses the session redirect URI. No provider registration or runtime flag is
changed by this retirement.

4F2 must establish owner-scoped
conversation storage before restoring normal saved-history access. Subsequent
integration work covers durable preparation resumption and separating local-index
readiness from Drive connectivity. This phase does not enable session-login or
indexing deployment configuration, start workers, or authorize production cutover.

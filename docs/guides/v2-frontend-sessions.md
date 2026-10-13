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

## Owner-scoped history (4F2)

Normal chat now uses the existing conversation sidebar, metadata/message helpers
and `/chat/<id>` pages. Verified session UUIDs select versioned browser-local
keys: `drivemind:v1:normal:<user_uuid>:conversations` and
`drivemind:v1:normal:<user_uuid>:conversation-messages:<conversation_id>`.
Anonymous demo retains `drivemind:demo:...`. Legacy unowned normal keys remain
intact, quarantined, and are never read, imported or assigned to a new account.

Each mounted account and async request captures owner, session generation and
an invalidation notice stamp. Reads and writes reject stale scopes; generation
changes remount private UI and request cancellation. Even cancellation-resistant
responses cannot settle another account's turns. Normal chat inspects the
server session again before supplying saved history and checks response ownership.
The existing bounded history window and citation identities are preserved.

Cross-tab storage notices and BroadcastChannel carry only random invalidation
nonces, not identity or credentials. Receivers immediately hide private UI and
inspect the server before choosing any owner. Logout signals both before its
network request and after revocation completes. Focus/visibility checks also
hide state during verification. Channels, listeners and request registrations
are cleaned up by their owners; received expiry notices do not echo indefinitely.

The key prefix defines schema version 1; records retain existing IDs and shapes.
Reads validate metadata, message and citation shapes. Each JSON value is bounded
to 2,000,000 UTF-16 code units; oversized/quota/disabled writes fail with safe UI
feedback before submitting a new chat request. Draft text and selected citations
remain in memory, and are discarded on account/generation changes. Stored pending
turns become retryable interrupted turns after a new account runtime loads.

This is browser-local persistence, not a server history API or authorization
boundary. Other browsers/devices are not synchronized. Same-owner simultaneous
editing uses localStorage's existing last-writer semantics, not transactional
merge. Cross-tab notification depends on browser storage events/BroadcastChannel;
focus, periodic checks and fresh pre-send inspection provide further fencing.
It cannot atomically bind browser-supplied history to a server cookie change that
occurs between inspection and dispatch; backend identity remains authoritative.
No cookies, tokens or OAuth state are stored by this feature.

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

Subsequent integration work covers durable preparation resumption and separating local-index
readiness from Drive connectivity. This phase does not enable session-login or
indexing deployment configuration, start workers, or authorize production cutover.

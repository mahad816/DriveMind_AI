# Application session foundation (inactive)

No existing route uses these dependencies and no public session issuer exists.
This does not enable secure multi-user operation: OAuth browser binding, verified
login issuance, all data-access ownership filters and job isolation remain future work.

One `ApplicationSession` table serves both Google accounts and anonymous demo
browsers. Real conversation ownership is the existing User UUID, independent of
browser sessions. Demo conversation ownership is the session UUID; corpus identity
is the configured DEMO_USER_ID. Visitors never create additional demo User rows.

`VerifiedGoogleIdentity` is a trusted server-code attestation, not an ID-token
verifier or request schema. The next step must produce it only after Google token,
issuer/audience/expiry/nonce and browser-bound OAuth state verification. Raw UUIDs,
strings and dictionaries cannot be passed to the authenticated issuer.

Credentials contain 32 random bytes; only a SHA-256 digest is stored. Independent
CSRF material is stored server-side. Issued secrets use redacted SecretStr fields
and are never logged. The future issuer sends credentials only in an HttpOnly
cookie, never JSON or URLs. Each resolution queries the database; expiry,
revocation and realm mismatch fail closed without anonymous/first-account fallback.
The caller owns commit/rollback; issuance flushes but does not commit. Commit
issuance before sending its cookie. A principal does not replace protected demo
corpus admission or authorize OAuth/indexing; future routes must retain those gates. There is no
last-seen write or positive authentication cache.

Inactive absolute lifetimes are seven days for Google sessions and thirty days
for demo sessions. Credential expiry does not define future conversation retention.
Cookie helpers require Secure/HttpOnly/SameSite=Lax/Path=/ and no Domain on HTTPS,
with separate __Host- names for each realm. Insecure local cookies are permitted
only for app_env=development, debug=true and an explicitly loopback HTTP frontend.
Only configured FRONTEND_URL is trusted; no Host or Origin reflection. Mutation
helpers require one matching Origin plus session-bound X-CSRF-Token. They do not
configure CORS or register endpoints.

Before integrating login, verify same-origin Cookie/Set-Cookie forwarding. The
current direct-backend OAuth callback cannot receive a frontend-host-only cookie;
a same-origin callback or separately reviewed safe binding is required. Logout,
credential rotation and Google disconnect are not activated in this step.

Real PostgreSQL tests require SESSION_TEST_DATABASE_URL pointing to a disposable
loopback database whose name starts with drivemind_session_test. Tests create and
drop only generated test schemas there, exercise the actual Alembic revision, and
never use Settings.database_url. Without that explicit URL they skip, rather than
claiming real database validation. Do not use an existing real/demo datastore.


## Step 2A: inactive Google session login

`GOOGLE_APPLICATION_SESSIONS_ENABLED=false` is the default. Existing
`/auth/google` and its Drive callback retain their single-user behavior and do
not issue application sessions. Existing chat/files/index/sources routes still
have their existing authorization; this step does **not** make them multi-user
safe. The new dependency is attached only to the opt-in session endpoints.

The separate `/api/v1/auth/session` flow requires both the flag and an explicit
`GOOGLE_SESSION_REDIRECT_URI` on the exact trusted `FRONTEND_URL` origin, with
path `/api/v1/auth/session/google/callback`. A direct Railway callback cannot
set a host-only cookie for Vercel. The old `GOOGLE_REDIRECT_URI` is untouched.
No deployed configuration or Google callback registration was changed.

Before future activation, register the new callback with Google, verify that
Next.js's same-origin rewrite forwards all `Set-Cookie` headers and request
cookies correctly in a real browser, and complete owner scoping of all private
API, SQL, vector and background-job paths. Do not enable public multi-user
operation merely because session login works. Local HTTP requires the existing
explicit development/debug/loopback cookie policy; production requires HTTPS.

Protocol:
- POST `/auth/session/google`, JSON `intent: LOGIN | CONNECT_DRIVE`, trusted
  Origin and `X-DriveMind-Auth: 1`. CONNECT_DRIVE additionally requires an active
  application session and `X-CSRF-Token`. LOGIN requests identity scopes only;
  CONNECT_DRIVE requests existing read-only Drive scopes and offline access.
- A short-lived HttpOnly host-only cookie binds the browser to a one-shot DB
  state with PKCE and nonce. Starting another login replaces that binding;
  parallel login windows should restart rather than reuse an older transaction.
- Callback atomically consumes and commits state before Google I/O. Google's
  maintained ID-token verifier checks signature, issuer, audience, expiry and
  issued-at. Nonce, verified email and stable subject are checked; userinfo must
  match the subject. CONNECT_DRIVE must match the initiating session's account
  and actually granted Drive scopes. Missing refresh tokens preserve the old
  refresh token. LOGIN never overwrites Drive credentials.
- Existing sessions rotate only after verified login. A revoked, expired or
  changed initiating session fails closed. Successful user/token/session changes
  commit together before the bearer cookie is emitted. State remains consumed
  on failure. Session cookies are never returned in JSON; generic failures hide
  provider and DB payloads.
- GET `/auth/session` validates the session freshly and returns user/kind and
  session-bound CSRF material (not a bearer credential), with `no-store`.
  POST `/auth/session/logout` requires trusted Origin and CSRF, commits revocation
  before clearing the cookie. Logout does **not** yet protect legacy private APIs
  or disconnect Drive; those changes belong to the authorization rollout.

All Google network stages have bounded transport timeouts; the async callback
has a 60-second exchange deadline. Cancellation rolls back pending local writes.
A cancelled worker thread may finish bounded Google I/O but performs no DB work
or cookie issuance. No semantic/provider retry loop was added.

Existing users remain keyed by stable Google subject. The existing unique email
constraint is retained: a different subject with a colliding email is rejected,
never silently linked. Concurrent first-time creation of the same user may fail
safely and require a fresh login; account linking is outside this step.

The additive migration preserves legacy pending rows. Secure pending states
cannot be redeemed through the legacy callback. Downgrading invalidates pending
secure logins; stop the opt-in flow before rollback. Existing user IDs and stored
Drive grants are unchanged by the migration.

Verification uses mocked Google exchanges and isolated loopback PostgreSQL;
no live Google login, production migration or browser proxy-cookie verification
is claimed.


## Step 3B1: inactive Google credential crypto foundation

`GoogleCredentialCrypto` is an independently tested utility. No route, OAuth
callback, credential loader, refresh operation or startup hook imports or calls
it. Configuring keys does **not** activate encrypted storage. PostgreSQL token
columns and current Google behavior remain unchanged; no migration or backfill
is included. Encryption also does not establish user ownership or multi-user
API safety.

Backend-only optional settings:
- `GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING`: a secret JSON object mapping key IDs to
  canonical URL-safe base64 Fernet keys (32 decoded bytes).
- `GOOGLE_CREDENTIAL_ENCRYPTION_ACTIVE_KEY_ID`: the ID used for new writes.

Both default to absent/empty. They are excluded from Settings representations
and ordinary serialization. Parsing happens only on explicit crypto construction;
malformed or incomplete configuration fails closed there. The keyring must have
1–16 entries and at most 8,192 characters. IDs contain 1–32 ASCII letters,
digits, underscores or hyphens, beginning with a letter or digit. Duplicate JSON
IDs, malformed key material and unknown active IDs are rejected. Never generate
a replacement key at startup, send these settings to browsers or put keys in
source, database rows, logs or `NEXT_PUBLIC_*` variables. No deployment keys were
created in this step. Keys must later be provisioned through external backend
secret management and protected backup/recovery procedures.

The storage envelope is `dm-google:v1:<key-id>:<Fernet-token>`. Its secret-safe
API returns `SecretStr`; future storage code must explicitly unwrap it. The
version and key ID are repeated inside Fernet-authenticated JSON, along with
provider `google`, application User UUID, credential-row UUID and access/refresh
tokens. All fields are required in the JSON schema; either token may be null,
but at least one must be nonempty. Decryption requires trusted expected owner,
row and provider identities, checks exact binding, and rejects unknown fields,
duplicate JSON fields, unsupported versions, noncanonical base64, corruption,
wrong keys and relabelled headers. Never derive expected ownership from the
ciphertext itself or an untrusted HTTP body.

Bounds: each token is at most 8,192 UTF-8 bytes; the complete authenticated JSON
is at most 16,384 bytes; the complete envelope is at most 32,768 characters.
Encryption uses the active key and a fresh Fernet IV; decryption selects only
its declared known key. Future rotation can explicitly decrypt an old envelope
and encrypt its payload with the active key, updating authenticated key metadata.
Retain old keys while their rows/backups need decryption. There is no automatic
rotation, stored-token TTL or plaintext fallback. Fernet exposes creation time
and approximate payload size; the envelope also exposes its key ID/version.
It cannot prevent replay of an older valid credential for the same owner/row;
revision and authorization-epoch checks belong to lifecycle integration.

Errors contain only fixed generic messages and never log secrets or ciphertext.
Payload, cipher/key configuration and legacy `DriveTokens` representations
hide secrets. Explicit unwrapping, dataclass conversion and raw diagnostic dumps
are still sensitive operations. Existing OAuth/client exception interpolation,
SQL parameter logging, job errors, plaintext token rows and historical backups
remain known risks for later work; this is not a broad logging or storage fix.

Step 3B2 should add reviewed additive ciphertext storage and a central credential
repository, then synthetic PostgreSQL migration/compatibility tests. Existing
row backfill, encrypted-only enforcement, rollout and rollback require separate
review. Never silently fall back to plaintext after ciphertext verification
fails, and never remove old keys before verifying recovery requirements.

Reference: https://cryptography.io/en/stable/fernet/ (maintained Fernet API).

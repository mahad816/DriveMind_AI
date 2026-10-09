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

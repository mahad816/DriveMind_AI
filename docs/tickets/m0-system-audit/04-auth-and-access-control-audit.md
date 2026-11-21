# 04: Authentication and access-control audit (A2, part 2)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner has a verified inventory of how every mounted route is authenticated, how sessions and demo mode bound access, how stored Google credentials are protected, whether logs can leak sensitive data, what abuse protection exists for Owner-mode requests, and which legacy authentication routes exist but are unmounted, with confirmed and unverified behavior clearly separated.
**Blocked by:** None (can start immediately). Ticket 01's hosted session-flag and demo-mode values are a soft input: if unread, they stay `Unverified`. Any new test that needs the database waits for ticket 02, as in ticket 03.
**Status:** ready-for-agent
**Progress:** resolved

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

- [x] Every mounted route is listed with its authentication dependency, demo-mode behavior and session-flag-off behavior.
- [x] Unmounted routers are identified, with whether anything can reach them, and the search method is stated.
- [x] Session and demo-mode access boundaries are described with code pointers.
- [x] Encryption-at-rest default and the unconfigured-encryption behavior are answered with evidence; the encrypted-only test's scope is stated.
- [x] The logging review states what was searched and whether tokens, authorization codes or File content can be logged.
- [x] Existing Owner-mode rate limiting/abuse protection is recorded (or "none found" with the search method) with a recommendation, not a decision.
- [x] Confirmed and unverified behavior are separated; any reachable vulnerability was reported to the Owner when found, with the time recorded.
- [x] Any added test is deterministic, free of paid API calls and meaningful. No application code changed.

## Findings

Audited 2026-11-21 on branch `feature/v2-state-performance`, base commit `69af359`. Method and results below. No application code was changed (two new test files, one registry entry and this ticket only). Labels and evidence types are those of the v1 spec ("How to read this spec"); I added one evidence type, **local run**, for a command I executed on this machine against local code only. No hosted system was contacted: no request was sent to Railway, Google or OpenAI.

### Verdict

- **No reachable authentication bypass or data-isolation vulnerability was found.** Every mounted private route resolves its owner from a verified session principal (or the demo user in demo mode), and every data read I traced filters on that owner. Evidence: code, plus 48 new tests that pin it.
- **One conditional exposure needs the Owner to read two hosted facts** (see "Sign-up gate"): the application has no sign-in allow-list, so with `GOOGLE_APPLICATION_SESSIONS_ENABLED` on, any Google account that Google lets through the consent screen gets its own user row and a session, and can then call the paid chat endpoints. It is **not confirmed**: it needs the hosted flag value (ticket 01, unread) and the OAuth consent-screen state, neither of which I could read. It is a cost-abuse exposure, not an isolation failure.
- **One new defect, KI-032**: abandoned login attempts are never removed by the running application. Storage growth reachable by an unauthenticated request while the flag is on. Not an authentication or data-isolation weakness.
- **One existing guard test is vacuous** (it checks nothing under the pinned FastAPI), and several documents contradict the code. Listed for ticket 09.
- There is **no rate limit or abuse protection for Owner mode** (search method below). Recommendation, not a decision, in section 7.

### Escalation log

| When (PKT) | What | Action |
|---|---|---|
| 2026-11-21 14:05 | After the last route, dependency and log site was read: no reachable authentication or data-isolation vulnerability. | None needed. |
| 2026-11-21 14:05 | Conditional cost-abuse exposure (open sign-up when the flag is on, no per-user limit), not confirmed: it depends on two unread hosted facts. KI-032 (availability) found in the same pass. | Not a stop condition (not confirmed; not authentication or isolation). **Nothing was reported to the Owner mid-audit**: the exposure was identified at the end of the pass and is reported in the closing session report, with the two facts that would confirm or clear it. Proposed M0-SEC items below. |

### Search method

1. **Routes:** read every module in `backend/app/api/` and `api/router.py`. Listed every `APIRouter(` definition, every `include_router`, `.mount(`, `add_api_route`, `@app.<verb>` and WebSocket decorator in `backend/app`: only `app/main.py:169` mounts the API router, and no sub-application, WebSocket or extra route exists. Counted the mounted operations with `create_app().openapi()` (26) and compared them with the routes found in the source (26, same set); this is the test `test_the_mounted_operations_are_exactly_the_reviewed_inventory`.
2. **Dependencies:** read `api/dependencies.py`, `api/session_dependencies.py`, `security/principal.py`, `security/session_helpers.py`, `services/application_session_service.py`. Derived each route's authentication dependencies from `APIRoute.dependant` (public FastAPI API) and cross-checked by hand.
3. **Unmounted routers:** `grep -rn "APIRouter("` (9 definitions); for each module compared its paths with the OpenAPI paths (test `test_only_the_retired_google_router_is_defined_but_unmounted`); `grep -rn "app.api.auth\|api import"` and an AST scan of every file under `backend/app` (test `test_nothing_in_the_application_imports_the_retired_google_router`).
4. **Encryption:** read `models/google_oauth_token.py`, `security/google_credential_crypto.py`, `services/google_credential_repository.py`, `google_credential_service.py`, `indexing_runtime.py:294`, the migration `20261011_1200`, `test_encrypted_only_credentials.py`, `test_google_credential_crypto.py`, `test_google_credential_repository.py`.
5. **Logging:** `grep -rn -E "logger\.(debug|info|warning|error|exception|critical)\(|logging\.|print\(|exc_info|echo=|hide_parameters" backend/app` (30 log calls, 3 `print` calls in offline command-line tools, every SQL echo setting); `grep -rn -E "raise [A-Za-z_.]+\(f[\"']"` for exception messages that interpolate values; read the start script, the Dockerfile and `core/logging.py`; ran a real uvicorn locally (section 6).
6. **Rate limits:** `grep -rn -i -E "slowapi|ratelimit|rate_limit|throttle|Limiter|status_code=429|, ?429|too_many"` over `backend/app` and `pyproject.toml`; `grep -rn -i -E "CORSMiddleware|TrustedHost|add_middleware|BaseHTTPMiddleware"`; read `core/public_safety.py`, `schemas/chat.py`, `schemas/conversation.py` and the indexing admission in `api/index.py`. A search that finds nothing is not proof of absence: a limit could live at the Vercel or Railway edge (Unverified).

### 1. Route inventory (26 operations, plus 3 framework documentation routes)

"Flag off" is `GOOGLE_APPLICATION_SESSIONS_ENABLED=false`, the shipped default. "No session" means no cookie. The statuses below were produced by the new tests (the real application, with a database mock that fails the test if any route touches it), so they are **test**-backed, not only read from code.

| Route | Authentication dependency | Normal mode, no session | Demo mode (`DEMO_MODE=true`) | Flag off |
|---|---|---|---|---|
| `GET /health`, `/health/ready`, `/health/indexing` | none | public (`/health/ready` reads the database; `/health/indexing` shows a fixed status and reason code) | public | same |
| `POST /auth/session/google` | router dependency `require_session_login_enabled`; then `Origin` equal to `FRONTEND_URL` and `X-DriveMind-Auth: 1`; intent `CONNECT_DRIVE` also needs a session and CSRF token | open to anyone **when the flag is on** and login is configured | 403 (flag on) / 404 | **404** |
| `GET /auth/session/google/callback` | same router dependency; one-shot `state` + browser-binding cookie + PKCE | as above | 403 / 404 | **404** |
| `GET /auth/session` | router dependency + `require_application_principal` | flag on: 401 | 403 / 404 | **404** |
| `POST /auth/session/logout` | router dependency + `require_session_mutation` (Origin + CSRF, checked **before** the cookie) | flag on: 403 without `Origin` or CSRF token, 401 once both are present but no valid cookie | 403 / 404 | **404** |
| `POST /index/sync`, `/ingest`, `/chunk`, `/build` | `require_index_user`: refuses demo mode; 401 without a session; Origin + CSRF; refuses the configured demo user id | 401 | **403** | 401 |
| `GET /index/status`, `/index/pending` | `require_index_read_user` | 401 | **anonymous** (demo status stays readable even when the demo corpus is unavailable) | 401 |
| `GET /files`, `GET /files/{id}/content`, `GET /sources/{id}`, `POST /chat` | `require_resource_user` (+ `require_demo_index`): the principal's `corpus_user_id` is the only owner passed down | 401 | **anonymous**; owner is `DEMO_USER_ID`; 503 if the demo corpus is incomplete | 401 |
| `/conversations` (9 operations: create, list, detail, rename, delete, submit, stream, turn status, interrupt) | router dependency `require_normal_mode`, then `require_application_principal` (reads) or `require_conversation_mutation` (Origin + CSRF) | 401 | **403** (demo visitors have no conversation API) | 401 |
| `/docs`, `/redoc`, `/openapi.json` (+ `/docs/oauth2-redirect`) | none (FastAPI defaults; `main.py` does not disable them) | public | public | public |

Notes:
- `tests/security/test_route_authentication_inventory.py` (48 tests) enforces the inventory: adding, removing or re-wiring a route fails it until the table in the test is updated. Mutation checks: removing `Depends(require_resource_user)` from `/sources`, mounting the legacy router, and enabling the access log each made the right tests fail (production files restored with `git checkout`, `git status` clean).
- `POST /chat` is authenticated by cookie only. Unlike every other mutation it does **not** require `Origin` or `X-CSRF-Token` (it uses `require_resource_user`, not `require_session_mutation`). It writes query history and spends model credits. Cross-site forgery is blocked today only by `SameSite=Lax` on the cookie. See M0-SEC item 4.
- The backend has **no CORS middleware** (no `CORSMiddleware` found), so browsers cannot read its responses cross-origin; the frontend reaches it through the same-origin Next rewrite.
- Every handler that takes a path id (`file_id`, `chunk_id`, `job_id`, `conversation_id`) was read: `DriveContentService._get_synced_file`, `SourceService.get_source_chunk`, `IndexingJobService.get_job`, the indexing file-target check in `_accept`, and the conversation cursor all filter on the caller's owner (code).
- Supported content types contain no HTML or SVG (`connectors/google_drive/constants.py`), so serving file content with `Content-Disposition: inline` does not create a script-execution path (code).

### 2. What the session flag does (and does not do)

- **Verified (code, test):** the flag gates only the four `/auth/session/*` endpoints (`require_session_login_enabled`: 404 when off, 403 in demo, 503 if the redirect URI or Google client is unconfigured). It does **not** appear in `require_application_principal`, `require_resource_user` or `require_index_user`.
- Consequence: with the flag off in normal mode **no session can be issued by the application**, so every private route answers 401 to everyone, except for sessions that already exist in the database. Flag off means "locked", not "legacy single-user". The older text in `security/README.md` ("existing private APIs retain their single-user behaviour") and the `AGENTS.md` wording ("Application sessions are gated by the flag") describe it inaccurately: the flag gates **issuance**, not **validation**.
- **Unverified:** the hosted value (ticket 01 not read). Session rows created earlier, while the flag was on, would still be honoured until they expire (7 days).

### 3. Unmounted routers

- **Verified (code, test):** exactly one router is defined and not mounted: `app/api/auth.py` (legacy Google OAuth: `GET /auth/google`, `GET /auth/google/callback`, which stored tokens through `GoogleOAuthService.handle_callback`). Nothing in `backend/app` imports it (AST scan). The only importer is `tests/test_demo_api_guard.py`, which uses it to override a dependency. Requests to those paths return 404 in normal and demo mode (`tests/test_auth_google.py::test_legacy_oauth_routes_unreachable`, existing, 8 cases).
- It stays unreachable unless someone adds an `include_router` line; the new test fails if they do. The class `GoogleOAuthService` it uses is **not** dead: `GoogleSessionAuthService` inherits it (`google_session_auth_service.py:148`). Only the router module is retired.
- Search limits: static search of this repository's `backend/app` only. It does not cover a reverse-proxy rewrite, another process or other branches (a copy of the code under `.claude/worktrees/` was ignored).

### 4. Session handling and the demo boundary

Session handling (code, test: `tests/security/test_session_security.py`, `test_application_session_postgres.py`, `test_google_session_auth.py`):
- The credential is 32 random bytes, sent only as an `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, host-only cookie (`__Host-drivemind-session` on HTTPS); only its SHA-256 digest is stored. Lifetime is 7 days (Google) or 30 days (demo, never issued). Every request does a fresh database lookup (expired, revoked, wrong realm, missing user: 401). There is no cache and no last-seen write.
- Mutations additionally need exactly one `Origin` equal to the configured `FRONTEND_URL` and exactly one session-bound `X-CSRF-Token`, compared in constant time. HTTP origins are accepted only for `APP_ENV=development`, `DEBUG=true` and a loopback host.
- Login: PKCE, one-shot state consumed before the Google call, browser-binding cookie, Google's ID-token verifier, nonce, verified email and subject match. The session is rotated after a verified login, and logout revokes it before clearing the cookie.
- Logout does **not** disconnect Drive or delete stored credentials (ticket 07 owns disconnect and deletion facts).

Demo boundary (what a Visitor can and cannot reach):
- **Can, with no cookie:** `/health*`; `GET /index/status` and `/index/pending` (demo readiness and sample questions); `GET /files`; `GET /files/{id}/content` (returns the extracted text of the **synthetic** demo documents as `text/plain`, from the database, never from Drive); `GET /sources/{id}`; `POST /chat` (global limiter); the public docs routes.
- **Cannot:** the four indexing mutations (403), all nine conversation operations (403), all four `/auth/session` endpoints (403 or 404), the retired Google OAuth router (404).
- The only thing separating demo data from Owner data is **storage isolation of a dedicated demo environment** (`config.py` comment; ADR 0002). In demo mode every anonymous read is scoped to `DEMO_USER_ID` and gated by `DemoCorpusService.is_ready()` (fails closed to 503). A database that held both demo and Owner data would expose the Owner's data to Visitors through `/files` and `/sources`. Whether the hosted demo is isolated is **Unverified** (ticket 01).
- The demo session code (`issue_demo`, 30-day demo sessions) has no route that issues a demo session; it is unused (recorded, not removed).

### Sign-up gate (conditional exposure, not confirmed)

- **Verified (code):** the `LOGIN` callback calls `_upsert_user(email, subject)` for any identity Google verifies (`google_session_auth_service.py:343`, `google_oauth_service.py:176`). The application has no allow-list, invitation, domain restriction or user cap (searched: `allow`, `invite`, `whitelist`).
- So when the flag is on, **access is gated only by Google's OAuth consent screen**. The repository guide describes "Testing" status with named test users (`docs/guides/GOOGLE_OAUTH.md`); the v1 spec's ledger says the hosted state came from unconfirmed research. If the consent screen is published, or a stranger is added as a test user, that person gets a session and an empty corpus of their own and can call `/chat` and conversation turns. **Analysis from code, not exercised:** with `TOOL_RAG_AGENT_ENABLED` on (default off; hosted value Unverified), the tool-agent path calls the language model for any question and has no early exit for an empty corpus (`rag_service.py:131-150`), so each such request probably costs money. I did **not** trace the default linear path, which may also call a model. There is no per-user or global limit in Owner mode.
- It is isolation-safe: each user sees only their own rows (verified above; `tests/security/test_two_user_rag_end_to_end.py`). It is a **cost-abuse** exposure.
- **To confirm or clear (Owner, read-only, dashboard):** (1) is `GOOGLE_APPLICATION_SESSIONS_ENABLED` on in the hosted backend (ticket 01)? (2) is the Google OAuth consent screen in "Testing" with only intended test users? If (1) is off, or (2) is a closed list, the exposure does not exist today.

### 5. Credential encryption at rest

- **Verified (code, test): encryption is not optional.** `GoogleOAuthToken` has no plaintext token columns; the only credential column is `encrypted_credentials` (`NOT NULL`, length 1 to 32768). Migration `20261011_1200` dropped the plaintext columns and refuses to run on a table that still holds credentials. `test_schema_and_safe_downgrade` asserts `access_token` and `refresh_token` are gone, and `test_populated_migration_refuses_and_rolls_back` asserts the refusal (both need PostgreSQL).
- **Format:** `dm-google:v1:<key-id>:<Fernet token>`. The authenticated payload binds provider, user id, credential-row id and key id; decryption requires the expected owner and row (`GoogleCredentialCrypto.decrypt`).
- **When encryption is not configured:** `GOOGLE_CREDENTIAL_ENCRYPTION_KEYRING` and `..._ACTIVE_KEY_ID` default to absent. `GoogleCredentialCrypto.from_settings` then raises `MissingEncryptionConfiguration`: there is **no plaintext fallback and no generated key**. Every credential read, write and refresh goes through it (`google_credential_repository.py:147,167,190`, `google_credential_service.py:352`), so connecting or using Drive **fails closed**. Tests: `test_google_credential_crypto.py::test_missing_partial_untrusted_key_configuration` (None, empty, partial, unknown id) and `test_encrypted_only_credentials.py::test_new_coordinator_missing_keys_and_configuration_fail_before_provider` (no provider call is made).
- **Scope of the "encrypted-only" test file** (`test_encrypted_only_credentials.py`, 20 test functions, nearly all PostgreSQL-backed): schema and migration safety, claim fencing and refresh outcomes, key rotation on refresh, constraints, and that the legacy callback stores ciphertext. It does **not** test: that the application refuses to start without keys (it starts; only indexing activation checks keys, `indexing_runtime.py:294`, and login configuration does not check them), key custody or backup, or any table other than the credential table.
- **Not encrypted (Verified, code):** `application_sessions.csrf_secret` (32 raw bytes; the session credential itself is stored only as a SHA-256 digest), `oauth_pending_states` (`code_verifier`, `nonce`; expire after 10 minutes), and all Document, Chunk and conversation text. Anyone who can read the database reads those.
- **Unverified:** whether the hosted keys exist, where they are held, whether they are backed up, whether Railway encrypts the volume, and whether pre-cutover plaintext survives in historical backups (the security README names "historical backups" as a known risk).

### 6. Logging review

Searched as in "Search method" step 5. Result: **no log call writes a token, authorization code, session cookie or File content.**
- **Verified (code):** all log calls are constants, counts, ids and fixed categories. Credential-bearing paths use `log_safe_failure` and `public_error_detail`, which log only `"<operation> failed (<category>)."`, with no exception text and no traceback (`credential_diagnostics.py`). Tests: `test_credential_diagnostics.py` (provider errors, SQL parameters, SDK refresh failures; 14 uses of `caplog`), `test_public_safety.py::test_errors_are_sanitized_logged_and_permit_released`.
- **Verified (code):** SQL parameters are hidden (`hide_parameters=True`, `echo=False`, `db/session.py:16`). The credential repository refuses to read a credential when SQL echo, DEBUG logging or visible parameters are on (`_safe_database`; test `test_unsafe_sql_logging_is_rejected_before_query`).
- **Verified (code, test): the hosted start script disables the access log** (`deploy/start.sh`: `--no-access-log`, with the comment that callback URLs carry `code` and `state`), and the Dockerfile sets `DEBUG=false` and `APP_ENV=production`. New test `test_the_hosted_entrypoint_disables_the_access_log`. **The local default differs:** `AGENTS.md` starts the dev server with `uv run uvicorn ... --reload`, which keeps the access log on, so a local callback URL with `code=` and `state=` is printed to the local terminal.
- **Verified (local run), a gap in the safe-logging rule:** an exception that no route catches becomes a safe 500 through `main.py`'s handler, and the app logs only `API operation failed (unexpected_failure).`. **But Starlette re-raises it, and uvicorn logs `Exception in ASGI application` with the traceback and the exception text.** I ran a local uvicorn (access log off, lifespan off, loopback port) with a throwaway route raising `RuntimeError("<marker>")` on a URL with `?code=...&state=...`: the marker text appeared in the error log, the query string did not. So the safe-logging guarantee covers the application's own log calls, not unhandled exceptions. Whether any reachable exception message contains a secret is **Unverified**: I found none that interpolates a token, code or File text (the `raise X(f"...")` search shows MIME types, file names in extractor errors, and provider error text).
- **Latent, offline only:** `indexing_service.py:260` logs a File name and `str(exc)` of an embedding or vector-store error (`"OpenAI embedding request failed: {exc}"`). Its only callers are `build_index` from the demo loader and the evaluation harness (ticket 03 caller table); the production worker logs a fixed sentence instead (`indexing_worker.py:983`). Provider error text can include masked key fragments or request echoes; not demonstrated.
- **Unverified:** what the hosting platforms record (request logs at the Railway or Vercel edge may include full URLs with callback query strings), log retention, and who can read logs.

### 7. Abuse protection for Owner-mode requests

**Found (code):**
- Indexing admission allows **one unresolved job per account** (409), and `/index/*` is session- and CSRF-protected. This limits indexing concurrency per Owner, not request rate.
- The Google callback bounds the `code` length (4096), and the login flow has bounded Google timeouts (20 s per call, 60 s overall).
- Conversation inputs are bounded (question 4000 characters, title 256, paging limit 100).

**Not found (search method above):**
- **No rate limit, quota, spend cap or concurrency limit for any Owner-mode route.** `DemoChatLimits` returns immediately when `demo_mode` is false (`public_safety.py:34`; the existing test `test_non_demo_limits_disabled_and_production_errors_safe` pins it), and `DemoChatBodyLimit` is likewise demo-only.
- **No size limit on `POST /chat`'s `question`, or on the request body, in Owner mode** (`schemas/chat.py` caps them only in demo mode; `history` is capped at 8 turns of 8000 characters). The conversation endpoints cap `question` at 4000.
- **No limit on `POST /auth/session/google`**: unauthenticated, one committed row per call (KI-032).
- uvicorn runs with `--no-proxy-headers`, so the app sees the proxy's address, not the client's: a per-IP limit would not work as configured. A per-session or per-user limit would.
- The demo limits are process-local (one worker and one replica per `railway.toml`); they would not hold if either were raised.
- Unverified: any limit at the Vercel or Railway edge.

**Recommendation (the Owner decides, per the v1 spec's security-triage item):**
1. First read the two hosted facts in "Sign-up gate". If sign-up is closed (flag off, or a closed consent-screen list) the exposure is small, and a limit is **cleanup, not urgent**.
2. If sign-up is or may become open: add a **per-user request limit and a global daily spend cap** on `POST /chat` and conversation turns before any wider access. Keep it small: a counter keyed on `corpus_user_id` (not on IP) is enough for a single-process deployment.
3. Cap `question` length and the request body in Owner mode (a few lines, using the limits the demo already has).
4. Prune expired login states and limit `POST /auth/session/google` (KI-032).

### 8. Result list

| # | Statement | Label | Evidence |
|---|---|---|---|
| 1 | All 26 mounted operations are listed; every private route carries a session or demo dependency | Verified | code, test (`test_route_authentication_inventory.py`) |
| 2 | Without a session every private route answers 401 in normal mode; session endpoints answer 404 with the flag off and 403 in demo mode | Verified | test |
| 3 | The flag gates issuance (4 endpoints), not validation | Verified | code, test |
| 4 | Hosted value of the session flag and of demo mode | Unverified | ticket 01 unread |
| 5 | The legacy Google router is unmounted and not imported by the application | Verified | code, test |
| 6 | Credentials are stored encrypted only; unconfigured encryption fails closed with no plaintext fallback | Verified | code, test |
| 7 | Hosted encryption keys, custody, backups, volume encryption, historical plaintext in backups | Unverified | not readable from the repository |
| 8 | No log call writes tokens, codes, cookies or File content; SQL parameters are hidden | Verified | code, test (existing) |
| 9 | The hosted start script has the access log off; the local dev start has it on | Verified | code, test (new) |
| 10 | Unhandled exceptions are logged by uvicorn together with their text | Verified | local run |
| 11 | A reachable exception message that contains a secret or File content | Unverified | no instance found; absence is not provable by search |
| 12 | Platform (Railway, Vercel) request logs and retention | Unverified | hosted |
| 13 | The application has no sign-up allow-list; any Google-verified account gets a user and a session when the flag is on | Verified | code |
| 14 | An outsider can reach the paid endpoints of the hosted app | Unverified | needs the hosted flag and the consent-screen state |
| 15 | No Owner-mode rate limit, quota or spend cap; `/chat` question and body unbounded in Owner mode | Verified (absence by search) | code, test (existing, `test_public_safety.py`) |
| 16 | Abandoned login attempts are never deleted by the running application (only consumption removes a row; the one expiry sweep is in the unmounted legacy router) | Defect | KI-032, test |
| 17 | `POST /chat` needs no Origin or CSRF token; `SameSite=Lax` is its only cross-site protection | Verified | code, test (the inventory pins its dependency set) |
| 18 | `/docs`, `/redoc` and `/openapi.json` are public in every mode | Verified | code, local run |
| 19 | `test_existing_application_routes_do_not_use_session_dependencies` checks nothing and is named for the opposite of reality | Defect (test quality, not a product bug) | local run: `app.routes` holds 0 `APIRoute` objects under FastAPI 0.139 |
| 20 | Demo and Owner data are separated only by a dedicated demo database | Verified (code); Unverified (hosted) | code; ADR 0002; ticket 01 |
| 21 | Public sign-up, per-user quotas, Disconnect/Revoke, spend cap | Future | not built; ticket 07, M7, M9 |

### 9. Proposed M0-SEC items for ticket 09 to merge

Urgency follows the spec's rules. None is a hotfix on current evidence. Items 1 and 2 move to **before substantial M1 work** if the Owner's two hosted reads show sign-up is open.

1. **Close or confirm sign-up (decision, then if needed a small allow-list).** Read the two hosted facts. If sign-up must stay restricted independently of Google's consent screen, add an application allow-list of permitted Google subjects or emails, checked in the `LOGIN` callback before `_upsert_user`. Acceptance: an unlisted verified account gets no user row and no session.
2. **Owner-mode limits (Owner decision):** a per-user request limit and a daily spend cap on `POST /chat` and conversation turns; cap `ChatRequest.question` and the body in Owner mode. Acceptance: the existing `test_non_demo_limits_disabled_and_production_errors_safe` is replaced by a test that Owner mode is limited, and an over-long question is refused.
3. **KI-032:** prune expired login states and limit `POST /auth/session/google`. Acceptance: the strict test passes (marker removed, KI-032 moved to Fixed).
4. **Optional hardening:** require `Origin` + CSRF on `POST /chat` in normal mode (demo stays anonymous); disable `/docs`, `/redoc` and `/openapi.json` outside development (the repository is public, so the schema is not secret; this only removes noise).
5. **Logging:** log unhandled exceptions without their text (a catch-all that logs the category only, or a filter on the `uvicorn.error` logger), and make `indexing_service.py:260` use `log_safe_failure`.
6. **Test debt (ticket 09):** delete or rewrite `test_existing_application_routes_do_not_use_session_dependencies` (superseded by the new inventory test), and correct the stale text below.

Documentation corrections found (ticket 09 owns them): `backend/app/security/README.md` ("no existing route uses these dependencies", "`/auth/google` retains single-user behaviour", "inactive"); the docstrings of `api/session_dependencies.py` ("deliberately NOT attached to any current route"), `api/google_session_auth.py` ("existing private APIs are untouched") and `services/application_session_service.py` ("Inactive"); `AGENTS.md` "Known Important Constraints" (the flag gates issuance, not validation; every private route requires a principal whatever the flag says).

### 10. Tests added (no application code changed)

- `backend/tests/security/test_route_authentication_inventory.py`: 48 protective tests, no database, no network, pass today. Route inventory against OpenAPI; each route's dependency set; the legacy router is defined but unmounted and not imported; 401 without a session on 19 routes; 404 on 4 session endpoints with the flag off; with the flag on, `GET /auth/session` is 401 and `POST /auth/session/logout` is 403 without `Origin`/CSRF and 401 with them but no cookie; 403 on 4 session endpoints in demo mode with the flag on; 403 for demo visitors on 13 routes; the hosted start script has `--no-access-log`.
- `backend/tests/known_issues/test_ki032_pending_login_state_growth.py`: 1 strict expected failure (fails today with "3 login attempts expired unfinished and are still stored after a new login started") and 1 passing guard. Needs the disposable PostgreSQL. Shown to be satisfiable with a temporary one-line prune (restored).
- No test was added for: the sign-up gate (needs hosted facts; the code fact is recorded above), the uvicorn traceback (Starlette's re-raise; shown by a local run, and a test would test the framework), `/docs` exposure (a test would pin behaviour the Owner may want to change), or credential encryption (existing tests cover it; listed in section 5).

### Verification (2026-11-21)

- **Focused:** `tests/security/test_route_authentication_inventory.py` 48 passed (no database, no network); `tests/known_issues/test_ki032_pending_login_state_growth.py` 1 passed, 1 xfailed (disposable PostgreSQL 18, loopback, throwaway container, stopped afterwards). `ruff check` and `ruff format --check` clean on both files; `basedpyright` 0 errors on both (project baseline of 48 errors in `tests/` unchanged by these files).
- **Full backend suite, once, on the working tree with PostgreSQL only and `OPENAI_API_KEY` unset:** `2623 passed, 376 skipped, 11 xfailed` in 13 min 10 s, exit 0, no failure. The 376 skips are the tests that need Qdrant (`QDRANT_TEST_URL` and `CONVERSATION_TEST_QDRANT_URL` were not provided, so they skip by design); I did not itemise the skip reasons, so that attribution is unverified. This is not a replacement for the ticket 02 baseline (full containers). The run started before the two flag-on tests were added to the inventory file (46 tests at that moment); the final 48-test file was run separately.
- **Independent review** (Standards and Spec sub-agents, run in parallel): no hard Standards violations. Spec review verified 16 claims true and found four imprecise ones, all corrected above: the escalation wording (nothing was reported mid-audit), the logout and session-inspect statuses (the flag-on tests showed logout answers 403 before 401), the "forever" wording of KI-032, and the cost analysis holding only for the tool-agent path. Judgement-call cleanups applied (clearer helper name, explicit precedence, one predicate for session endpoints, accurate mock comment); left as is: a file-wide `ruff: noqa: F811` and fixtures imported from `test_google_session_postgres.py` (same pattern as KI-031's imports, a conftest move would touch an existing test file).
- **Not run:** mypy on `app` (no application code changed), frontend suite (untouched).

### Caveats (confirmed and unverified, together)

- **Static plus local only.** No hosted system, Railway, Google or OpenAI was contacted. Everything about hosted flags, consent-screen state, keys, backups, edge limits and platform logs is Unverified.
- The route inventory proves which dependencies each route carries and that, without a cookie, each answers 401, 403 or 404 with the database untouched. It does **not** prove isolation between two logged-in users on every route; that rests on the owner filters I read and on existing PostgreSQL tests (`test_private_read_authorization.py`, `test_two_user_rag_end_to_end.py`, `test_conversation_api.py`), which I did not re-derive.
- The frontend was not audited (its role as same-origin proxy is taken from `AGENTS.md`). Next.js route protection, cookie forwarding and `NEXT_PUBLIC_*` exposure are outside this ticket.
- The cost claim in "Sign-up gate" is analysis: I did not send a chat request. That the consent-screen "Testing" list is the intended gate comes from a repository guide, not from the live project.
- The uvicorn run used a throwaway route in an in-process application with the lifespan off. It shows uvicorn's behaviour for unhandled exceptions, not the output of the hosted deployment.
- `test_the_hosted_entrypoint_disables_the_access_log` reads `deploy/start.sh` and the Dockerfile; it does not prove Railway runs that script (a dashboard start command can override the Dockerfile `CMD`; ticket 01).
- The `SameSite=Lax` argument for `/chat` assumes the frontend and the backend are the same site as the browser sees it. On a custom domain with attacker-controllable sibling subdomains it would not hold.
- The disposable PostgreSQL used for the KI-032 test was a throwaway local container, removed afterwards.

## Comments

### Owner decisions on the audit (2026-11-21)

The Owner accepted this ticket and its commit `39ebb46`. The findings above are unchanged. These decisions are the input for the M0-SEC handoff; ticket 09 merges them with the credential-owner items of ticket 03. No fix is implemented by this ticket.

1. **Sign-in (decision).** DriveMind stays a private, single-Owner application. A restricted Google OAuth test-user list may be enough temporarily, but its actual configuration must be verified, not assumed. Before any broader sign-in is allowed, the application must require **explicit application-level authorization** (an allow-list checked in the `LOGIN` callback before `_upsert_user`, as in proposed item 1). The test-user list is a temporary external control, not the authorization model.
2. **Rate limits and spending (decision: add as an M0-SEC requirement).** Simple backend protection for Owner-mode paid requests. Requirements: it must cover **both the legacy linear path and the tool-agent path** (the audit only traced the tool-agent path for cost, so the linear path, including `POST /chat` without conversation turns, must be traced when this is specified); limits are derived from **measured usage and cost**, not guessed; no complicated infrastructure (a small in-process counter keyed on the authenticated owner, as in the recommendation, is the starting point). Proposed item 2 is amended accordingly.
3. **KI-032 (decision).** Stays registered. The M0-SEC proposal states both implications: security (an unauthenticated request can create a stored row per call while sessions are enabled; no data exposure) and storage (unbounded table growth). Proposed item 3 covers expired-state pruning plus a limit on `POST /auth/session/google`.
4. **CSRF on `POST /chat` (decision: assess, do not assume).** The inconsistency (cookie-only, no `Origin` or `X-CSRF-Token`, unlike every other mutation) is recorded for a **focused risk assessment**. `SameSite=Lax` is not assumed to make every request safe: the assessment must cover the real deployed site layout (frontend and backend hosts, any custom domain or sibling subdomains), same-site cross-origin requests, and what a forged request can do (spend credits, write query history). Proposed item 4 is promoted from "optional hardening" to "assessment, then fix if the risk is real". Demo mode stays anonymous.
5. **Hosted configuration (decision).** Ticket 01 must verify the relevant Railway flags (at least `GOOGLE_APPLICATION_SESSIONS_ENABLED`, `DEMO_MODE`, `TOOL_RAG_AGENT_ENABLED`). **Google's OAuth publishing state and test-user restrictions must also be checked before the private beta is declared safe.** Note for planning: those Google facts are read in the Google Cloud console, not Railway, and ticket 01's current scope lists only Railway facts. They are tracked here as an Owner dashboard checklist item and are not yet inside ticket 01's own checklist; the Owner decides whether to add one line to ticket 01 (this ticket does not edit it).
6. **Escalation (standing rule for the hosted reads).** If the confirmed configuration exposes private data or permits unauthorized paid usage, it is reported to the Owner immediately, with a proposed separately approved hotfix (outside M0's read-only diff). Until both hosted facts are read, the sign-up exposure stays **Unverified**.

**Owner dashboard checklist (read-only, no Railway command needed from this ticket):** (a) hosted value of `GOOGLE_APPLICATION_SESSIONS_ENABLED` (ticket 01); (b) Google Cloud console, OAuth consent screen: user type, publishing status (Testing or In production), and the exact test-user list; (c) hosted value of `TOOL_RAG_AGENT_ENABLED` (decides which answering path a paid request takes).

**Status:** ticket 04 is closed (`Progress: resolved`). No blocker for ticket 05.

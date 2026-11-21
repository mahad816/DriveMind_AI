# M0 system audit: consolidated report

**Spec:** `docs/specs/m0-system-audit.md`. **Tickets consolidated:** `docs/tickets/m0-system-audit/01` to `08`. **Written:** 2026-11-21, on branch `feature/v2-state-performance` (HEAD `ca35ae3` when this report was written).
**Audited commit:** `7197af4` is the baseline commit of ticket 02; later M0 tickets added tests, a CI workflow and documents on top. Application code, migrations, the frontend and the infrastructure files are identical at `bf15b20`, `7197af4` and HEAD (`git diff bf15b20 HEAD -- backend/app backend/alembic backend/evaluation frontend infra backend/pyproject.toml backend/deploy` is empty). M0 changed no application behavior.

This repository is public. This report holds no secrets, connection strings, hosted identifiers, e-mail addresses or private Drive content. Hosted facts are statuses, yes/no, counts, or "set / not set".

## How to read this report

- **Labels** (v1 spec): **Verified** (confirmed by the evidence named), **Defect** (a known problem), **Unverified** (not established; do not state as fact), **Future** (not built, not a defect).
- **Evidence types:** *code* (read in source), *test* (asserted by a named test), *local run* (a command run on this Mac against local code), *Git comparison*, *repo doc* (stated in a document, not re-checked), *Owner-reported* (the Owner read a dashboard on 2026-11-21 and told the assistant; not independently seen), *hosted read (CLI)* (a read-only Railway command the Owner approved), *analysis* (reasoning from code, not exercised), *code search* (a grep or name search; a null result is not proof), *none* (no evidence was gathered; always `Unverified`).
- **Terms.** *Fail open*: when a check itself breaks, the answer is let through; *fail closed*: it is refused. *Allow-list*: a list of accounts permitted to sign in. *CSRF*: a forged request sent from another site using the victim's logged-in cookie. *Strict expected failure*: a test that states the correct behavior and is expected to fail until the bug is fixed (it turns the suite red when the bug is fixed, so the registry gets updated). *KI-nnn*: an entry in `docs/KNOWN_ISSUES.md`. *M0-SEC*: the proposed security follow-up (section 4). *Owner*: the project owner. *Claim check*: a second model call that removes unsupported statements from an answer. *Alembic head*: the newest database migration.
- A **pointer** names the ticket section that holds the full evidence (`T04 §1` = ticket 04, section 1) and, where it helps, a file, symbol or test. A search that found nothing is not proof of absence.
- **No finding was invented here.** Everything below comes from the tickets' `## Findings` and `## Comments` (including the Owner decisions). Where this report adds judgement (ordering, assignment to milestones), it says "proposal".

## 1. What the Owner needs to know

1. **No reachable vulnerability was found, and no escalation was needed** (section 3). Every mounted private route resolves its owner from a verified session principal, and every data read traced filters on that owner.
2. **Six "first stored credential" fallbacks exist, all latent.** No live request, job, startup task or script reaches them, because every production caller passes an owner. With two or more owners holding credentials, a future caller that forgets the owner would act on an arbitrary owner's credential (KI-031).
3. **Sign-in has no application allow-list.** With `GOOGLE_APPLICATION_SESSIONS_ENABLED` on, any Google account that Google lets through becomes a user with a session and can call paid endpoints. Today only the Google test-user list (4 accounts, Owner-reported) guards this. **Nothing is deployed**, so the exposure is dormant until a redeploy.
4. **Owner mode has no rate limit, spend cap or request-size limit.** The tool-agent path has no early exit for an empty corpus, so each such question probably costs a paid call (analysis). The linear path was not traced.
5. **The production answering path is the tool agent**, not the code default (linear). The claim check **fails open**: if its provider call fails, an unchecked answer is published. The Owner decided this is not acceptable for release (section 6, D5-3).
6. **Deleting a conversation hides it; it removes nothing.** There is no backend Disconnect, Revoke or Delete-stored-data path. Logout revokes one session row and leaves the Google credential and all data.
7. **Preparation never starts by itself (Verified).** The v1 spec's Preparation requirements are mostly partial or missing; Unsupported files are never shown, because they are never stored.
8. **Railway:** all four services are offline and the Owner will rebuild it cleanly. Most hosted facts are Owner-reported or `Unverified`, by the Owner's decision. A deploy of HEAD would turn the claim check on and does not run migrations.
9. **Baseline:** all 2927 backend tests pass in the right environment (qualified, section 2.A6). A small free CI workflow exists and is verified locally only.

## 2. Findings by audit area

### A1. Answering paths and flags (T05, T01 H2 to H10)

| # | Finding | Label | Evidence | Pointer |
|---|---|---|---|---|
| A1.1 | With `TOOL_RAG_AGENT_ENABLED` on, every question goes to the tool agent before the top-level router runs. `AGENT_GRAPH_ENABLED` and `HYBRID_RETRIEVAL_ENABLED` have no effect on it (the agent always builds a hybrid retriever) | Verified | code | T05 §1, `rag_service.py` (`ask`), `tool_agent_service.py` |
| A1.2 | Local defaults (`tool_rag_agent_enabled=False`) answer through the legacy linear path with six router outcomes (chitchat, file inventory, file target, grounded, conversation-history recall, collection summary). The developer's own `.env` was not read | Verified (code defaults) | code | T05 §1, §2 |
| A1.3 | Hosted flag values: tool agent on, graph off, hybrid on, claim check not set (HEAD default: on), backend streaming on, indexing on, sessions on, demo off. Chat model `gpt-4o-mini`, embedding `text-embedding-3-small`, claim-check model not set (default `gpt-5.4-mini`). The frontend build flags `NEXT_PUBLIC_CHAT_STREAMING_ENABLED` and `NEXT_PUBLIC_DEMO_MODE` were not read | Unverified (Owner-reported values, no independent read) | Owner-reported, 2026-11-21 | T01 §1 H2 to H10 |
| A1.4 | Per route on the production path: chitchat is a server-owned reply after an intent model call; file inventory is rendered deterministically from the metadata result; file target and grounded go through agent tools, the claim check and citation finalization. Which kind a question "is" is a model decision, not a code branch | Verified | code, test | T05 §2 |
| A1.5 | `/chat`, `/conversations/{id}/turns` and `/turns/stream` all call `RagService.ask` with the same settings, so they reach the same path. Streaming changes only how the agent's model call is made. `/chat` is the demo UI's endpoint; the normal UI uses conversation turns | Verified | code | T05 §3 |
| A1.6 | Provider failure of the answering model on the production path (first call, after evidence, during the citation-correction retry): HTTP 503, nothing saved, no legacy fallback. Reading "ungrounded" as "not built from retrieved evidence with validated citations", the requirement holds | Verified | test: `tests/test_provider_failure_paths.py` (3 cases); legacy path by code reading | T05 §4 |
| A1.7 | Claim-check provider failure fails **open**: the answer is published unchecked, with its citations. A stricter reading of "ungrounded" makes this a defect | Defect (by Owner decision D5-3; not yet in the registry) | test: `test_claim_check_model_failure_publishes_the_unchecked_answer` (characterises today's behavior) | T05 §4, Owner decision 3 |
| A1.8 | Eight documentation contradictions (section 7) | Defect (documentation) | code vs docs | T05 §5 |
| A1.9 | Hosted state is HEAD plus Owner-reported flags; nothing is deployed (T01 H1, H14) | Verified (CLI status) | hosted read (CLI) | T01 §1 |

### A2. Authentication, ownership and credential fallbacks (T03, T04)

**Fallbacks (T03).** Search: every `select(GoogleOAuthToken)`, every `limit(1)`, `.first()`, `select(User)` in `backend/app`, then every caller of each entry method in `backend/app` and `backend/evaluation`. All six are classified **Latent unsafe behavior**; none is a reachable vulnerability.

| # | Location | Production callers | Test |
|---|---|---|---|
| 1 | `services/user_resolution.py` (`resolve_active_user`) | owner-less only in demo-only code (`demo/service.py`, `demo/load.py`); normal-mode callers pass an owner | KI-031 `[user_resolution]` |
| 2 | `services/drive_sync_service.py` (`_resolve_user`) | routes via `require_resource_user`; worker passes `claim.user_id`; `sync_metadata` and `get_latest_sync_job` have no production caller | `[drive_sync]` |
| 3 | `services/drive_content_service.py` | `api/files.py`; worker (raises unless the owner is a `UUID`); ingestion | `[drive_content]` |
| 4 | `services/chunking_service.py` | none (the worker calls a lower-level method) | `[chunking]` |
| 5 | `services/ingestion_service.py` | none (same) | `[ingestion]` |
| 6 | `services/indexing_service.py` | demo loader and evaluation harness, both pass an id | `[indexing]` |

Label: **Defect** (latent), evidence: test `tests/known_issues/test_ki031_credential_owner_fallback.py` (6 strict expected failures, 12 passing guards) and `tests/security/test_owner_fallback_callers.py` (10 protective tests, no database; they are tripwires and cannot see a variable that is `None` at run time). Other unfiltered selects (`demo/service.py`, `evaluation/runner.py`) are safe. Pointer: T03 "Fallback table". The v1 spec said **four**; the verified count is **six**.

**Routes and access control (T04).**

| # | Finding | Label | Evidence | Pointer |
|---|---|---|---|---|
| A2.1 | 26 mounted operations plus 3 framework documentation routes; every private route carries a session or demo dependency; without a session each answers 401 (normal mode), 403 (demo mode, indexing and conversations) or 404 (session endpoints, flag off) | Verified | test: `tests/security/test_route_authentication_inventory.py` (48 tests) | T04 §1 |
| A2.2 | The session flag gates **issuance** (four `/auth/session/*` endpoints), not validation. Flag off means "locked" (every private route 401), not "legacy single-user", except that sessions already in the database stay valid until they expire (7 days). No CORS middleware exists; the demo-session issuer (`issue_demo`) is unused | Verified | code, test | T04 §2 |
| A2.3 | One router is defined and unmounted (`app/api/auth.py`, legacy Google OAuth); nothing in `backend/app` imports it; its paths return 404 | Verified | code, test, existing `test_auth_google.py::test_legacy_oauth_routes_unreachable` | T04 §3 |
| A2.4 | Session cookie: 32 random bytes, only the SHA-256 digest stored, `HttpOnly`, `Secure`, `SameSite=Lax`; fresh database lookup every request; mutations need exact `Origin` and a session-bound CSRF token; 7-day lifetime | Verified | code, test | T04 §4 |
| A2.5 | **No sign-in allow-list.** The `LOGIN` callback upserts a user for any Google-verified identity. The only gate is Google's consent screen. This is a cost-abuse exposure, not an isolation failure | Verified (code reading) | code | T04 "Sign-up gate" |
| A2.6 | Google consent screen (Owner-reported): External, **Testing**, **4** listed test users, all described as intended; 6 lifetime users of the client. Conclusion when the backend runs: sign-in is "closed only by the Google test-user list" | Unverified (Owner-reported; the list lives outside the repository) | Owner-reported, analysis | T01 §2 G1 to G4 |
| A2.7 | Credentials are stored **encrypted only** (`encrypted_credentials NOT NULL`; plaintext columns dropped by migration `20261011_1200`). With no keys configured, every credential read and write fails closed; there is no plaintext fallback and no generated key. The application starts without keys; only indexing activation checks them | Verified | code, test: `test_encrypted_only_credentials.py`, `test_google_credential_crypto.py` | T04 §5 |
| A2.8 | Not encrypted: `application_sessions.csrf_secret`, `oauth_pending_states` (verifier, nonce), all Document, Chunk and conversation text | Verified | code | T04 §5 |
| A2.9 | Hosted encryption keys, custody, backups, volume encryption, plaintext in historical backups | Unverified | not readable from the repository | T04 §5 |
| A2.10 | No log call writes a token, authorization code, session cookie or File content; SQL parameters are hidden; the hosted start script disables the access log (the local dev command does not) | Verified | code, test | T04 §6 |
| A2.11 | An exception no route catches is logged by uvicorn **with its text** (Starlette re-raises after the safe 500). Whether any reachable message contains a secret is not established | Verified (behavior, local run); Unverified (a secret in a message) | local run | T04 §6 |
| A2.12 | `indexing_service.py` logs a file name and `str(exc)` of an embedding or vector-store failure; only offline callers reach it (demo loader, evaluation) | Defect (latent, offline only) | code | T04 §6 |
| A2.13 | **No Owner-mode rate limit, quota, spend cap or body limit.** `POST /chat` `question` is unbounded in Owner mode (conversation endpoints cap it at 4000). The demo limiter is separate and process-local; uvicorn runs with `--no-proxy-headers`, so a per-IP limit would not work | Verified (code reading; null search) | code search, test (`test_public_safety.py`) | T04 §7 |
| A2.14 | The tool-agent path has no early exit for an empty corpus; each question from a signed-in account with no files probably costs a paid call. The linear path was **not** traced | Unverified (analysis) | analysis | T04 "Sign-up gate" |
| A2.15 | `POST /chat` is authenticated by cookie only: no `Origin` or CSRF token, unlike every other mutation. `SameSite=Lax` is its only cross-site protection | Verified | code, test (inventory pins the dependency set) | T04 §1 |
| A2.16 | Abandoned login attempts are never removed by the running application, and `POST /auth/session/google` is unauthenticated and unlimited: KI-032 | Defect | test: `tests/known_issues/test_ki032_pending_login_state_growth.py` | T04 §8 #16 |
| A2.17 | `/docs`, `/redoc`, `/openapi.json` are public in every mode | Verified | code, local run | T04 §1 |
| A2.18 | Demo and Owner data are separated only by a dedicated demo database. Whether the hosted demo is isolated is not known | Verified (code); Unverified (hosted) | code, ADR 0002 | T04 §4 |
| A2.19 | `test_existing_application_routes_do_not_use_session_dependencies` (`tests/security/test_session_security.py`) checks nothing under the pinned FastAPI (`app.routes` holds no `APIRoute`) and is named for the opposite of reality | Defect (test quality) | local run | T04 §8 #19 |
| A2.20 | Public sign-up, per-user quotas, Disconnect/Revoke, spend cap | Future | not built | T04 §8 #21 |

**Real current vulnerabilities versus scalability concerns (spec requirement).** *Current vulnerabilities:* none found. *Conditional (dormant while nothing is deployed):* A2.5 with A2.13 and A2.14 (cost abuse). *Latent, multi-owner only:* the six fallbacks and KI-033. *Hygiene:* A2.11, A2.12, KI-032.

### A3. Preparation and File states (T06)

| # | Finding | Label | Evidence | Pointer |
|---|---|---|---|---|
| A3.1 | Nothing starts a Drive check or Preparation by itself. Jobs come only from `POST /index/{sync,ingest,chunk,build}`; frontend callers are button handlers; effects only read status. Nuance: jobs already `QUEUED` resume after a restart | Verified (search, not proof of absence) | code search | T06 §2 |
| A3.2 | `INDEXING_ENABLED` (default off) gates the worker: off means every index POST answers 503. On, startup validates a long list of conditions and refuses to start otherwise | Verified | code | T06 §1 |
| A3.3 | The UI prepares at most 5 files per queue, one file at a time, three stages, with explicit confirmation. `prepareKnowledge`, `prepareSingleFile` and `AdvancedDiagnostics` have no non-test caller, so `/index/pending` has no UI consumer | Verified | code | T06 §1 |
| A3.4 | v1 spec requirements 12 to 18: **exists** 12, 16a, 16b, 17b; **partial** 13, 15, 16d, 16g, 18c, freshness; **missing** 14 (exclusions), 16c (unsupported), 16e (outdated), 17a (last Preparation time shown), 17c ("index may be outdated"), 18a, 18b | Verified | code | T06 §3 |
| A3.5 | Unsupported files are **not shown** to the Owner: sync filters them before any row exists | Verified | code | T06 §3 |
| A3.6 | One `skipped` value mixes: removed or trashed in Drive, type no longer supported, missing at a full sync, empty text, zero chunks, scanned PDF | Defect (plan for M6) | code | T06 §3 16f |
| A3.7 | The UI refuses to re-prepare `indexed`, `failed` and `skipped` files ("conservative beta policy"). A stale-pipeline file cannot be re-prepared from the UI | Defect (temporary policy, Owner decision D6-1) | code | T06 §3 row 15 |
| A3.8 | Reprocessing triggers (none triggered): raising `EXTRACTION_PIPELINE_VERSION` (now 3); applying migration `20261120_1200` (labels every existing document version 1, so all become stale); changing the embedding model (same dimension: old and new vectors mix silently; different dimension: startup refused); restart (resumes queued jobs only); any Drive check (resets edited and every still-listed `SKIPPED` file to `DISCOVERED`) | Verified (code reading) | code | T06 §5 |
| A3.9 | Scale of any re-read or re-embedding | Unverified | no safe count exists; PostgreSQL volume was 0.2 GB (bounds the corpus, not a cost) | T06 §5, T01 H14 |

### A4. Conversations, deletion and privacy (T07)

| # | Finding | Label | Evidence | Pointer |
|---|---|---|---|---|
| A4.1 | **Deleting a conversation does not remove its linked query history.** `DELETE /conversations/{id}` sets `deleted_at`; the conversation, every turn (with question text) and the `query_history` row (answer, citations) stay | Verified | test: `tests/security/test_conversation_deletion_privacy.py::test_conversation_delete_keeps_every_row_today` | T07 §2 |
| A4.2 | Logout revokes one session row. Credential, Drive metadata, documents, chunks, jobs, conversations, query history, Qdrant points and browser records stay | Verified | test: `test_logout_revokes_only_the_session_row_today` | T07 §2 |
| A4.3 | **No backend Disconnect, Revoke or Delete-stored-data path found.** The only DELETE route is the conversation soft delete. "Disconnect" in the interface is a link to Google Account permissions. Search: OpenAPI route list, grep for delete/cascade/revoke/disconnect in `backend/app` and migrations, `backend/app/ops/`, frontend strings | Verified (null search, not proof) | test: `test_only_one_delete_route_exists_and_none_is_named_disconnect_revoke_or_purge`; code search | T07 §3 |
| A4.4 | Storage inventory: PostgreSQL (users, credentials, sessions, login attempts, drive files, documents with full extracted text, chunks, jobs, conversations, turns, query history), Qdrant (embedding plus payload with filename and `user_id`, no chunk text), browser `localStorage` (preparation and discovery progress; logout removes none of it). There is **no owner-level deletion action** for any item. What does delete rows: login attempts when their callback consumes them (abandoned ones are never swept, KI-032), and per-file chunk and vector reconciliation. Nothing deletes session rows (logout only sets `revoked_at`), and the conversation soft delete only hides. Demo mode also keeps conversation and message text in `localStorage` (`drivemind:demo:*`, per-conversation delete in the demo sidebar); `drivemind:connected-email` has helpers but no mounted reader or writer | Verified | code | T07 §1 |
| A4.5 | `POST /chat` without a conversation writes a query-history row that no conversation links to and no route deletes (the mounted UI calls `/chat` only in demo mode, where persistence is off) | Verified (code reading) | code | T07 §1 |
| A4.6 | An owner who has submitted one question cannot be deleted from `users` (two foreign keys without `ON DELETE`): KI-033. Not reachable today | Defect | test: `tests/known_issues/test_ki033_user_delete_blocked_by_turns.py` (2 strict expected failures) | T07 verdict 4 |
| A4.7 | History received by the answering path: server-side, completed turns only; at most 4 pairs fetched (8000 characters each, 24000 total); the model-facing steps get the last 6 messages (3 pairs), 6000 characters; the tool agent masks identifiers in prior messages and does not replay tool calls | Verified (code only) | code, test | T07 §4 |
| A4.8 | Whether that history is enough for follow-ups | Unverified | evaluation question (M1/M4) | T07 §4 |
| A4.9 | Backups, platform logs, retention, OpenAI and Google copies; Qdrant behavior (code reading only, no container used) | Unverified | not inspected | T07 §6 |

### A5. Railway and migration state (T01)

| # | Finding | Label | Evidence | Pointer |
|---|---|---|---|---|
| A5.1 | No backend deployment is active: the three newest backend deployments (latest 2026-10-26) are `REMOVED`, and frontend, backend, Qdrant and PostgreSQL all show `Offline`. That this is intentional is the Owner's statement | Verified (status); Owner-reported (intent) | hosted read (CLI), 2026-11-21 | T01 H1, H14 |
| A5.2 | Deployed commit and branch of the removed deployments | Unverified (the CLI output has no such field; further reading deferred by Owner decision) | none | T01 H1 |
| A5.3 | Hosted Alembic revision; managed-backup status; document, file, user and session counts | Unverified (deferred by Owner decision: the environment is disposable and will be rebuilt) | none | T01 H11, H12, H15 |
| A5.4 | `main` is an ancestor of HEAD; HEAD was 164 commits ahead at ticket 01. Ten Alembic migrations are not on `main`; one head, `20261120_1200` | Verified | Git comparison | T01 §3 |
| A5.5 | A deploy does not migrate (`deploy/start.sh` runs only `uvicorn`). With indexing on and a database below `20261120_1200`, startup probably refuses ("SCHEMA_INCOMPATIBLE") | Verified (code: no migration); Unverified (analysis: the refused start) | code | T01 §3 points 1, 6 |
| A5.6 | A deploy of HEAD turns the claim check on (default on, hosted value unset): one extra paid small-model call per tool-agent answer. Chat and embedding models do not change (set explicitly on Railway) | Verified (code: the default is on); Unverified (analysis: the extra paid call; hosted value Owner-reported) | code, analysis | T01 §3 |
| A5.7 | Migrating an existing database labels every document version 1 (code at 3): the next Prepare could trigger paid re-embedding for changed files. On a fresh database this does not arise | Verified (code: migration default 1, code at 3); Unverified (analysis: the re-embedding cost, not exercised) | code, analysis | T01 §3 point 2, T06 §5 |
| A5.8 | Whether the retrieval thresholds, activation target and keyring on Railway match HEAD: not read | Unverified | none | T01 §3 |

### A6. Tests, baseline and CI (T02, T08)

| # | Finding | Label | Evidence | Pointer |
|---|---|---|---|---|
| A6.1 | Baseline on `7197af4`: backend `2923 passed, 1 failed, 3 skipped` in 24 min 9 s. The failure and the three skips were test-environment problems; with `OPENAI_API_KEY` absent the failing test passes (3 of 3), and with Qdrant at exactly `http://127.0.0.1:61448` the skipped file ran 32 passed, 0 skipped. **Qualified baseline:** all 2927 pass in the right environment, shown by the full run plus two focused re-runs, not by one clean full run | Verified | local run | T02 "Baseline" |
| A6.2 | Static checks: `ruff check`, `ruff format --check`, `mypy app` clean; `basedpyright` clean on `app/` only, **48 errors, all in `tests/`** (the preserved baseline, not a target). Frontend: 876 tests, lint and build pass | Verified | local run | T02 |
| A6.3 | Dependency groups (counts at ticket 02): needs nothing 2174 (53 s wall without one 155 s test); needs PostgreSQL (some also Qdrant) 753, about 21 min summed; needs network 0; needs a paid API 0. The 753 include the ownership, session, indexing-job and vector-isolation tests in `tests/security` | Verified | local run | T02 "Tests grouped by dependency" |
| A6.4 | A test fails when `OPENAI_API_KEY` is exported (`test_http_graph_strategy_plans`); three tests hard-code the Qdrant URL `http://127.0.0.1:61448` and skip on any other port | Defect (test environment) | local run | T02 F1, F2 |
| A6.5 | CI: one workflow, `.github/workflows/ci.yml` (push to `main`, pull request, manual). No secrets, no `OPENAI_API_KEY`, no evaluation, no deploy; a guard fails the job if the key is set. Backend job: ruff, format, mypy, `basedpyright app`, container-free pytest; frontend job: `npm ci`, test, lint, build. **Verified by running the commands locally on a clean export only; not run on GitHub** | Verified (local); Unverified (hosted) | local run | T08 |
| A6.6 | On a clean checkout **four** container-free tests fail for local-state reasons and the workflow deselects them: `test_agent_smoke.py::test_frozen_sixteen_case_gold_and_identities` (needs a commit that is not an ancestor of HEAD) and three in `test_cli_corpus.py` (need git-ignored public PDFs). Ticket 02's "skips on a clean checkout" holds for one test only | Defect (test environment) | local run | T08 "Failures found" |
| A6.7 | A green CI run does not exercise the skipped PostgreSQL/Qdrant tests (785 in ticket 08's CI-style run; 753 at the ticket 02 baseline, the difference being tests added by M0 tickets 03 to 07) (ownership, session, indexing, isolation). The container suite (about 24 min) stays a local checkpoint run | Verified | local run | T02, T08 |
| A6.8 | **CI cost:** free for standard GitHub-hosted runners in public repositories (`gh repo view` reported the repository as PUBLIC on 2026-11-21). Source: GitHub billing documentation, https://docs.github.com/en/billing/concepts/product-billing/github-actions, read 2026-11-21. If the repository became private, usage would count against the plan's included compute | Verified | repo doc (official GitHub page) | T08 |
| A6.9 | Evaluation-only issues: KI-022 (keyword half) and KI-030 (chunk-level proxy) have strict expected-failure tests; KI-027, KI-028 and KI-029 need a real model or embeddings and stay RAG evaluation cases | Verified | test, analysis | T02 "Known-issue feasibility" |

## 3. Security escalation record

| When (PKT, 2026-11-21) | Where | Result |
|---|---|---|
| 13:36 | T03, after the last caller was traced | No reachable vulnerability. Nothing to escalate |
| 14:05 | T04, after the last route, dependency and log site was read | No reachable authentication or data-isolation vulnerability. A conditional cost-abuse exposure (A2.5, A2.13) was identified at the end of the pass; it was **not** reported mid-audit because it was unconfirmed (it depended on two unread hosted facts). No time was recorded for the report to the Owner; it is reported in the closing session report of ticket 04 and here |
| 2026-11-21 (Owner's dashboard reads) | T01 | With the Owner-reported flags and consent screen, sign-in is "closed only by the Google test-user list", and no backend is running. No vulnerability reachable through the hosted configuration was confirmed. No hotfix proposed |

No exploit was run against any hosted system. No hotfix was needed, and no change outside the audit's read-only boundary was made.

## 4. Proposed M0-SEC

> **Addendum (2026-11-22).** This section is kept as written on 2026-11-21: a dated proposal. The Owner approved it (with changes) as the milestone `docs/specs/m0-sec-security-hardening.md`, tickets in `docs/tickets/m0-sec-security-hardening/`. What was built and verified, and what remains deferred, is recorded in that spec and in ticket 09 (`## Findings`). Where this section says a fallback, limit or CSRF gap is open, it describes the code as audited, not as it is now.

This section is a **proposal**. The Owner decides scope and timing. It merges ticket 03's fallback items with ticket 04's items and the Owner decisions on both.

**Urgency.** None is a hotfix: nothing is reachable and nothing is deployed. The spec's rule puts *latent but unsafe* items (the six fallbacks, KI-031) before substantial M1 implementation; that ordering is the spec's, not an Owner decision. The Owner decided only that the allow-list (D4-1) and the Owner-mode limits (D4-2) are M0-SEC requirements. The spec has no "dormant" category: the allow-list, limits and KI-032 matter only once the backend runs again with sessions on. Ticket 04 said that if sign-up is closed the limit is "cleanup, not urgent", and the Owner-reported consent screen (Testing, 4 listed users) is closed-ish; I still propose them before M1 because the Owner made them requirements, the fixes are small, and a redeploy would otherwise carry them unprotected. Items 6 and 7 (logging, test debt) are cheap hygiene that I propose to batch here; they could wait without risk. Item 5's values need M1 data (marked).

**Scope, in proposed order** (cheapest and most certain first; the ordering is mine, the content comes from the tickets):

| # | Item | Source | Acceptance criteria |
|---|---|---|---|
| 1 | **Make the owner mandatory** in the six services: required `uuid.UUID`, raise `ValueError("An explicit corpus owner is required")` for `None` or a non-UUID, delete the `select(GoogleOAuthToken).limit(1)` branches; keep the demo branches of `resolve_active_user`. Delete or require an owner on the four production-dead entry points (`sync_metadata`, `get_latest_sync_job`, `chunk_documents`, `ingest_files`). Replace `test_normal_mode_preserves_first_oauth_token_resolution`; give about 60 owner-less unit-test calls an owner | T03 | No unscoped `select(GoogleOAuthToken)` remains in `backend/app` (allow-list shrinks to `demo/service.py`). Each of the six entry points raises `ValueError` with `user_id=None` and reads no credential. The six KI-031 markers are removed and pass; the 12 guards keep passing. No route, schema, status or citation contract changes; suite, ruff, mypy no worse than the baseline; basedpyright 48 errors, all in `tests/` |
| 2 | **Application-level sign-in allow-list**, checked in the `LOGIN` callback before `_upsert_user` (Owner decision D4-1: the Google test-user list is a temporary outer control only) | T04 item 1 | An unlisted, Google-verified account gets no user row and no session; a listed account still signs in |
| 3 | **KI-032:** prune expired login states and limit `POST /auth/session/google`. Security implication: an unauthenticated request can create one stored row per call while sessions are enabled; storage implication: unbounded growth; no data exposure (D4-3) | T04 item 3 | The KI-032 strict test passes with its marker removed; the guard still passes; KI-032 moves to Fixed |
| 4 | **Assess, then fix if real: CSRF on `POST /chat`** (D4-4). The assessment covers the real frontend and backend hosts, any custom domain or sibling subdomains, same-site cross-origin requests, and what a forged request can do (spend credits, write query history). Do not assume `SameSite=Lax` is enough. Demo mode stays anonymous | T04 item 4 | A written assessment against the real site layout; if the risk is real, `Origin` plus `X-CSRF-Token` on `/chat` in normal mode with a test |
| 5 | **Owner-mode limits and spend cap** (D4-2): a small in-process counter keyed on the authenticated owner, covering **both the tool-agent path and the linear path** (including `POST /chat` without conversation turns, which was not traced); a cap on `question` length and request body in Owner mode. **Limit values come from measured usage and cost, not guesses**, so the mechanism and the question cap can be built first and the numbers set after M1 measurements; the limits must exist before any redeploy with sign-in on | T04 items 2, D4-2 | `test_non_demo_limits_disabled_and_production_errors_safe` replaced by a test that Owner mode is limited; an over-long question is refused; the linear path's cost is traced and recorded; values cite measurements |
| 6 | **Logging:** log unhandled exceptions without their text (catch-all or a filter on the `uvicorn.error` logger); make `indexing_service.py` use `log_safe_failure` | T04 item 5 | A test shows an unhandled exception's text is not logged; no log call formats provider error text |
| 7 | **Test debt:** delete or rewrite the vacuous `test_existing_application_routes_do_not_use_session_dependencies` (superseded by the inventory test) | T04 item 6 | The test no longer claims what it does not check |
| 8 | **Docstring and README corrections in application code** that the audit proved wrong: `api/session_dependencies.py`, `api/google_session_auth.py`, `services/application_session_service.py`, `RagService` class and `ask` docstrings (A1.8). Ticket 09 changed no application code, so these wait here | T04, T05 | Docstrings match the code |

**Optional hardening (the Owner's call):** disable `/docs`, `/redoc` and `/openapi.json` outside development (noise only; the repository is public).

**Out of M0-SEC (assigned elsewhere):** Disconnect, Revoke and Delete stored data, KI-033 (M7); claim-check fail-closed (M3); Railway rebuild requirements (M9, section 6 D1-F).

## 5. Risk register: nothing is lost

Every risk found by the audit, with its owner milestone. "Proposal" means the assignment is mine; "Owner" means the Owner decided it.

| Risk | Where recorded | Assigned to |
|---|---|---|
| Six credential fallbacks (KI-031) | A2, T03 | M0-SEC item 1 (proposal, from the spec's urgency rule for latent items) |
| No sign-in allow-list; test-user list is the only gate | A2.5, A2.6 | M0-SEC item 2 (Owner) |
| No Owner-mode limit, spend cap, body limit; linear path cost not traced | A2.13, A2.14 | M0-SEC item 5 (Owner: add as requirement); values after M1 (proposal) |
| `POST /chat` without CSRF | A2.15 | M0-SEC item 4 (Owner: assess first) |
| KI-032 login-state growth | A2.16 | M0-SEC item 3 (Owner) |
| Unhandled-exception text in logs; offline log of provider error text | A2.11, A2.12 | M0-SEC item 6 (proposal) |
| Claim check fails open | A1.7 | M3 (Owner decision D5-3: fail closed; proposal recorded in T05). Noted (without a registry entry) in `docs/KNOWN_ISSUES.md` until M3 turns the characterisation test into a strict expected failure |
| Production path differs from code default; evaluation must target the agent | A1.1, A1.2 | M1 (Owner: every evaluation sets `TOOL_RAG_AGENT_ENABLED=true` and states the flags) |
| Single production path, linear and LangGraph kept until M9 | A1 | M9 disable, M10 remove (Owner decision D5-1) |
| Conversation delete only hides; no Disconnect, Revoke, Delete stored data; browser records survive logout; KI-033 | A4 | M7 (Owner: separate actions, permanent delete, retention rules written before any claim) |
| Backups, provider-side copies, platform logs, retention | A4.9, A2.9 | M7 / M9 (Unverified; read when the environment is rebuilt) |
| Preparation requirements missing or partial (exclusions, Unsupported, outdated, failure reasons, `skipped` mixing, re-preparation) | A3 | M6 (Owner D6-1 to D6-4) |
| Embedding model or dimension mixing is silent | A3.8 | M6 or the milestone that owns indexing correctness (Owner: record in the appropriate milestone; **proposal: M6**) |
| Reprocessing safety: keep the last usable version until a replacement succeeds | A3.7, A3.8 | M6 (Owner D6-6) |
| Manual initiation must stay | A3.1 | M6 (Owner D6-3) |
| Conversation history sufficiency (3 pairs and 6000 characters reach the model; the agent does no rewrite) | A4.7, A4.8 | M4 (evaluation) |
| Railway: clean rebuild, validated variables, one migration run, security controls before real data, cost limits, backups | A5, T01 §4 | M9 (Owner decision D1-F), after M0-SEC |
| Claim check turns on at the next deploy | A5.6 | M9 (set `CLAIM_CHECK_ENABLED` explicitly) |
| CI never run on GitHub; four deselected tests; skipped PostgreSQL tests; actions pinned to tags | A6.5 to A6.7 | M9 (expanded CI, hosted verification). Making the four tests skip without their inputs: proposal, small, any time |
| `OPENAI_API_KEY` exported fails one test; hard-coded Qdrant port | A6.4 | M9 (CI) or earlier test cleanup (proposal) |
| `gpt-5.4-nano` shutdown 2027-04-01 | v1 spec | M9 checkpoint (unchanged) |

## 6. Owner decisions preserved

These were made during M0 and are not reopened. Source: the `## Comments` of the named ticket.

- **D1 (T01):** The Railway environment is disposable, intentionally offline, and will be rebuilt after the audit. Investigation stopped after two read-only commands. **D1-F, future deployment requirements:** validated environment variables set explicitly (`CLAIM_CHECK_ENABLED`, models, thresholds, `INDEXING_ACTIVATION_TARGET`, credential-encryption settings); migrations run once from an empty database to the single head as a separately approved step; security controls decided before real user data (allow-list, Owner-mode limits and spend cap, the test-user list as a temporary outer control); a hard OpenAI budget, a claim-check decision and no Prepare on a large corpus before the re-embedding cost is estimated; backups appropriate to the data. Before any destructive reset, check that nothing needs preserving (6 lifetime users; the keyring is held separately from the database; the demo project must not be touched).
- **D2 (T02):** Qualified backend baseline accepted; the 24-minute suite is not repeated. The `OPENAI_API_KEY` sensitivity is recorded for CI.
- **D4 (T04):** (1) DriveMind stays a private single-Owner application; an application-level allow-list is required before broader sign-in. (2) Owner-mode limits are an M0-SEC requirement covering both paths, with limits from measured usage and cost. (3) KI-032 stays registered, with both implications stated. (4) CSRF on `/chat` is assessed, not assumed. (5) Hosted flags and Google OAuth state must be checked before the private beta is declared safe. (6) Standing escalation rule for hosted reads.
- **D5 (T05):** (1) The tool agent is the intended single production path, subject to the M1 evaluation and release gates; legacy paths are not switched off or removed during M0 (M9 disables, M10 removes). (2) Every future local evaluation sets `TOOL_RAG_AGENT_ENABLED=true` and states its flags. (3) A claim-check provider failure must not silently publish an unchecked answer; proposal for M3: fail closed with a distinct fixed error category, a clear retryable message, and fail-closed tests through `/chat`, conversation turns and streaming, with faked providers; open points for M3 (cost and latency, whether `CLAIM_CHECK_ENABLED=false` stays a production setting, whether demo follows). (4) Ticket 09 owns the eight documentation contradictions. (5) Keep the `/implement` workflow.
- **D6 (T06):** (1) Refusing to re-prepare prepared, failed and skipped files is a temporary beta policy. (2) M6 provides explicit, safe, user-initiated re-preparation and retry. (3) Manual initiation stays: page load, navigation and a Drive check never trigger paid preparation. (4) M6 also covers persistent exclusions, visible Unsupported states, meaningful failure reasons, stale-file handling (and the `skipped` mixing and the Drive-check reset). (5) Embedding compatibility and version checks go into the appropriate milestone. (6) Prevent duplicate concurrent jobs; preserve the last usable version where feasible. (7) No Railway restart, no cost estimates from unavailable hosted data.
- **D7 (T07):** (1) Delete conversation must eventually mean permanent deletion of its questions, answers, citations and related records; no M0 behavior change, and the "today" tests change together with that implementation. (2) Separate actions with their own retention rules: Disconnect Google, Revoke Google access, Delete stored data; retention rules (Qdrant vectors, browser records, backups, provider copies) written before any deletion claim. (3) KI-033 stays registered.

## 7. Documentation corrections

Each correction below matches a cited finding. Nothing else in documentation changed.

| File | Correction | Finding |
|---|---|---|
| `docs/specs/drivemind-v1-product-definition.md` (Status ledger) | "four services" fallback entry replaced by six, latent, KI-031; CI row (workflow now exists, hosted run unverified); commits-ahead count; last backend run replaced by the ticket 02 baseline; conversation delete is a soft delete; hosted tool-agent flag is Owner-reported on; Unverified list updated for answered items (backend Disconnect path, encryption default, Unsupported files, CI cost, full suites, Google consent state) and the new defects KI-031 to KI-033 added | T03, T04, T07, T08, T01, T02 |
| `AGENTS.md` | "Known Important Constraints" authentication paragraph (six fallbacks and latent; the flag gates issuance not validation; every private route requires a principal); hybrid/LangGraph sentence (legacy path only); "Architecture" and "Core Flows" sentences about routing and `/chat` (the tool agent skips the router; the normal UI uses conversation turns); "Latest recorded verification" gains the CI workflow and the four-deselected-tests note | T03, T04, T05, T08 |
| `backend/app/security/README.md` | A "Current status (M0 audit, 2026-11-21)" block at the top; the three statements proven false ("no existing route uses these dependencies", "`/auth/google` retains its single-user behavior", "Existing chat/files/index/sources routes still have their existing authorization") are marked as superseded. Historical text is kept, with a pointer | T04 §2, §3 |
| `docs/KNOWN_ISSUES.md` | A short note recording items found by the audit that have no reproducing test yet (claim-check fail-open, no Owner-mode limits, `/chat` CSRF, vacuous test, 4 CI deselects). No new entry without a test | T04, T05, T08 |
| `docs/ARCHITECTURE.md` | The "Security and scope" paragraph (OAuth is not the session boundary; first-credential fallback is latent, six services); the localStorage sentence (conversations are server-side); the router outcome list (six) and a note that the tool agent skips the router and that conversation turns are the normal UI's chat endpoint | T05 §5 items 4, 5, 7 |
| `docs/TOOL_RAG_ARCHITECTURE.md` | A "historical decision record; superseded by the implementation" note | T05 §5 item 6 |
| `docs/guides/INDEXING.md` | The sentence that sends the Owner to "the full scan option in the app" (no mounted screen sends `full=true`) | T06 §4 item 3 |

**Partly corrected:** `docs/ARCHITECTURE.md` still does not describe the intent model, claim check or streaming (T05 §5 item 5); only the router, tool-agent and conversation-turn facts were fixed.

**Deliberately not corrected (outside the ticket's allowed set, or needs a code change):** docstrings in `backend/app` (`api/session_dependencies.py`, `api/google_session_auth.py`, `services/application_session_service.py`, `RagService`) are application code, so they go to M0-SEC item 8. The `INDEXING.md` note that `/index/pending` has no UI consumer is true of the UI, not wrong, so it is recorded here (A3.3) only. `docs/EVALUATION_RESULTS.md`, `docs/DECISIONS.md` and the phase trackers were not reviewed by M0 and were not touched; the "skips on a clean checkout" statement in ticket 02 and `AGENTS.md` holds for one test only (A6.6).

## 8. Proposal: M1 to M10 order

Evidence-based, and a **proposal for the Owner**. The M0 row of the v1 spec is not changed by this report.

1. **Insert M0-SEC before substantial M1 implementation.** Reason: the six fallbacks, the missing sign-in allow-list and the missing Owner-mode limits are latent or dormant, not reachable now (A2), so they are not a hotfix; but they are cheap, they sit under everything M1 onward builds on, and the spec's urgency rule puts latent unsafe items ahead of substantial M1 work. **No security finding needs to move ahead of M0 itself, and none requires an emergency hotfix.**
2. **Split M0-SEC in time, not in scope.** Items 1 to 4, 6 and 7 first. Item 5 (limits): build the mechanism and the question-length cap first; set the values after M1 has measured real cost per question on both paths (Owner: values from measurements). The limit must exist before any redeploy with sign-in on.
3. **M1 (evaluation foundation):** unchanged in position. Add: every run sets `TOOL_RAG_AGENT_ENABLED=true` and states its flags (D5-2); record cost per question for the tool-agent and the linear path (feeds M0-SEC item 5); the evaluation harness measures what a rebuilt Railway would run.
4. **M2 (retrieval):** unchanged. KI-022's keyword half and KI-030's chunk-level cause now have deterministic strict tests (A6.9), so M2 can start from them; KI-027 stays an evaluation case.
5. **M3 (grounding):** add the claim-check fail-closed decision (D5-3) next to Supported-answer checking.
6. **M4 (conversations):** unchanged. Add the history findings (A4.7): the agent receives at most 3 pairs and 6000 characters and does no rewrite.
7. **M5:** unchanged, conditional on M1 (KI-029).
8. **M6 (preparation):** the v1 spec says it depends only on M0, so it can run in parallel with M2 to M4. Add the audit's M6 requirements (D6-1 to D6-6) and, as a proposal, **embedding model and dimension compatibility checks**.
9. **M7 (data control):** keep deletion, Disconnect, Revoke, permanent conversation delete and KI-033 here (D7). M7 keeps its scope (session validation, isolation tests, Disconnect, Revoke, deletion); the allow-list and limits are new M0-SEC items, not taken from M7.
10. **M9 (release):** add the Railway rebuild requirements (D1-F) as an explicit gate: M0-SEC complete, variables validated against `config.py` at the deployed commit, one migration run read back, backups decided. Add hosted verification of CI and the four deselected tests.
11. **M8 and M10:** unchanged.

Net order: **M0 (done) → M0-SEC → M1 → M2 / M3 / M4 / M6 → M5 (if needed) → M7 → M8 → M9 → M10.** M6 can run in parallel with M2 to M4 because it depends only on M0.

## 9. What this report does not establish

- Anything about Railway beyond the CLI status of 2026-11-21 and the Owner's reports. All hosted flag values, the consent-screen state and the claim "nothing important is stored" are the Owner's statements.
- That any test not named was re-run for this report. This ticket ran no suite; the figures are those of the tickets, taken on the commits they name.
- That the workflow works on GitHub (never run there), or that the 24-minute container suite passes on HEAD today (last run on `7197af4`; tickets 03 to 08 added tests and ran focused or partial suites only).
- The legacy linear path's cost, the frontend build flags, the logs and retention of Railway and Vercel, and the legacy `app/api/auth.py` for deletion paths.
- That the Owner-reported "intended" accounts on the test-user list include the Owner's own account (the assistant's reading, T01 G3a).

## 10. Diff scope check (ticket 09)

Against the baseline `7197af4`, the repository changed only in: this report; nine new test files and `.github/workflows/ci.yml` (tickets 02 to 08); the nine ticket files; and documentation corrections (`AGENTS.md`, `docs/KNOWN_ISSUES.md`, `docs/specs/drivemind-v1-product-definition.md`, `docs/ARCHITECTURE.md`, `docs/TOOL_RAG_ARCHITECTURE.md`, `docs/guides/INDEXING.md`, `backend/app/security/README.md`, which is documentation inside `backend/app`). No Python or TypeScript application file, migration or infrastructure file changed (`git diff bf15b20 HEAD -- backend/app backend/alembic backend/evaluation frontend infra backend/pyproject.toml backend/deploy` is empty for the commits; with this ticket's working-tree changes it shows only that README). A pattern scan of the diff for keys, connection strings, e-mail addresses, UUIDs and hosted hostnames found nothing.

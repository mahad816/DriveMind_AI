# 09: Security test integrity, documentation, milestone verification and the M9 gate

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** The security tests and documents say what the code now does, the deferred items sit in their later milestones, and one full verification run proves M0-SEC is complete.
**Blocked by:** 01, 02, 03, 04, 05, 06, 07, 08.
**Status:** done (local commit, not pushed)
**Progress:** complete 2026-11-22; verification and both reviews recorded in Findings

## Scope

- Fix `test_existing_application_routes_do_not_use_session_dependencies` (it checks nothing under the pinned FastAPI and is named for the opposite of reality): rewrite it to assert something real or delete it where the route inventory already covers the claim.
- Correct the docstrings the audit proved wrong: the session dependency module, the Google session auth route module, the application session service, and the `RagService` class and `ask` docstrings (audit A1.8). No behavior change.
- Registry (`docs/KNOWN_ISSUES.md`): KI-031 and KI-032 are in Fixed (tickets 02 and 07); remove the "found by the audit, not yet registered" bullets for Owner-mode limits and `/chat` CSRF; keep the claim-check, CI-deselect items.
- Documents: `AGENTS.md` ("Known Important Constraints": remove the latent-fallback sentence, add the allow-list and session invalidation, the persistent paid-question quota (20/hour, 50/day, 1 concurrent, provisional) and the new table; "Latest recorded verification"); `backend/app/security/README.md` status block; the v1 spec ledger and milestone table (add the M0-SEC row; add the M9 gate below); `docs/ARCHITECTURE.md` security paragraph; `docs/guides/GOOGLE_OAUTH.md` (allow-list is the authorization model, test users are an outer control); an addendum line in `docs/audits/m0-system-audit.md` section 4 pointing to this milestone (the report stays a historical record).
- The M9 gate, recorded in the v1 spec's M9 row and in the spec's Further Notes: before any redeploy with sign-in on, (1) limit values recalibrated from M1 data, (2) the deployment-only list verified (Google consent screen and test users, flags, encryption keys, `FRONTEND_URL` and cookie settings matching the real hosts, layout facts from ticket 08, proxy and edge limits), (3) practical provider spending safeguards verified, (4) deferred logging items done in M9; and, for item (3), the Owner's practical spending safeguards in the provider dashboard (a project usage budget and usage alerts), described as safeguards and never as guaranteed hard caps. Also record: the allow-list deferrals of ticket 03 (running turns, queued indexing jobs with the worker check assigned to M6 and re-verified at the M9 gate, stale stored e-mail) as deferrals, never as guarantees, and add the M6 worker-check item to the v1 spec's M6 row; the future requirement of per-user quota management for beta testers, to be started only after ownership isolation is verified (M7), and the multi-replica checklist from the spec (section C).
- Quota documentation from tickets 05 and 06 (open items assigned here): add `PAID_QUESTION_HOUR_LIMIT`, `_DAY_LIMIT`, `_CONCURRENT_LIMIT`, `_LEASE_SECONDS`, `_RETENTION_HOURS`, `CONVERSATION_EXECUTION_SECONDS`, `CONVERSATION_GENERATION_TIMEOUT` and `CHAT_EXECUTION_SECONDS` to `.env.example` and the operating guide with the lease rule (lease at least the longest bound plus 60 s); document the 429 and 503 contract, the order of checks, the body caps (512 KiB `/chat`, 64 KiB turns and stream) and the 4000-character `/chat` question cap. Record in the v1 spec's M8 row the frontend items (Owner-mode 429 wording, stream status and SSE-error handling) and in the M9 row the items below.
- Add to the M9 gate list (item 2, deployment-only verification): migration `20261121_1200` applied on the hosted database; the quota settings present and the application starting with the lease validator accepting them; the database connection pool size checked against admit, finish and release taking a connection beside each request's own; the edge or proxy read timeout for slow request bodies.
- Run the full verification once and record it.

## Out of scope

Any new fix. Deferred items (log text, `/docs`, empty-corpus exit). Deployment. Changes to ADRs.

## Inspect

All earlier tickets' `## Comments`; `docs/specs/m0-sec-security-hardening.md` ("What must be true before M0-SEC is complete"); `AGENTS.md`; `CODING_STANDARDS.md`; `docs/GIT_WORKFLOW.md`.

## Deliverables

Test and docstring fixes; documentation corrections; `## Findings` here with the verification record (counts, durations, environment, commit); diff summary for the Owner's approval. Do not commit or push without it.

## Needs

Local Docker for the disposable PostgreSQL and Qdrant containers (about 24 minutes for the full backend suite). `OPENAI_API_KEY` unexported. No paid API, no Railway.

- [x] The vacuous test no longer claims what it does not check.
- [x] The four named docstrings match the code; `git diff` of those files shows comments and docstrings only.
- [x] Registry and documents match the final behavior; no document still calls KI-031 latent-open or the allow-list and limits missing.
- [x] The M9 gate is written in both places and lists the four items; the M6 worker-authorization item and the ticket 03 deferrals are recorded in the v1 spec, `AGENTS.md` and the security README, worded as deferrals.
- [x] Backend full container suite run once in the qualified environment: all pass; counts, duration and environment recorded. Container-free subset, `ruff check`, `ruff format --check`, `mypy app` pass; `basedpyright` clean on `app` and no more than the 48 baseline errors in `tests/`; frontend `npm test`, `npm run lint`, `npm run build` pass.
- [x] The quota settings are in `.env.example` and the guide; the M8 and M9 rows of the v1 spec carry the items listed above; the spec's "Added after ticket 06" rows match them.
- [x] Every item of the spec's completion list (1 to 8) is ticked with a pointer to its test or document.
- [x] `git diff` scope: only files named in tickets 01 to 08 (and this one), exactly one migration (ticket 05), no frontend file unless ticket 08 proved it necessary; a scan of the diff for keys, e-mail addresses, connection strings, UUIDs and hosted hostnames finds nothing.

## Comments

## Findings

### Verification record (2026-11-22, commit base `d117df0` plus this ticket's working-tree changes)

**Environment.** Disposable containers created for this run only: PostgreSQL 18.7 (database name starting `drivemind_session_test`), Qdrant 1.18.0 at `127.0.0.1:61449` (`QDRANT_TEST_URL`) and a second at `127.0.0.1:61448` (`CONVERSATION_TEST_QDRANT_URL`, the port the three real-RAG-mode tests require). `OPENAI_API_KEY` not exported (the ignored local `.env` was neither read nor changed); outbound HTTP(S) pointed at a dead loopback proxy so that no test could reach a provider (loopback exempt). No Google, OpenAI or Railway call.

**Backend full run (3245 tests collected; collection verified).** One run: `5 failed, 3233 passed, 1 skipped, 6 xfailed` in 32 min 13 s (slower than the recorded 24 min because the frontend suite, build and static checks ran in parallel on the same machine).
- **The 5 failures were not product failures.** (1) `test_google_session_auth.py::test_invalid_signed_claims_rejected[claims3]`: a real test defect. The parameter `int(time.time()) + 600` was evaluated at import, so any run longer than 10 minutes made the "future iat" token valid. Fixed in this ticket (test only: the value is computed when the test runs). (2) to (5) four indexing runtime tests that failed on database-probe timeouts (`SCHEMA_OR_DATABASE_UNAVAILABLE`, `TimeoutError`, `503 == 202`): `test_indexing_lifecycle.py::test_task_death_closes_actual_api_admission[cancel]` and, in `test_normal_indexing_runtime.py`, `test_normal_lifespan_synthetic_two_owner_pipeline_and_exact_job_polling`, `test_normal_shutdown_rejects_owner_lock_waiter_and_joins_cleanup[shutdown]` and `test_normal_issued_build_with_lost_acknowledgement_remains_blocked`. They coincided with the frontend suite, build and static checks running on the same machine. Not hidden: they failed in the full run. Rerun in isolation, unloaded: `test_google_session_auth.py`, `test_indexing_lifecycle.py`, `test_normal_indexing_runtime.py` **125 passed** in 119 s; the fixed test, 14 of 14. The full suite was **not** repeated after the test fix (qualified result, like the M0 baseline: the suite passes in the right environment, shown by the full run plus the isolated reruns, not by one clean run). Treat the indexing-probe timeouts as a load sensitivity of those tests (a recorded observation, not registered: no reproducing test), and do not run other heavy work beside the suite.
- **1 skip:** `test_paid_question_routes.py:173` "Streaming is tool-agent only" (a parametrised case that does not apply to that path; by design, not an environment gap). The 3 real-RAG-mode tests ran and passed (no skips from the 61448 requirement).
- **6 expected failures (strict xfail, not passes):** KI-022 x2, KI-030 x2, KI-033 x2. KI-031 and KI-032 carry no marker: their tests are ordinary passing tests.

**Container-free subset** (no container variables, public-PDF test deselected): `2313 passed, 929 skipped, 2 xfailed` in 60 s. All skips need PostgreSQL or Qdrant; they are not counted as passed, and this subset does not guard ownership, session, quota or vector-isolation behavior (the container run does).

**Static.** `ruff check app tests` and `ruff format --check app tests` clean (364 files); `mypy app` clean (189 files); `basedpyright app tests`: 48 errors, all in 9 files under `tests/`, none in `app/` (the preserved baseline; the edited test file has 0).

**Frontend** (no frontend file changed by M0-SEC): `npm test` 876 passed in 76 files; `npm run lint` clean; `npm run build` succeeded.

**Migrations.** One Alembic head, `20261121_1200`. On a fresh disposable database: upgrade to head, downgrade one, upgrade again all succeed; the table has the owner FK `ON DELETE CASCADE`. `alembic check` reports index and constraint drift on `users` and `chunks` only (not the new table); it predates M0-SEC and is outside its scope (recorded here; a data-model cleanup item, no security effect found).

**Diff scope.** `24a9aa7..HEAD` plus this ticket: backend app and tests, docs, the two env example files, exactly one migration, no frontend file. Scan of every added line: only synthetic `*.invalid` addresses; no keys, UUIDs, connection strings or hosted hostnames.

### Completion list (spec "What must be true before M0-SEC is complete")
1. KI-031: `tests/known_issues/test_ki031_credential_owner_fallback.py` (6 sites + 12 guards, no markers), `tests/security/test_owner_fallback_callers.py` (allow-list: the demo existence check only); registry, Fixed. Ticked.
2. Allow-list: `tests/security/test_sign_in_allow_list.py` (18) and the route inventory. Ticked.
3. Quota: `tests/security/test_paid_question_quota.py`, `test_paid_question_routes.py`, `test_conversation_chat.py` (real-RAG modes), `tests/test_paid_execution_marker.py`, `test_paid_question_settings.py`, `test_paid_call_counts.py`, `test_public_safety.py`. Ticked.
4. KI-032: `tests/known_issues/test_ki032_pending_login_state_growth.py`, `tests/security/test_login_start_limit.py`; registry, Fixed. Ticked.
5. CSRF: assessment in ticket 08; `tests/security/test_chat_csrf.py`. Ticked.
6. Test integrity: the vacuous test replaced (`test_session_security.py::test_demo_mode_and_tool_agent_default_off`); route inventory passes. Ticked.
7. Full verification: this record. Ticked, qualified as stated above.
8. Process items: ticket 04 findings; ticket 08's M9 layout checks and the M9 gate in the v1 spec (M0-SEC row, M6, M7, M8, M9 rows, "The M9 gate") and this spec; the Owner's decisions in the tickets. Ticked.
9. Diff scope: see above. Ticked.

### Remaining risks and limitations (not closed by M0-SEC)
See the spec's "Residual risk after M0-SEC" and Deferred table. In short: provisional, unmeasured limits (a count is not a cost); running turns and queued jobs of a removed address; stored e-mail refreshed only at sign-in; slot held until the lease after a stream disconnect or process kill; the body-size buffer has no read timeout before authentication; the login-start limiter is global and process-local; the claim check fails open (M3); Disconnect, Revoke and Delete stored data (M7); frontend Owner-mode 429 wording and stream handling (M8, fix before beta); everything deployment-only is Unverified until the M9 gate.

### Independent reviews
Two separate read-only reviewers ran after the documents and the test fix were in place.

- **Standards, documentation, maintainability: no blocking findings.** Confirmed: application code changed in comments and docstrings only; the replaced and fixed tests are sound; documented defaults, caps, messages and the migration id match the code; no stale statement remains outside dated snapshots; every deferred item has an owner. Non-blocking, all applied: the ticket's status line (this edit); the spec header now says approved and implemented (the Problem Statement is marked as the state at proposal time); legacy `/auth/google` rows in `GOOGLE_OAUTH.md` marked legacy; a "superseded by M0-SEC" header on the dated `HANDOFF_2026-11-21.md`.
- **Spec, security, correctness, milestone completeness: no blocking findings; judged closable.** Verified in code: the only unscoped credential select is the demo existence check; all six services refuse a missing Owner; the allow-list is enforced at login (both intents) and on every private request, logout is revoke-only and never a principal; all five provider call sites mark before sending; the admit, execute, settle order on `/chat`, turns and streaming; the lease validator; prune and login-start limit; Origin and CSRF before any provider call; demo `/chat` anonymous. One documentation gap, now fixed: paid embeddings from Owner-queued indexing jobs are not counted by the question quota (reachable only with `INDEXING_ENABLED` and an allow-listed Owner; added to the spec's Deferred table, owner M6 and the M9 spend-safeguard gate, and to the operating guide). Accepted, no change: the login-start limiter runs before the sessions-enabled gate (harmless, in memory); service signatures still read `UUID | None` (M10).
- **Re-run after the review edits** (no other heavy work running): `test_google_session_auth.py`, `test_indexing_lifecycle.py`, `test_normal_indexing_runtime.py`, `test_session_security.py`, `test_route_authentication_inventory.py`: 227 passed in 113 s.

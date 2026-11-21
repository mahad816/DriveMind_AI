# 03: Credential fallback and ownership safety (A2, part 1)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows, with evidence, whether any request, background job, startup task or script can act on another Owner's Google credential or data. Each of the six suspected "first stored credential" fallbacks is classified, every caller is traced, and the Owner receives a proposed M0-SEC follow-up ordered by the spec's urgency rules.
**Blocked by:** None (can start immediately). Sequencing note: code inspection and classification need no other ticket. Writing any new database-backed regression test waits until ticket 02 is resolved (or the local container environment has otherwise been verified by ticket 02's baseline), so a new test's failure is not confused with an environment fault. Ticket 01's hosted session-flag value is a soft input: if unread, it stays `Unverified`.
**Status:** ready-for-agent
**Progress:** resolved

## Scope

- Verify each of the six suspected fallbacks (user resolution, Drive sync, Drive content, chunking, ingestion, indexing services) or show it does not exist. Find the pattern by search (selects of the Google credential model with no owner filter, "first" or limit-one patterns), not only by the six names, and state the search used.
- Find every caller of each: routes, the indexing worker, demo loading, startup, internal services and scripts. Do not assume safety because mounted routes appear to pass an explicit Owner.
- Classify each as exactly one of: **Reachable security vulnerability** / **Latent unsafe behavior** / **Safe or unreachable** (with evidence such as every caller passing a non-null Owner and a test or type constraining it).
- Separate real current vulnerabilities from future multi-Owner scalability concerns.
- Tests: per fallback, a deterministic defect test (strict expected failure) if reachable or latent, or a protective test (passes today) if safe, only where meaningful. A new defect gets a `docs/KNOWN_ISSUES.md` entry with its test.
- **Escalation:** if a reachable vulnerability is confirmed, stop, report it to the Owner at once with evidence and record the time in `## Findings`, before continuing. An emergency fix is a separately approved change, not part of this ticket.
- Write the proposed M0-SEC (scope, ordering, acceptance criteria) for the fallbacks only after all six and all callers are confirmed. Ticket 09 merges in any M0-SEC items from ticket 04.

## Out of scope

Fixing any fallback or removing code. Running exploits against anything hosted. Route inventory, encryption, logging and rate-limit audit (ticket 04). Disconnect/Revoke/Delete-data facts (ticket 07). Corrections to the v1 spec ledger and security README (ticket 09).

## Inspect

`backend/app/services/` (`drive_sync_service.py`, `drive_content_service.py`, `chunking_service.py`, ingestion and indexing services, user resolution), the indexing worker, `backend/app/main.py` (startup), `backend/scripts/` if present, `backend/app/security/principal.py`, `backend/tests/security/` (prior art for ownership tests), `backend/tests/known_issues/`, `docs/KNOWN_ISSUES.md`.

## Deliverables

`## Findings` in this ticket: fallback table (location, callers, classification, evidence, test name), escalation log, proposed M0-SEC for the fallbacks. New tests and registry entries as above.

## Needs

No paid APIs, no live infrastructure (reachability from code and local tests; hosted facts only from ticket 01). Local Docker only for database-backed tests, after ticket 02.

- [x] All six suspected fallbacks are verified or shown not to exist, with the search method stated; every caller of each is listed.
- [x] Each fallback has exactly one classification with evidence.
- [x] Any reachable vulnerability was reported to the Owner when found; the time is recorded in `## Findings`.
- [x] The proposed M0-SEC has scope, acceptance criteria and an ordering that follows the urgency rules (hotfix / before substantial M1 implementation / recorded cleanup).
- [x] Every added test is deterministic, free of paid API calls and meaningful; defect tests fail today for the stated reason; protective tests pass; no artificial expected failures.
- [x] No database-backed test was written before ticket 02 was resolved or its environment was otherwise verified.
- [x] No application code changed.

## Findings

Audited 2026-11-21 on branch `feature/v2-state-performance`, base commit `52d73a1`. Method and results below; no application code was changed.

### Verdict

- **No reachable vulnerability.** All six suspected fallbacks exist and none can be reached by a request, background job, startup task, script or the evaluation harness, because every production caller passes an explicit, non-null owner.
- **All six are latent unsafe behavior.** Nothing in the code or tests *constrains* the owner to be present (the signatures accept `UUID | None`, and a unit test pins the fallback), so a future caller that omits the owner would silently act on an arbitrary owner's Google credential once a second owner exists.
- **Current vulnerability vs. scalability concern:** there is no current vulnerability. The risk is a future multi-owner one: it only matters when 2+ owners hold credentials and a new caller forgets the owner.

### Escalation log

| When | What | Action |
|---|---|---|
| 2026-11-21 13:36 PKT (determination time, after the last caller was traced) | No reachable vulnerability confirmed; nothing to escalate | None. Had one been found, work would have stopped for an immediate report. |

### Search method

1. `grep -rn GoogleOAuthToken backend/app backend/scripts`: every select of the credential model (there is no `backend/scripts`). Result: the six `select(GoogleOAuthToken).limit(1)` sites, one more unfiltered select (`demo/service.py:53`, an existence check), and owner-scoped uses (`google_credential_repository.py`, `indexing_worker.py:555,755`, `ops/indexing_recovery.py:75`, schema probes in `indexing_runtime.py:149`).
2. `grep -rn -E "limit\(1\)|select\(User\)|\.first\(\)" backend/app`: every other unfiltered or "first" pattern. All remaining `limit(1)` selects are scoped by an owner column, are job-queue claims keyed on `job.user_id`, or are existence probes (`IndexingJob`, `ConversationTurn`, `DriveFile`, `Document` with `user_id` filters). The only other `select(User)` is `google_oauth_service.py:177` (login lookup by Google subject, not a fallback) and the demo inspection (`demo/service.py:50`, demo storage only).
3. Callers: `grep -rn` for every `_resolve_user`, `resolve_active_user`, constructor and public entry method (`sync_metadata`, `get_latest_sync_job`, `list_synced_files`, `is_connected`, `get_pending_counts`, `fetch_file_content`, `ingest_files`, `chunk_documents`, `build_index`) across `backend/app` and `backend/evaluation`; routes, worker, recovery, startup (`main.py`), demo and evaluation were read, not assumed. Outside `backend/` only `.claude/worktrees/matt-skills-setup/` (a copy of the same code) matched.
4. `evaluation/runner.py:310` also joins `GoogleOAuthToken` to pick an evaluation user, but it fails closed (error unless exactly one candidate, or an explicit `--user-id`); it is an offline CLI, not a fallback, and is classified as safe.

### Fallback table

All six are **Latent unsafe behavior**. Test: defect = `tests/known_issues/test_ki031_credential_owner_fallback.py::test_no_owner_must_not_resolve_to_an_arbitrary_credential_owner[<site>]` (strict expected failure, fails today with "resolved to owner ... although two owners hold credentials"); guards = `...::test_explicit_owner_resolves_to_exactly_that_owner[<site>-owner_a|owner_b]` (pass).

| # | Location | Reached with no owner via | Production callers (all pass an owner) | Evidence it is not reachable | Test `<site>` |
|---|---|---|---|---|---|
| 1 | `services/user_resolution.py:54` (`resolve_active_user`) | `resolve_active_user(db, settings)` or `user_id=None` in normal mode | `rag_service.py:109` (guarded by `isinstance(user_id, UUID)`); `drive_sync_service.py:63`, `drive_content_service.py:85` (demo-mode branches only, which return the demo user); `demo/service.py:137`, `demo/load.py:47` (demo only: `load_corpus` raises outside demo mode; `is_ready` is only called behind `settings.demo_mode` gates in `api/index.py:175` and `api/dependencies.py:44`) | Normal-mode callers always pass an owner; the owner-less calls are demo-only | `user_resolution` |
| 2 | `services/drive_sync_service.py:70` (`_resolve_user`) | `sync_metadata`, `get_latest_sync_job`, `list_synced_files`, `is_connected`, `get_pending_counts` with `user_id=None` | `api/files.py:38` (`require_resource_user`); `api/index.py:103,198` (`is_connected(owner)`), `:215,221` (`get_pending_counts`: demo id or `owner`); `indexing_worker.py:546` (`claim.user_id`). `sync_metadata` and `get_latest_sync_job` have **no production caller** (tests only) | Route dependencies return a `UUID` principal field (`security/principal.py:48,52` type-checks it) or the demo user | `drive_sync` |
| 3 | `services/drive_content_service.py:53` | `fetch_file_content(file_id)` with `user_id=None` | `api/files.py:57`; `indexing_worker.py:112` (the worker's reader raises unless `user_id` is a `UUID`); `ingestion_service.py:180` (`drive_file.user_id`) | Same, plus the worker's own non-UUID guard | `drive_content` |
| 4 | `services/chunking_service.py:57` | `chunk_documents()` with `user_id=None` | **None** in production: the worker calls `ChunkingService._replace_chunks` directly (`indexing_worker.py:844`) | No production caller of the entry method | `chunking` |
| 5 | `services/ingestion_service.py:77` | `ingest_files()` with `user_id=None` | **None** in production: the worker calls `IngestionService._ingest_single_file` (`indexing_worker.py:827`) | No production caller of the entry method | `ingestion` |
| 6 | `services/indexing_service.py:71` | `build_index()` with `user_id=None` | `demo/load.py:76` (`user.id`); `evaluation/rag_eval/target.py:147` (`EVAL_USER_ID`). `indexing_recovery.py:551` and the worker (`indexing_worker.py:973`) use only `_chunk_payload` / `_index_document`, which take no owner lookup | Both callers pass an explicit id | `indexing` |

Other unfiltered credential selects (not fallbacks): `demo/service.py:53` (asserts demo storage holds *no* credential; protective, listed in the allow-list); `evaluation/runner.py:310` (fails closed, see method step 4).

### Protective tests (pass today, no database)

`tests/security/test_owner_fallback_callers.py` (10 tests): (a) every production call of the nine entry methods passes a non-literal-`None` `user_id`; (b) `resolve_active_user` is called without an owner only from `demo/load.py` and `demo/service.py`; (c) no seventh `select(GoogleOAuthToken).limit(1)` exists outside the allow-list; (d) each allow-listed module still contains the pattern, so a fixed module must be removed from the list. A mutation check on a deliberately bad sample file made (a), (b) and (c) fail as intended. These are tripwires, not proof: a variable that is `None` at run time is invisible to them.

Existing coverage that backs the table (not duplicated): `tests/services/test_user_resolution.py` (demo identity never touches credentials; explicit owner needs no credential), `tests/security/test_private_read_authorization.py`, `test_chat_file_evidence_authorization.py`, `test_two_user_rag_end_to_end.py` (owner-scoped reads), `test_indexing_worker.py`. Runtime isolation of indexing jobs for two owners is ticket 04's route/authentication audit.

### Things the fix will touch (found while tracing)

- `tests/services/test_user_resolution.py::test_normal_mode_preserves_first_oauth_token_resolution` asserts the fallback and its `LIMIT 1`; it must be replaced, not just deleted.
- About 60 existing unit-test calls (single-line heuristic) invoke `ingest_files()`, `build_index()`, `chunk_documents()`, `sync_metadata()`, `list_synced_files()` and similar with no owner and rely on the fallback with a mocked session: `tests/services/test_{chunking,drive_content,drive_sync,indexing,ingestion}_service.py` (about 10, 6, 7, 14, 11), `tests/security/test_document_pipeline_version_pg.py` (4), `test_google_sdk_construction.py`, `test_indexing_recovery.py`, `test_indexing_worker.py` (1 each), `tests/test_demo_corpus.py` (6; demo path, not the fallback).
- `DriveSyncService(db=db)` in `api/files.py:23,28` builds services with default settings; unrelated to the fallback, noted only because ticket 04 inventories route wiring.

### Proposed M0-SEC (credential-owner hardening)

**Urgency: latent but unsafe, so a focused milestone that completes before substantial M1 implementation. Not a hotfix** (no reachable path). Ordering within M0-SEC:

1. **Make the owner mandatory (core).** In `user_resolution.py`, `drive_sync_service.py`, `drive_content_service.py`, `chunking_service.py`, `ingestion_service.py`, `indexing_service.py`: change `user_id` to a required `uuid.UUID`; reject a non-`UUID` with `ValueError("An explicit corpus owner is required")` (the wording `RagService._resolve_user` and `FileTargetRetriever._resolve_user` already use); delete the `select(GoogleOAuthToken).limit(1)` branches. Keep the demo branches of `resolve_active_user` unchanged.
2. **Remove production-dead owner-less surface.** `sync_metadata`, `get_latest_sync_job`, `chunk_documents`, `ingest_files` have no production caller; either delete them with their tests or keep them only with a required owner (decide in M0-SEC; do not widen).
3. **Update tests.** Replace `test_normal_mode_preserves_first_oauth_token_resolution` with a test that an owner-less call raises; give the ~60 owner-less service unit-test calls an explicit owner.
4. **Close the tripwires.** Remove the six strict-xfail markers (KI-031 moves to Fixed), shrink `KNOWN_UNSCOPED_CREDENTIAL_SELECTS` in `test_owner_fallback_callers.py` to `{"app/demo/service.py"}`, and tighten the entry-method check to also cover new service entry points.
5. **Docs.** Update `AGENTS.md` ("Known Important Constraints" sentence about the first stored credential), the security README and the v1 spec ledger (ticket 09 owns the corrections).

**Acceptance criteria:**
- No `select(GoogleOAuthToken)` without an owner filter remains in `backend/app` (the test_owner_fallback_callers allow-list is `{demo/service.py}`).
- Calling any of the six entry points with `user_id=None` (or a non-UUID) raises `ValueError` and reads no credential row; the KI-031 defect tests, markers removed, pass.
- With two owners holding credentials, an explicit owner still resolves to exactly that owner (the 12 guards keep passing).
- Backend suite, ruff, mypy and basedpyright are no worse than the ticket 02 baseline (basedpyright 48 errors, all under `tests/`).
- No route, schema, status or citation contract changes.

**Out of M0-SEC (belongs elsewhere):** route/authentication inventory, encryption, logging and rate limits (ticket 04); the `GOOGLE_APPLICATION_SESSIONS_ENABLED` hosted value (ticket 01); deletion and privacy behavior (ticket 07). Ticket 09 merges any M0-SEC items from ticket 04 into this list.

### Caveats

- **Static analysis only.** Reachability was established by reading the code and by tests that read source; no request was sent to a running or hosted instance. Call-site evidence cannot see a variable that is `None` at run time; the route dependencies' types and the worker's non-UUID guard cover that, but no end-to-end test sends an owner-less request.
- **Ticket 01 input unread:** the hosted `GOOGLE_APPLICATION_SESSIONS_ENABLED` value is `Unverified`. It does not change this classification (both session and demo paths supply an owner), but it matters for ticket 04.
- The defect tests use `_resolve_user` (a private method) at five sites because the public entry points do more work (Drive clients, Qdrant, OpenAI); a refactor that renames it will turn those tests into errors, not silent passes.
- The about-60 count is a single-line grep heuristic and may be off by a few.

## Comments

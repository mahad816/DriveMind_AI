# 02: Make the Owner mandatory in chunking, ingestion and indexing, and close KI-031 (part 2)

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** The last three "first stored credential" fallbacks are removed. After this ticket no code in the application can act on an arbitrary Owner's Google credential, and KI-031 moves to Fixed.
**Blocked by:** 01.
**Status:** done (local commit, not pushed)
**Progress:** complete

## Scope

- Chunking service (`chunk_documents`), ingestion service (`ingest_files`) and indexing service (`build_index`): owner required, same error and same pre-read refusal as ticket 01. Delete the three remaining `select(GoogleOAuthToken).limit(1)` branches.
- `chunk_documents` and `ingest_files` have no production caller (the worker calls lower-level methods). They are kept with a required owner, not deleted.
- `build_index` callers are the demo loader and the evaluation harness; both already pass an explicit id. Confirm it again by reading, and run the tests that cover them. Do not run the evaluation harness (paid).
- Give the roughly 35 owner-less unit-test calls in `tests/services/test_{chunking,ingestion,indexing}_service.py`, and the callers in `tests/security/test_document_pipeline_version_pg.py`, `test_google_sdk_construction.py`, `test_indexing_recovery.py` and `test_indexing_worker.py`, an explicit owner.
- Remove the remaining three KI-031 markers (`[chunking]`, `[ingestion]`, `[indexing]`). Shrink the allow-list in `test_owner_fallback_callers.py` to the one demo existence check (`demo/service.py`).
- Move KI-031 from Open to Fixed in `docs/KNOWN_ISSUES.md` with the evidence below.

## Out of scope

The sync, content and user-resolution services (ticket 01). Deleting entry points (M10). Changing the worker's lower-level calls. Any change to extraction text (so `EXTRACTION_PIPELINE_VERSION` stays as it is: assert it is untouched).

## Inspect

Ticket 01's list for the three services; `backend/app/demo/load.py`; `backend/evaluation/rag_eval/target.py` (read only); `backend/app/services/indexing_worker.py` and `ops/indexing_recovery.py` (confirm they use no owner-less entry).

## Deliverables

Three services changed; tests updated; KI-031 entry moved to Fixed; `## Comments` listing documentation for ticket 09.

## Needs

Disposable PostgreSQL and Qdrant for the indexing and worker tests. No paid API, no network.

## Comments` listing documentation for ticket 09.

## Needs

Disposable PostgreSQL and Qdrant for the indexing and worker tests. No paid API, no network.

- [ ] Before the fix, the three KI-031 cases `[chunking]`, `[ingestion]`, `[indexing]` fail for their registered reason; after, they pass with markers removed. All six KI-031 tests are now ordinary tests.
- [ ] `grep` for `select(GoogleOAuthToken)` in `backend/app` finds only owner-scoped uses and `demo/service.py`; the tripwire test enforces the allow-list `{demo/service.py}`.
- [ ] Each of the three entry points raises `ValueError` for `None` and for a non-UUID and issues no credential query.
- [ ] The 12 guards pass. The demo loader test and `tests/test_demo_corpus.py` pass.
- [ ] The container-backed worker, recovery and indexing suites (`tests/security/test_indexing_*`, `test_worker_vector_reconciliation.py`) pass.
- [ ] `EXTRACTION_PIPELINE_VERSION` and all route, schema, status and citation contracts are unchanged. Static checks no worse than the baseline.
- [ ] KI-031 is listed under Fixed with date, the six tests and the guard count.

## Comments

**What changed.** `ChunkingService`, `IngestionService` and `IndexingService` `_resolve_user` now delegate to `resolve_active_user`, as ticket 01 did for sync and content. Normal mode refuses a missing or non-UUID owner with `ValueError("An explicit corpus owner is required")` before any read or job row. The three `select(GoogleOAuthToken).limit(1)` branches are deleted. Demo mode now also applies the demo-user rule in these three services (an explicit id that differs from `DEMO_USER_ID` raises `DemoIdentityError`); the demo loader passes the id it just resolved, and the evaluation harness runs with `demo_mode=False`, so both are unaffected.

**Tests.** The three KI-031 cases were confirmed fixed first (strict xfail turned into XPASS), then `FIXED_SITES` and the conditional marker were removed: 18 ordinary tests (6 sites + 12 guards). The tripwire allow-list is `{app/demo/service.py}`. Unit tests in `tests/services/test_{chunking,ingestion,indexing}_service.py` pass an explicit owner (`settings=MagicMock(demo_mode=False)`; the credential-query mock entries were dropped; the "does not load the stale document" assertions count 1 scalar call instead of 2). Each service has a new test that `None` and `"not-a-uuid"` raise and issue no query. The four security test files named in Scope already passed an owner (positionally), so they needed no change. Run on disposable PostgreSQL and Qdrant, no `OPENAI_API_KEY`: known-issues, services, indexing/worker/recovery/vector-reconciliation, pipeline-version, SDK construction, tripwire and demo-corpus suites: 559 passed, 7 xfailed (other known issues). `ruff` and `mypy app` clean; `basedpyright` still 48 errors, all in `tests/`. The evaluation harness was not run. See the commit message for the full-suite result.

**Left as is on purpose.** Signatures still read `user_id: uuid.UUID | None = None`; tightening the type and deleting the unused entry points are M10.

**Ticket 09 must update in documentation** (not touched here):
- `AGENTS.md` "Known Important Constraints" (the KI-031 sentence, "six services") and "Latest recorded verification".
- `docs/ARCHITECTURE.md` (~line 73), `docs/specs/drivemind-v1-product-definition.md` (~line 352).
- `backend/app/security/README.md` line 8 ("services fall back to the first stored credential ... KI-031").
- `docs/audits/m0-system-audit.md` and `docs/tickets/m0-system-audit/03-credential-fallbacks-and-ownership.md` where they describe KI-031 as open.
- `docs/KNOWN_ISSUES.md` line 24 and the "Pinned by"/"6 strict expected failures" wording are already resolved by the Fixed entry.

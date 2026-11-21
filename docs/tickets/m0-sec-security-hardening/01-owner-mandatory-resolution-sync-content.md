# 01: Make the Owner mandatory in user resolution, Drive sync and Drive content (KI-031, part 1)

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** In normal mode, user resolution, Drive sync and Drive content refuse to act unless the caller names the Owner, instead of picking whichever Google credential PostgreSQL returns first. Nothing a user can see changes, because every production caller already passes an Owner.
**Blocked by:** None (can start immediately).
**Status:** done (local commit, not pushed)
**Progress:** complete

## Scope

- `resolve_active_user`: in normal mode a missing or non-`uuid.UUID` owner raises `ValueError("An explicit corpus owner is required")` (the wording `RagService._resolve_user` already uses) before any database read. Delete the normal-mode `select(GoogleOAuthToken).limit(1)` branch. The demo-mode branch is unchanged.
- Drive sync service `_resolve_user` and its entry points (`sync_metadata`, `get_latest_sync_job`, `list_synced_files`, `get_pending_counts`): owner required, `ValueError` for `None` or a non-UUID. `is_connected` deliberately keeps its current contract (it catches `ValueError` and returns `False`, and `/index` routes rely on that): an owner-less call returns `False` and issues no credential query. `sync_metadata` and `get_latest_sync_job` have no production caller; they are kept, with a required owner, not deleted (M10 owns removal).
- Drive content service (`fetch_file_content`): owner required.
- Replace `test_normal_mode_preserves_first_oauth_token_resolution` with a test that an owner-less normal-mode call raises. Give the owner-less calls in the unit tests of these two services an explicit owner.
- Remove the strict-expected-failure markers of the KI-031 cases `[user_resolution]`, `[drive_sync]`, `[drive_content]`. Remove those three modules from the allow-list in `tests/security/test_owner_fallback_callers.py` (its check (d) fails if a fixed module stays listed).

## Out of scope

Chunking, ingestion and indexing (ticket 02). Any route, schema, status or worker change. Deleting entry points. Moving KI-031 to Fixed (ticket 02 does it when all six are closed).

## Inspect

`docs/tickets/m0-system-audit/03-credential-fallbacks-and-ownership.md` ("Fallback table", "Things the fix will touch"); `docs/KNOWN_ISSUES.md` KI-031; `backend/app/services/user_resolution.py`, `drive_sync_service.py`, `drive_content_service.py`; their callers (`api/files.py`, `api/index.py`, `api/dependencies.py`, `services/indexing_worker.py`, `demo/`); `tests/known_issues/test_ki031_credential_owner_fallback.py`; `tests/security/test_owner_fallback_callers.py`; `tests/services/test_user_resolution.py`.

## Deliverables

The three services changed; tests updated; `## Comments` of this ticket listing what ticket 09 must update in documentation.

## Needs

Disposable PostgreSQL (the KI-031 tests skip without it). No paid API, no network.

- [ ] Before the fix, the three KI-031 cases are shown failing for their registered reason (an owner-less call returns an owner although two owners hold credentials); after the fix they pass with markers removed.
- [ ] With `user_id=None` or a non-UUID value, each entry point above except `is_connected` raises `ValueError`, and `is_connected` returns `False`; none issues a credential query (asserted by a statement-capturing or mock session).
- [ ] The 12 KI-031 guards (explicit owner resolves to exactly that owner, two owners) still pass.
- [ ] Demo mode still resolves the demo owner without touching a credential (`tests/services/test_user_resolution.py` demo tests unchanged and passing); `tests/test_demo_corpus.py` passes.
- [ ] `tests/security/test_owner_fallback_callers.py` passes with the three modules removed from its allow-list.
- [ ] `tests/security/test_route_authentication_inventory.py` (48), `test_private_read_authorization.py` and `test_indexing_worker.py` pass unchanged.
- [ ] No route, schema, status or citation contract changes. Backend suite, `ruff check`, `ruff format --check`, `mypy app` no worse than the recorded baseline; `basedpyright` clean on `app`, 48 errors in `tests/` unchanged.

## Comments

**What changed.** `resolve_active_user` (normal mode) refuses a missing or non-UUID owner with `ValueError("An explicit corpus owner is required")` before any read; `DriveSyncService._resolve_user` and `DriveContentService._resolve_user` now delegate to it. `is_connected` returns `False` for an owner-less call without a credential query. No-connection with an explicit owner raises `DriveClientError` from the credential service (as before for explicit owners); the unit tests were updated for that.

**Ticket 02 must also:** delete `FIXED_SITES` and the conditional marker in `tests/known_issues/test_ki031_credential_owner_fallback.py` (the three fixed cases now run as plain tests there); remove chunking, ingestion and indexing from the `test_owner_fallback_callers.py` allow-list; move KI-031 to Fixed; consider changing `user_id` to a required `uuid.UUID` in signatures (kept `| None` here because `is_connected` and demo mode accept it).

**Ticket 09 must update in documentation** (not touched here, by design):
- `docs/KNOWN_ISSUES.md` KI-031: "six services", "6 strict expected failures", cause line numbers (`user_resolution.py`, `drive_sync_service.py`, `drive_content_service.py` references) and the "Pinned by an existing test" line (the first-credential test was replaced).
- `docs/ARCHITECTURE.md` (~line 73) "Six services still select the first stored OAuth token".
- `docs/specs/drivemind-v1-product-definition.md` (~line 352) "six".
- `AGENTS.md` "Known Important Constraints" KI-031 sentence (six services, KI-031) and the "Latest recorded verification" figures.
- `docs/audits/m0-system-audit.md` and `docs/tickets/m0-system-audit/03-credential-fallbacks-and-ownership.md` if they restate the six.

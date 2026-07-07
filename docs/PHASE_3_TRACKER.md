# Phase 3 Tracker — Google Drive Read-Only Integration

Track milestone-by-milestone progress for Phase 3, with matching commit messages.

## Phase Goal

Authenticate with Google (read-only), sync Drive file metadata into PostgreSQL, and support export/download of MVP file types.

## Current Snapshot

- **Phase status:** Complete
- **Last completed milestone:** Milestone 6 (incremental sync + phase closure)
- **Next phase:** Phase 4 — Document Ingestion & Text Extraction
- **Blocker:** None

## Your Action Items (manual setup)

- [x] Step A — Google Cloud Console (project, Drive API, OAuth consent, OAuth client)
- [x] Step B — `.env` saved on disk with `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (must press Save)
- [x] Step C — Start Postgres + run `alembic upgrade head`
- [x] Step D — Manual browser OAuth test at `/api/v1/auth/google`

### Step B verification (no secrets printed)

```bash
cd backend
uv run python -c "from app.core.config import Settings; s=Settings(); print('id', len(s.google_client_id), 'secret', len(s.google_client_secret))"
```

Both lengths must be `> 0`.

### Step D commands

```bash
cd backend
uv run uvicorn app.main:app --reload
# browser: http://localhost:8000/api/v1/auth/google
```

## Milestone Status

- [x] Milestone 0 — Phase 3 tracker + setup checklist
- [x] Milestone 1 — Google deps, config, OAuth token model + migration
- [x] Milestone 2 — OAuth routes + auth service
- [x] Milestone 3 — Read-only Drive API client
- [x] Milestone 4 — Metadata sync service + API
- [x] Milestone 5 — Export/download handlers
- [x] Milestone 6 — Incremental sync + phase closure

## Commit Plan

1. `docs(drive): add phase 3 tracker and google cloud setup checklist`
2. `feat(drive): add google oauth config and token persistence model`
3. `feat(drive): add google oauth login and callback flow`
4. `feat(drive): add read-only google drive api client`
5. `feat(drive): sync drive file metadata into postgres`
6. `feat(drive): add supported file export and download handlers`
7. `feat(drive): add incremental sync and complete phase 3 docs`

## Milestone 2 Deliverables (done)

- `backend/app/services/google_oauth_service.py`
- `backend/app/api/auth.py`
  - `GET /api/v1/auth/google`
  - `GET /api/v1/auth/google/callback`
- Tests: `backend/tests/test_auth_google.py`

## Milestone 3 Deliverables (done)

- `backend/app/connectors/google_drive/constants.py`
  - Supported MVP MIME types (Google Docs, PDF, TXT, DOCX, images)
  - Drive field selectors, default list query, page-size limits
  - `is_supported_mime_type()` helper
- `backend/app/connectors/google_drive/client.py`
  - `GoogleDriveClient` builds read-only credentials from stored OAuth tokens
  - Automatic token refresh with optional `on_token_refresh` persistence callback
  - `list_files` / `iter_files` with pagination and MIME-type filtering
  - `get_file_metadata` for a single file
  - `DriveTokens` and `DriveFileMetadata` dataclasses; `DriveClientError`
- Tests: `backend/tests/connectors/test_google_drive_client.py` (mocked, no live Google calls)
- `pyproject.toml` mypy note: Google `Credentials`/`refresh` are inline-ignored (`no-untyped-call`)

## Milestone 4 Deliverables (done)

- `backend/app/services/drive_sync_service.py`
  - Resolves connected user from stored OAuth token (single-user MVP)
  - Builds `GoogleDriveClient` with token-refresh persistence back to DB
  - Upserts supported Drive files into `drive_files` (created / updated / unchanged)
  - Tracks each sync run in `indexing_jobs` (queued → running → completed/failed)
- `backend/app/schemas/drive_sync.py`
  - `DriveSyncResponse`, `DriveFileListResponse`, `DriveSyncStatusResponse`
- `backend/app/api/index.py`
  - `POST /api/v1/index/sync` — trigger metadata sync
  - `GET /api/v1/index/status` — latest sync job status
- `backend/app/api/files.py`
  - `GET /api/v1/files` — list synced file metadata from PostgreSQL
- Tests:
  - `backend/tests/services/test_drive_sync_service.py` (mocked service logic)
  - `backend/tests/test_drive_sync_api.py` (mocked route tests)

## Milestone 5 Deliverables (done)

- `backend/app/connectors/google_drive/constants.py`
  - `requires_export()`, `output_content_mime_type()`, `GOOGLE_DOC_EXPORT_MIME`
- `backend/app/connectors/google_drive/client.py`
  - `get_file_content()` — export Google Docs as plain text; download PDF/TXT/DOCX/images
  - `get_file_content_with_type()` — bytes + content MIME type
  - `_read_media_bytes()` — chunked media download via Drive API
- `backend/app/services/drive_content_service.py`
  - Validates synced file exists in PostgreSQL for connected user
  - Builds authenticated client, fetches content, persists token refresh
  - `DriveFileContent` dataclass
- `backend/app/api/files.py`
  - `GET /api/v1/files/{file_id}/content` — returns file bytes (not saved to disk)
- Tests (mocked, no live Google calls):
  - `backend/tests/connectors/test_google_drive_client.py` (content methods)
  - `backend/tests/services/test_drive_content_service.py`
  - `backend/tests/test_drive_content_api.py`

### Milestone 5 manual smoke test

```bash
# 1. Ensure OAuth connected and metadata synced
curl -X POST http://localhost:8000/api/v1/index/sync

# 2. List files and copy a file UUID from the response
curl http://localhost:8000/api/v1/files

# 3. Download/export content (replace FILE_UUID)
curl -v http://localhost:8000/api/v1/files/FILE_UUID/content --output /tmp/drivemind-test.bin
```

## Milestone 6 Deliverables (done)

- `backend/app/db/models/drive_sync_state.py` + migration `20260707_1700`
  - Stores Google Drive Changes API `changes_page_token` per user
- `backend/app/connectors/google_drive/client.py`
  - `DriveChange` dataclass
  - `get_start_page_token()` — baseline after full sync
  - `list_changes(page_token)` — incremental changes with pagination
- `backend/app/services/drive_sync_service.py`
  - **Full sync** (default when no token, or `?full=true`): lists all supported files, saves start page token
  - **Incremental sync** (default when token exists): `changes.list`, upserts modified files, marks removed as `skipped`
  - `DriveSyncResult.mode` and `removed` count
- `backend/app/api/index.py`
  - `POST /api/v1/index/sync?full=false` — incremental by default
- Tests: client changes API, incremental/full service paths, updated API schema tests

### Incremental sync smoke test

```bash
# After at least one full sync has established a changes token:
curl -X POST http://localhost:8000/api/v1/index/sync
# Response includes: "mode":"incremental", "removed":N, ...

# Force full rescan when needed:
curl --max-time 300 -X POST "http://localhost:8000/api/v1/index/sync?full=true"
```

## Phase 3 Completion Notes

- Verification suite: `uv run ruff check app tests`, `uv run mypy app`, `uv run pytest -q` (81 tests)
- Read-only Drive scope only; OAuth tokens + sync state in PostgreSQL
- Blocking Google API calls run in thread pool (`asyncio.to_thread`) to avoid freezing the server
- Never commit `.env`, credentials, or downloaded Drive files

## New Chat Handoff Prompt

> Continue DriveMind AI Phase 4 from `docs/CURRENT_STATUS.md` and `docs/ROADMAP.md`.

## Troubleshooting

### OAuth 503: credentials not configured

Cause: `google_client_secret` is empty when backend loads settings.

Fix:

1. Open repo-root `.env`
2. Ensure `GOOGLE_CLIENT_SECRET=...` has your Google client secret
3. **Save file** (Cmd+S) — unsaved editor buffer does not count
4. Restart uvicorn

### OAuth redirect: Invalid OAuth state

Cause: PKCE state was lost (common with `uvicorn --reload` restarting between login and callback), callback URL was refreshed/reused, or login was not started fresh.

Fix:

1. Open a **new** login URL: `http://localhost:8000/api/v1/auth/google`
2. Complete Google sign-in **once** — do not refresh the callback page
3. Ensure migration is applied: `cd backend && uv run alembic upgrade head`
4. Restart uvicorn after pulling OAuth state persistence fix

### OAuth redirect mismatch

Google Console redirect URI must exactly match:

`http://localhost:8000/api/v1/auth/google/callback`

## Notes

- Read-only scope only: `https://www.googleapis.com/auth/drive.readonly`
- OAuth tokens stored in `google_oauth_tokens` table
- Never commit `.env`, credentials, or downloaded Drive files

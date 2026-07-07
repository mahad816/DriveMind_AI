# Phase 3 Tracker — Google Drive Read-Only Integration

Track milestone-by-milestone progress for Phase 3, with matching commit messages.

## Phase Goal

Authenticate with Google (read-only), sync Drive file metadata into PostgreSQL, and support export/download of MVP file types.

## Current Snapshot

- **Phase status:** In progress
- **Last completed milestone:** Milestone 2 (OAuth login + callback)
- **Next milestone:** Milestone 3 (read-only Drive API client)
- **Blocker:** Step D failed with OAuth 503 because `GOOGLE_CLIENT_SECRET` is empty on disk — save `.env` and retry

## Your Action Items (manual setup)

- [x] Step A — Google Cloud Console (project, Drive API, OAuth consent, OAuth client)
- [ ] Step B — `.env` saved on disk with `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` (must press Save)
- [x] Step C — Start Postgres + run `alembic upgrade head`
- [ ] Step D — Manual browser OAuth test at `/api/v1/auth/google`

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
- [ ] Milestone 3 — Read-only Drive API client
- [ ] Milestone 4 — Metadata sync service + API
- [ ] Milestone 5 — Export/download handlers
- [ ] Milestone 6 — Incremental sync + phase closure

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

## Troubleshooting

### OAuth 503: credentials not configured

Cause: `google_client_secret` is empty when backend loads settings.

Fix:

1. Open repo-root `.env`
2. Ensure `GOOGLE_CLIENT_SECRET=...` has your Google client secret
3. **Save file** (Cmd+S) — unsaved editor buffer does not count
4. Restart uvicorn

### OAuth redirect mismatch

Google Console redirect URI must exactly match:

`http://localhost:8000/api/v1/auth/google/callback`

## Notes

- Read-only scope only: `https://www.googleapis.com/auth/drive.readonly`
- OAuth tokens stored in `google_oauth_tokens` table
- Never commit `.env`, credentials, or downloaded Drive files

## New Chat Handoff Prompt

> Continue DriveMind Phase 3 from `docs/CURRENT_STATUS.md` and `docs/PHASE_3_TRACKER.md`. Proceed with Milestone 3 after Step D passes.

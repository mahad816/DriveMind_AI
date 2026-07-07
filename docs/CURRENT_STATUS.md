# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 3 complete (Google Drive read-only integration). All milestones 0–6 done.

## Completed Phases

| Phase | Status | Notes |
|-------|--------|-------|
| 0 | Complete | Repo structure, docs, Cursor rules |
| 1 | Complete | FastAPI foundation, health, logging |
| 2 | Complete | DB models, Alembic migration, schemas, tests |
| 3 | Complete | OAuth, Drive client, sync, export/download, incremental sync |

## Phase 3 Summary (Drive Integration)

See [PHASE_3_TRACKER.md](PHASE_3_TRACKER.md) for full milestone log.

| Capability | Endpoint / module |
|------------|-------------------|
| OAuth login | `GET /api/v1/auth/google` |
| OAuth callback | `GET /api/v1/auth/google/callback` |
| Full / incremental sync | `POST /api/v1/index/sync` (`?full=true` for full scan) |
| Sync status | `GET /api/v1/index/status` |
| List synced files | `GET /api/v1/files` |
| Export / download content | `GET /api/v1/files/{file_id}/content` |

## What's Next

**Phase 4 — Document Ingestion & Text Extraction**

- Convert supported Drive files into normalized text
- Extractors for Google Docs, PDF, DOCX, TXT, images (OCR)

Say in a new chat:

> Continue DriveMind AI Phase 4 from `docs/CURRENT_STATUS.md` and `docs/ROADMAP.md`.

## Quick Commands

```bash
# Infra
docker compose -f infra/docker-compose.yml up -d postgres

# Backend
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Tests
uv run pytest -q
```

## Drive Sync Commands

```bash
# Incremental sync (default when a changes token exists)
curl -X POST http://localhost:8000/api/v1/index/sync

# Force full rescan (slower, re-establishes changes baseline)
curl --max-time 300 -X POST "http://localhost:8000/api/v1/index/sync?full=true"

# List synced files
curl http://localhost:8000/api/v1/files
```

## Manual Setup (Phase 3 — all done)

- [x] Step A — Google Cloud Console (Drive API + OAuth client)
- [x] Step B — `.env` with `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
- [x] Step C — Docker Postgres + `alembic upgrade head`
- [x] Step D — Browser OAuth test at `/api/v1/auth/google`

## Key Docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_2_TRACKER.md](PHASE_2_TRACKER.md) — Phase 2 log (complete)
- [PHASE_3_TRACKER.md](PHASE_3_TRACKER.md) — Phase 3 log (complete)

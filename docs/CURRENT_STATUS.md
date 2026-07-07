# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 4 complete (document ingestion and text extraction). All milestones 0–6 done.

## Completed Phases

| Phase | Status | Notes |
|-------|--------|-------|
| 0 | Complete | Repo structure, docs, Cursor rules |
| 1 | Complete | FastAPI foundation, health, logging |
| 2 | Complete | DB models, Alembic migration, schemas, tests |
| 3 | Complete | OAuth, Drive client, sync, export/download, incremental sync |
| 4 | Complete | Text extractors, IngestionService, ingest API |

## Phase 4 Summary (Document Ingestion)

See [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md) for full milestone log.

| Capability | Endpoint / module |
|------------|-------------------|
| TXT / Docs / PDF / DOCX / image extractors | `app/ingestion/extractors/` |
| Batch or single-file ingestion | `POST /api/v1/index/ingest` (`?file_id=` optional) |
| Extracted text storage | `documents.extracted_text` + `extracted_text_hash` |

## Phase 3 Summary (Drive Integration)

| Capability | Endpoint / module |
|------------|-------------------|
| OAuth login | `GET /api/v1/auth/google` |
| OAuth callback | `GET /api/v1/auth/google/callback` |
| Full / incremental sync | `POST /api/v1/index/sync` (`?full=true` for full scan) |
| Sync status | `GET /api/v1/index/status` |
| List synced files | `GET /api/v1/files` |
| Export / download content | `GET /api/v1/files/{file_id}/content` |

## What's Next

**Phase 5 — Chunking & Embeddings**

- Split extracted text into chunks
- Generate embeddings and store in Qdrant
- Idempotent indexing pipeline

Say in a new chat:

> Continue DriveMind AI Phase 5 from `docs/CURRENT_STATUS.md` and `docs/ROADMAP.md`.

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

## Drive + Ingestion Commands

```bash
# Incremental metadata sync
curl -X POST http://localhost:8000/api/v1/index/sync

# Ingest all supported synced files (text extraction)
curl -X POST http://localhost:8000/api/v1/index/ingest

# Ingest one file by drive_files.id (UUID from GET /files)
curl -X POST "http://localhost:8000/api/v1/index/ingest?file_id=<uuid>"

# List synced files
curl http://localhost:8000/api/v1/files
```

## Manual Setup Checklist

- [x] Google OAuth configured (Phase 3)
- [x] Tesseract installed (`brew install tesseract`)
- [ ] Postgres running + migrations applied (`uv run alembic upgrade head`)
- [ ] Drive metadata synced (`POST /api/v1/index/sync`) before first ingest

## Key Docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_2_TRACKER.md](PHASE_2_TRACKER.md) — Phase 2 log (complete)
- [PHASE_3_TRACKER.md](PHASE_3_TRACKER.md) — Phase 3 log (complete)
- [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md) — Phase 4 log (complete)

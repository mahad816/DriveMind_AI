# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 5 Milestone 3 complete (embedding provider abstraction). Phase 4 complete.

## Completed Phases

| Phase | Status | Notes |
|-------|--------|-------|
| 0 | Complete | Repo structure, docs, Cursor rules |
| 1 | Complete | FastAPI foundation, health, logging |
| 2 | Complete | DB models, Alembic migration, schemas, tests |
| 3 | Complete | OAuth, Drive client, sync, export/download, incremental sync |
| 4 | Complete | Text extractors, IngestionService, ingest API |

## Phase 5 Summary (Chunking & Embeddings) — active

See [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md) for milestone-by-milestone plan.

| Planned capability | Module |
|--------------------|--------|
| Text chunking | `app/ingestion/chunking.py` | Done (M1) |
| Chunk rows in Postgres | `app/services/chunking_service.py` | Done (M2) |
| Chunk API | `POST /api/v1/index/chunk` | Done (M2) |
| Embeddings | `app/embeddings/` | Done (M3) |
| Vectors in Qdrant | `app/embeddings/vector_store.py` |
| Build index API | `POST /api/v1/index/build` (Milestone 5) |

## Phase 4 Summary (Document Ingestion)

See [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md) for full milestone log.

| Capability | Endpoint / module |
|------------|-------------------|
| TXT / Docs / PDF / DOCX / image extractors | `app/ingestion/extractors/` |
| Batch or single-file ingestion | `POST /api/v1/index/ingest` (`?file_id=` optional) |
| Extracted text storage | `documents.extracted_text` + `extracted_text_hash` |

## What's Next

**Phase 5 Milestone 4** — Qdrant client + collection setup (`app/embeddings/vector_store.py`)

Say in a new chat:

> Continue DriveMind AI Phase 5 from `docs/PHASE_5_TRACKER.md` and `docs/CURRENT_STATUS.md`.

## Quick Commands

```bash
# Infra (Postgres + Qdrant for Phase 5)
docker compose -f infra/docker-compose.yml up -d postgres qdrant

# Backend
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Tests
uv run pytest -q
```

## Drive + Ingestion Commands (prerequisite for indexing)

```bash
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl http://localhost:8000/api/v1/files
```

## Manual Setup (Phase 5)

- [x] Google OAuth configured (Phase 3)
- [x] Tesseract installed (Phase 4)
- [ ] Qdrant running (`docker compose ... up -d qdrant`) — before M4
- [ ] `OPENAI_API_KEY` set in `.env` — before real embedding smoke tests (M5+)
- [ ] Postgres + migrations applied
- [ ] Documents ingested (`POST /api/v1/index/ingest`) — before chunk/index smoke tests

## Key Docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_2_TRACKER.md](PHASE_2_TRACKER.md) — Phase 2 log (complete)
- [PHASE_3_TRACKER.md](PHASE_3_TRACKER.md) — Phase 3 log (complete)
- [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md) — Phase 4 log (complete)
- [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md) — Phase 5 log (active)

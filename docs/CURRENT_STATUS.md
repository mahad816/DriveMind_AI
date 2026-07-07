# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 6 complete (Basic RAG API). Phase 7 next.

## Completed Phases

| Phase | Status | Notes |
|-------|--------|-------|
| 0 | Complete | Repo structure, docs, Cursor rules |
| 1 | Complete | FastAPI foundation, health, logging |
| 2 | Complete | DB models, Alembic migration, schemas, tests |
| 3 | Complete | OAuth, Drive client, sync, export/download, incremental sync |
| 4 | Complete | Text extractors, IngestionService, ingest API |
| 5 | Complete | Chunking, embeddings, Qdrant vector index, build API |
| 6 | Complete | Vector RAG, chat API, source viewer, 240 tests |

## Phase 6 Summary (Basic RAG API) — Complete

See [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md) for full milestone log.

| Capability | Module | Status |
|------------|--------|--------|
| Vector retrieval | `app/retrieval/vector.py` | Done |
| Qdrant search | `app/embeddings/vector_store.py` | Done |
| LLM chat service | `app/llm/openai_service.py` | Done |
| RAG orchestration | `app/services/rag_service.py` | Done |
| Chat API | `POST /api/v1/chat` | Done |
| Source viewer | `GET /api/v1/sources/{chunk_id}` | Done |
| Query persistence | `query_history` table | Done |

**Endpoints:**

- `POST /api/v1/chat` — grounded answer + citations
- `GET /api/v1/sources/{chunk_id}` — full chunk text for citation viewer

**Verification:** 240 tests passing; smoke test confirmed grounded answers with citations.

## Phase 5 Index (verified)

- 367 documents indexed, 6036 chunks in Qdrant
- Build result: `embedded: 4888`, `unchanged: 1148`, `failed: 0`
- Qdrant batched upsert fix committed (`fix(embeddings): batch qdrant upserts...`)

## What's Next

**Phase 7 — Hybrid Retrieval** — metadata + keyword + vector merge, reranking, evidence grading

Say in a new chat:

> Continue DriveMind AI Phase 7 from `docs/ROADMAP.md` — hybrid retrieval.

## Quick Commands

```bash
# Infra (Postgres + Qdrant)
docker compose -f infra/docker-compose.yml up -d postgres qdrant

# Backend
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload

# Full index pipeline
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl -X POST http://localhost:8000/api/v1/index/build

# RAG chat (Phase 6)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is tensile strength?"}'
```

## Manual Setup (Phase 6+)

- [x] Google OAuth configured (Phase 3)
- [x] Qdrant running with vectors built
- [x] `OPENAI_API_KEY` set in `.env`
- [x] Postgres + migrations applied
- [x] Index built (`failed: 0`)
- [x] `CHAT_MODEL` wired in settings

## Key Docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md) — Phase 6 log (complete)
- [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md) — Phase 5 log (complete)

# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 8 in progress (LangGraph Agent). M0–M1 complete.

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
| 7 | Complete | Hybrid retrieval, rerank, evidence grading, RAG integration |
| 8 | In progress | LangGraph agent — M0–M1 complete (foundation) |

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

## Phase 7 Summary (Hybrid Retrieval) — Complete

See [PHASE_7_TRACKER.md](PHASE_7_TRACKER.md) for milestone-by-milestone progress.

| Capability | Module | Status |
|------------|--------|--------|
| Metadata retriever | `app/retrieval/metadata.py` | Done |
| Keyword retriever | `app/retrieval/keyword.py` | Done |
| Hybrid merge + dedupe | `app/retrieval/merge.py` | Done |
| Weighted reranking | `app/retrieval/rerank.py` | Done |
| Evidence grading | `app/retrieval/grade.py` | Done |
| RAG integration | `app/retrieval/hybrid.py` + `app/services/rag_service.py` | Done |

**Verification:** full suite passed (`ruff`, `mypy`, `basedpyright`, `pytest`) with 271 tests.

## Phase 8 Summary (LangGraph Agent) — In Progress

See [PHASE_8_TRACKER.md](PHASE_8_TRACKER.md) for milestone-by-milestone progress.

| Capability | Module | Status |
|------------|--------|--------|
| LangGraph dependency | `backend/pyproject.toml` | Done (M1) |
| Drive graph state | `app/agents/drive_graph/state.py` | Done (M1) |
| Intent + retrieval types | `app/agents/drive_graph/types.py` | Done (M1) |
| Agent config flags | `app/core/config.py` | Done (M1) |
| Graph skeleton + runner | `app/agents/drive_graph/graph.py` | Pending (M2) |

**Next milestone:** M2 — graph skeleton + runner.

Say in a new chat (if needed):

> Continue DriveMind AI Phase 8 from `docs/PHASE_8_TRACKER.md` — Milestone 2.

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
- [x] Re-sync after M4 for improved `folder_path` metadata

## Key Docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_8_TRACKER.md](PHASE_8_TRACKER.md) — Phase 8 log (in progress)
- [PHASE_7_TRACKER.md](PHASE_7_TRACKER.md) — Phase 7 log (complete)
- [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md) — Phase 6 log (complete)
- [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md) — Phase 5 log (complete)

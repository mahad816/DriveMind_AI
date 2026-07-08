# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 9 — Frontend Foundation (M0–M9 complete; M10 docs closure in progress).

## Completed Phases

| Phase | Status | Notes |
|-------|--------|-------|
| 0 | Complete | Repo structure, docs, Cursor rules |
| 1 | Complete | FastAPI foundation, health, logging |
| 2 | Complete | DB models, Alembic migration, schemas, tests |
| 3 | Complete | OAuth, Drive client, sync, export/download, incremental sync |
| 4 | Complete | Text extractors, IngestionService, ingest API |
| 5 | Complete | Chunking, embeddings, Qdrant vector index, build API |
| 6 | Complete | Vector RAG, chat API, source viewer |
| 7 | Complete | Hybrid retrieval, rerank, evidence grading, RAG integration |
| 8 | Complete | LangGraph agent — intent routing, rewrite loop, citation verify |
| 9 | Near complete | Next.js UI — chat, files, indexing, settings, sources, chat history, polish |

## Phase 9 Summary (Frontend Foundation)

See [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md) for milestone log.

| Capability | Status |
|------------|--------|
| Next.js scaffold + API proxy | Done |
| App shell + sidebar navigation | Done |
| Settings (OAuth, theme) | Done |
| Indexing dashboard + incremental prepare | Done |
| Files browser + per-file prepare | Done |
| Chat interface + citations | Done |
| Source viewer `/sources/[chunkId]` | Done |
| Chat history (localStorage) + rename/delete/search | Done |
| Copy, retry, regenerate, follow-ups, shortcuts | Done |
| Frontend tests (Vitest) | Done |
| Docs closure (README, status) | In progress |

## Backend Highlights (Phases 6–8)

| Capability | Module |
|------------|--------|
| Hybrid retrieval | `app/retrieval/hybrid.py` |
| FILE_TARGET route | `app/retrieval/file_target.py`, `query_router.py` |
| Filename-aware rerank | `app/retrieval/rerank.py` |
| LangGraph agent | `app/agents/drive_graph/` |
| Incremental indexing | `ingestion_service.py`, `drive_sync_service.py` |
| RAG orchestration | `app/services/rag_service.py` |

**Graph flow (when `AGENT_GRAPH_ENABLED=true`):**

```text
receive_question → classify_intent → plan_retrieval → route_retriever
→ retrieve → rerank → grade_evidence
→ (rewrite_query loop) → generate_answer → verify_citations → return_response
```

## Test Baseline

- Backend: **480** tests passing (`uv run pytest -q`)
- Frontend: **44** tests passing (`npm test`)

## Quick Commands

```bash
# Infra (Postgres + Qdrant)
docker compose -f infra/docker-compose.yml up -d postgres qdrant

# Backend
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Full index pipeline (API)
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl -X POST http://localhost:8000/api/v1/index/chunk
curl -X POST http://localhost:8000/api/v1/index/build

# RAG chat
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is in my latest resume?"}'
```

## Manual Setup Checklist

- [x] Google OAuth configured
- [x] Qdrant running with vectors built
- [x] `OPENAI_API_KEY` in `.env`
- [x] Postgres + migrations applied
- [x] `FRONTEND_URL=http://localhost:3000` in `.env`
- [x] **Recommended:** `AGENT_GRAPH_ENABLED=true` (restart API after change)
- [x] Tesseract installed for image OCR (`brew install tesseract`)

## Next Up

- **Phase 9 M10:** Final verification + phase closure
- **Phase 10:** Evaluation dashboard and retrieval quality metrics
- **Phase 11:** Deployment docs and production hardening

## Key Docs

- [README.md](../README.md) — GitHub landing page
- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md) — Phase 9 log

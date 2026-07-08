# DriveMind AI — Current Status

Use this file to resume work in a new chat.

**Last updated:** Phase 9 in progress (Frontend Foundation). M0–M1 complete.

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
| 8 | Complete | LangGraph agent — intent routing, rewrite loop, citation verify |
| 9 | In progress | Next.js frontend — M0–M1 complete (scaffold) |

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

## Phase 8 Summary (LangGraph Agent) — Complete

See [PHASE_8_TRACKER.md](PHASE_8_TRACKER.md) for milestone-by-milestone progress.

| Capability | Module | Status |
|------------|--------|--------|
| LangGraph dependency | `backend/pyproject.toml` | Done |
| Drive graph state + types | `app/agents/drive_graph/state.py`, `types.py` | Done |
| Graph skeleton + runner | `app/agents/drive_graph/graph.py`, `runner.py` | Done |
| Intent + retrieval planning | `app/agents/drive_graph/nodes.py`, `prompts.py` | Done |
| Routed retrieval | `app/agents/drive_graph/nodes.py` | Done |
| Rerank + grade + rewrite loop | `app/agents/drive_graph/nodes.py`, `graph.py` | Done |
| Answer + citation verify | `app/agents/drive_graph/nodes.py` | Done |
| RAG integration | `app/services/rag_service.py` (`AGENT_GRAPH_ENABLED`) | Done |

**Graph flow:**

```
receive_question → classify_intent → plan_retrieval → route_retriever
→ retrieve → rerank → grade_evidence
→ (rewrite_query loop) → generate_answer → verify_citations → return_response
```

**Verification:** 307 tests passing (+36 from Phase 7 baseline); live smoke confirmed grounded answers with citations on both graph and linear paths.

**Next phase:** Phase 9 — Frontend Foundation (in progress).

See [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md) for milestone-by-milestone progress.

| Capability | Module | Status |
|------------|--------|--------|
| Next.js scaffold | `frontend/app/`, `components/ui/` | Done (M1) |
| API client + proxy | `frontend/lib/api/` | Pending (M2) |
| App shell + pages | `frontend/components/layout/` | Pending (M3+) |

**Next milestone:** M2 — typed API client and OAuth redirect wiring.

Say in a new chat (if needed):

> Continue DriveMind AI Phase 9 from `docs/PHASE_9_TRACKER.md` — Milestone 2.

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

# RAG chat (set AGENT_GRAPH_ENABLED=true in .env for LangGraph path)
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
- [ ] **Recommended:** `AGENT_GRAPH_ENABLED=true` in `.env` (restart API after change)

## Key Docs

- [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) — product vision
- [ROADMAP.md](ROADMAP.md) — all phases
- [ARCHITECTURE.md](ARCHITECTURE.md) — system design
- [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md) — Phase 9 log (in progress)
- [PHASE_7_TRACKER.md](PHASE_7_TRACKER.md) — Phase 7 log (complete)
- [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md) — Phase 6 log (complete)
- [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md) — Phase 5 log (complete)

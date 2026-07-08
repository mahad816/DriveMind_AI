# DriveMind AI — Roadmap

Phased execution plan for building DriveMind AI. Work **one phase at a time** — propose, approve, implement, review, commit.

---

## Phase Overview

| Phase | Name | Status |
|-------|------|--------|
| 0 | Repository & Standards Foundation | Complete |
| 1 | Backend Foundation | Complete |
| 2 | Data Model & Indexing State | Complete |
| 3 | Google Drive Read-Only Integration | Complete |
| 4 | Document Ingestion & Text Extraction | Complete — see [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md) |
| 5 | Chunking & Embeddings | Complete — see [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md) |
| 6 | Basic RAG API | Complete — see [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md) |
| 7 | Hybrid Retrieval | Complete — see [PHASE_7_TRACKER.md](PHASE_7_TRACKER.md) |
| 8 | LangGraph Agent | Complete — see [PHASE_8_TRACKER.md](PHASE_8_TRACKER.md) |
| 9 | Frontend Foundation | Near complete — see [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md) |
| 10 | Evaluation & Quality | Not started |
| 11 | Documentation & Deployment | Not started |

---

## Phase 0: Repository & Standards Foundation

**Goal:** Professional project structure before feature work.

**Deliverables:**

- [x] Monorepo folder structure (`backend/`, `frontend/`, `docs/`, `infra/`, `scripts/`)
- [x] `.gitignore`, `.env.example`, `README.md`
- [x] Core documentation (`PROJECT_CONTEXT`, `ROADMAP`, `ARCHITECTURE`, `GIT_WORKFLOW`)
- [x] Cursor project rule (`.cursor/rules/drivemind-core.mdc`)
- [x] Docker Compose skeleton (PostgreSQL + Qdrant)
- [x] Initialize Git repository
- [x] First commits

**Suggested commits:**

```
chore: initialize DriveMind repository
docs: add DriveMind project context and roadmap
chore: add project rules and git workflow
```

---

## Phase 1: Backend Foundation

**Goal:** Clean FastAPI backend with production-style structure.

**Build:**

- FastAPI app factory
- Settings via environment variables
- Structured logging
- Health endpoint
- Database connection layer
- Alembic migrations
- Base test setup

**Key files:**

- `backend/app/main.py`
- `backend/app/core/config.py`
- `backend/app/core/logging.py`
- `backend/app/api/health.py`
- `backend/app/db/session.py`

**Suggested commits:**

```
feat(backend): add FastAPI application foundation
feat(db): add PostgreSQL session and migrations
test(backend): add health endpoint tests
```

**Phase 1 completion notes:**

- FastAPI app factory and startup lifespan configured
- Settings loaded via environment variables
- Structured logging initialized at app startup
- Liveness and readiness health endpoints implemented
- Async PostgreSQL session layer added
- Alembic migration scaffold initialized
- Health endpoint tests added and passing

---

## Phase 2: Data Model & Indexing State

**Goal:** Model Drive files, documents, chunks, and indexing jobs.

**PostgreSQL tables:**

- `users` (single user for MVP)
- `drive_files` — file metadata from Google Drive
- `documents` — extracted document records
- `chunks` — text chunks with metadata
- `indexing_jobs` — sync and indexing status
- `query_history` — chat query log
- `citations` — answer trace (later)

**Design rule:** PostgreSQL stores metadata and chunk text; Qdrant stores embeddings only.

**Phase 3 progress (complete):**

- All milestones done: OAuth, Drive client, metadata sync, export/download, incremental sync
- Tracker: [PHASE_3_TRACKER.md](PHASE_3_TRACKER.md)
- Next: Phase 6 — basic RAG chat

**Phase 2 completion notes:**

- Shared DB primitives added (`enums`, timestamp mixin)
- Core SQLAlchemy models implemented for users, drive files, documents, chunks, indexing jobs, and query history
- Initial Alembic migration created and validated
- Typed Pydantic schemas added for file, indexing, and query state contracts
- Integrity test suite added for models and migrations

---

## Phase 3: Google Drive Read-Only Integration

**Goal:** Authenticate and sync supported files safely.

**Status:** Complete. See [PHASE_3_TRACKER.md](PHASE_3_TRACKER.md).

**Delivered:**

- OAuth with read-only scopes + PKCE state in PostgreSQL
- Read-only Drive API client (list, metadata, export, download)
- Metadata sync into `drive_files` with indexing job tracking
- Export/download via `GET /files/{id}/content`
- Incremental sync via Drive Changes API + `drive_sync_states` table

**Key files:**

- `backend/app/connectors/google_drive/client.py`
- `backend/app/services/drive_sync_service.py`
- `backend/app/services/drive_content_service.py`
- `backend/app/api/auth.py`, `index.py`, `files.py`

---

## Phase 4: Document Ingestion & Text Extraction

**Goal:** Convert supported file types into normalized text.

**Status:** Complete. See [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md).

**Delivered:**

- Extractor protocol, MIME registry, text hashing, `documents.extracted_text` storage
- Extractors: Google Docs, TXT, DOCX, PDF (text-only), images (Tesseract OCR)
- `IngestionService` orchestration + `POST /api/v1/index/ingest`

**Out of scope (deferred):** EasyOCR, PDF OCR fallback, chunking/embeddings (Phase 5)

**Key files:**

- `backend/app/ingestion/extractors/`
- `backend/app/services/ingestion_service.py`
- `backend/app/api/index.py`

---

## Phase 5: Chunking & Embeddings

**Goal:** Searchable chunks with rich metadata in PostgreSQL and embeddings in Qdrant.

**Status:** Complete. See [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md).

**Delivered:**

- Deterministic text chunker with overlap + metadata
- Idempotent chunk persistence (`POST /api/v1/index/chunk`)
- OpenAI embedding service abstraction
- Qdrant vector store + `drivemind_chunks` collection
- End-to-end index build (`POST /api/v1/index/build`)
- Reindex on `extracted_text_hash` change; stale vector cleanup

**Out of scope:** Chat/RAG (Phase 6), hybrid retrieval (Phase 7), LangGraph (Phase 8)

**Key files:**

- `backend/app/ingestion/chunking.py`
- `backend/app/services/chunking_service.py`
- `backend/app/services/indexing_service.py`
- `backend/app/embeddings/`
- `backend/app/api/index.py`

---

## Phase 6: Basic RAG API

**Goal:** End-to-end question answering with citations.

**Status:** Complete. See [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md).

**Build:**

- Vector retrieval (M1) — Qdrant search + Postgres chunk hydration
- LLM chat service + grounded prompts (M2)
- `RagService` orchestration + `query_history` persistence (M3)
- `POST /chat` endpoint (M4)
- `GET /sources/{chunk_id}` source viewer (M4)
- Citation return format via `CitationItem`
- Test coverage for retrieval, RAG, and API routes (M5)

**Important:** Prove simple RAG works before adding LangGraph.

**Key files:**

- `backend/app/retrieval/vector.py`
- `backend/app/llm/` (M2)
- `backend/app/services/rag_service.py` (M3)
- `backend/app/api/chat.py`, `sources.py` (M4)

**Phase 6 completion notes:**

- End-to-end flow: question → embed → Qdrant search → Postgres hydrate → LLM answer → citations → `query_history`
- Vector-only retrieval (hybrid deferred to Phase 7)
- 240 backend tests passing; smoke test confirmed grounded answers with citations
- Next: Phase 7 — hybrid metadata + keyword + merge + rerank

---

## Phase 7: Hybrid Retrieval

**Goal:** Reliable retrieval for real Drive questions.

**Status:** Complete. See [PHASE_7_TRACKER.md](PHASE_7_TRACKER.md).

**Build:**

- Metadata retriever (latest, type, folder, date)
- Keyword retriever (PostgreSQL full-text search)
- Vector retriever (Qdrant)
- Result merge and deduplication
- Reranking
- Evidence grading

**Key files:**

- `backend/app/retrieval/metadata.py`
- `backend/app/retrieval/keyword.py`
- `backend/app/retrieval/vector.py`
- `backend/app/retrieval/hybrid.py`

**Phase 7 completion notes:**

- Hybrid retrieval stack delivered: vector + keyword + metadata retrieval
- Reciprocal-rank-fusion merge + weighted reranking + threshold evidence grading
- `RagService` integrated with `HybridRetriever` and vector fallback toggle
- Coverage expanded across retrieval internals and service integration
- Verification passed: `ruff`, `mypy`, `basedpyright`, and 271 backend tests

---

## Phase 8: LangGraph Agent

**Goal:** Agentic retrieval workflow replacing linear RAG.

**Status:** Complete. See [PHASE_8_TRACKER.md](PHASE_8_TRACKER.md).

**Delivered:**

- LangGraph foundation (`DriveGraphState`, `QueryIntent`, `RetrievalPlan`, config flags)
- Graph skeleton with runner (`build_drive_graph`, `run_drive_graph`)
- Intent classification + retrieval planning (rule heuristics + LLM fallback)
- Routed retrieval (selective retrievers per intent)
- Rerank + evidence grading (reuse Phase 7)
- Query rewrite loop with `AGENT_MAX_REWRITE_ATTEMPTS` cap
- Answer generation + citation verification
- `RagService` integration behind `AGENT_GRAPH_ENABLED`

**Graph nodes:**

```
receive_question → classify_intent → plan_retrieval → route_retriever
→ retrieve → rerank → grade_evidence
→ (rewrite_query loop) → generate_answer → verify_citations → return_response
```

**Key files:**

- `backend/app/agents/drive_graph/state.py`
- `backend/app/agents/drive_graph/types.py`
- `backend/app/agents/drive_graph/graph.py`
- `backend/app/agents/drive_graph/nodes.py`
- `backend/app/agents/drive_graph/runner.py`
- `backend/app/services/rag_service.py` (feature-flag delegation)

**Verification:** `ruff`, `mypy`, `basedpyright`, and **307** backend tests; live smoke confirmed grounded answers with citations on both graph and linear paths.

---

## Phase 9: Frontend Foundation

**Goal:** Next.js UI after backend API is meaningful.

**Status:** Near complete. See [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md).

**Build:**

- Next.js App Router + TypeScript + Tailwind + shadcn/ui
- Typed API client with Next.js proxy (same-origin `/api/v1`)
- App shell with sidebar navigation and chat history (localStorage)
- Settings (Drive OAuth connection, theme)
- Indexing dashboard (sync → ingest → chunk → build pipeline, incremental)
- Files browser with per-file prepare and ask-about-file
- Chat interface with citations, copy/retry/regenerate, follow-ups, shortcuts
- Source citation viewer

**Milestones:**

| # | Deliverable |
|---|-------------|
| M0 | Tracker + docs alignment |
| M1 | Next.js scaffold + design system |
| M2 | API client + proxy + OAuth redirect |
| M3 | App shell + navigation |
| M4 | Settings page |
| M5 | Indexing dashboard |
| M6 | Files browser |
| M7 | Chat interface |
| M8 | Source citation viewer |
| M9 | Polish + chat history + message actions + frontend tests |
| M10 | Verification + docs closure |

**Explicitly deferred:** Server-backed chat history, evaluation dashboard (Phase 10), SSE streaming, multi-user auth UI.

---

## Phase 10: Evaluation & Quality

**Goal:** Demonstrate AI engineering rigor.

**Build:**

- Golden test questions
- Retrieval evaluation endpoint
- Citation correctness checks
- Answer quality metrics
- Regression dataset

---

## Phase 11: Documentation & Deployment

**Goal:** Portfolio-ready project.

**Docs:**

- Local setup guide
- Google Drive OAuth setup
- Indexing lifecycle
- Retrieval strategy
- LangGraph workflow
- Evaluation methodology
- Limitations and future roadmap

**Deployment:** Backend, frontend, PostgreSQL, Qdrant with proper secret management.

---

## Execution Rule

For each phase:

1. Propose exact files and implementation steps
2. Get approval
3. Implement only approved scope
4. Run relevant checks
5. Show diff summary
6. Approve commit
7. Create commit with professional message

See [GIT_WORKFLOW.md](GIT_WORKFLOW.md) for commit and branch discipline.

See [EXECUTION_PLAN.md](EXECUTION_PLAN.md) for the full detailed plan with file references.

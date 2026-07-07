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
| 6 | Basic RAG API | Not started — next phase |
| 7 | Hybrid Retrieval | Not started |
| 8 | LangGraph Agent | Not started |
| 9 | Frontend Foundation | Not started |
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

**Build:**

- `POST /chat` endpoint
- Vector retrieval
- Grounded answer prompt
- Citation return format
- Source viewer endpoint

**Important:** Prove simple RAG works before adding LangGraph.

---

## Phase 7: Hybrid Retrieval

**Goal:** Reliable retrieval for real Drive questions.

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

---

## Phase 8: LangGraph Agent

**Goal:** Agentic retrieval workflow replacing linear RAG.

**Graph nodes:**

```
receive_question
    ↓
classify_intent
    ↓
plan_retrieval
    ↓
route_retriever
    ↓
retrieve → rerank → grade_evidence
    ↓
Enough? ──No──→ rewrite_query → retrieve_again
    │
   Yes
    ↓
generate_answer
    ↓
verify_citations
    ↓
return_response
```

**Key files:**

- `backend/app/agents/drive_graph/state.py`
- `backend/app/agents/drive_graph/graph.py`
- `backend/app/agents/drive_graph/nodes.py`

---

## Phase 9: Frontend Foundation

**Goal:** Next.js UI after backend API is meaningful.

**Pages:**

- Chat interface
- Indexing dashboard
- Source/citation viewer
- Settings (Drive connection, model config)
- Evaluation dashboard (later)

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

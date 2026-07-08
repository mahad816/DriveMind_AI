# DriveMind AI — Execution Plan

Detailed phase-by-phase execution plan. This document mirrors the approved Cursor plan and serves as the in-repo source of truth.

> **Execution rule:** Work one phase at a time. Propose → approve → implement → review → commit.

---

## Current Starting Point

Repository foundation at `INFO_VAULT`. Backend and frontend are scaffolded with module structure only — no feature implementation yet.

---

## Approval And Memory Workflow

- Use Plan Mode for architecture decisions and major feature designs
- Switch to Agent Mode only after approving an implementation plan
- Make small commits after each meaningful milestone
- Before each commit: review `git status`, `git diff`, use clear commit message
- Never commit secrets, tokens, `.env`, downloaded Drive files, or local DB data

**Persistent project memory:**

| File | Purpose |
|------|---------|
| `docs/PROJECT_CONTEXT.md` | Full product and architecture context |
| `docs/ROADMAP.md` | Phases and execution order |
| `docs/ARCHITECTURE.md` | System design |
| `docs/GIT_WORKFLOW.md` | Commit discipline and branch rules |
| `.cursor/rules/drivemind-core.mdc` | Always-applied Cursor rule |

---

## Repository Structure

```text
backend/
  app/
    api/          FastAPI route handlers
    agents/       LangGraph workflow
    connectors/   Google Drive integration
    core/         Config, logging, utilities
    db/           Models, session, migrations
    embeddings/   Embedding generation, Qdrant
    evaluation/   Quality metrics
    ingestion/    Extraction, chunking
    jobs/         Background tasks
    retrieval/    Hybrid search
    schemas/      Pydantic models
    services/     Domain logic
  tests/
  pyproject.toml
  Dockerfile
frontend/
  app/            Next.js pages
  components/     UI components
  lib/            API client, utilities
  public/
  package.json
  next.config.ts
docs/
infra/
  docker-compose.yml
scripts/
.cursor/rules/
```

The backend owns AI, Drive, indexing, retrieval, and APIs. The frontend consumes backend APIs only.

---

## Phase 0: Repo And Standards Foundation

**Goal:** Professional project before features.

- [x] Monorepo structure
- [x] `.gitignore`, `.env.example`, `README.md`
- [x] Core docs and Cursor rules
- [x] Docker Compose skeleton
- [ ] Initialize Git repo
- [ ] First commits

**Commits:**

```
chore: initialize DriveMind repository
docs: add DriveMind project context and roadmap
chore: add project rules and git workflow
```

---

## Phase 1: Backend Foundation

**Goal:** Clean FastAPI backend.

**Files:**

- `backend/app/main.py`
- `backend/app/core/config.py`
- `backend/app/core/logging.py`
- `backend/app/api/health.py`
- `backend/app/db/session.py`

**Commits:**

```
feat(backend): add FastAPI application foundation
feat(db): add PostgreSQL session and migrations
test(backend): add health endpoint tests
```

---

## Phase 2: Data Model And Indexing State

**Goal:** PostgreSQL models for Drive files, chunks, indexing jobs.

**Tables:** users, drive_files, documents, chunks, indexing_jobs, query_history

**Rule:** PostgreSQL = metadata + chunk text; Qdrant = embeddings only.

---

## Phase 3: Google Drive Read-Only Integration

**Goal:** OAuth, listing, metadata sync, export/download.

**Files:**

- `backend/app/connectors/google_drive/client.py`
- `backend/app/connectors/google_drive/service.py`
- `backend/app/api/drive.py`

---

## Phase 4: Document Ingestion And Text Extraction

**Goal:** Normalize text from Google Docs, PDF (text-only), DOCX, TXT, and images.

**Status:** Complete. See [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md).

**Delivered:** Extractors, `IngestionService`, `POST /api/v1/index/ingest`.

**Location:** `backend/app/ingestion/`, `backend/app/services/ingestion_service.py`

---

## Phase 5: Chunking And Embeddings

**Goal:** Searchable chunks with metadata in PostgreSQL + Qdrant vectors.

**Status:** Complete. See [PHASE_5_TRACKER.md](PHASE_5_TRACKER.md).

**Delivered:** Chunker, chunk API, OpenAI embeddings, Qdrant store, `POST /api/v1/index/build`.

---

## Phase 6: Basic RAG API

**Goal:** `/chat` with vector retrieval and citations. No LangGraph yet.

**Status:** Complete. See [PHASE_6_TRACKER.md](PHASE_6_TRACKER.md).

**Delivered:** Vector retriever, OpenAI chat service, `RagService`, `POST /api/v1/chat`, `GET /api/v1/sources/{chunk_id}`, query history persistence, 240 tests.

---

## Phase 7: Hybrid Retrieval

**Goal:** Metadata + keyword + vector + merge + rerank + evidence grading.

**Status:** Complete. See [PHASE_7_TRACKER.md](PHASE_7_TRACKER.md).

**Milestones:**

| # | Deliverable |
|---|-------------|
| M0 | Tracker + docs alignment |
| M1 | Retrieval foundation (`types`, protocol, candidate pool config) |
| M2 | PostgreSQL FTS migration + chunk search-vector sync |
| M3 | Keyword retriever |
| M4 | Metadata retriever + folder path sync fix |
| M5 | Reciprocal rank fusion merge + dedupe |
| M6 | Weighted fusion reranker |
| M7 | Evidence grader |
| M8 | Hybrid retriever wiring into `RagService` |
| M9 | Test coverage for hybrid retrieval |
| M10 | Verification + docs closure |

**Files:**

- `backend/app/retrieval/metadata.py`
- `backend/app/retrieval/keyword.py`
- `backend/app/retrieval/vector.py`
- `backend/app/retrieval/hybrid.py`

---

## Phase 8: LangGraph Agent

**Goal:** Agentic workflow with intent classification, retrieval routing, query rewrite, citation verification.

**Status:** Complete. See [PHASE_8_TRACKER.md](PHASE_8_TRACKER.md).

**Milestones:**

| # | Deliverable |
|---|-------------|
| M0 | Tracker + docs alignment |
| M1 | LangGraph dependency + `DriveGraphState` + types + config |
| M2 | Graph skeleton + runner |
| M3 | Intent classification + retrieval planning nodes |
| M4 | Route retriever + retrieve node |
| M5 | Rerank + grade evidence nodes |
| M6 | Query rewrite loop |
| M7 | Generate answer + verify citations + return |
| M8 | RagService integration behind `AGENT_GRAPH_ENABLED` |
| M9 | Agent node + graph integration tests |
| M10 | Verification + docs closure |

**Nodes:** receive_question → classify_intent → plan_retrieval → route_retriever → retrieve → rerank → grade_evidence → (rewrite_query loop) → generate_answer → verify_citations → return_response

**Files:**

- `backend/app/agents/drive_graph/state.py`
- `backend/app/agents/drive_graph/types.py`
- `backend/app/agents/drive_graph/graph.py`
- `backend/app/agents/drive_graph/nodes.py`
- `backend/app/agents/drive_graph/runner.py`

---

## Phase 9: Frontend Foundation

**Goal:** Next.js chat, indexing dashboard, source viewer, settings.

**Status:** In progress. See [PHASE_9_TRACKER.md](PHASE_9_TRACKER.md).

**Milestones:**

| # | Deliverable |
|---|-------------|
| M0 | Tracker + docs alignment |
| M1 | Next.js scaffold + Tailwind + shadcn/ui |
| M2 | Typed API client + Next.js proxy + OAuth redirect |
| M3 | App shell + sidebar navigation |
| M4 | Settings page (Drive connect, theme) |
| M5 | Indexing dashboard (pipeline stepper) |
| M6 | Files browser |
| M7 | Chat interface with citations |
| M8 | Source citation viewer |
| M9 | Polish + vitest coverage |
| M10 | Verification + docs closure |

**Pages:** `/chat`, `/index`, `/files`, `/settings`, `/sources/[chunkId]`

**Files:**

- `frontend/app/` — App Router pages
- `frontend/components/` — layout, chat, index, files, ui
- `frontend/lib/api/` — typed API client (M2+)

---

## Phase 10: Evaluation And Quality

**Goal:** Golden questions, retrieval eval, citation checks, regression dataset.

---

## Phase 11: Documentation And Deployment

**Goal:** Portfolio-ready setup guides, OAuth docs, deployment plan.

---

## Execution Rule (Per Phase)

1. Propose exact files and implementation steps
2. User approves
3. Implement only approved scope
4. Run relevant checks
5. Show diff summary
6. User approves commit
7. Create commit with professional message

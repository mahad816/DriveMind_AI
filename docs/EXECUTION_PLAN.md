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

**Tracker:** [PHASE_4_TRACKER.md](PHASE_4_TRACKER.md)

**In scope:**

- Google Docs, TXT, DOCX, PDF (`pypdf`), image OCR (Tesseract)

**Out of scope:**

- EasyOCR, PDF OCR fallback, chunking/embeddings (Phase 5)

**Location:** `backend/app/ingestion/extractors/`

---

## Phase 5: Chunking And Embeddings

**Goal:** Searchable chunks with metadata in PostgreSQL + Qdrant.

**Chunk metadata:** file ID, filename, MIME type, Drive URL, modified time, page/section, chunk index.

---

## Phase 6: Basic RAG API

**Goal:** `/chat` with vector retrieval and citations. No LangGraph yet.

---

## Phase 7: Hybrid Retrieval

**Goal:** Metadata + keyword + vector + merge + rerank + evidence grading.

**Files:**

- `backend/app/retrieval/metadata.py`
- `backend/app/retrieval/keyword.py`
- `backend/app/retrieval/vector.py`
- `backend/app/retrieval/hybrid.py`

---

## Phase 8: LangGraph Agent

**Goal:** Agentic workflow with intent classification, retrieval routing, query rewrite, citation verification.

**Nodes:** receive_question → classify_intent → plan_retrieval → route_retriever → retrieve → rerank → grade_evidence → (rewrite_query loop) → generate_answer → verify_citations → return_response

**Files:**

- `backend/app/agents/drive_graph/state.py`
- `backend/app/agents/drive_graph/graph.py`
- `backend/app/agents/drive_graph/nodes.py`

---

## Phase 9: Frontend Foundation

**Goal:** Next.js chat, indexing dashboard, source viewer, settings.

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

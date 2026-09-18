# DriveMind Agent Guide

## Project

DriveMind / InfoVault is a single-user Google Drive knowledge assistant. It syncs read-only Drive content, builds a hybrid search index, and answers questions with source citations.

Main stack: Next.js 15, React 19, TypeScript, FastAPI, SQLAlchemy/asyncpg, PostgreSQL, Qdrant, Google Drive OAuth/API, OpenAI embeddings and chat completions, LangGraph, and Tesseract OCR.

## Architecture

- The Next.js frontend calls only the FastAPI REST API through the `/api/v1` rewrite in `frontend/next.config.ts`. Browser conversation history is stored in `localStorage`.
- PostgreSQL stores users/OAuth state, Drive metadata, extracted document text, chunks and full-text vectors, indexing jobs, and query history. Qdrant stores embeddings keyed by PostgreSQL chunk UUID.
- Google Drive access is read-only. Sync stores metadata; ingestion later exports/downloads content. Chat reads the local PostgreSQL/Qdrant index and does not query Drive directly.
- `RagService` routes every question first. Chitchat and inventory have dedicated paths; named files use direct file-target retrieval. General grounded queries use the linear hybrid pipeline unless `AGENT_GRAPH_ENABLED` enables the LangGraph retrieval/rewrite workflow. Preserve both grounded paths.

## Important Directories

- `backend/app/api/`: FastAPI routes and dependency wiring.
- `backend/app/services/`: OAuth, Drive sync/content, ingestion, chunking, indexing, RAG, and source orchestration.
- `backend/app/connectors/google_drive/`: Drive API client and supported MIME behavior.
- `backend/app/ingestion/`: extractors, normalization, hashing, and deterministic chunking.
- `backend/app/retrieval/`: query routing, inventory/file-target/vector/keyword/metadata retrieval, fusion, reranking, and evidence grading.
- `backend/app/agents/drive_graph/`: LangGraph state, nodes, graph, and runner.
- `backend/app/llm/`, `backend/app/embeddings/`: OpenAI generation, context/citations, embeddings, and Qdrant integration.
- `backend/app/db/`, `backend/alembic/`: persistence models, sessions, enums, and migrations.
- `backend/tests/`: backend unit, service, API, retrieval, ingestion, and graph tests.
- `frontend/app/`, `frontend/components/`: routes and UI.
- `frontend/lib/api/`: backend client; `frontend/lib/knowledge/`: indexing workflow; `frontend/lib/conversations/`: local chat history.
- `infra/docker-compose.yml`: local PostgreSQL and Qdrant.
- `docs/ARCHITECTURE.md` and `docs/guides/`: detailed design and operating documentation.

## Core Flows

1. **Indexing:** `POST /index/sync` discovers or updates Drive metadata and change cursors. `POST /index/ingest` downloads/exports supported files, extracts normalized text, hashes it, and persists `Document` rows. `POST /index/chunk` creates overlapping chunks and PostgreSQL full-text vectors. `POST /index/build` embeds pending chunks, reconciles per-file Qdrant points, and marks files indexed. These are separate in-process background jobs; the frontend sequences and polls them.
2. **Query:** `POST /chat` calls `RagService.ask`, which classifies the route. Grounded retrieval uses vector, PostgreSQL keyword, and metadata candidates as selected by the linear or LangGraph path, then merges/reranks and grades evidence. Bounded prompt context is passed to the chat model. Citation payloads are derived from prompt chunks, filtered/verified, persisted with query history, and resolved through `/sources/{chunk_id}`.

## Stabilization Baseline

Pre-evaluation stabilization A1-A6, A7/A9, and A11 is complete, reviewed, tested, committed, and pushed. Treat these behaviors as the current baseline and do not revisit them unless a later task directly requires it.

Relevant stabilization commits on `main`:

- `d1b0e47` — exclude non-indexed files from retrieval.
- `7f752af` — reconcile missing files during full Drive sync.
- `47edbbf` — handle trashed and unsupported Drive changes.
- `4cfa8c8` — capture the Drive change token before full sync.
- `f9a599e` — normalize RAG citations consistently.
- `60770b1` — make indexing job states reliable (A7/A9).
- `4791d20` — route short knowledge queries to retrieval (A11).

### Final indexing/job semantics (A7/A9)

- Successful extraction with empty or whitespace-only searchable text sets the `DriveFile` to `SKIPPED`, counts as skipped, and does not fail the stage job. Existing coherent document/chunk data is not overwritten merely to store empty content.
- A zero-chunk result sets the parent file to `SKIPPED`; stale PostgreSQL chunks are removed when chunk replacement produces zero chunks. Index build also defensively maps zero chunks to `SKIPPED`.
- Explicit chunk/build requests for an already-`SKIPPED` file stop before loading or processing preserved stale content. They count the file as skipped and cannot restore it to `INDEXED`.
- Caught extraction/fetch, embedding, and vector-store failures set the affected file to `FAILED`. Successful files in the same batch retain their successful states.
- In ingestion and index build, `failed == 0` means job `COMPLETED`; `failed > 0` means job `FAILED` with a concise stage-specific `job.error`. An unexpected guarded exception also fails the persisted job.
- Index-build jobs are created and committed before `ensure_collection()` runs, so collection-setup failure produces a visible terminal `FAILED` job.
- `COMPLETED` means the stage finished without file-processing failures; it does not imply that any file became `INDEXED`.
- No new status, schema, migration, API contract, frontend polling behavior, or physical stale-vector cleanup was introduced.

### Final top-level routing semantics (A11)

- `CHITCHAT` is positively identified from a narrow normalized exact-phrase set covering greetings, acknowledgements, farewells, simple social conversation, and the explicit capability/identity questions `what can you do` and `who are you`.
- Query length is not a chitchat signal. The former five-word fallback and finite knowledge-keyword exception list were removed.
- Uncertain substantive queries fall through to existing specialized routing or `GROUNDED_RAG`. Examples such as `CoreChain architecture`, `machine learning`, `notes`, and `Python` reach grounded retrieval rather than bypassing the knowledge base.
- Quoted-file handling, `FILE_INVENTORY`, `FILE_TARGET`, and grounded linear/LangGraph execution retain their prior precedence and behavior.
- The existing ambiguity where unquoted `Tell me about CoreChain` routes to `FILE_TARGET` is intentional and remains out of scope pending routing evaluation.

At this stabilization checkpoint, focused and full backend verification passed (`562 passed`) together with Ruff, Ruff formatting, mypy, basedpyright, and `git diff --check`.

## Development

Run commands from the repository root unless a `cd` is shown.

```bash
# Infrastructure
docker compose -f infra/docker-compose.yml up -d postgres qdrant
docker compose -f infra/docker-compose.yml ps

# Backend setup and start
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# Frontend setup and start
cd frontend
npm install
npm run dev

# Backend tests and checks (from backend/)
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run basedpyright app tests

# Frontend tests and checks (from frontend/)
npm test
npm run lint
npm run build
```

## Engineering Rules

- Inspect the relevant implementation, tests, configuration, and call sites before modifying behavior.
- Preserve the existing architecture unless a change has a clear, task-specific justification.
- Keep changes scoped; avoid unrelated refactors or formatting churn.
- Preserve both linear and LangGraph RAG behavior unless the task explicitly changes them.
- Add or update tests whenever behavior changes, and run the relevant tests afterward.
- Never expose secrets, print real credentials, or commit `.env` values.
- Treat code and configuration as authoritative when documentation disagrees; update affected docs when appropriate.
- Do not unintentionally change public API paths, schemas, status semantics, citation contracts, or frontend expectations.
- Preserve user work in a dirty worktree and do not overwrite unrelated changes.

## Known Important Constraints

- This is a single-user MVP: services commonly resolve the first stored Google OAuth token when no explicit user ID is supplied. Do not assume multi-user isolation exists.
- Drive access must remain read-only unless a task explicitly changes the product security model.
- Supported ingestion types are Google Docs, TXT, PDF text extraction, DOCX paragraph extraction, and image OCR; scanned PDFs have no OCR fallback.
- Chunk text is authoritative in PostgreSQL; embeddings are in Qdrant. Keep their shared chunk UUID and per-file reconciliation behavior intact.
- File lifecycle is `discovered -> indexing -> indexed`, with `failed` and `skipped` states. Index build is the stage that marks a file indexed.
- Index jobs run inside the FastAPI process, and `/index/status` reports the latest job for the connected user.
- Hybrid retrieval and LangGraph are independently controlled by `HYBRID_RETRIEVAL_ENABLED` and `AGENT_GRAPH_ENABLED`; LangGraph applies only to grounded RAG after top-level routing.
- Chitchat and file-inventory responses intentionally have no citations. Grounded and file-target citations use PostgreSQL chunk IDs and must remain compatible with the source endpoint and frontend source viewer.
- `backend/app/evaluation/` currently has no implemented runner or metrics; evaluation methodology is documented as planned work.

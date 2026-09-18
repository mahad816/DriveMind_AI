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

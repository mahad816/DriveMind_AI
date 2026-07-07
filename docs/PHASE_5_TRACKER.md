# Phase 5 Tracker — Chunking & Embeddings

Track milestone-by-milestone progress for Phase 5, with matching commit messages.

## Phase Goal

Turn Phase 4 extracted text into searchable chunks stored in PostgreSQL, generate embeddings, and store vectors in Qdrant — ready for retrieval in Phase 6.

## Scope (MVP)

| Capability | Method | Status |
|------------|--------|--------|
| Text chunking | Deterministic splitter with overlap + metadata | Done (M1) |
| Chunk persistence | Idempotent rows in `chunks` table | Done (M2) |
| Embedding service | Provider abstraction (OpenAI `text-embedding-3-small`) | Done (M3) |
| Vector store | Qdrant collection `drivemind_chunks` | Done (M4) |
| Indexing pipeline | Chunks → embed → upsert, reindex on text change | Done (M5) |

## Explicitly Out of Scope (Phase 5)

| Item | Reason |
|------|--------|
| **Chat / RAG answers** | Phase 6 |
| **Hybrid retrieval, reranking** | Phase 7 |
| **LangGraph agent** | Phase 8 |
| **Frontend UI** | Phase 9 |
| **Multi-provider embedding routing** | MVP uses one provider |
| **Background job queue** | Sync API is enough for single-user MVP unless perf forces change |

### Design rules (unchanged from architecture)

- **PostgreSQL** stores chunk text and metadata.
- **Qdrant** stores embeddings and lookup payloads only — never original Drive files.
- Reindex when `documents.extracted_text_hash` changes.

## Current Snapshot

- **Phase status:** Complete
- **Last completed milestone:** Milestone 6 (verification + phase closure)
- **Next phase:** Phase 6 — Basic RAG Chat
- **Blocker:** None

## Your Action Items (manual setup)

- [x] **Step A — Qdrant running**
- [x] **Step B — OpenAI API key in `.env`**
- [x] **Step C — Postgres + migrations**
- [x] **Step D — Extracted documents exist**

## Milestone Status

- [x] Milestone 0 — Phase 5 tracker + setup checklist + docs alignment
- [x] Milestone 1 — Deterministic text chunker (`app/ingestion/chunking.py`)
- [x] Milestone 2 — Chunk persistence service + `POST /api/v1/index/chunk`
- [x] Milestone 3 — Embedding provider abstraction + settings
- [x] Milestone 4 — Qdrant client + collection setup (`app/embeddings/vector_store.py`)
- [x] Milestone 5 — End-to-end indexing pipeline (`POST /api/v1/index/build`)
- [x] Milestone 6 — Verification + Phase 5 docs closure

## Commit Plan

1. `docs(indexing): add phase 5 tracker and chunking plan`
2. `feat(indexing): add deterministic text chunker`
3. `feat(indexing): persist document chunks idempotently`
4. `feat(embeddings): add embedding service abstraction`
5. `feat(embeddings): add qdrant vector store setup`
6. `feat(indexing): build chunk embedding pipeline`
7. `docs(indexing): complete phase 5 chunking and embeddings`

## Target Module Layout

```text
backend/app/ingestion/
  chunking.py              # text splitter + chunk metadata (M1)

backend/app/services/
  chunking_service.py      # documents -> chunks in Postgres (M2)
  indexing_service.py      # chunks -> embeddings -> Qdrant (M5)

backend/app/embeddings/
  base.py                  # EmbeddingService protocol (M3)
  openai_service.py        # OpenAI embeddings (M3)
  vector_store.py          # Qdrant upsert/search setup (M4)
  factory.py               # get_embedding_service()

backend/app/api/index.py   # POST /chunk, POST /build (M2, M5)
```

## API Endpoints (Phase 5)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/index/chunk` | Split extracted documents into Postgres chunks |
| POST | `/api/v1/index/build` | Chunk + embed + upsert vectors into Qdrant |

`POST /build` orchestrates chunk sync, embedding, stale vector cleanup, and idempotent skip when `extracted_text_hash` already indexed in Qdrant.

## Chunk defaults

| Setting | MVP value |
|---------|-----------|
| Target size | ~3,500 characters (~900 tokens) |
| Overlap | ~500 characters (~150 tokens) |
| Boundaries | Prefer paragraph breaks |

## Qdrant payload

```text
Collection: drivemind_chunks
  vector: float[1536]  # text-embedding-3-small
  payload:
    chunk_id
    drive_file_id
    filename
    mime_type
    modified_at
    chunk_index
    extracted_text_hash
```

## Verification Commands

```bash
cd backend
uv sync --dev
uv run ruff check app tests
uv run mypy app
uv run basedpyright app tests
uv run pytest -q
```

## End-to-end smoke test

```bash
# Infra + backend running
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl -X POST http://localhost:8000/api/v1/index/build
curl http://localhost:6333/collections/drivemind_chunks
```

Optional granular steps:

```bash
curl -X POST http://localhost:8000/api/v1/index/chunk
```

## Phase 5 Closure

All milestones complete. Verification before moving to Phase 6:

```bash
cd backend
uv run ruff check app tests
uv run mypy app
uv run basedpyright app tests
uv run pytest -q
```

Smoke test (with backend running, Drive connected, Qdrant up, OpenAI key set):

```bash
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl -X POST http://localhost:8000/api/v1/index/build
```

## Notes

- Input to chunking is `documents.extracted_text` from Phase 4 ingest — not raw Drive bytes.
- Use `extracted_text_hash` for idempotent skip/reindex in both Postgres chunks and Qdrant payloads.
- Mock OpenAI and Qdrant in unit tests; no network in CI.
- Phase 6 will add vector retrieval and `/chat` on top of this index.

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
| Vector store | Qdrant collection `drivemind_chunks` | Planned |
| Indexing pipeline | Chunks → embed → upsert, reindex on text change | Planned |

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

- **Phase status:** In progress (Milestone 3 complete)
- **Next milestone:** Milestone 4 (Qdrant client + collection setup)
- **Blocker:** None

## Your Action Items (manual setup)

Complete **before Milestone 4** (Qdrant smoke tests):

- [ ] **Step A — Qdrant running**
  ```bash
  cd /Users/maddy/Desktop/INFO_VAULT
  docker compose -f infra/docker-compose.yml up -d qdrant
  curl http://localhost:6333/readyz
  ```
  Expected: HTTP 200 from readiness endpoint.

Complete **before Milestone 3** (real embedding calls):

- [ ] **Step B — OpenAI API key in `.env`**
  ```bash
  # In repo-root .env (save file after edit):
  OPENAI_API_KEY=sk-...
  EMBEDDING_MODEL=text-embedding-3-small
  ```
  Restart uvicorn after changing `.env`.

Complete **before Milestone 2** chunk smoke tests (should already be done from Phase 4):

- [ ] **Step C — Postgres + migrations**
  ```bash
  docker compose -f infra/docker-compose.yml up -d postgres
  cd backend && uv run alembic upgrade head
  ```

- [ ] **Step D — Extracted documents exist**
  ```bash
  # Backend running; OAuth connected
  curl -X POST http://localhost:8000/api/v1/index/sync
  curl -X POST http://localhost:8000/api/v1/index/ingest
  ```

Steps A–D are not required for Milestone 0–1 (docs + chunker code only).

## Milestone Status

- [x] Milestone 0 — Phase 5 tracker + setup checklist + docs alignment
- [x] Milestone 1 — Deterministic text chunker (`app/ingestion/chunking.py`)
- [x] Milestone 2 — Chunk persistence service + optional `POST /api/v1/index/chunk`
- [x] Milestone 3 — Embedding provider abstraction + settings
- [ ] Milestone 4 — Qdrant client + collection setup
- [ ] Milestone 5 — End-to-end indexing pipeline (`POST /api/v1/index/build`)
- [ ] Milestone 6 — Verification + Phase 5 docs closure

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

backend/app/api/index.py   # POST /chunk, POST /build (M2, M5)
```

## Chunk defaults (Milestone 1)

| Setting | MVP value |
|---------|-----------|
| Target size | ~3,500 characters (~900 tokens) |
| Overlap | ~500 characters (~150 tokens) |
| Boundaries | Prefer paragraph breaks |

## Qdrant payload (Milestone 4+)

```text
Collection: drivemind_chunks
  vector: float[embedding_dim]
  payload:
    chunk_id      # PostgreSQL chunks.id
    drive_file_id
    filename
    mime_type
    modified_at
    chunk_index
```

## Verification Commands (per milestone)

```bash
cd backend
uv sync --dev
uv run ruff check app tests
uv run mypy app
uv run basedpyright app tests
uv run pytest -q
```

## End-to-end smoke test (after Milestone 5)

```bash
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl -X POST http://localhost:8000/api/v1/index/build
curl http://localhost:6333/collections/drivemind_chunks
```

## Notes

- Input to chunking is `documents.extracted_text` from Phase 4 ingest — not raw Drive bytes.
- Use `extracted_text_hash` for idempotent skip/reindex.
- Mock OpenAI and Qdrant in unit tests; no network in CI.
- Phase 6 will add vector retrieval and `/chat` on top of this index.

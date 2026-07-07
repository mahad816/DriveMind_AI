# Phase 6 Tracker — Basic RAG API

Track milestone-by-milestone progress for Phase 6, with matching commit messages.

## Phase Goal

Deliver end-to-end grounded question answering over indexed Drive content: embed the question, retrieve similar chunks from Qdrant, load authoritative chunk text from PostgreSQL, and prepare for LLM answers with citations in later milestones.

## Scope (MVP)

| Capability | Method | Status |
|------------|--------|--------|
| Vector retrieval | Qdrant similarity search + Postgres chunk hydration | Done (M1) |
| LLM chat service | OpenAI chat completions + grounded prompts | Done (M2) |
| RAG orchestration | Retrieve → generate → cite → persist `query_history` | Not started (M3) |
| Chat API | `POST /api/v1/chat` | Not started (M4) |
| Source viewer | `GET /api/v1/sources/{chunk_id}` | Not started (M4) |
| Query persistence | Store question, answer, citations in `query_history` | Not started (M3) |

## Explicitly Out of Scope (Phase 6)

| Item | Reason |
|------|--------|
| **LangGraph agent workflow** | Phase 8 |
| **Hybrid retrieval (metadata + keyword + merge)** | Phase 7 |
| **Reranking and evidence grading** | Phase 7 |
| **Streaming responses (SSE)** | Phase 9 frontend |
| **Multi-turn conversation memory** | Phase 8+; Phase 6 is single-turn |
| **Frontend chat UI** | Phase 9 |
| **Retrieval evaluation endpoint** | Phase 10 |
| **`GET /chat/history` list API** | Optional; defer to Phase 10 unless needed |

### Design rules (unchanged from architecture)

- **LLM never reads Google Drive directly** — only retrieved Postgres chunk text.
- **PostgreSQL** stores authoritative chunk text; **Qdrant** stores embeddings and lookup payloads.
- **Every chat answer must return citations** (`chunk_id`, `filename`, `snippet`, `score`).
- If retrieval returns no evidence above threshold → honest "not found" answer (implemented in M3).
- Phase 6 uses **vector-only** retrieval; keyword/metadata improve in Phase 7.

## Current Snapshot

- **Phase status:** In progress
- **Last completed milestone:** Milestone 2 (OpenAI chat service + RAG prompts)
- **Next milestone:** Milestone 3 — RAG orchestration service
- **Blocker:** None

## Your Action Items (manual setup)

- [x] **Step A — Qdrant running with vectors** (`points_count` ~6000+ after `/build`)
- [x] **Step B — OpenAI API key in `.env`**
- [x] **Step C — Postgres + migrations**
- [x] **Step D — Index built** (`POST /api/v1/index/build` completed with `failed: 0`)
- [x] **Step E — `CHAT_MODEL` in `.env`** (default `gpt-4o-mini`; wired in M2)

## Milestone Status

- [x] Milestone 0 — Phase 6 tracker + setup checklist + docs alignment
- [x] Milestone 1 — Vector retriever + Qdrant `search_similar()` (`app/retrieval/`)
- [x] Milestone 2 — LLM chat service + grounded prompts (`app/llm/`)
- [ ] Milestone 3 — RAG orchestration service (`app/services/rag_service.py`)
- [ ] Milestone 4 — Chat + source viewer API routes
- [ ] Milestone 5 — Retrieval, RAG, and API test coverage
- [ ] Milestone 6 — Verification + Phase 6 docs closure

## Commit Plan

1. `docs(rag): add phase 6 tracker and basic rag plan`
2. `feat(retrieval): add vector retriever and qdrant search`
3. `feat(llm): add openai chat service and rag prompts`
4. `feat(rag): add grounded answer orchestration service`
5. `feat(api): add chat and source viewer endpoints`
6. `test(rag): add retrieval chat and source api coverage`
7. `docs(rag): complete phase 6 basic rag api`

## Target Module Layout

```text
backend/app/retrieval/
  types.py                 # RetrievedChunk (M1)
  vector.py                # VectorRetriever (M1)

backend/app/llm/
  base.py                  # ChatService protocol (M2)
  openai_service.py        # OpenAI chat (M2)
  prompts.py               # RAG prompt templates (M2)
  factory.py               # get_chat_service() (M2)

backend/app/services/
  rag_service.py           # orchestration (M3)

backend/app/embeddings/
  vector_store.py          # + search_similar() (M1)

backend/app/api/
  chat.py                  # POST /chat (M4)
  sources.py               # GET /sources/{chunk_id} (M4)

backend/app/schemas/
  chat.py                  # ChatRequest/Response (M4)
```

## API Endpoints (Phase 6)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/v1/chat` | Ask a question; return grounded answer + citations |
| GET | `/api/v1/sources/{chunk_id}` | Full chunk text + file metadata for citation viewer |

Reuse `CitationItem` from `app/schemas/query.py` in chat responses.

## RAG defaults

| Setting | Env var | MVP default |
|---------|---------|-------------|
| Chat model | `CHAT_MODEL` | `gpt-4o-mini` |
| Top-k retrieval | `RETRIEVAL_TOP_K` | `8` |
| Score threshold | `RETRIEVAL_SCORE_THRESHOLD` | `0.35` |
| Max context chars | `RAG_MAX_CONTEXT_CHARS` | `12000` (M2/M3) |
| Citation snippet length | — | `300` chars (M3) |

## Retrieval flow (M1)

```text
Question text
  → embed via EmbeddingService
  → Qdrant query_points (top-k, score_threshold)
  → batch-load Chunk + DriveFile from PostgreSQL
  → drop orphan Qdrant hits with no Postgres row
  → return list[RetrievedChunk] ordered by score
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

## End-to-end smoke test (after M4)

```bash
# Backend + Qdrant running, index built
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What topics are covered in the Materials Science textbook?"}'

curl http://localhost:8000/api/v1/sources/<chunk_id_from_citations>
```

## Phase 6 Closure (M6)

All milestones complete. Verification before moving to Phase 7:

```bash
cd backend
uv run ruff check app tests
uv run mypy app
uv run basedpyright app tests
uv run pytest -q
```

Smoke test with backend running, Drive connected, Qdrant indexed, OpenAI key set:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Summarize my notes on tensile strength."}'
```

## Notes

- Phase 5 index build verified: 367 documents, 6036 chunks, `failed: 0`.
- Qdrant upserts are batched (100/request) — retrieval uses small query payloads.
- Mock OpenAI and Qdrant in unit tests; no network in CI.
- Reuse user resolution pattern from `IndexingService` in `RagService` (M3).
- Phase 7 replaces vector-only retrieval with hybrid metadata + keyword + merge.

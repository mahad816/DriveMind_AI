# DriveMind Backend

FastAPI backend for DriveMind AI — ingestion (text extraction), hybrid retrieval, and LangGraph agent.

Phase 4 adds extractors under `app/ingestion/extractors/` (TXT, Docs, DOCX, PDF text-only, image OCR). See [PHASE_4_TRACKER.md](../docs/PHASE_4_TRACKER.md).

Phase 5 adds chunking, embeddings, and Qdrant under `app/ingestion/chunking.py`, `app/embeddings/`, and `app/services/indexing_service.py`. See [PHASE_5_TRACKER.md](../docs/PHASE_5_TRACKER.md).

Phase 6 adds vector RAG under `app/retrieval/`, `app/llm/`, `app/services/rag_service.py`, and chat/source API routes. See [PHASE_6_TRACKER.md](../docs/PHASE_6_TRACKER.md).

Phase 7 adds hybrid retrieval (metadata + keyword + vector) with merge, rerank, and evidence grading under `app/retrieval/`. See [PHASE_7_TRACKER.md](../docs/PHASE_7_TRACKER.md).

Phase 8 adds LangGraph orchestration for intent routing, retrieval loops, answer generation, and citation verification under `app/agents/drive_graph/`. See [PHASE_8_TRACKER.md](../docs/PHASE_8_TRACKER.md).

## Phase 6 — RAG chat API

Grounded question answering over indexed Drive content:

```text
Question → embed → Qdrant search → Postgres chunk hydrate → LLM answer → citations → query_history
```

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/chat` | POST | Ask a question; return grounded answer + citations |
| `/api/v1/sources/{chunk_id}` | GET | Full chunk text + file metadata for citation viewer |

### Environment variables (Phase 6)

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHAT_MODEL` | `gpt-4o-mini` | OpenAI chat model for grounded answers |
| `RETRIEVAL_TOP_K` | `8` | Max chunks retrieved from Qdrant |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.35` | Minimum similarity score for retrieval |
| `RAG_MAX_CONTEXT_CHARS` | `12000` | Max context sent to the LLM |

Requires `OPENAI_API_KEY`, a built Qdrant index (`POST /api/v1/index/build`), and Google OAuth connected.

### Example requests

```bash
# Ask a grounded question
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is tensile strength?"}'

# View full source for a citation (use chunk_id from citations[], not query_id)
curl http://localhost:8000/api/v1/sources/<chunk_id>
```

## Phase 7 — Hybrid Retrieval

Hybrid retrieval runs three retrievers in parallel, then merges, reranks, and grades evidence before generation:

```text
Question -> vector + keyword + metadata retrieval -> RRF merge -> weighted rerank -> evidence grade -> answer or no-evidence
```

### Environment variables (Phase 7)

| Variable | Default | Purpose |
|----------|---------|---------|
| `HYBRID_RETRIEVAL_ENABLED` | `true` | Toggle hybrid retrieval in `RagService` |
| `RETRIEVAL_CANDIDATE_K` | `24` | Candidate pool size per retriever before merge |
| `RETRIEVAL_TOP_K` | `8` | Final reranked chunks sent downstream |
| `RETRIEVAL_SCORE_THRESHOLD` | `0.35` | Vector score floor and evidence weak-signal rule |
| `HYBRID_RRF_K` | `60` | Reciprocal rank fusion denominator constant |
| `HYBRID_WEIGHT_VECTOR` | `0.5` | Weighted rerank contribution for vector scores |
| `HYBRID_WEIGHT_KEYWORD` | `0.3` | Weighted rerank contribution for keyword scores |
| `HYBRID_WEIGHT_METADATA` | `0.2` | Weighted rerank contribution for metadata scores |
| `EVIDENCE_MIN_FUSION_SCORE` | `0.15` | Minimum fused score for sufficient evidence |
| `FTS_LANGUAGE` | `english` | PostgreSQL text-search language config |

### Manual operations tied to Phase 7

```bash
# After introducing full-text search schema (M2)
cd backend
uv run alembic upgrade head

# After metadata folder-path sync improvements (M4)
curl -X POST http://localhost:8000/api/v1/index/sync
```

## Phase 8 — LangGraph Agent

When enabled, chat requests are orchestrated through the Drive graph:

```text
receive_question -> classify_intent -> plan_retrieval -> route_retriever
-> retrieve -> rerank -> grade_evidence
-> (rewrite_query loop, capped) -> generate_answer -> verify_citations -> return_response
```

### Environment variables (Phase 8)

| Variable | Default | Recommended | Purpose |
|----------|---------|-------------|---------|
| `AGENT_GRAPH_ENABLED` | `false` | `true` | Toggle LangGraph orchestration inside `RagService` |
| `AGENT_MAX_REWRITE_ATTEMPTS` | `2` | `2` | Max rewrite-query loop attempts before forcing answer path |

Set `AGENT_GRAPH_ENABLED=true` in `.env` and restart the API to use the LangGraph path. The Phase 7 linear path remains available when set to `false`.

### Manual operations tied to Phase 8

```bash
# 1) Add to .env: AGENT_GRAPH_ENABLED=true
# 2) Restart backend server
# 3) Run chat smoke test
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"What is tensile strength?"}'

# Optional — confirm Phase 7 fallback still works
# Set AGENT_GRAPH_ENABLED=false and repeat curl above
```

## System dependencies (Phase 4 image OCR)

Image OCR uses `pytesseract`, which requires the **Tesseract** binary on your `PATH`:

```bash
brew install tesseract
tesseract --version
```

Python packages (`pillow`, `pytesseract`) are installed via `uv sync`. No extra `.env` variable is required when Tesseract is on `PATH`.

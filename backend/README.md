# DriveMind Backend

FastAPI backend for DriveMind AI — ingestion (text extraction), hybrid retrieval, and LangGraph agent.

Phase 4 adds extractors under `app/ingestion/extractors/` (TXT, Docs, DOCX, PDF text-only, image OCR). See [PHASE_4_TRACKER.md](../docs/PHASE_4_TRACKER.md).

Phase 5 adds chunking, embeddings, and Qdrant under `app/ingestion/chunking.py`, `app/embeddings/`, and `app/services/indexing_service.py`. See [PHASE_5_TRACKER.md](../docs/PHASE_5_TRACKER.md).

Phase 6 adds vector RAG under `app/retrieval/`, `app/llm/`, `app/services/rag_service.py`, and chat/source API routes. See [PHASE_6_TRACKER.md](../docs/PHASE_6_TRACKER.md).

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

## System dependencies (Phase 4 image OCR)

Image OCR uses `pytesseract`, which requires the **Tesseract** binary on your `PATH`:

```bash
brew install tesseract
tesseract --version
```

Python packages (`pillow`, `pytesseract`) are installed via `uv sync`. No extra `.env` variable is required when Tesseract is on `PATH`.

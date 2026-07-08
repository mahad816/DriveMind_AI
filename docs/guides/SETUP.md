# Local Setup Guide

Step-by-step instructions to run DriveMind AI on your machine.

---

## Prerequisites

| Requirement | Version / notes |
|-------------|-----------------|
| Docker | For PostgreSQL and Qdrant |
| Python | 3.11+ with [uv](https://github.com/astral-sh/uv) |
| Node.js | 20+ with npm |
| Tesseract | `brew install tesseract` (macOS) — required for image OCR |
| Google Cloud project | OAuth 2.0 credentials (see [Google OAuth](GOOGLE_OAUTH.md)) |
| OpenAI API key | Embeddings + chat |

---

## 1. Clone and configure environment

```bash
git clone <your-repo-url>
cd INFO_VAULT
cp .env.example .env
```

Edit `.env` with your values. Minimum required:

```bash
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
OPENAI_API_KEY=sk-...
FRONTEND_URL=http://localhost:3000
DATABASE_URL=postgresql+asyncpg://drivemind:drivemind@localhost:5432/drivemind
```

Recommended for full agent behavior:

```bash
AGENT_GRAPH_ENABLED=true
HYBRID_RETRIEVAL_ENABLED=true
```

---

## 2. Start infrastructure

```bash
docker compose -f infra/docker-compose.yml up -d postgres qdrant
```

Verify:

```bash
docker compose -f infra/docker-compose.yml ps
```

---

## 3. Backend setup

```bash
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/ready
```

---

## 4. Frontend setup (second terminal)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**

The frontend proxies `/api/v1/*` to `BACKEND_URL` (default `http://localhost:8000`) via Next.js rewrites.

---

## 5. Connect Google Drive

1. Open **http://localhost:3000/settings**
2. Click **Connect Google Drive**
3. Complete Google consent
4. You should redirect back with `?connected=true`

Or start OAuth directly:

```bash
curl -I http://localhost:8000/api/v1/auth/google
```

---

## 6. Build your knowledge index

### Via UI (recommended)

1. Go to **Build knowledge** (`/index`) or complete onboarding
2. Run setup — syncs Drive, ingests text, chunks, embeds

### Via API

```bash
curl -X POST http://localhost:8000/api/v1/index/sync
curl -X POST http://localhost:8000/api/v1/index/ingest
curl -X POST http://localhost:8000/api/v1/index/chunk
curl -X POST http://localhost:8000/api/v1/index/build
```

Poll job status:

```bash
curl http://localhost:8000/api/v1/index/status
curl http://localhost:8000/api/v1/index/pending
```

---

## 7. Ask your first question

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is in my latest resume?"}'
```

Or use the Chat UI at **http://localhost:3000/chat**.

---

## Environment variables reference

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | — | PostgreSQL async connection |
| `QDRANT_HOST` | `localhost` | Vector DB host |
| `QDRANT_PORT` | `6333` | Vector DB port |
| `QDRANT_COLLECTION` | `drivemind_chunks` | Collection name |
| `OPENAI_API_KEY` | — | LLM + embeddings |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `CHAT_MODEL` | `gpt-4o-mini` | Chat model |
| `GOOGLE_CLIENT_ID` | — | OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | — | OAuth client secret |
| `GOOGLE_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/google/callback` | OAuth callback |
| `FRONTEND_URL` | `http://localhost:3000` | Post-OAuth redirect |
| `BACKEND_URL` | `http://localhost:8000` | Next.js proxy target |
| `AGENT_GRAPH_ENABLED` | `false` | Use LangGraph for GROUNDED_RAG |
| `HYBRID_RETRIEVAL_ENABLED` | `true` | Metadata + keyword + vector |
| `RETRIEVAL_TOP_K` | `8` | Chunks passed to LLM |
| `RAG_MAX_CONTEXT_CHARS` | `12000` | Max context window for RAG |

Full list: [`.env.example`](../.env.example)

---

## Verification

```bash
# Backend
cd backend
uv run pytest -q
uv run ruff check app tests

# Frontend
cd frontend
npm test
npm run build
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| OAuth redirect fails | Ensure `FRONTEND_URL` matches browser origin; restart backend after `.env` change |
| `503` on `/index/sync` | Connect Google Drive first |
| Chat returns no evidence | Run full index pipeline; check `GET /index/pending` |
| Image files empty | Install Tesseract: `brew install tesseract` |
| Frontend can't reach API | Check backend is running on port 8000; verify `BACKEND_URL` |

---

## Next steps

- [Google Drive OAuth](GOOGLE_OAUTH.md) — production OAuth setup
- [Indexing Lifecycle](INDEXING.md) — how files move through the pipeline
- [Deployment](DEPLOYMENT.md) — hosting for portfolio demos

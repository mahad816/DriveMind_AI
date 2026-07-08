# Deployment Guide

How to deploy DriveMind AI for a portfolio demo or personal use.

---

## Recommended topology

DriveMind is a **multi-service** application. Do not attempt to run the full stack on Vercel alone.

```mermaid
flowchart LR
    Browser --> Vercel[Next.js on Vercel]
    Vercel -->|rewrite /api/v1| API[FastAPI on Railway/Render/Fly]
    API --> PG[(Neon PostgreSQL)]
    API --> QD[(Qdrant Cloud)]
    API --> Google[Google Drive API]
    API --> OpenAI[OpenAI API]
```

| Component | Recommended host | Free tier? |
|-----------|------------------|------------|
| **Frontend** | [Vercel](https://vercel.com) | Yes (Hobby) |
| **Backend** | Railway, Render, or Fly.io | Limited free / ~$5/mo |
| **PostgreSQL** | [Neon](https://neon.tech) or Supabase | Yes |
| **Qdrant** | [Qdrant Cloud](https://cloud.qdrant.io) | Free tier available |
| **Secrets** | Platform env vars | — |

---

## Why not all-in on Vercel?

| Requirement | Issue on Vercel serverless |
|-------------|---------------------------|
| FastAPI long-running app | Not a native fit; timeout limits |
| Indexing jobs (minutes) | Exceeds function duration |
| LangGraph + RAG latency | Cold starts; 10s hobby timeout |
| PostgreSQL / Qdrant | Not hosted by Vercel |

**Frontend on Vercel + backend elsewhere** is the intended production pattern (see [Architecture](../ARCHITECTURE.md)).

---

## Step 1: Deploy PostgreSQL

### Neon (recommended)

1. Create project at [neon.tech](https://neon.tech)
2. Copy connection string
3. Convert to asyncpg format:

```bash
DATABASE_URL=postgresql+asyncpg://user:pass@ep-....neon.tech/drivemind?sslmode=require
```

4. Run migrations from CI or one-off:

```bash
cd backend && uv run alembic upgrade head
```

---

## Step 2: Deploy Qdrant

### Qdrant Cloud

1. Create free cluster at [cloud.qdrant.io](https://cloud.qdrant.io)
2. Copy host, port, API key
3. Set env vars:

```bash
QDRANT_HOST=....cloud.qdrant.io
QDRANT_PORT=6333
QDRANT_API_KEY=...   # if using cloud auth
```

The collection `drivemind_chunks` is created on first build.

---

## Step 3: Deploy backend

### General steps (Railway / Render / Fly)

1. Connect GitHub repo
2. Set root directory to `backend/`
3. Start command:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

4. Set all env vars from [`.env.example`](../../.env.example)
5. Note public URL: `https://your-api.railway.app`

### Required production env vars

```bash
APP_ENV=production
DEBUG=false
DATABASE_URL=postgresql+asyncpg://...
QDRANT_HOST=...
OPENAI_API_KEY=...
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://your-api.railway.app/api/v1/auth/google/callback
FRONTEND_URL=https://your-app.vercel.app
AGENT_GRAPH_ENABLED=true
HYBRID_RETRIEVAL_ENABLED=true
```

### Health checks

Configure platform health check on:

```
GET /api/v1/health
```

Readiness (includes DB):

```
GET /api/v1/health/ready
```

---

## Step 4: Deploy frontend (Vercel)

1. Import repo in [Vercel](https://vercel.com)
2. Set **Root Directory** to `frontend/`
3. Framework preset: **Next.js**
4. Environment variables:

| Variable | Value |
|----------|-------|
| `BACKEND_URL` | `https://your-api.railway.app` |
| `NEXT_PUBLIC_API_URL` | `/api/v1` |

5. Deploy

The existing `next.config.ts` rewrite proxies `/api/v1/*` → `BACKEND_URL/api/v1/*`.

---

## Step 5: Update Google OAuth

In Google Cloud Console, add:

| URI type | Value |
|----------|-------|
| Authorized redirect URI | `https://your-api.railway.app/api/v1/auth/google/callback` |

Update backend env:

```bash
GOOGLE_REDIRECT_URI=https://your-api.railway.app/api/v1/auth/google/callback
FRONTEND_URL=https://your-app.vercel.app
```

---

## Step 6: First production index

After OAuth connect:

```bash
curl -X POST https://your-api.railway.app/api/v1/index/sync
curl -X POST https://your-api.railway.app/api/v1/index/ingest
curl -X POST https://your-api.railway.app/api/v1/index/chunk
curl -X POST https://your-api.railway.app/api/v1/index/build
```

Or use the UI **Build knowledge** page.

---

## Secret management rules

| Rule | Detail |
|------|--------|
| Never commit secrets | `.env` is gitignored |
| Use platform env vars | Vercel, Railway secret stores |
| Rotate on leak | Regenerate Google + OpenAI keys |
| Separate dev/prod OAuth clients | Different redirect URIs |

---

## Cost estimate (portfolio demo)

| Service | Typical cost |
|---------|--------------|
| Vercel Hobby | $0 |
| Railway / Render | $0–7/mo |
| Neon free | $0 |
| Qdrant Cloud free | $0 |
| OpenAI API | Pay per use (~$1–5/mo light usage) |

---

## Known production limitations

- Chat history is browser `localStorage` — cleared if user switches device
- Indexing jobs run in-process background tasks — not a distributed queue
- Single-user OAuth token storage — not multi-tenant
- No CDN caching for API responses

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| OAuth `redirect_uri_mismatch` | Match Google Console URI exactly |
| Frontend 502 on chat | Check `BACKEND_URL`; verify backend health |
| CORS errors | Should not occur — frontend uses same-origin proxy |
| Empty chat answers | Run index pipeline; check OpenAI key |
| Slow first request | Cold start on free backend tier |

---

## Related docs

- [Google OAuth](GOOGLE_OAUTH.md)
- [Local Setup](SETUP.md)
- [Architecture](../ARCHITECTURE.md)

# Local controlled demo

This corpus is entirely synthetic. HarborDesk is a fictional bicycle-shop support
inbox, not DriveMind's architecture. Seven short UTF-8 documents share decisions,
requirements, feedback, and dated launch gates. `corpus/manifest.json` records the
version, stable file IDs, normalized-content SHA-256 hashes, and eight validation
questions with expected sources. Questions are also served to the frontend by
`GET /index/status`; they are not generated answers or evaluation runtime code.

## Before loading

Use a **dedicated empty demo PostgreSQL database** and a **dedicated empty Qdrant
collection** (or dedicated Qdrant instance). Never point this loader or demo
backend at the owner's database or collection. A second User in the owner's
database is insufficient. Review the effective environment first: backend settings
read root `.env`, then `backend/.env`, with process environment taking precedence.
Never commit actual environment files or credentials.

Set these existing backend settings in the isolated environment:

- `DEMO_MODE=true`
- `DEMO_USER_ID`: a chosen UUID, kept stable across runs.
- `DATABASE_URL`: the dedicated demo PostgreSQL database URL.
- `QDRANT_HOST`, `QDRANT_PORT`, `QDRANT_COLLECTION`: the dedicated demo collection.
- `OPENAI_API_KEY`: backend only, needed for real embeddings and chat.
- `DEBUG=false` for a visitor-facing runtime.

Default normal database/collection values are rejected in demo mode. Name changes
alone do not establish isolation: verify the target datastores yourself. The loader
also refuses extra users, OAuth tokens, unapproved files/documents/chunks, and
foreign vector points before writing. It never deletes or clears a datastore.

Apply the existing Alembic migrations **only after confirming the database is the
dedicated demo target**. With existing dependencies and isolated services ready,
run from `backend/` in the same configured environment:

```sh
uv run alembic upgrade head
uv run python -m app.demo.load --confirm-isolated-demo-storage
uv run uvicorn app.main:app --port 8000
```

The loader creates only the configured demo User if absent. The required legacy
`google_id` column receives a synthetic `demo:<UUID>` identifier, not a Google
account or token. It persists approved local Document text and uses the existing
IndexingService for deterministic chunks, PostgreSQL full-text vectors, OpenAI
embeddings, and Qdrant reconciliation. Nothing loads on backend startup or via HTTP.

Re-running the same version reuses file/document IDs and unchanged chunk/vector
IDs. A failed build exits unsuccessfully; diagnose the persisted index job and
retry offline. Changes to corpus version/content require separately reviewed
storage preparation; the loader refuses unknown/stale content instead of wiping it.
Do not run a loader concurrently with another loader or a live public demo.

## Frontend

Set `NEXT_PUBLIC_DEMO_MODE=true` and `BACKEND_URL` in `frontend/.env.local` (using
`frontend/.env.example` as the guide); restart/rebuild Next.js. This public boolean
only controls UI. The frontend checks it against backend mode; disagreement fails
as unavailable. Backend mutation guards remain authoritative.

Run the existing frontend locally (`npm run dev` from `frontend/`). The root URL
opens chat without onboarding. Settings/setup become read-only sample information.
The file browser previews stored approved text and citation viewers show real
chunk evidence, without Google Drive links.
Demo browser conversations use separate localStorage keys, preserving normal-mode
history without showing it in the demo on the same origin.

`connected` still means Google OAuth and remains false in the demo. `demo_ready`
requires all seven approved files, documents, matching chunks, and Qdrant points.
Health probes retain their existing meaning; they do not certify corpus or answer
quality. Chat and source reads fail closed when the controlled index is unavailable.
No tenant filtering was added: dedicated storage remains mandatory.

## Local validation before release

Ask every manifest question using both the default linear pipeline and
`AGENT_GRAPH_ENABLED=true` where applicable. Inspect returned citations, follow
source links, open sample previews, and record latency. Inventory has no citations;
grounded answers should cite the expected documents. The subscription-price
question must not invent a price: no price is approved in this corpus. Review
cross-file synthesis rather than assuming every expected file will always be cited.

Verify OAuth start/callback and sync/ingest/chunk/build return 403 in demo mode.
Verify unavailable/misconfigured storage cannot serve owner data. Separately run
normal-mode regression checks with demo settings disabled and the normal environment.
Existing evaluation-runner adaptation, public-use protection, hosting, and deployment
are separate phases. Passing unit tests does not certify live RAG quality.

# DriveMind AI

DriveMind is a single-user Google Drive knowledge assistant. It prepares a searchable copy of supported Drive content, then answers questions from that local index with source citations. The project combines a Next.js interface, a FastAPI backend, PostgreSQL full-text data, Qdrant vectors, OpenAI embeddings and chat generation, and optional LangGraph orchestration.

Drive access is read-only. Google OAuth authorizes that access; it is not an application login system.

## What it does

- **Prepare knowledge:** Sync Drive metadata, download or export supported files, extract text, chunk it, and build vector representations. Full scans and incremental Changes API sync are supported.
- **Answer questions:** Route conversation recall, chitchat, file inventory, named-file, and general grounded questions. Grounded answers use bounded evidence and return citations that open the indexed source text.
- **Inspect the index:** Browse synced files and their processing status, run or retry preparation, and view cited chunks. Chat history is kept in browser localStorage.
- **Evaluate behavior:** A controlled gold dataset, deterministic evaluation metrics, execution traces, and CLI runners support retrieval and answer review.

Supported content: Google Docs, TXT, DOCX paragraphs, text-based PDFs, and images through Tesseract OCR. Scanned PDFs do not have an OCR fallback.

## Architecture

![DriveMind system architecture showing separate knowledge preparation and question-answering paths](docs/assets/drivemind-runtime.svg)

> ▶ **[Explore the interactive system architecture →](https://mahad816.github.io/DriveMind_AI/interactive/runtime/)**
>
> [Architecture guide](docs/ARCHITECTURE.md)

The browser calls the Next.js `/api/v1` rewrite, which forwards requests to FastAPI. Preparation jobs synchronize Drive metadata and later ingest, chunk, and index content. PostgreSQL owns OAuth records, file metadata and status, extracted text, searchable chunks, jobs, and query history. Qdrant stores embeddings associated with PostgreSQL chunk IDs. Normal chat retrieves from this local index; it does not fetch Drive content for each answer.

### Drive sync and indexing

The frontend starts and polls four separate in-process backend jobs: **sync → ingest → chunk → build**. First or forced full sync lists supported files and reconciles missing ones; later syncs can use a stored Google Drive Changes API token. Sync updates metadata, while ingest fetches content. Build sends chunk text to OpenAI for embeddings, writes vectors to Qdrant, and marks successfully built files indexed. Unsupported, empty, removed, or failed files have distinct outcomes.

**Explore:** [Interactive Drive sync & indexing flow →](https://mahad816.github.io/DriveMind_AI/interactive/indexing/)\
**Read:** [Indexing guide](docs/guides/INDEXING.md)

### Question answering

`RagService` routes each question before retrieval. Conversation-history recall, chitchat, and file inventory have dedicated paths. Named-file questions load matching PostgreSQL chunks; general grounded questions use the linear retrieval path by default. Hybrid retrieval combines vector, PostgreSQL keyword, and metadata candidates when enabled; disabling it selects vector-only retrieval. `AGENT_GRAPH_ENABLED=true` selects the optional LangGraph path for general grounded questions. Selected evidence is bounded before OpenAI generation, citations are normalized against that evidence, and answers are recorded in PostgreSQL. The source viewer resolves cited chunk IDs to PostgreSQL text.

**Explore:** [Interactive RAG answer flow →](https://mahad816.github.io/DriveMind_AI/interactive/answer-flow/)\
**Read:** [Retrieval guide](docs/guides/RETRIEVAL.md) · [LangGraph guide](docs/guides/LANGGRAPH.md)

## Stack

| Layer | Technology |
|-------|------------|
| UI | Next.js 15, React 19, TypeScript, Tailwind |
| API and jobs | FastAPI, SQLAlchemy/asyncpg |
| Search and storage | PostgreSQL full-text search, Qdrant |
| Drive integration | Google Drive API and read-only OAuth |
| AI and extraction | OpenAI embeddings/chat, optional LangGraph, Tesseract OCR |

## Run locally

Prerequisites: Docker, Python 3.11+ with [uv](https://github.com/astral-sh/uv), Node.js 20+ with npm, Tesseract for image OCR, Google Cloud OAuth credentials, and an OpenAI API key.

```bash
git clone https://github.com/mahad816/DriveMind_AI.git
cd DriveMind_AI
cp .env.example .env
```

Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `OPENAI_API_KEY` in `.env`. The default `FRONTEND_URL` is `http://localhost:3000`. The Google OAuth callback defaults to `http://localhost:8000/api/v1/auth/google/callback`; configure that URI in Google Cloud. See [Local Setup](docs/guides/SETUP.md) for the full environment and OAuth steps.

```bash
# Terminal 1: PostgreSQL and Qdrant
docker compose -f infra/docker-compose.yml up -d postgres qdrant

# Terminal 2: backend
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# Terminal 3: frontend (from repository root)
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, connect Google Drive in Settings, run **Build knowledge**, then ask a question in Chat. Indexing requires supported files in the connected Drive account.

## API at a glance

The browser uses these endpoints through `/api/v1`:

| Endpoint | Purpose |
|----------|---------|
| `GET /auth/google` | Start Drive authorization |
| `POST /index/sync`, `/index/ingest`, `/index/chunk`, `/index/build` | Start preparation stages |
| `GET /index/status`, `/index/pending` | Poll jobs and pending work |
| `GET /files` | List synced file metadata across processing statuses |
| `POST /chat` | Route a question and return an answer and any citations |
| `GET /sources/{chunk_id}` | Read an indexed PostgreSQL chunk for a citation |

## Development and evaluation

```bash
cd backend
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run basedpyright app tests

cd ../frontend
npm test
npm run lint
npm run build
```

The repository includes `backend/evaluation/datasets/gold_v1.json`, a CLI runner (`python -m evaluation.runner`), deterministic metrics, and conversation evaluation tooling. Running a gold evaluation requires an explicit `--execute-gold` flag, a prepared index, and live dependencies; this README does not claim a new baseline result. See the [Evaluation guide](docs/guides/EVALUATION.md) for the supported workflow and recorded experiments.

## Documentation

| Guide | Start here for |
|-------|----------------|
| [Documentation index](docs/README.md) | All guides and reference documents |
| [Architecture](docs/ARCHITECTURE.md) | Components, storage ownership, and boundaries |
| [Indexing](docs/guides/INDEXING.md) | Full/incremental sync and preparation stages |
| [Retrieval](docs/guides/RETRIEVAL.md) | Routing, evidence, and citations |
| [LangGraph](docs/guides/LANGGRAPH.md) | Optional graph-specific flow |
| [Evaluation](docs/guides/EVALUATION.md) | Implemented tooling and evaluation methodology |
| [Interactive architecture](https://mahad816.github.io/DriveMind_AI/) | Animated system, indexing, and RAG flows |

## Current scope

This is a single-user MVP. Google OAuth grants Drive access, but the application does not provide a separate user authentication or multi-tenant isolation boundary. Indexing jobs run inside the FastAPI process. Chat history lives in the browser. Drive access is read-only, and image-only PDFs are not OCRed. See [Limitations and roadmap](docs/LIMITATIONS_AND_ROADMAP.md) and [Current status](docs/CURRENT_STATUS.md) for more detail.

## License

Private portfolio project.

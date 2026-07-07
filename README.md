# DriveMind AI

A production-style, LangGraph-powered personal knowledge assistant for Google Drive.

DriveMind indexes your Google Drive, retrieves relevant information using hybrid search (metadata + keyword + vector), and generates grounded answers with citations. It is **not** a simple "chat with PDFs" demo — it is an agentic RAG system built to demonstrate strong AI and backend engineering.

## What It Does

- Indexes Google Docs, PDFs (text extraction), TXT, DOCX, and images (Tesseract OCR)
- Answers questions using retrieved evidence from your Drive
- Supports metadata queries (latest resume, files by date, folder path)
- Uses LangGraph to orchestrate intent classification, retrieval planning, evidence grading, and citation verification

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend API | FastAPI |
| Agent orchestration | LangGraph |
| AI components | LangChain |
| Frontend | Next.js |
| Structured data | PostgreSQL |
| Vector search | Qdrant |
| File source | Google Drive API (read-only) |

## Repository Structure

```text
backend/     FastAPI app, ingestion, retrieval, LangGraph agent
frontend/    Next.js chat UI, indexing dashboard, source viewer
docs/        Project context, architecture, roadmap, git workflow
infra/       Docker Compose for PostgreSQL and Qdrant
scripts/     Utility scripts
```

## Documentation

- [Project Context](docs/PROJECT_CONTEXT.md) — goals, scope, and design principles
- [Roadmap](docs/ROADMAP.md) — phased execution plan
- [Architecture](docs/ARCHITECTURE.md) — system design and data flow
- [Git Workflow](docs/GIT_WORKFLOW.md) — commit and branch discipline
- [Execution Plan](docs/EXECUTION_PLAN.md) — detailed phase-by-phase plan
- [Current Status](docs/CURRENT_STATUS.md) — resume point for new chats
- [Phase 2 Tracker](docs/PHASE_2_TRACKER.md) — Phase 2 log (complete)
- [Phase 3 Tracker](docs/PHASE_3_TRACKER.md) — Phase 3 log (complete)
- [Phase 4 Tracker](docs/PHASE_4_TRACKER.md) — Phase 4 log (complete)
- [Phase 5 Tracker](docs/PHASE_5_TRACKER.md) — Phase 5 log (complete)

## Development Status

- Phase 0 — Repository foundation (complete)
- Phase 1 — Backend foundation (complete)
- Phase 2 — Data model and indexing state (complete)
- Phase 3 — Google Drive read-only integration (complete)
- Phase 4 — Document ingestion and text extraction (complete)
- Phase 5 — Chunking and embeddings (complete)
- Phase 6 — Basic RAG chat (not started)

See [docs/ROADMAP.md](docs/ROADMAP.md) and [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md) for the active phase.

## Local Setup

> Full setup and production deployment docs will be expanded in Phase 11. For now:

```bash
# Start infrastructure
docker compose -f infra/docker-compose.yml up -d

# Backend
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload

# Run backend tests
uv run pytest -v

# Frontend (after Phase 9)
cd frontend && npm install && npm run dev
```

## License

Private portfolio project.

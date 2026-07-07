# DriveMind AI

A production-style, LangGraph-powered personal knowledge assistant for Google Drive.

DriveMind indexes your Google Drive, retrieves relevant information using hybrid search (metadata + keyword + vector), and generates grounded answers with citations. It is **not** a simple "chat with PDFs" demo — it is an agentic RAG system built to demonstrate strong AI and backend engineering.

## What It Does

- Indexes Google Docs, PDFs, TXT, DOCX, and images (OCR)
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

## Development Status

**Phase 0 — Repository foundation** (in progress)

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full phase breakdown.

## Local Setup

> Full setup instructions will be added in Phase 11. For now:

```bash
# Start infrastructure
docker compose -f infra/docker-compose.yml up -d

# Backend (after Phase 1)
cd backend && uv sync && uv run uvicorn app.main:app --reload

# Frontend (after Phase 9)
cd frontend && npm install && npm run dev
```

## License

Private portfolio project.

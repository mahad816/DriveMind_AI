# DriveMind AI — Project Context

## Overview

**DriveMind AI** is a production-style AI application that acts as a **personal knowledge assistant for Google Drive**.

The goal is **not** to build a simple "chat with PDFs" application. The goal is to build a **LangGraph-powered agentic RAG system** that indexes personal Google Drive content, understands documents and other supported file types, retrieves relevant information using hybrid search, and generates grounded answers with citations.

This project is intended to demonstrate strong understanding of:

- Retrieval-Augmented Generation (RAG)
- Agentic AI
- LangGraph
- LangChain
- Hybrid Retrieval
- Production backend architecture
- Google Drive integration
- AI system design
- Full-stack engineering

The project is designed to be portfolio-worthy, resume-worthy, and documented professionally.

---

## Example Questions

The system should answer questions like:

- Find my latest resume.
- Summarize everything related to CoreChain.
- Find documents from my PTCL internship.
- Which files mention federated learning?
- Show documents useful for job applications.
- Find screenshots related to my portfolio.
- Which files are duplicates?
- Summarize a project using multiple documents.

All answers must use **retrieved evidence from Google Drive**, not LLM knowledge alone.

---

## MVP Scope

| Constraint | Detail |
|------------|--------|
| Users | Single authenticated user (MVP) |
| Permissions | Read-only — never modify or delete Drive files |
| File types | Google Docs, PDF (text-only), TXT, DOCX, Images (Tesseract OCR) |
| Later | Audio files via Whisper (Phase 2+) |

---

## Core Technologies

### LangChain

Provides reusable AI components: document loaders, text splitters, embedding interfaces, retrievers, prompt templates, and LLM abstraction.

**LangChain is not responsible for application flow.**

### LangGraph

Controls the entire AI workflow:

- Intent classification
- Retrieval planning
- Retrieval routing
- Evidence grading
- Query rewriting
- Answer generation
- Citation verification

**LangGraph is the brain that coordinates the pipeline.**

### RAG

```
Question → Retrieve relevant chunks → Pass chunks to LLM → Generate grounded answer
```

### FastAPI

Backend REST API for authentication, Google Drive integration, indexing, chat, source retrieval, and evaluation endpoints.

### Next.js

Frontend for chat interface (history, citations, message actions), files browser, indexing dashboard, source viewer, settings, and onboarding. Evaluation dashboard is Phase 10.

### PostgreSQL

Stores structured data only: users, file metadata, chunks, tags, indexing state, query history.

### Qdrant

Vector database for embeddings and semantic search. **Never stores original files.**

### Google Drive API

Read-only: authenticate, list files, download/export supported documents, synchronize changes.

### OCR

Tesseract (via `pytesseract`) for standalone images (PNG, JPEG, WebP, etc.).

**Phase 4 scope:** image OCR only. **Not in Phase 4:** EasyOCR, PDF OCR fallback for scanned PDFs (deferred).

### Whisper (optional, later)

Convert audio notes into searchable text.

---

## High-Level Data Flow

```
Google Drive
    ↓
Drive Connector
    ↓
Document Ingestion
    ↓
Text Extraction
    ↓
Chunking
    ↓
Embedding Generation
    ↓
PostgreSQL + Qdrant
    ↓
LangGraph Agent
    ↓
LLM
    ↓
Grounded Response with Citations
```

---

## Retrieval Pipeline

The system must **not** rely only on vector search.

1. Metadata retrieval
2. Keyword retrieval
3. Vector retrieval
4. Merge results
5. Rerank
6. Evidence grading
7. Query rewrite if necessary
8. Generate answer

### Retrieval Types

| Type | Examples |
|------|----------|
| Metadata | Latest file, file type, modified date, folder path |
| Keyword | CoreChain, PTCL, Resume |
| Vector | Semantic understanding |
| Hybrid | Combination of all three |

---

## Storage Design

| Store | Responsibility |
|-------|----------------|
| Google Drive | Original files |
| PostgreSQL | Metadata, chunk text, indexing status, tags |
| Qdrant | Embeddings, vector IDs, payload references |

**The LLM never reads Google Drive directly.** It only receives retrieved chunks.

---

## Design Principles

### Prefer

- Modular architecture
- Clean separation of concerns
- Dependency injection
- Reusable services
- Configuration through environment variables
- Proper typing
- Asynchronous APIs where appropriate
- Production-style folder organization
- Docker support
- Comprehensive logging
- Unit tests

### Avoid

- Monolithic files
- Business logic inside routes
- Duplicated code
- Global state
- Hardcoded values
- Unnecessary abstractions

---

## What We Are NOT Building

- A simple PDF chatbot
- A ChatGPT clone
- A Google Drive replacement
- An autonomous file manager
- A multi-user SaaS (for MVP)

---

## Priority Order

1. Correct architecture
2. Clean codebase
3. Reliable retrieval
4. Good LangGraph workflow
5. Professional documentation
6. Good UI
7. Additional features

Every implementation decision should support these priorities.

---

## Module Responsibilities

### Backend (`backend/app/`)

| Module | Responsibility |
|--------|----------------|
| `api/` | FastAPI route handlers |
| `agents/` | LangGraph workflow |
| `connectors/` | Google Drive and external APIs |
| `core/` | Config, logging, shared utilities |
| `db/` | Models, session, migrations |
| `embeddings/` | Embedding generation, Qdrant |
| `evaluation/` | Retrieval and answer quality metrics |
| `ingestion/` | Extraction, chunking, indexing |
| `jobs/` | Background sync and indexing tasks |
| `retrieval/` | Metadata, keyword, vector, hybrid search |
| `schemas/` | Pydantic request/response models |
| `services/` | Domain business logic |

### Frontend (`frontend/`)

| Module | Responsibility |
|--------|----------------|
| `app/` | Next.js App Router pages |
| `components/` | Reusable UI components |
| `lib/` | API client, utilities, types |

### Documentation (`docs/`)

Architecture, roadmap, setup guides, evaluation methodology.

---

## Coding Guidelines

- Write readable, maintainable code.
- Prefer composition over large utility files.
- Use meaningful names.
- Add concise docstrings where useful.
- Keep functions focused on one responsibility.
- Separate domain logic from framework code.
- Build features incrementally — do not scaffold everything at once.

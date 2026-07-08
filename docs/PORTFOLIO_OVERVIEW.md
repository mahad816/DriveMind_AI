# DriveMind AI — Portfolio Overview

A one-page summary for recruiters, reviewers, and technical interviewers.

---

## Elevator pitch

**DriveMind AI** is a personal knowledge assistant for Google Drive. It indexes your files, retrieves relevant evidence with hybrid search, and answers questions with citations — orchestrated by a LangGraph agent.

It demonstrates production-style AI engineering: not a PDF chatbot, but an agentic RAG system with real backend architecture.

---

## Problem

Personal knowledge is scattered across Google Drive — resumes, project docs, notes, PDFs, images. Generic LLMs cannot access this private corpus. Simple RAG demos fail on real queries like:

- *Find my latest resume*
- *How many certificate files do I have?*
- *Tell me about "Far611"*

DriveMind solves this with **hybrid retrieval**, **query routing**, and **grounded generation**.

---

## Solution architecture

```text
Google Drive (read-only)
    → Sync metadata → Ingest text → Chunk → Embed → Qdrant
    → PostgreSQL (metadata, chunks, indexing state)
    → Hybrid retrieval (metadata + keyword + vector)
    → LangGraph agent (intent, rewrite, citation verify)
    → Next.js UI (chat, files, citations)
```

---

## Technical highlights

| Area | What was built |
|------|----------------|
| **Ingestion** | Multi-format extractors (Docs, PDF, DOCX, TXT, OCR images); incremental pipeline |
| **Retrieval** | Metadata + PostgreSQL FTS + Qdrant vectors; RRF merge; filename-aware rerank |
| **Routing** | CHITCHAT, FILE_INVENTORY, FILE_TARGET, GROUNDED_RAG paths |
| **Agent** | LangGraph with evidence grading and query rewrite loop |
| **API** | FastAPI REST, background indexing jobs, OAuth |
| **Frontend** | Next.js App Router, chat history, source viewer, setup wizard |

---

## Engineering decisions worth discussing

1. **Chunk text in PostgreSQL, vectors in Qdrant** — auditability + keyword search + dedicated vector index.
2. **Backend-first** — frontend consumes REST only; no direct Drive/LLM access from browser.
3. **Incremental indexing** — only changed files re-processed; pending-only pipeline skips idle steps.
4. **Filename-aware rerank** — short quoted names get exact-match priority without score inflation bugs.
5. **LangGraph behind a flag** — linear hybrid path for debugging; graph path for agentic behavior.

---

## Demo flow (5 minutes)

1. Connect Google Drive in Settings.
2. Run **Build knowledge** (sync → ingest → chunk → embed).
3. Open **Chat** → ask *"Summarize my most recent resume"*.
4. Click a **source pill** → verify excerpt matches your Drive file.
5. Open **Files** → browse indexed library, ask about a specific file.

---

## Test coverage

- Backend: 480+ pytest tests (retrieval, ingestion, API, agents)
- Frontend: 44 Vitest tests (components, API client, utilities)

---

## Limitations (honest MVP scope)

- Single user, read-only Drive
- Chat history in browser localStorage (not server-backed)
- No SSE streaming yet
- Scanned PDF OCR deferred
- Evaluation dashboard planned (Phase 10)

See [Limitations & Future](LIMITATIONS_AND_ROADMAP.md) for the full list.

---

## Links

- [README](../README.md) — setup and API reference
- [Architecture](ARCHITECTURE.md) — system design
- [Retrieval Strategy](guides/RETRIEVAL.md) — how search works
- [LangGraph Workflow](guides/LANGGRAPH.md) — agent flow

# Limitations and Future Roadmap

Honest scope boundaries for the MVP and what comes next.

---

## Current limitations (MVP)

### Product scope

| Limitation | Detail |
|------------|--------|
| Single user | No multi-tenant auth or user management UI |
| Read-only Drive | Never writes, deletes, or modifies Drive files |
| Personal use | Designed for one Google account per deployment |

### File types

| Supported | Not supported (yet) |
|-----------|---------------------|
| Google Docs, PDF (text), TXT, DOCX | Google Sheets, Slides, Excel |
| Images (Tesseract OCR) | Scanned PDF OCR (no page rasterization) |
| — | Audio / Whisper transcription |

### Chat and UI

| Limitation | Detail |
|------------|--------|
| Chat history | Browser `localStorage` only — not synced across devices |
| No streaming | Answers return complete; no SSE token stream |
| No server threads API | `GET /chat/history` not implemented |

### Indexing and infrastructure

| Limitation | Detail |
|------------|--------|
| Background jobs | In-process `BackgroundTasks` — not Celery/Redis queue |
| No auto-sync cron | Manual or UI-triggered sync |
| OCR quality | Varies by image; handwriting poor |

### AI quality

| Limitation | Detail |
|------------|--------|
| Heuristic routing | Query router uses rules + patterns, not LLM classification |
| Rewrite cap | Max 2 query rewrites in LangGraph path |
| No eval dashboard | Phase 10 — metrics not yet automated |

---

## Phase 10 — Evaluation and quality (planned)

| Deliverable | Purpose |
|-------------|---------|
| Question set JSON banks | Smoke, route coverage, adversarial |
| Evaluation runner CLI | Batch queries + metric logging |
| hit@k, MRR, route accuracy | Retrieval benchmarks |
| Grounding review tooling | Citation precision checks |
| Optional eval dashboard | Frontend stats view |

See [Evaluation Methodology](guides/EVALUATION.md).

---

## Phase 11 — Documentation and deployment (this phase)

| Deliverable | Status |
|-------------|--------|
| Local setup guide | Done |
| Google OAuth guide | Done |
| Indexing lifecycle | Done |
| Retrieval strategy | Done |
| LangGraph workflow | Done |
| Evaluation methodology | Done |
| Deployment guide | Done |
| Portfolio overview | Done |

---

## Future enhancements (post-MVP)

### Near term

- Server-backed chat history (`conversations` table + API)
- SSE streaming answers for better UX
- Scheduled Drive sync (cron job)
- Scanned PDF OCR (poppler + Tesseract per page)

### Medium term

- Google Sheets / Slides extractors
- Evaluation dashboard with regression tracking
- Redis job queue for indexing at scale
- Multi-file comparison queries

### Long term (explicit non-goals for MVP)

- Multi-tenant SaaS billing
- Write access to Drive (create/edit files)
- Autonomous file manager agent
- Real-time collaborative editing

---

## Architectural constraints (unchanged)

These principles should survive future phases:

1. **LLM never reads Drive directly** — only retrieved chunks
2. **Frontend consumes REST API only**
3. **Chunk text in PostgreSQL, vectors in Qdrant**
4. **Modular services** — business logic in `services/`, not `api/`
5. **Incremental indexing** — avoid re-processing unchanged files

---

## Version history

| Phase | Milestone |
|-------|-----------|
| 0–5 | Foundation through embeddings |
| 6 | Basic RAG API |
| 7 | Hybrid retrieval |
| 8 | LangGraph agent |
| 9 | Next.js frontend |
| 10 | Evaluation (planned) |
| 11 | Documentation (in progress) |

Full timeline: [ROADMAP.md](ROADMAP.md)

# Phase 7 Tracker — Hybrid Retrieval

Track milestone-by-milestone progress for Phase 7, with matching commit messages.

## Phase Goal

Improve retrieval quality for real Drive questions by combining metadata, keyword, and vector retrieval, then merge, rerank, and grade evidence before answer generation.

## Scope (MVP)

| Capability | Method | Status |
|------------|--------|--------|
| Metadata retrieval | File-level filters and recency ranking over `drive_files` | Planned (M4) |
| Keyword retrieval | PostgreSQL full-text search over `chunks` | Planned (M3) |
| Vector retrieval | Qdrant semantic search candidate pool | Planned update (M1) |
| Hybrid merge | Reciprocal rank fusion + dedupe by `chunk_id` | Planned (M5) |
| Reranking | Weighted score fusion (no extra LLM call) | Planned (M6) |
| Evidence grading | Threshold-based sufficient/insufficient decision | Planned (M7) |
| RAG integration | `HybridRetriever` wired into `RagService` | Planned (M8) |

## Explicitly Out of Scope (Phase 7)

| Item | Reason |
|------|--------|
| **LangGraph retrieval routing and query rewrite loops** | Phase 8 |
| **LLM reranker / cross-encoder reranker** | Deferred; weighted fusion is MVP |
| **Retrieval evaluation endpoint** | Phase 10 |
| **Frontend retrieval controls** | Phase 9 |
| **New public retrieval API endpoint** | Keep retrieval internal to `RagService` in MVP |

### Design rules (unchanged from architecture)

- **PostgreSQL** stores authoritative chunk text and search metadata.
- **Qdrant** stores embeddings and lookup payloads only.
- **LLM never reads Google Drive directly** — only retrieved chunk text from PostgreSQL.
- Phase 7 keeps the existing `POST /api/v1/chat` API contract.
- Use weighted fusion reranking only (no extra LLM rerank call in this phase).

## Current Snapshot

- **Phase status:** In progress
- **Last completed milestone:** Milestone 8 (hybrid retriever integration in `RagService`)
- **Next milestone:** Milestone 9 — retrieval and API test coverage
- **Blocker:** None

## Your Action Items (manual setup)

- [x] **Step A — Postgres running + migrations applied**
- [x] **Step B — Qdrant running with indexed vectors**
- [x] **Step C — OAuth connected and metadata synced at least once**
- [x] **Step D — OpenAI API key in `.env`** (for end-to-end chat verification)
- [ ] **Step E — Re-sync after M4** to populate improved `folder_path`

## Milestone Status

- [x] Milestone 0 — Phase 7 tracker + docs alignment
- [x] Milestone 1 — Retrieval foundation (`retrieval` types/protocol + candidate pool config)
- [x] Milestone 2 — PostgreSQL FTS migration + chunk search vector sync
- [x] Milestone 3 — Keyword retriever (`app/retrieval/keyword.py`)
- [x] Milestone 4 — Metadata retriever + folder path population fix
- [x] Milestone 5 — Hybrid merge + dedupe (`RRF`)
- [x] Milestone 6 — Weighted fusion reranker
- [x] Milestone 7 — Evidence grader
- [x] Milestone 8 — Hybrid retriever integration in `RagService`
- [ ] Milestone 9 — Retrieval and API test coverage
- [ ] Milestone 10 — Verification + Phase 7 docs closure

## Commit Plan

1. `docs(retrieval): add phase 7 tracker and hybrid retrieval plan`
2. `feat(retrieval): extend types and candidate pool settings`
3. `feat(db): add chunk full text search index`
4. `feat(retrieval): add postgres keyword retriever`
5. `feat(retrieval): add metadata retriever and folder path sync`
6. `feat(retrieval): add reciprocal rank fusion merge`
7. `feat(retrieval): add weighted fusion reranker`
8. `feat(retrieval): add threshold evidence grader`
9. `feat(rag): wire hybrid retrieval into rag service`
10. `test(retrieval): add hybrid retrieval coverage`
11. `docs(retrieval): complete phase 7 hybrid retrieval`

## Target Module Layout

```text
backend/app/retrieval/
  base.py                  # Retriever protocol (M1)
  types.py                 # RetrievedChunk extensions (M1)
  vector.py                # candidate pool update (M1)
  keyword.py               # PostgreSQL full-text retriever (M3)
  metadata.py              # metadata retriever (M4)
  merge.py                 # reciprocal rank fusion + dedupe (M5)
  rerank.py                # weighted reranker (M6)
  grade.py                 # evidence grading (M7)
  hybrid.py                # orchestration (M8)
```

## Configuration Targets (Phase 7)

| Setting | Env var | Default |
|---------|---------|---------|
| Hybrid toggle | `HYBRID_RETRIEVAL_ENABLED` | `true` |
| Candidate pool size | `RETRIEVAL_CANDIDATE_K` | `24` |
| Final top-k | `RETRIEVAL_TOP_K` | `8` |
| Vector threshold | `RETRIEVAL_SCORE_THRESHOLD` | `0.35` |
| RRF constant | `HYBRID_RRF_K` | `60` |
| Fusion weights | `HYBRID_WEIGHT_VECTOR/KEYWORD/METADATA` | `0.5 / 0.3 / 0.2` |
| Evidence floor | `EVIDENCE_MIN_FUSION_SCORE` | `0.15` |
| FTS language | `FTS_LANGUAGE` | `english` |

## Verification Commands

```bash
cd backend
uv sync --dev
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run basedpyright app tests
uv run pytest -q
```

## Manual Commands Across Phase 7

```bash
# After M2 (FTS migration)
cd backend
uv run alembic upgrade head

# After M4 (folder path improvements)
curl -X POST http://localhost:8000/api/v1/index/sync

# After M8 (hybrid retrieval wired into chat)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is tensile strength?"}'
```

## Notes

- Phase 6 already proved baseline RAG works (vector-only, grounded answers, citations).
- Phase 7 focuses retrieval quality improvements only; API shape remains stable.
- Phase 8 will add query rewrite loops and intent-based routing with LangGraph.

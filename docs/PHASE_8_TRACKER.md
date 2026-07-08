# Phase 8 Tracker — LangGraph Agent

Track milestone-by-milestone progress for Phase 8, with matching commit messages.

## Phase Goal

Replace the linear `RagService.ask()` flow with a LangGraph agentic workflow that classifies intent, routes retrieval, loops on query rewrite when evidence is weak, generates grounded answers, and verifies citations.

## Scope (MVP)

| Capability | Method | Status |
|------------|--------|--------|
| LangGraph foundation | `langgraph` dependency, `DriveGraphState`, `QueryIntent`, `RetrievalPlan` | Done (M1) |
| Graph skeleton | `StateGraph` with stub nodes + runner | Done (M2) |
| Intent classification | Rule heuristics + structured LLM fallback | Done (M3) |
| Retrieval planning | Map intent → retriever subset + options | Done (M3) |
| Routed retrieval | Selective vector/keyword/metadata retrievers | Done (M4) |
| Rerank + grade | Reuse Phase 7 `weighted_fusion_rerank` + `grade_evidence` | Done (M5) |
| Query rewrite loop | LLM rewrite with `AGENT_MAX_REWRITE_ATTEMPTS` cap | Done (M6) |
| Answer + citations | Reuse `ChatService` + citation verification | Done (M7) |
| RAG integration | `AGENT_GRAPH_ENABLED` flag in `RagService` | Done (M8) |
| Test coverage | Node + graph integration + RagService flag tests | Done (M9) |

## Explicitly Out of Scope (Phase 8)

| Item | Reason |
|------|--------|
| **Frontend chat UI / streaming SSE** | Phase 9 |
| **Retrieval evaluation endpoint** | Phase 10 |
| **Multi-turn conversation memory** | Post-MVP |
| **New public agent/debug API** | Post-MVP |
| **LLM cross-encoder reranker** | Deferred; Phase 7 uses weighted fusion |

### Design rules (unchanged from architecture)

- **PostgreSQL** stores authoritative chunk text and search metadata.
- **Qdrant** stores embeddings and lookup payloads only.
- **LLM never reads Google Drive directly** — only retrieved chunk text from PostgreSQL.
- Phase 8 keeps the existing `POST /api/v1/chat` API contract.
- Phase 7 linear RAG path remains available when `AGENT_GRAPH_ENABLED=false`.

## Current Snapshot

- **Phase status:** Complete
- **Last completed milestone:** Milestone 10 (verification + Phase 8 docs closure)
- **Next phase:** Phase 9 — Frontend Foundation
- **Blocker:** None

## Your Action Items (manual setup)

- [x] **Step A — Postgres running + migrations applied**
- [x] **Step B — Qdrant running with indexed vectors**
- [x] **Step C — OAuth connected and metadata synced at least once**
- [x] **Step D — OpenAI API key in `.env`** (for end-to-end chat verification)
- [x] **Step E — After M1:** run `cd backend && uv sync` to install `langgraph`
- [ ] **Step F — Recommended:** set `AGENT_GRAPH_ENABLED=true` in `.env` and restart API

## Milestone Status

- [x] Milestone 0 — Phase 8 tracker + docs alignment
- [x] Milestone 1 — LangGraph dependency + drive graph state/types + config
- [x] Milestone 2 — Graph skeleton + runner
- [x] Milestone 3 — Intent classification + retrieval planning nodes
- [x] Milestone 4 — Route retriever + retrieve node
- [x] Milestone 5 — Rerank + grade evidence nodes
- [x] Milestone 6 — Query rewrite loop
- [x] Milestone 7 — Generate answer + verify citations + return
- [x] Milestone 8 — RagService integration behind feature flag
- [x] Milestone 9 — Agent node + graph integration tests
- [x] Milestone 10 — Verification + Phase 8 docs closure

## Commit Plan

1. `docs(agent): add phase 8 tracker and align roadmap`
2. `feat(agent): add langgraph dependency and drive graph state`
3. `feat(agent): add drive graph skeleton and runner`
4. `feat(agent): add intent classification and retrieval planning nodes`
5. `feat(agent): add routed retrieval node`
6. `feat(agent): add rerank and evidence grading nodes`
7. `feat(agent): add query rewrite loop with attempt cap`
8. `feat(agent): add answer generation and citation verification nodes`
9. `feat(agent): wire langgraph into rag service behind feature flag`
10. `test(agent): add langgraph node and integration coverage`
11. `docs(agent): complete phase 8 langgraph agent`

## Target Module Layout

```text
backend/app/agents/drive_graph/
  __init__.py              # public exports
  state.py                 # DriveGraphState + initial state factory
  types.py                 # QueryIntent, RetrievalPlan
  prompts.py               # intent + rewrite prompts
  nodes.py                 # graph node functions
  graph.py                 # StateGraph wiring + conditional edges
  runner.py                # async invoke helper
```

## Configuration Targets (Phase 8)

| Setting | Env var | Default | Recommended |
|---------|---------|---------|-------------|
| Agent graph toggle | `AGENT_GRAPH_ENABLED` | `false` | `true` (after smoke) |
| Max rewrite attempts | `AGENT_MAX_REWRITE_ATTEMPTS` | `2` | `2` |

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

## Manual Commands Across Phase 8

```bash
# After M1 (install langgraph)
cd backend
uv sync

# Enable LangGraph orchestration (recommended after M10 verification)
# Add to .env: AGENT_GRAPH_ENABLED=true
# Restart API, then smoke test:
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is tensile strength?"}'

# Optional — confirm Phase 7 fallback still works
# Set AGENT_GRAPH_ENABLED=false and repeat curl above
```

## Notes

- Phase 7 delivered hybrid retrieval; Phase 8 orchestrates it with LangGraph.
- `AGENT_GRAPH_ENABLED` defaults to `false` in code; set `true` in `.env` to use the graph path.
- Phase 7 verification baseline: 271 tests. Phase 8 closure: **307 tests** (+36), all static checks clean.
- Live smoke (M10): both paths verified — Phase 7 linear (`AGENT_GRAPH_ENABLED=false`) and LangGraph agent (`AGENT_GRAPH_ENABLED=true`) return grounded answers with citations for indexed content.

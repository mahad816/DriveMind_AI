# Phase 9 Tracker — Frontend Foundation

Track milestone-by-milestone progress for Phase 9, with matching commit messages.

## Phase Goal

Deliver a professional single-user Next.js UI that consumes the backend REST API only — chat, indexing pipeline, file browser, citation viewer, and Drive connection settings.

## Scope (MVP)

| Capability | Method | Status |
|------------|--------|--------|
| Next.js scaffold | App Router, TypeScript strict, Tailwind, shadcn/ui | Done (M1) |
| API client + proxy | Typed `lib/api/`, Next.js rewrites to backend | Done (M2) |
| App shell | Sidebar nav, connection banner, responsive layout | Done (M3) |
| Settings page | Drive OAuth connect, theme toggle | Done (M4) |
| Indexing dashboard | Pipeline stepper, job status, incremental prepare | Done (M5) |
| Files browser | Table, filters, per-file prepare, ask-about-file | Done (M6) |
| Chat interface | Composer, markdown answers, citation cards | Done (M7) |
| Source viewer | `/sources/[chunkId]` citation drill-down | Done (M8) |
| Polish + tests | Chat history, actions, shortcuts, vitest | Done (M9) |
| Verification + docs | README, CURRENT_STATUS, phase closure | In progress (M10) |

## Explicitly Out of Scope (Phase 9)

| Item | Reason |
|------|--------|
| **Server-backed chat history** | MVP uses browser `localStorage`; API later |
| **Evaluation dashboard** | Phase 10 |
| **SSE streaming answers** | Post-MVP |
| **Multi-user auth UI** | Post-MVP single-user MVP |
| **In-app file binary preview** | Optional later |
| **Frontend Docker service** | Phase 11 deployment |

### Design rules (unchanged from architecture)

- **Frontend** consumes backend REST API only — no direct Drive, Qdrant, or LLM access.
- **Next.js rewrite proxy** avoids CORS; browser uses same-origin `/api/v1`.
- **Single-user MVP** — connection status via `GET /index/status`, no login screen.
- Phase 9 keeps existing backend API contracts unchanged (except OAuth redirect in M2).

## Current Snapshot

- **Phase status:** Complete
- **Last completed milestone:** Milestone 9 (polish, chat history, message actions, tests)
- **Next milestone:** — (phase complete)
- **Blocker:** None

## Your Action Items (manual setup)

- [x] **Step A — Postgres running + migrations applied**
- [x] **Step B — Qdrant running with indexed vectors**
- [x] **Step C — OAuth connected and metadata synced at least once**
- [x] **Step D — OpenAI API key in `.env`**
- [x] **Step E —** `cd frontend && npm install`
- [x] **Step F —** `FRONTEND_URL=http://localhost:3000` in `.env`, restart API
- [x] **Step G —** `cd frontend && npm run dev` alongside backend

## Milestone Status

- [x] Milestone 0 — Phase 9 tracker + docs alignment
- [x] Milestone 1 — Next.js scaffold + Tailwind + shadcn/ui
- [x] Milestone 2 — API client + proxy + OAuth redirect
- [x] Milestone 3 — App shell + navigation + connection gate
- [x] Milestone 4 — Settings page
- [x] Milestone 5 — Indexing dashboard
- [x] Milestone 6 — Files browser
- [x] Milestone 7 — Chat interface
- [x] Milestone 8 — Source citation viewer
- [x] Milestone 9 — Polish + frontend tests + chat history + message actions
- [x] Milestone 10 — Verification + Phase 9 docs closure

## Commit Plan

1. `docs(frontend): add phase 9 tracker and align roadmap`
2. `feat(frontend): scaffold next.js app with tailwind and shadcn`
3. `feat(frontend): add typed api client and oauth redirect wiring`
4. `feat(frontend): add app shell layout and navigation`
5. `feat(frontend): add settings page with drive connection`
6. `feat(frontend): add indexing dashboard and pipeline controls`
7. `feat(frontend): add drive files browser page`
8. `feat(frontend): add chat interface with citations`
9. `feat(frontend): add source citation viewer page`
10. `feat(chat): sidebar history with rename, delete, and message persistence`
11. `feat(chat): add copy, retry, regenerate, shortcuts, and chat search`
12. `test(frontend): add component and api client coverage`
13. `docs(frontend): complete phase 9 frontend foundation`

## Target Module Layout

```text
frontend/
  app/
    layout.tsx                 # Root layout: sidebar, providers, fonts
    page.tsx                   # redirect → /chat
    globals.css
    chat/page.tsx
    chat/[id]/page.tsx
    index/page.tsx
    files/page.tsx
    settings/page.tsx
    sources/[chunkId]/page.tsx
  components/
    layout/                    # sidebar, conversation-item, app-shell
    chat/                      # composer, answers, citations, follow-ups
    knowledge/                 # prepare flow, diagnostics
    files/                     # files table, preview panel
    sources/                   # source content viewer
    ui/                        # shadcn primitives
  lib/
    api/                       # client, types, domain modules
    chat/                      # clipboard, follow-ups, source labels
    conversations/             # localStorage history + titles
    hooks/                     # connection, knowledge, conversations, shortcuts
    knowledge/                   # prepare pipeline client logic
```

## Configuration Targets (Phase 9)

| Setting | Env var | Default | Purpose |
|---------|---------|---------|---------|
| Browser API base | `NEXT_PUBLIC_API_URL` | `/api/v1` | Same-origin proxy path |
| Server API base | `API_URL` | `http://localhost:8000/api/v1` | Server Components (optional) |
| Backend proxy target | `BACKEND_URL` | `http://localhost:8000` | Next.js rewrite destination |
| Frontend URL | `FRONTEND_URL` | `http://localhost:3000` | OAuth callback redirect (M2, backend) |

## Verification Commands

```bash
cd frontend
npm install
npm run lint
npm run build
npm test

cd ../backend
uv run pytest -q
```

## Manual Commands Across Phase 9

```bash
# Daily dev (two terminals)
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev

# OAuth smoke
# Open http://localhost:3000/settings → Connect Google Drive

# Chat smoke
curl -X POST http://localhost:3000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is tensile strength?"}'
```

## Notes

- Phase 8 delivered LangGraph agent behind `AGENT_GRAPH_ENABLED`; frontend uses same `POST /chat` contract.
- Chat history persists in browser `localStorage` (not server-backed).
- Incremental indexing: setup skips unchanged files; full-scan retry available on setup errors.
- Design aesthetic: refined productivity (Linear/Vercel-style), zinc palette, minimal motion.

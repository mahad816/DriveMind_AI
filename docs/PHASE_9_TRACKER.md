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
| Settings page | Drive OAuth connect, theme toggle | Pending (M4) |
| Indexing dashboard | Pipeline stepper, job status, file stats | Pending (M5) |
| Files browser | Table, filters, per-file re-ingest | Pending (M6) |
| Chat interface | Composer, markdown answers, citation cards | Pending (M7) |
| Source viewer | `/sources/[chunkId]` citation drill-down | Pending (M8) |
| Polish + tests | Error/empty states, vitest coverage | Pending (M9) |

## Explicitly Out of Scope (Phase 9)

| Item | Reason |
|------|--------|
| **Evaluation dashboard** | Phase 10 |
| **Chat history / threads** | No `GET /chat/history` API yet |
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

- **Phase status:** In progress
- **Last completed milestone:** Milestone 3 (App shell + navigation + connection gate)
- **Next milestone:** Milestone 4 — Settings page
- **Blocker:** None

## Your Action Items (manual setup)

- [x] **Step A — Postgres running + migrations applied**
- [x] **Step B — Qdrant running with indexed vectors**
- [x] **Step C — OAuth connected and metadata synced at least once**
- [x] **Step D — OpenAI API key in `.env`**
- [ ] **Step E — After M1:** run `cd frontend && npm install`
- [ ] **Step F — After M2:** add `FRONTEND_URL=http://localhost:3000` to `.env`, restart API
- [ ] **Step G — After M3+:** run `cd frontend && npm run dev` alongside backend

## Milestone Status

- [x] Milestone 0 — Phase 9 tracker + docs alignment
- [x] Milestone 1 — Next.js scaffold + Tailwind + shadcn/ui
- [x] Milestone 2 — API client + proxy + OAuth redirect
- [x] Milestone 3 — App shell + navigation + connection gate
- [ ] Milestone 4 — Settings page
- [ ] Milestone 5 — Indexing dashboard
- [ ] Milestone 6 — Files browser
- [ ] Milestone 7 — Chat interface
- [ ] Milestone 8 — Source citation viewer
- [ ] Milestone 9 — Polish + frontend tests
- [ ] Milestone 10 — Verification + Phase 9 docs closure

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
10. `test(frontend): add component and api client coverage`
11. `docs(frontend): complete phase 9 frontend foundation`

## Target Module Layout

```text
frontend/
  app/
    layout.tsx                 # Root layout: sidebar, providers, fonts
    page.tsx                   # redirect → /chat
    globals.css
    chat/page.tsx
    index/page.tsx
    files/page.tsx
    settings/page.tsx
    sources/[chunkId]/page.tsx
  components/
    layout/                    # app-sidebar, connection-banner, page-header
    chat/                      # composer, answer, citation cards
    index/                     # pipeline stepper, stats
    files/                     # files table, status badges
    sources/                   # source content viewer
    ui/                        # shadcn primitives
  lib/
    api/                       # client, types, domain modules
    hooks/                     # use-connection-status
    utils.ts
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
npm test          # after M9
```

Backend regression (when M2 touches auth):

```bash
cd backend && uv run pytest -q
```

## Manual Commands Across Phase 9

```bash
# After M1
cd frontend && npm install

# Daily dev (two terminals)
cd backend && uv run uvicorn app.main:app --reload
cd frontend && npm run dev

# After M2 — OAuth smoke
# Add FRONTEND_URL=http://localhost:3000 to .env, restart backend
# Open http://localhost:3000/settings → Connect Google Drive

# After M7 — Chat smoke
curl -X POST http://localhost:3000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "What is tensile strength?"}'
```

## Notes

- Phase 8 delivered LangGraph agent behind `AGENT_GRAPH_ENABLED`; frontend uses same `POST /chat` contract.
- Backend baseline: 307 tests, 14 endpoints under `/api/v1`.
- Design aesthetic: refined productivity (Linear/Vercel-style), zinc palette, minimal motion.
- API wiring is M2; M1 delivers runnable scaffold with rewrite stub in `next.config.ts`.

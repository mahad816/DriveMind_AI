# Phase 3 Tracker — Google Drive Read-Only Integration

Track milestone-by-milestone progress for Phase 3, with matching commit messages.

## Phase Goal

Authenticate with Google (read-only), sync Drive file metadata into PostgreSQL, and support export/download of MVP file types.

## Your Action Items (manual setup)

- [x] Step A — Google Cloud Console (project, Drive API, OAuth consent, OAuth client)
- [ ] Step B — Copy `.env.example` → `.env` and fill `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
- [ ] Step C — Start Postgres + run `alembic upgrade head` (after Milestone 1 migration exists)
- [ ] Step D — Manual browser OAuth test (after Milestone 2 only)

## Milestone Status

- [x] Milestone 0 — Phase 3 tracker + setup checklist
- [x] Milestone 1 — Google deps, config, OAuth token model + migration
- [ ] Milestone 2 — OAuth routes + auth service
- [ ] Milestone 3 — Read-only Drive API client
- [ ] Milestone 4 — Metadata sync service + API
- [ ] Milestone 5 — Export/download handlers
- [ ] Milestone 6 — Incremental sync + phase closure

## Commit Plan

1. `docs(drive): add phase 3 tracker and google cloud setup checklist`
2. `feat(drive): add google oauth config and token persistence model`
3. `feat(drive): add google oauth login and callback flow`
4. `feat(drive): add read-only google drive api client`
5. `feat(drive): sync drive file metadata into postgres`
6. `feat(drive): add supported file export and download handlers`
7. `feat(drive): add incremental sync and complete phase 3 docs`

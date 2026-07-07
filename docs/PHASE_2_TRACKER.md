# Phase 2 Tracker — Data Model & Indexing State

Track milestone-by-milestone progress for Phase 2, with matching commit messages.

## Phase Goal

Model DriveMind persistence for users, drive files, documents, chunks, indexing jobs, and query history in PostgreSQL.

## Milestone Status

- [x] Milestone 1 — DB primitives (`enums`, `mixins`)
- [x] Milestone 2 — Core relational SQLAlchemy models
- [x] Milestone 3 — Initial Alembic migration scaffolded and validated locally (lint + alembic metadata checks)
- [x] Milestone 4 — Pydantic schemas for indexing/query state
- [x] Milestone 5 — DB model and migration integrity tests
- [x] Milestone 6 — Docs updates and phase completion status

## Commit Plan

1. `feat(db): add shared enums and timestamp mixin primitives`
2. `feat(db): add phase-2 core relational models`
3. `feat(db): add initial alembic migration for phase-2 schema`
4. `feat(schemas): add typed schemas for indexing and query state`
5. `test(db): add model and migration integrity tests`
6. `docs(db): update roadmap and schema notes for phase 2`

## Notes

- Migration file is manually authored to keep deterministic structure and avoid environment-coupled autogeneration issues.
- Full upgrade/downgrade runtime validation requires a running local PostgreSQL daemon (`docker compose` or local Postgres service).
- Milestone 3 live migration verified on local Docker PostgreSQL (upgrade -> downgrade -> upgrade).
- Phase 2 verification suite passed: lint, mypy, 18 tests, alembic head check, and offline upgrade/downgrade SQL generation.

# DriveMind coding standards

What a reviewer checks a change against. The `code-review` skill reads this file (not `AGENTS.md`) for its Standards axis.
Project facts, commands and architecture live in `AGENTS.md`; this file only holds rules a diff can be judged by.
Sources: the "Engineering Rules" and "Known Important Constraints" of `AGENTS.md`, the verified invariants in `docs/HANDOFF_2026-11-21.md` section 8, and the module rules of the old Cursor rule.

## Engineering rules (from `AGENTS.md`)

- Inspect the relevant implementation, tests, configuration and call sites before modifying behavior.
- Preserve the existing architecture unless a change has a clear, task-specific justification.
- Keep changes scoped; no unrelated refactors or formatting churn.
- Preserve both linear and LangGraph RAG behavior unless the task explicitly changes them (and keep the tool-agent path).
- Add or update tests whenever behavior changes, and run the relevant tests afterward.
- Never expose secrets, print real credentials, or commit `.env` values.
- Code and configuration are authoritative when documentation disagrees; update the affected docs.
- Do not unintentionally change public API paths, schemas, status semantics, citation contracts or frontend expectations.
- Preserve user work in a dirty worktree and do not overwrite unrelated changes.
- Known unfixed defects live in `docs/KNOWN_ISSUES.md` with strict expected-failure tests (`backend/tests/known_issues/`, `frontend/lib/knowledge/known-issues.test.tsx`, which exists only while a frontend defect is open). Fixing one removes its marker and updates the registry. A new known defect is added there with a reproducing test.
- A fix counts as fixed only after a held-out question set (written before the fix) and the full suite (`docs/DECISIONS.md`, `docs/HANDOFF_2026-11-21.md` section 3).

## Invariants a change must not break

- Drive access is read-only (`drive.readonly`) unless a task explicitly changes the product security model.
- Every tool query filters on `DriveFile.user_id` and `status == INDEXED`. Qdrant searches filter on the owner before top-K. Do not assume full multi-user isolation of indexing jobs (see `AGENTS.md`, "Known Important Constraints").
- Chunk text is authoritative in PostgreSQL; embeddings are in Qdrant under the same chunk UUID, reconciled per file.
- `EXTRACTION_PIPELINE_VERSION` (`backend/app/ingestion/pipeline_version.py`) is raised whenever a change alters extracted text.
- Citations: an invented marker is never repaired by deleting it or adding real ones (one corrective retry only); a leaked source handle or id is never retried; chitchat and inventory answers carry no citations; citation IDs stay resolvable through `/sources/{chunk_id}`.
- A NOT_FOUND hint depends only on the shape of the typed reference, never on whether a file exists (no existence oracle between users).
- Indexing job states keep the semantics in `AGENTS.md` ("Final indexing/job semantics"): `COMPLETED` means no file-processing failures, not that any file became `INDEXED`.

## Structure and style

- Business logic lives in `services/`, not in `api/` route handlers.
- The frontend calls only the FastAPI REST API (`/api/v1`); it never reaches Drive, Qdrant or a model directly. The model never reads Drive; it receives retrieved chunks only.
- Small, single-responsibility modules; no monolithic files; no unnecessary abstractions; no duplicated logic.
- Dependency injection over global state.
- Configuration through environment variables (`backend/app/core/config.py`); no hardcoded secrets or tunable values.
- Typed code: Python type hints and TypeScript `strict`. mypy runs in strict mode and basedpyright in `standard` mode (`backend/pyproject.toml`); both must pass on the code a change touches. This does not claim the whole project is basedpyright-clean (see `docs/HANDOFF_2026-11-21.md`, section 5).
- Async where the work is I/O; do not block the event loop.

## Checks a change should pass

Run from the repository root (full command list in `AGENTS.md`, "Development").

- Backend, from `backend/`: `uv run pytest -q`, `uv run ruff check app tests`, `uv run ruff format --check app tests`, `uv run mypy app`, `uv run basedpyright app tests`.
- Frontend, from `frontend/`: `npm test`, `npm run lint`, `npm run build`.

## Git

- Follow `docs/GIT_WORKFLOW.md`: one logical change per commit, Conventional Commits (`<type>(<scope>): <description>`), review `git status` and `git diff` first, and get the owner's approval before committing.
- Never commit `.env`, tokens, credentials, Drive downloads or database volumes.
- Specs, tickets and ADRs are committed to a **public** repository: no secrets, private Drive content, credentials or user data in them.

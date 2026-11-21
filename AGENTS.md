# DriveMind Agent Guide

## Project

DriveMind / InfoVault is a Google Drive knowledge assistant. Private reads are owner-scoped per user through application sessions; some older service paths still assume a single user (see Known Important Constraints). It syncs read-only Drive content, builds a hybrid search index, and answers questions with source citations.

Main stack: Next.js 15, React 19, TypeScript, FastAPI, SQLAlchemy/asyncpg, PostgreSQL, Qdrant, Google Drive OAuth/API, OpenAI embeddings and chat completions, LangGraph, and Tesseract OCR.

## Architecture

- The Next.js frontend calls only the FastAPI REST API through the `/api/v1` rewrite in `frontend/next.config.ts`. Conversations are persisted server-side through the `/conversations` API (`backend/app/services/conversation_repository.py`); the browser still uses `localStorage` for session-scope and transition state (`frontend/lib/conversations/`).
- PostgreSQL stores users/OAuth state, Drive metadata, extracted document text, chunks and full-text vectors, indexing jobs, and query history. Qdrant stores embeddings keyed by PostgreSQL chunk UUID.
- Google Drive access is read-only. Sync stores metadata; ingestion later exports/downloads content. Chat reads the local PostgreSQL/Qdrant index and does not query Drive directly.
- On the legacy (linear and LangGraph) paths `RagService` routes every question first. Chitchat and inventory have dedicated paths; named files use direct file-target retrieval. General grounded queries use the linear hybrid pipeline unless `AGENT_GRAPH_ENABLED` enables the LangGraph retrieval/rewrite workflow. Preserve both grounded paths. When `TOOL_RAG_AGENT_ENABLED` is true (default false), `RagService.ask` hands the question to the tool-calling agent in `backend/app/agents/tool_rag/` instead; that is the path the evaluation harness measures.

## Important Directories

- `backend/app/api/`: FastAPI routes and dependency wiring.
- `backend/app/services/`: OAuth, Drive sync/content, ingestion, chunking, indexing, RAG, and source orchestration.
- `backend/app/connectors/google_drive/`: Drive API client and supported MIME behavior.
- `backend/app/ingestion/`: extractors, normalization, hashing, and deterministic chunking.
- `backend/app/retrieval/`: query routing, inventory/file-target/vector/keyword/metadata retrieval, fusion, reranking, and evidence grading.
- `backend/app/agents/drive_graph/`: LangGraph state, nodes, graph, and runner.
- `backend/app/llm/`, `backend/app/embeddings/`: OpenAI generation, context/citations, embeddings, and Qdrant integration.
- `backend/app/db/`, `backend/alembic/`: persistence models, sessions, enums, and migrations.
- `backend/tests/`: backend unit, service, API, retrieval, ingestion, and graph tests.
- `frontend/app/`, `frontend/components/`: routes and UI.
- `frontend/lib/api/`: backend client; `frontend/lib/knowledge/`: indexing workflow; `frontend/lib/conversations/`: local chat history.
- `infra/docker-compose.yml`: local PostgreSQL and Qdrant.
- `docs/ARCHITECTURE.md` and `docs/guides/`: detailed design and operating documentation.

## Core Flows

1. **Indexing:** `POST /index/sync` discovers or updates Drive metadata and change cursors. `POST /index/ingest` downloads/exports supported files, extracts normalized text, hashes it, and persists `Document` rows. `POST /index/chunk` creates overlapping chunks and PostgreSQL full-text vectors. `POST /index/build` embeds pending chunks, reconciles per-file Qdrant points, and marks files indexed. These are separate in-process background jobs; the frontend sequences and polls them.
2. **Query:** `POST /chat` (the demo UI's endpoint) and conversation turns (`/conversations/{id}/turns[/stream]`, the normal UI) both call `RagService.ask`. On the legacy paths it classifies the route (six outcomes: conversation-history recall, chitchat, file inventory, collection summary, file target, grounded); with `TOOL_RAG_AGENT_ENABLED` on it hands the question to the tool agent before any routing. Grounded retrieval uses vector, PostgreSQL keyword, and metadata candidates as selected by the linear or LangGraph path, then merges/reranks and grades evidence. Bounded prompt context is passed to the chat model. Citation payloads are derived from prompt chunks, filtered/verified, persisted with query history, and resolved through `/sources/{chunk_id}`.

## Stabilization Baseline

Pre-evaluation stabilization A1-A6, A7/A9, and A11 is complete, reviewed, tested, committed, and pushed. Treat these behaviors as the current baseline and do not revisit them unless a later task directly requires it.

Relevant stabilization commits on `main`:

- `d1b0e47` — exclude non-indexed files from retrieval.
- `7f752af` — reconcile missing files during full Drive sync.
- `47edbbf` — handle trashed and unsupported Drive changes.
- `4cfa8c8` — capture the Drive change token before full sync.
- `f9a599e` — normalize RAG citations consistently.
- `60770b1` — make indexing job states reliable (A7/A9).
- `4791d20` — route short knowledge queries to retrieval (A11).

### Final indexing/job semantics (A7/A9)

- Successful extraction with empty or whitespace-only searchable text sets the `DriveFile` to `SKIPPED`, counts as skipped, and does not fail the stage job. Existing coherent document/chunk data is not overwritten merely to store empty content.
- A zero-chunk result sets the parent file to `SKIPPED`; stale PostgreSQL chunks are removed when chunk replacement produces zero chunks. Index build also defensively maps zero chunks to `SKIPPED`.
- Explicit chunk/build requests for an already-`SKIPPED` file stop before loading or processing preserved stale content. They count the file as skipped and cannot restore it to `INDEXED`.
- Caught extraction/fetch, embedding, and vector-store failures set the affected file to `FAILED`. Successful files in the same batch retain their successful states.
- In ingestion and index build, `failed == 0` means job `COMPLETED`; `failed > 0` means job `FAILED` with a concise stage-specific `job.error`. An unexpected guarded exception also fails the persisted job.
- Index-build jobs are created and committed before `ensure_collection()` runs, so collection-setup failure produces a visible terminal `FAILED` job.
- `COMPLETED` means the stage finished without file-processing failures; it does not imply that any file became `INDEXED`.
- No new status, schema, migration, API contract, frontend polling behavior, or physical stale-vector cleanup was introduced.

### Final top-level routing semantics (A11)

- `CHITCHAT` is positively identified from a narrow normalized exact-phrase set covering greetings, acknowledgements, farewells, simple social conversation, and the explicit capability/identity questions `what can you do` and `who are you`.
- Query length is not a chitchat signal. The former five-word fallback and finite knowledge-keyword exception list were removed.
- Uncertain substantive queries fall through to existing specialized routing or `GROUNDED_RAG`. Examples such as `CoreChain architecture`, `machine learning`, `notes`, and `Python` reach grounded retrieval rather than bypassing the knowledge base.
- Quoted-file handling, `FILE_INVENTORY`, `FILE_TARGET`, and grounded linear/LangGraph execution retain their prior precedence and behavior.
- The existing ambiguity where unquoted `Tell me about CoreChain` routes to `FILE_TARGET` is intentional and remains out of scope pending routing evaluation.

At that stabilization checkpoint (historical), the full backend run passed with `562 passed`. That count is outdated and is kept only as history. For the current figures see "Latest recorded verification" below.

## Development

Run commands from the repository root unless a `cd` is shown.

```bash
# Infrastructure
docker compose -f infra/docker-compose.yml up -d postgres qdrant
docker compose -f infra/docker-compose.yml ps

# Backend setup and start
cd backend
uv sync --dev
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000

# Frontend setup and start
cd frontend
npm install
npm run dev

# Backend tests and checks (from backend/)
uv run pytest -q
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run basedpyright app tests

# Frontend tests and checks (from frontend/)
npm test
npm run lint
npm run build
```

## Engineering Rules

- Inspect the relevant implementation, tests, configuration, and call sites before modifying behavior.
- Preserve the existing architecture unless a change has a clear, task-specific justification.
- Keep changes scoped; avoid unrelated refactors or formatting churn.
- Preserve both linear and LangGraph RAG behavior unless the task explicitly changes them.
- Add or update tests whenever behavior changes, and run the relevant tests afterward.
- Never expose secrets, print real credentials, or commit `.env` values.
- Treat code and configuration as authoritative when documentation disagrees; update affected docs when appropriate.
- Do not unintentionally change public API paths, schemas, status semantics, citation contracts, or frontend expectations.
- Preserve user work in a dirty worktree and do not overwrite unrelated changes.
- Known unfixed defects live in `docs/KNOWN_ISSUES.md` with strict expected-failure tests (`backend/tests/known_issues/`, `frontend/lib/knowledge/known-issues.test.tsx`). When you fix one, remove its marker and update the registry. Add new known defects there with a reproducing test.

## Known Important Constraints

- Authentication and ownership are in a mixed state. Verified in code: `/chat` and the conversation routes require an application-session principal (`require_resource_user` / `require_application_principal`, unless `DEMO_MODE`), and the tool-agent file tools filter on `DriveFile.user_id` and `status == INDEXED`. `GOOGLE_APPLICATION_SESSIONS_ENABLED` (default false) gates only **issuing** sessions (the four `/auth/session/*` endpoints, 404 when off); every private route requires a principal whatever its value, so flag off means locked (except sessions already in the database, valid up to 7 days), not single-user. A fail-closed sign-in allow-list (`GOOGLE_SIGN_IN_ALLOWED_EMAILS`, verified Google e-mails, M0-SEC ticket 03) is checked at login completion and on every private request in normal mode; unset or empty means nobody signs in or keeps a session, and logout uses its own revoke-only resolution that skips the allow-list. Six services (user resolution, Drive sync, Drive content, chunking, ingestion, indexing) still fall back to the first stored `GoogleOAuthToken` when no explicit user ID is given (KI-031). This is latent: every production caller passes an owner (M0 audit, `docs/audits/m0-system-audit.md`). Owner mode has no rate limit or spend cap. Do not assume full multi-user isolation of indexing jobs without checking the tests in `backend/tests/security/`. `backend/app/security/README.md` has a current-status block at the top; its older text is historical.
- Drive access must remain read-only unless a task explicitly changes the product security model.
- Supported ingestion types are Google Docs (exported as DOCX), Google Sheets and Slides, TXT, Markdown, CSV, PDF text extraction (headers/footers removed, page markers, ruled tables), DOCX with tables and headings, PPTX, XLSX, and image OCR; scanned PDFs have no OCR fallback. `EXTRACTION_PIPELINE_VERSION` (`backend/app/ingestion/pipeline_version.py`, currently 3) must be raised when a change alters extracted text; the stored `documents.pipeline_version` triggers a re-read.
- Chunk text is authoritative in PostgreSQL; embeddings are in Qdrant. Keep their shared chunk UUID and per-file reconciliation behavior intact.
- File lifecycle is `discovered -> indexing -> indexed`, with `failed` and `skipped` states. Index build is the stage that marks a file indexed.
- Index jobs run inside the FastAPI process, and `/index/status` reports the latest job for the connected user.
- On the legacy path, hybrid retrieval and LangGraph are independently controlled by `HYBRID_RETRIEVAL_ENABLED` and `AGENT_GRAPH_ENABLED`; LangGraph applies only to grounded RAG after top-level routing. Both flags are ignored when `TOOL_RAG_AGENT_ENABLED` is on: the tool agent always uses hybrid retrieval.
- Chitchat and file-inventory responses intentionally have no citations. Grounded and file-target citations use PostgreSQL chunk IDs and must remain compatible with the source endpoint and frontend source viewer.
- `backend/app/evaluation/` holds only a trace helper. The evaluation harness is `backend/evaluation/rag_eval/` (datasets in `backend/evaluation/datasets/`, results in the Git-ignored `backend/evaluation/results/`); methodology and numbers are in `docs/EVALUATION_RESULTS.md`.

## Latest recorded verification

Recorded by M0 ticket 02 on 2026-11-21, on commit `7197af4` (no application code differs from `bf15b20`; only docs and one test type fix came after the previous run). Details, timings and the dependency groups are in `docs/tickets/m0-system-audit/02-test-baseline-and-classification.md`.

- **Backend full run (2927 tests), one run, as measured:** `2923 passed, 1 failed, 3 skipped` in 24 min 9 s on disposable PostgreSQL 18.7 and Qdrant 1.18.2 containers. Its failure and its skips were set-up problems of that run (next item); the full suite was **not** repeated.
- **Focused re-runs on the same commit, recorded separately:**
  - `tests/security/test_two_user_rag_end_to_end.py::test_http_graph_strategy_plans`, which holds the 1 failure (`[Show only txt-False]`), with `OPENAI_API_KEY` not exported: 3 passed. With a dummy key exported it failed 3 of 3. The test needs the variable **absent**: the graph rewrite node makes a model request when `settings.openai_api_key` is set, and the test asserts none.
  - `tests/security/test_conversation_chat.py`, which holds the 3 skips (`test_real_rag_modes_owner_filtered_qdrant_and_citation_publication[linear|graph|tool]`), with a disposable Qdrant at exactly `http://127.0.0.1:61448` (the test body requires that URL): 32 passed, 0 skipped.
  - **Qualified baseline:** the 2927 tests all pass in the right environment, shown by the full run plus these two focused re-runs, not by one clean full run. The run took 7 min longer than the previous one (17 min 24 s); the cause was not investigated.
- **Container-free subset (no container variables set, no `OPENAI_API_KEY`):** `2174 passed, 753 skipped` in 3 min 35 s; all skipped tests need PostgreSQL. One test, `tests/evaluation/test_rag_eval_dataset.py::test_public_cases_validate_when_the_public_documents_are_downloaded`, takes 155 s because the git-ignored public PDFs exist locally (it skips on a clean checkout; four other container-free tests do not, see the "Added after" item). With it deselected: `2173 passed, 753 skipped` in 53 s. **Limits of this subset:** it contains none of the 753 PostgreSQL/Qdrant tests, which include the ownership, session, indexing-job and vector-isolation tests in `tests/security` (judged from file names), so it does not guard those behaviours; those need the container suite (about 24 min).
- **Static checks (backend):** `ruff check app tests` and `ruff format --check app tests` clean (342 files); `mypy app` clean (183 files); `basedpyright app tests` **48 errors, all in 9 files under `tests/`, none in `app/`**, so basedpyright is clean on `app/` only; the 48 are the preserved baseline, not a target.
- **Frontend:** `npm test` 876 passed in 76 files (50 s, nothing skipped); `npm run lint` clean (`next lint` prints a deprecation notice); `npm run build` succeeded (18.6 s; it downloads the Geist fonts from Google Fonts).
- **Added after the run:** two known-issue test files (KI-022, KI-030; 7 tests: 3 passing guards, 4 expected failures). `tests/known_issues` afterwards: `19 passed, 4 xfailed` with PostgreSQL; `18 passed, 3 skipped, 2 xfailed` without containers (the KI-022 tests need PostgreSQL). Ruff is clean (342 files) and the basedpyright error count is unchanged (48).
- **Test environment:** `SESSION_TEST_DATABASE_URL` (loopback, database name starting `drivemind_session_test`), `QDRANT_TEST_URL` (loopback, not port 6333/6334), `CONVERSATION_TEST_QDRANT_URL=http://127.0.0.1:61448`; `OPENAI_API_KEY` must not be exported. No test reached OpenAI, Google or Railway.
- **Added after the run (M0 tickets 03 to 08):** tests for the credential fallbacks, route authentication, RAG provider failure, conversation deletion and KI-031 to KI-033 (the backend now has about 3,000 tests; the figures above are those of the recorded run and were not repeated). Of the container-free tests, four fail on a clean checkout for local-state reasons (a commit that is not an ancestor, git-ignored public PDFs); they pass on the development Mac. The CI workflow (`.github/workflows/ci.yml`) deselects them. CI was verified only by running its commands locally; it has not run on GitHub.
- **Not covered:** any test against a real Google Doc, Sheet or Excel-saved file (see `docs/KNOWN_ISSUES.md`).

## Agent skills

### Issue tracker

Version-controlled Markdown, no external tracker: specs in `docs/specs/<feature>.md`, tickets in `docs/tickets/<feature>/NN-<slug>.md`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles, recorded as a `Status:` line in each ticket. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. `docs/DECISIONS.md` keeps engineering and evaluation history. See `docs/agents/domain.md`.

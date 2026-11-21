# 06: Preparation and File-state audit (A3)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows what Preparation does end to end today, which of the v1 spec's Preparation and File-state requirements exist, are partial or are missing, whether Unsupported files are shown, and what could trigger expensive reprocessing, so M6 builds only what is missing.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** awaiting-owner-acceptance

## Scope

- Describe Preparation today: Drive check, the separate stages (sync, ingest, chunk, build), how the frontend sequences and polls them, what `INDEXING_ENABLED` gates, and whether anything starts a Drive check or Preparation without explicit Owner action (the v1 spec's Freshness rule forbids it: check startup tasks, schedulers, page-load effects).
- Map the v1 spec's File states (prepared, unprepared, unsupported, failed, outdated) and its selection, exclusion and summary requirements to the code: exists / partial / missing, each with evidence. Report whether Unsupported files are shown to the Owner.
- List what could cause expensive reprocessing without triggering any of it: raising `EXTRACTION_PIPELINE_VERSION`, applying pending migrations, changing embedding settings, restart or redeploy. Estimate scale only from counts the Owner can safely read, never by running it.

## Out of scope

Building file-state UI, selection or exclusion (M6, M7); starting any sync, ingestion, chunking or build; any Drive or OpenAI call; fixing defects; live Railway counts (ask the Owner to read them if needed, via ticket 01's approval process).

## Inspect

v1 spec sections "Preparation and freshness" and "Freshness"; `backend/app/api/index.py`, `backend/app/services/` (sync, content, ingestion, chunking, indexing), `backend/app/db/` (File status enum), `backend/app/ingestion/pipeline_version.py`, `backend/app/main.py` (startup), `frontend/lib/knowledge/`, `frontend/app/`, `frontend/components/`, `docs/guides/`.

## Deliverables

`## Findings` in this ticket: Preparation flow description, requirement-to-implementation mapping (exists / partial / missing with evidence), automatic-start check result, reprocessing-trigger list. Tests only if meaningful and deterministic.

## Needs

No paid APIs. No live infrastructure. No Docker unless a focused test needs the database fixtures.

- [x] The end-to-end Preparation flow and frontend sequencing are described with code pointers, including what `INDEXING_ENABLED` gates.
- [x] Every v1 spec Preparation and File-state requirement is marked exists, partial or missing, with evidence.
- [x] The report states whether anything starts a Drive check or Preparation without explicit Owner action, with the search method.
- [x] The report states whether Unsupported files are shown to the Owner.
- [x] Reprocessing triggers are listed; nothing was triggered; any scale estimate names its source count.
- [x] No application code changed.

## Findings

Audited 2026-11-21 on branch `feature/v2-state-performance`, base commit `41340e5`. Static reading of code, configuration and documents only. **No application code was changed, no test was added** (nothing here needed a deterministic new test; existing tests are named where they back a fact). No sync, ingestion, chunking or build was started, no Drive, OpenAI or Railway call was made, no Docker was used. "Hosted" facts come from ticket 01 and are Owner-reported or `Unverified`.

### Verdict

- **Nothing starts a Drive check or Preparation by itself (Verified by code reading, search method below).** Every job is created by a `POST /index/{sync,ingest,chunk,build}` call, and the only frontend callers are button handlers. Page-load effects and timers only read status.
- **The v1 spec's Preparation requirements are mostly missing or partial.** Of the 7 requirements (12-18): 1 exists (12), 4 are partial (13, 15, 16, 17), 2 are missing (14, 18 for Unsupported files). The File-state set is 2 of 5 (prepared, unprepared) plus a weak "failed".
- **Unsupported files are not shown to the Owner, because they are never stored.** Sync drops them before the database (section 3).
- **The current UI prepares at most 5 files per queue, one file at a time, with per-file confirmation.** The older all-in-one flow (`prepareKnowledge`) still exists but no screen calls it (section 1).
- **Reprocessing risk is real but gated by explicit job requests today.** Nothing re-reads or re-embeds files unless an Owner-started job covers them (section 5). One consequence to plan for: after the pipeline-version migration, every existing document counts as stale (version 1 < 3).

### 1. Preparation today, end to end

**Backend (admission, then a worker).**
1. `POST /index/sync?full=`, `/index/ingest?file_id=`, `/index/chunk?file_id=`, `/index/build?file_id=` (`backend/app/api/index.py:99-137`) call `_accept` (`:62-96`). It needs a signed-in application session (`require_index_user`), the lifecycle flag `indexing_admission_ready`, and a supervisor on `app.state`; otherwise it answers 503. SYNC and INGEST also require a stored Drive connection.
2. `IndexingJobService.admit` (`services/indexing_job_service.py:34-103`) inserts one `QUEUED` `IndexingJob` per owner. A second unresolved job (queued, running or `recovery_required`) for the same owner gives 409. So jobs are strictly one at a time per owner.
3. The worker polls and claims the oldest `QUEUED` job (`indexing_lifecycle.py:396-430`, `indexing_worker.py:164-204`) and runs the stage. With a `file_id` it works on that one file; **without one it works on all of the owner's files** (`indexing_worker.py:577-578`). The API allows the no-`file_id` form, so a bulk job is possible by API even though the current UI never sends it.
4. Stages: **SYNC** lists Drive metadata and upserts `drive_files` rows (new files `DISCOVERED`; a file whose Drive `modifiedTime` changed goes back from `INDEXED` to `DISCOVERED`; `drive_sync_service.py:160-226`). **INGEST** downloads or exports the file and extracts text into `documents` (`DISCOVERED`/`FAILED` files, plus `INDEXED` files with an older pipeline version; `ingestion_service.py:91-110`), leaving the file `INDEXING`. **CHUNK** creates chunks for `INDEXING` files. **BUILD** embeds chunks that are new or whose text hash changed (`indexing_service.py:198-203`) and marks the file `INDEXED`.
5. `GET /index/status` returns the latest (or a named) job; `GET /index/pending` returns the `to_ingest/to_chunk/to_build` counts; `GET /files` lists every `drive_files` row of the owner with its status (`api/files.py:31-46`).

**What `INDEXING_ENABLED` gates.** It defaults to `False` (`core/config.py:31`). Off: `lifespan` never builds the runtime or supervisor, so `indexing_admission_ready` stays false and **every POST above answers 503** ("Indexing execution is unavailable…"); only the legacy `_cleanup_stuck_jobs()` runs (`main.py:73-99`). On: `create_normal_runtime` first validates a long list of conditions (not demo mode, not `debug`, target fingerprint, credential keyring, OpenAI key present, database and Qdrant collection reachable and compatible; `indexing_runtime.py:283-328`) and refuses to start with an `IndexingActivationError` otherwise; then the supervisor starts the polling worker. The hosted value is in ticket 01 (not re-read here).

**Frontend sequencing (what the Owner sees today).**
- **Drive check = SYNC only.** `DriveDiscovery` (`components/files/drive-discovery.tsx`) uses `DiscoveryController` (`lib/knowledge/discovery.ts`). Its `start` runs only from a button: "Sync Drive" in the Files header variant (`:30-35`) or "Check Drive for files / changes" in the other variant (`:50`). It submits `POST /index/sync` and then only polls `GET /index/status`. It refuses to start while an unfinished Preparation record exists (`clearFinishedPreparation`, `discovery.ts:67-85`). Tests: `lib/knowledge/discovery-preparation-gate.test.tsx`, `discovery-api.test.tsx`.
- **Preparation = per file, three stages, explicit confirmation.** `/prepare` (`app/prepare/page.tsx`) shows `QueuePreparationView` (a queue of up to 5 files chosen on `/files`, "N of 5 documents selected", `knowledge-library.tsx:309`) or `SingleFilePreparationView` (`?file=`). `SingleFilePreparation` (`lib/knowledge/single-file-preparation.ts`) submits INGEST, then CHUNK, then BUILD for **one** file, each only after the Owner's "Prepare this document" or "Continue preparation" click. After the first confirm, the 3-second status poll may submit the next stage of **that same file** (`:176-182`, the `submitNext` call at the end of `check`); the queue never moves to the next file without another explicit confirm ("Explicitly confirm before preparing the next document", `preparation-queue.ts`). Progress state is kept in browser `localStorage` (`drivemind:preparation:v1:<owner>`), with Web Locks coordination (a browser feature that stops two tabs from acting on the same record at once).
- **Dead code:** `prepareKnowledge` (`lib/knowledge/prepare.ts`, the old Sync→Ingest→Chunk→Build chain over all files, using `/index/pending`) and `prepareSingleFile` (`prepare-file.ts`) have no non-test caller (`grep -rn "prepareKnowledge\b"`). `AdvancedDiagnostics` (`components/knowledge/advanced-diagnostics.tsx`, which can fire all four stages for all files) is not imported by any other file. **Recommendation for M6:** delete or deliberately wire these; as they stand, `/index/pending` and the stale-pipeline "to_ingest" count have **no UI consumer**.

### 2. Automatic-start check

**Result: nothing found that starts a Drive check or Preparation without an explicit Owner action.** Search method (limited to the code in the working tree; a search that finds nothing is not proof, per the spec):
1. Backend creators of jobs: `grep -rn "IndexingJob(" backend/app` finds `IndexingJobService.admit` (HTTP-admitted, owner-scoped) and four older service-level creators (`drive_sync_service.py:363`, `ingestion_service.py:252`, `chunking_service.py:185`, `indexing_service.py:277`). `grep -rnE "\.(sync_metadata|ingest_files|chunk_documents|build_index)\(" backend/app` shows the only direct caller outside tests is `app/demo/load.py:76` (it calls `IndexingService.build_index` for the demo corpus; whether anything runs it at startup was not inspected).
2. Background machinery: `grep -rnE "create_task|BackgroundTasks|add_task|apscheduler|cron|asyncio\.sleep|call_later|ensure_future|TaskGroup|run_in_executor" backend/app` finds only the indexing supervisor (polling, heartbeat, shutdown), cleanup tasks, chat streaming and the credential lifecycle. No scheduler, no cron, no periodic Drive call. Startup (`main.py`) runs `_cleanup_stuck_jobs` (marks legacy `RUNNING` jobs `FAILED`; no processing) or starts the supervisor; `indexing_recovery.py` says "No lifecycle or HTTP caller invokes this service" (operator-only; its docstring, not independently re-verified).
3. Frontend callers of the four POST helpers: `grep -rnE "syncDriveMetadata|ingestDriveFiles|chunkDocuments|buildVectorIndex|prepareSingleFile|prepareKnowledge" frontend/{app,components,lib}` (non-test) gives only button paths: `discovery.ts` (via the button), `submitFilePreparationStage` (via confirm), and the unmounted `AdvancedDiagnostics`/`prepare*` code. Every `useEffect` in `components/knowledge` and `components/files` was read: they call `check()` (GET status and file list) and set 3 s and 5 s timers; none calls `start`, `confirm` or `reserve`. Also checked: `grep -rnE "\.(start|confirm|reserve|finish)\(" frontend/components frontend/app`.
4. **Two nuances, not violations:** (a) Jobs already `QUEUED` in the database are picked up by the worker after a restart or redeploy, including a bulk job requested earlier by API (`claim_next`). They were Owner-approved when created, but a long-queued job can run much later. (b) Syncing resets an edited `INDEXED` file to `DISCOVERED`, which changes its state (and removes it from retrieval, per AGENTS.md commit `d1b0e47`) but starts no work.

### 3. Requirement-to-implementation map (v1 spec: user stories 12-18, "Freshness", "Preparation Q17")

| # | Requirement | Status | Evidence |
|---|---|---|---|
| 12 | Drive check on Owner's choice; nothing starts preparing as a result | **Exists** | SYNC only writes metadata (`drive_sync_service.py`). Button-only start (`discovery.ts`, `drive-discovery.tsx`). Tests `discovery-preparation-gate.test.tsx`. Not re-run. |
| 13 | Choose single, several, folders, all supported; search, filters, bulk selection | **Partial** | Exists: single file and a hand-picked set of at most 5 (`knowledge-library.tsx:309`), text search (`:242`), status filters (`:184-192`). Missing (not found in `knowledge-library.tsx`): folder selection or a folder filter, "all supported", bulk or select-all. (Folder paths are stored, shown and matched by the search box, `:151`, so folders are only partly absent.) Note: in the normal (non-demo) UI the filter chips are only To prepare, Ready, Preparing, All, so Failed and Skipped files show only under "All". |
| 14 | Exclude Files; exclusion persists | **Missing** | No exclusion column or value: `DriveFile` has no such field (`db/models/drive_file.py`), enum has none (`db/enums.py`), no frontend string. Limit: name search only. |
| 15 | Prepare only what needs updating | **Partial** | Backend: edited files return to `DISCOVERED` after the next check, so they appear under "To prepare"; unchanged ones are skipped by `_is_document_current`; unchanged chunks are not re-embedded (hash match). Gap: the queue refuses `indexed`, `failed` and `skipped` files (`preparationEligibility`, `single-file-preparation.ts:46-55`), so an `INDEXED` file with a stale pipeline version, and any failed or skipped file, **cannot be re-prepared from the UI** (its message says to ask the beta owner). |
| 16a | File states: prepared | **Exists** | `indexed` ("Ready"). |
| 16b | unprepared | **Exists** | `discovered` ("Found" / "To prepare"). (`indexing` = "Preparing…" is a transient extra.) |
| 16c | unsupported | **Missing** | No state; unsupported files never enter the table (below). |
| 16d | failed | **Partial** | `failed` exists but shows as "Unavailable" (`frontend/lib/user-language.ts:9`); no reason is shown in the list; set by ingest, embedding and vector-store failures (AGENTS.md A7/A9). |
| 16e | outdated | **Missing** | No `outdated` value. The nearest cases are invisible: a stale pipeline version leaves the file `INDEXED`; an edited file becomes `DISCOVERED` (indistinguishable from never prepared). |
| 16f | `skipped` conflation (not in the spec) | **Defect to plan for in M6** | One `skipped` value covers: removed or trashed in Drive, no longer a supported type after an incremental change (`drive_sync_service.py:228-241`, `:330-331`), missing at a full sync (`:257-279`), empty extracted text, zero chunks (AGENTS.md A7/A9). The UI shows one label, "Skipped". |
| 16g | Summary before starting: selection, estimated time, estimated cost | **Partial** | A review step lists the selection (`preparation-review.tsx`, `QueuePreparationView`). No time or cost estimate found (`grep -rniE "estimated (time|cost)"` in frontend is empty). |
| 17a | Last successful Preparation time | **Missing in the UI** | `indexed_at` is set at build (`indexing_service.py:234`) and is in the API type (`lib/api/types.ts:75`), but no component reads it. |
| 17b | Each Source's modified date | **Exists** | `files-table.tsx:57`, `file-preview-panel.tsx:152`, `source-panel.tsx`, `source-viewer.tsx`. |
| 17c | "Index may be outdated" relative to last Drive check | **Missing** | The closest wording is "Your assistant may be out of date" (`knowledgeStatusLabel.stale`, `frontend/lib/user-language.ts:21`), not "index may be outdated", and nothing uses it (`grep -rn knowledgeStatusLabel` finds only its definition). No "last Drive check" time is shown beyond the transient "Drive check completed. N metadata updates processed." |
| 18a | Told about every Unsupported file | **Missing** | Full sync lists with `supported_only=True` (`drive_sync_service.py:290`, `client.py:255`); incremental sync turns an unsupported change into `_mark_file_removed` (`:330-331`). `drive_files` never holds an unsupported file, so `/files` cannot show one. The frontend's `preparationEligibility` "This document type is not supported." is therefore, by inference from the sync code, unreachable for synced rows. Folders are also not stored (only used for paths). |
| 18b | Told about every oversized File | **Missing** | No size limit in the pipeline apart from Google's roughly 10 MB export ceiling, which falls back to a simpler export (`constants.py`, comment) and is not reported. `size` is requested from Drive (`FILE_FIELDS`, `constants.py`) but not stored in `drive_files`. Spreadsheet readers truncate to row and column caps (`extractors/tabular.py:20-28`); a "Note: only the first N rows/columns are indexed" line is added to the extracted text (`:70-74`), but the Owner is not told in the Files UI. |
| 18c | Scanned PDFs (spec: unsupported until OCR exists) | **Partial** | Not rejected: they are ingested, give empty text, and end as `skipped` ("may have no searchable text"), indistinguishable from other skips. AGENTS.md says "scanned PDFs have no OCR fallback". |
| Freshness: queue sequential, progress, recovery, clear errors | | **Partial (M6)** | Sequential per owner (backend) and per file (frontend), progress and recovery states exist (`indexing_recovery.py`, `single-file-preparation.ts` phases), but the messages repeatedly send the Owner to "the beta owner", and recovery has no UI. |

**Are Unsupported files shown to the Owner? No.** They are filtered out during sync, before any database row exists, so neither `/files` nor the Files screen can show them. The spec's open question (v1 spec, "Whether Unsupported files are reported in the current interface") is answered: not reported.

### 4. Cross-checks and documentation notes (for ticket 09)

1. `docs/guides/INDEXING.md:28` says pending counts report stale-pipeline files "as `to_ingest`" and that the frontend uses them to skip steps. True of the API; but no mounted screen calls `/index/pending` now (section 1).
2. The "Stabilization Baseline" in AGENTS.md describes `COMPLETED` as "stage finished without file-processing failures", matching the worker; the frontend's per-file checks additionally demand `total=1, processed=1, succeeded=1` (`single-file-preparation.ts:146`), so a bulk job result is never accepted by the UI as "ready".
3. `docs/guides/INDEXING.md` (the paragraph on newly supported file types) tells the Owner to use "the full scan option in the app", but no mounted screen sends `full=true` (only the unused `prepareKnowledge`).
4. Spec story 12 says "Drive check" and "Preparation" are distinct; the code matches (SYNC versus INGEST/CHUNK/BUILD), but the old `prepareKnowledge` chain joined them. It is unmounted; remove it before M6 to avoid a future accidental reuse.

### 5. What could cause expensive reprocessing (nothing was triggered)

Costs involved per file: a Drive download or export (Drive API, bandwidth), extraction (CPU; OCR for images), embedding calls to OpenAI for each new or changed chunk (`text-embedding-3-small`, `config.py:66`). Listing and chunking are cheap by comparison. Note that the ingest list also includes files left in `INDEXING` state (`ingestion_service.py:91-110`), not only `DISCOVERED`, `FAILED` and stale ones.

| Trigger | What would happen | Automatic? |
|---|---|---|
| **Raise `EXTRACTION_PIPELINE_VERSION`** (now 3, `ingestion/pipeline_version.py`) | Every `INDEXED` file with `documents.pipeline_version` below the new value counts as stale: it is re-downloaded on the next INGEST that covers it (a bulk INGEST, or a file-scoped one), counted in `/index/pending`. If the new text is identical only the version is updated; if it differs, CHUNK and BUILD follow and only changed chunks are re-embedded (hash comparison). | **No.** Needs an Owner-started job. The current UI cannot start it for an `indexed` file (section 3, row 15), so today only an API caller can. |
| **Apply the pending migration `20261120_1200`** (adds `documents.pipeline_version` with `server_default='1'`) | Does no reprocessing itself. **But it labels every existing document version 1**, so with code at version 3 every previously prepared file becomes stale at once. The next bulk INGEST would re-read all of them. Hosted database revision: `Unverified` (ticket 01); the container start script runs no migrations (`backend/deploy/start.sh`, per the v1 spec ledger). | No. |
| **Change embedding settings** | Model change with a different dimension: startup is refused (`check_collection` raises `VECTOR_CONFIGURATION_INCOMPATIBLE`, `indexing_runtime.py:235-240`), so nothing is reprocessed but indexing is down until the collection is rebuilt. Model change with the **same** dimension: nothing is re-embedded, because BUILD compares only `extracted_text_hash` (`indexing_service.py:119-127`, `:198-203`; the payload stores no model name), so old and new vectors would mix silently (code reading; no test run). Chunk-size constants (`ingestion/chunking.py:10-11`) affect only files chunked afterwards; `INDEXED` files are not re-chunked. | No. |
| **Restart or redeploy** | The worker resumes any job already `QUEUED` (including a bulk one) and the lease logic (a time-limited claim a worker holds on a job) handles interrupted `RUNNING` jobs (`indexing_lifecycle.py`, `indexing_worker.py`); the legacy cleanup marks old unmanaged `RUNNING` jobs `FAILED`. No new job is created. Browser `localStorage` records survive and the UI only observes them. | Resumes only Owner-approved work. |
| **Any Drive check** (`POST /index/sync`, full or incremental) | Metadata only, no content is read. It flips every file whose Drive `modifiedTime` differs back to `DISCOVERED`. **It also resets every `SKIPPED` file that Drive still lists to `DISCOVERED`** (`_upsert_file` treats `SKIPPED` as changed, "Re-enable previously removed files", `drive_sync_service.py:205-224`, reached by both sync kinds through `_apply_metadata`), so files skipped for empty text or zero chunks are retried at the next ingest that covers them. A full check also marks files missing from Drive `SKIPPED` (`:257-279`). The mounted UI never sends `full=true` (`discovery.ts:143` passes `false`; only the unused `prepare.ts` can pass it). | No: needs a later Owner-started ingest. |
| **Editing files in Drive, then a Drive check** | Each edited `INDEXED` file becomes `DISCOVERED` and leaves retrieval until re-prepared (AGENTS.md `d1b0e47`). Not costly by itself, but chat answers silently lose those files. | Only after an Owner-started check. |

**Scale estimate: none.** No file counts are available in the repository or from a safe read. To size the one-time re-read after the migration, the Owner would need two numbers from the hosted database (via ticket 01's approval process): the count of `documents` rows with `pipeline_version < 3`, and the sum of their file sizes (not stored today; it would have to come from Drive). Embedding cost then depends only on how many chunks change, which is not knowable without running it.

### 6. Caveats

- Everything is from reading code and existing tests; the existing tests named above were **not re-run** in this session.
- The name searches for "exclude", "unsupported", "oversized" and "estimated" are limited text searches; absence in the files read is not proof that no such code exists elsewhere.
- Hosted behaviour (`INDEXING_ENABLED` value, migrations applied, number of files) is `Unverified`; nothing is deployed according to ticket 01.
- "Bulk job is possible by API" comes from the route accepting no `file_id` and the worker's `claim.file_id is not None` branch; I did not run it.
- Whether the "queue refuses indexed files" gap is intended beta policy ("Conservative beta policy" comment, `single-file-preparation.ts:45`) or a gap is an Owner decision for M6.

## Comments

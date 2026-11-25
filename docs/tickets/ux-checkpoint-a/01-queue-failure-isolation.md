# 01: Preparation queue continues past a file-specific failure

**Spec:** none (scoped fix from `docs/audits/product-ux-issues.md`: Q-01, Q-03, F-01, A5 blink, V-01 default theme, L-01 partial)
**What to build:** one failed or skipped document no longer blocks the rest of a preparation batch. The user still confirms each next document. Anything uncertain or system-wide still pauses the queue. Also: selection stays usable after Review then Back, returning to the tab no longer blinks the page, new users see the Light theme.
**Blocked by:** None.
**Status:** ready-for-agent
**Progress:** resolved
**Risk:** high (frontend queue rules plus a backend change: one nullable column on `indexing_jobs`, a migration, and the worker's terminal write; no auth, quota, retrieval or paid-call change)

## Queue correctness contract (owner-approved 2026-11-25)

**Safe to continue** (all must hold): the exact job id from the saved receipt, owned by this user, for this file and stage;
a terminal result with exact evidence: **failed** means `status = failed`, `failure_class = "document"`, `total = processed = failed = 1`,
`succeeded = skipped = 0` and the file `failed`; **skipped** means `completed`, `total = processed = skipped = 1`, nothing failed or
succeeded and the file `skipped`. No `recovery_required`; Drive connected; session owner and revision unchanged; the saved queue
record is exactly the one read (compare-and-set). Counters alone never prove the cause. A canceled job is never definite.
The same rules re-verify saved history, so a recorded result the backend no longer agrees with pauses the queue.

**Backend failure class (new, backward compatible).** The backend had no structured cause: a per-file `failed` mixed unreadable
documents with Drive, embedding and Qdrant faults, and a job-level failure (restart, lease expiry, heartbeat, unexpected exception)
could look like a failed document. `indexing_jobs.failure_class` (nullable, migration `20261125_1200`) now records one of
`document | infrastructure | provider | authentication | configuration | unknown`, set from exception types and the existing structured
credential categories, never from message text. `document` is written only for an extraction failure the extractor positively typed as the document's own (malformed, empty, too large, unsupported: a plain `ExtractionError`). A missing OCR engine is `ExtractionEnvironmentError` (`configuration`); `OSError`, `MemoryError` and `RecursionError` at an extractor's catch-all are `infrastructure`; `ImportError` is `configuration`; any other unexpected extractor fault is `UnclassifiedExtractionError` (`unknown`). Drive
errors follow their category (authentication, provider, configuration, else unknown); embedding and vector-store faults are
`provider` (or `configuration`); heartbeat loss, interruption and lease expiry are `infrastructure`; any other exception is `unknown`.
Rows without a class (older jobs, startup cleanup, admission and recovery paths) read as unclassified and make the client pause.
The result and its receipt are recorded and the cursor moves in ONE write. The next document is only *offered*
(`awaiting_next`); it starts after another explicit confirmation. Failed and skipped documents are never re-submitted.

**Must pause** (nothing is recorded, nothing advances): unknown outcome or lost acknowledgement; `recovery_required`; Drive
disconnected or lost; session expired or user changed; queue owner or batch changed by another writer; the backend
disagrees with saved history; any system-wide dependency failure. Such a paused queue is ended locally (see "Local exit"); it is never closable while a stage is observed running.

**Persistence:** schema 3 allows `failed`/`skipped` entries before the cursor, each with its terminal receipt. Schema 2
stays readable; a v2 record that had stopped on a failed entry is upgraded by the next check (one compare-and-set write),
losing nothing, but only if its job now carries the definite evidence above. Older jobs have no class, so such a record fails closed. Invalid records are rejected and left untouched. **Multi-tab:** the advance is compare-and-set, so two tabs
advance once. **Exit:** a finished batch, a queue waiting between documents, and any **paused** queue can be ended. Ending a paused queue is
purely local: no request is made, so it works with Drive disconnected or the backend down. It submits nothing, deletes no backend
history, keeps every file's backend state, does not cancel a server job that may still run (the message says so) and is refused
only while a stage is observed running or the saved record changed under it.

**Retry is deferred.** Backend evidence for re-ingesting a FAILED file is code reading only, no test proves it, and a retry
spends paid embeddings. Failed and skipped files stay non-selectable; messages say so plainly instead of "ask the beta owner".

## Acceptance criteria

- [x] Failure at first, middle, last, several and all positions behaves per the contract (29 tests, `preparation-queue.failure-isolation.test.tsx`)
- [x] Global and uncertain cases still pause: recovery flag, lost acknowledgement, Drive disconnected, owner change, record changed elsewhere, history mismatch
- [x] v2 upgrade, v3 validation, refresh/remount and two-tab cases tested
- [x] Four superseded old assertions updated, each with a comment saying why (stop-on-failure replaced by continue-with-confirmation; recovery assertion kept)
- [x] Selection no longer disabled by a background inventory refresh; first load and ineligible-after-refresh still blocked
- [x] Tab return revalidates silently (no unmount, selection kept); expired session, different owner, failed check still fail closed
- [x] Default theme Light; saved Dark/System/Light preserved
- [x] Review fix: system-wide and unclassified failures pause (15 pause cases, saved v2 and history cases); backend classes tested against real PostgreSQL (30 tests)
- [x] Review fix: a paused queue can be ended locally with no request (Drive disconnected, lost acknowledgement, recovery flag)
- [x] Live Chrome verification on a stub backend (see Comments)
- [x] Independent reviewer APPROVE (closing cycle, exact staged diff)

## Comments

- 2026-11-25, first review: BLOCK on one P1 (a job-level failure with `failed = 0` advanced the queue). Fixed by the failure class above;
  the reviewer's probe is now a permanent test.
- Retry remains deferred (no backend retry safety proof; retry costs paid embeddings).
- Deploy note: **apply and verify migration `20261125_1200` before starting the new backend.** The ORM maps the new column, so an
  unmigrated database makes the new backend fail on every `indexing_jobs` read and write; it does not merely pause the queue.
  Steps are in `docs/guides/DEPLOYMENT.md`. Only once migrated does a job without a class (older rows) make the queue pause.
- 2026-11-25, second review: BLOCK on one P2 (a missing OCR engine was recorded as `document`). Fixed with typed extraction errors
  (`ExtractionEnvironmentError`, `UnclassifiedExtractionError`) and an injected-fault matrix over every extractor boundary.
  The two `OSError` catches in the XLSX reader no longer treat disk errors as an unreadable workbook.
- Known limitation: an unexpected exception at a PDF, DOCX, PPTX, XLSX, CSV or image catch-all is `unknown` and pauses the queue,
  even if it was in fact a malformed document that raised an untyped library error. That is deliberate (fail closed); the user can
  end the paused queue and continue with other documents.
- Known limitation: after a local end following a lost acknowledgement, a job that did run can leave its file `indexing`
  without a queue record to reopen. The Files page shows the file's real state.

- 2026-11-25, third review: BLOCK on one P2. After a reload, a queue past its first document could not be ended while the backend
  was down or the saved history disagreed with it: the blocked state kept `queue: null`, so the page showed no End button and
  `finish()` returned false. Fixed by keeping the record that was read in the blocked state (`lastRead` in `preparation-queue.ts`).
  It grants no permission to submit, ending still compare-and-sets against the stored record, and it is cleared when the queue is
  closed or gone. Regression tests: the reviewer's probe plus reload with the backend down, history mismatch, cursor 2, Drive
  status down, unknown job outcome, compare-and-set conflict, repeated End, no extra submission, and normal navigation afterwards.
  Limitation: if the whole backend is down the app stops at the session gate before any queue screen (existing behaviour).

- 2026-11-25, fourth review: BLOCK on one P2. Without a reload, after a lost acknowledgement with the backend down, the blocked
  state displayed an older copy of the record than the one stored, so the compare-and-set in End preparation refused. Fixed:
  `blocked()` now re-reads the stored record (falling back to the newest record this controller read or wrote only if the read
  throws), and `lastRead` is refreshed after every controller-owned write and after the post-check re-read. A tab that fell
  behind another tab therefore shows, and can safely end, the newer record. Ending still compare-and-sets against the exact
  record shown, so a record changed after it was shown is never deleted, and blocked stays inert (no submit, no advance).
  Messages after a paused end no longer claim "prepared documents remain available"; they point to the Files page for each
  document's current state. State lifecycle audit: every site that reads, writes, publishes, blocks, restores or clears a queue
  record was checked (reserve, runCheck top read, post-check re-read, ready handoff, failed/skipped advance, final publish,
  blocked(), finish(), corrupt record, another tab ending the queue).

- 2026-11-25, fifth review: BLOCK on one P2 (two confirmed probes). The blocked screen paired the newest stored record with a child
  progress snapshot computed against an older record, and End treated that child's job as "ended" without matching it to the entry's
  latest receipt. With another tab running a newer stage, End could say "nothing was left running", and a finished document's child
  could mark the current document Failed. Fixed with two shared predicates in `preparation-queue.ts`: `childBelongsTo` (the child is for
  the current entry's file and its job id equals the entry's latest receipt job id, both null while nothing is known) and `lastJobHasEnded`
  (a belonging child with a terminal job and a real receipt job id). `blocked()` publishes `child: null` unless the child belongs to the
  record it publishes; the End message and the progress screen's `lastJobEnded` and per-row `outcome` use the same predicates.

## Final state-management invariants (Checkpoint A)

1. The queue record in storage is the authority. A controller's copy is only the `expected` value of a compare-and-set; it is never written back.
2. A blocked state publishes the record stored now (re-read), falling back to the newest record this controller read or wrote only if the read throws.
3. Child progress describes one document and one job. It is shown or trusted only for the record whose current entry has the same file and whose
   latest receipt is that job. Otherwise it is dropped (`child: null`).
4. A job counts as finished only with evidence: a terminal job whose id is the entry's latest receipt. An unknown submission (no job id), a mismatched
   or missing job is never "ended"; the End message then says a job already sent was not cancelled and may still finish.
5. Only a positively document-specific failure (or a definite skip) with the exact job, owner and file may advance the cursor, in ONE compare-and-set write.
6. Blocked is inert: `confirm()` is refused, nothing is submitted, the cursor does not move, and no record is deleted except through a compare-and-set
   against the exact record the screen showed. A record changed after it was shown, or an unreadable one, is never deleted.
7. Ending a paused queue is local: no request, no backend deletion, no claim of cancellation or completion. The backend's own file and job states keep
   protecting files from being prepared twice. A new queue starts with no child from an earlier one.

## Tests added in this checkpoint (frontend, `preparation-queue.failure-isolation.test.tsx`, `preparation-progress.test.tsx`)

Reload with the backend down, history mismatch, cursor 2, status endpoint down, Drive reported disconnected, unknown outcome, compare-and-set conflict
(shown first so only the CAS can refuse), repeated End, no extra submission, normal navigation after End, the lost acknowledgement without a reload,
a corrupt record after it was read, a tab that fell behind, another tab that ended the queue, a controller writing after the block, the record stored at the
moment of failure, two tabs confirming at once (one submission), a stale tab (cannot submit or overwrite), reload after a lost acknowledgement, a new queue
without inherited progress, stale child versus latest receipt (probes A and B) and the component's row and warning gates.
Mutation checks (guard removed, tests must fail): job-id match in `childBelongsTo`, the stale-child drop in `blocked()`, the job match in `lastJobHasEnded`,
the re-read in `blocked()`, and the two component gates. All six produced at least one failing test; one (the component's own warning) first survived and a
test was added before the check passed.

## Browser verification (TEST, scratch copy and synthetic stub, port 3000 untouched)

Two tabs with a stale tab, single-tab failure of one document with the queue continuing, reload restoring the same state, End with no resubmission. Details and
limits are in the scratchpad notes `out-browser-exit.txt`; a whole-page network cut trips the session gate (existing behaviour), so the stale-tab runs used a
selective cut. Accepted submissions: 5 in total, none from End or from reload.

## Remaining limitations (P3, deliberately not changed)

- Retry stays deferred until backend retry safety is established.
- A lost acknowledgement can leave the file `indexing`; the Files page shows the file's real state and keeps it unselectable.
- An older open tab (before this change) rejects a version 3 queue record.
- An untyped library error at an extractor catch-all is `unknown` and pauses the queue, even if the document was in fact malformed.
- `runCheck`'s early returns update the internal record without publishing, so a blocked screen can lag one check behind storage (the first End is then refused
  by the compare-and-set and nothing is lost).
- `finish()` does not refresh the screen after a compare-and-set refusal; the next check does.
- After a history contradiction the idle panel after End shows the generic "no preparation queue is reserved" text rather than the end message.
- A corrupt stored record on a fresh load is not offered for ending (it fails closed and stays untouched).
- With the whole backend down the app stops at the session gate before any queue screen (existing behaviour).
- Corrupt or truncated images can surface as `infrastructure` (the queue still pauses); a registry mix-up could label a MIME mismatch `document`.
- The backend migration must be applied and verified before the new backend starts (`docs/guides/DEPLOYMENT.md`).

- 2026-11-25, final full-diff review: BLOCK on one P1, reproduced and NOT yet fixed. `single-file-preparation.ts` (terminal non-document branch of `check()`)
  publishes `phase: "blocked", canRelease: false` for any failed or canceled job that is not a definite `document` failure, and for pre-migration failed jobs
  (NULL class). At the base commit these published `failed` with `canRelease: true`. The queue does not read `canRelease`, but the legacy single-document view
  does: its only exit (`finish()`) needs `canRelease`, the record then stays as a legacy gate, Files selection stays disabled, and `/prepare` returns to the same
  view. Probe (3 cases: provider/failed, NULL/failed, document/canceled) fails on the current tree. Reviewer's smallest fix: keep `canRelease: true` in that
  branch (release only removes the local record) and add the probe as a permanent test; then verify the exact staged tree on its own, because
  `knowledge-library.tsx` and `types.ts` hunks depend on excluded Drive-sync changes. Other reviewer notes (P3): ending after a transient read error leaves a file
  `indexing`; known defects belong in `KNOWN_ISSUES.md` with a test per AGENTS.md; `revalidating` stays true if a refresh never settles.

## Closing cycle (2026-11-25, Owner-authorized: fix confirmed P0-P2 in one bounded cycle, then one independent review of the exact staged diff)

One systematic audit of the whole Checkpoint A diff (backend extraction typing, failure-class propagation through ingestion, worker,
classifier and schema, migration, queue, queue store, legacy single-file controller and views, progress screen, session revalidation,
multi-tab compare-and-set, reload, exits). Issue register (P0-P2 only; P3 stays in "Remaining limitations"):

| Issue | Severity | Root cause | Fix | Regression test |
|---|---|---|---|---|
| Legacy single-document screen locks permanently after a terminal job that is not a definite document failure (provider class, NULL class from before the migration, canceled) | P1 (final-review finding, reproduced red) | `single-file-preparation.ts` published `phase: "blocked", canRelease: false` for every non-definite `failed`/`canceled` job. The queue never reads `canRelease`, but the legacy screen's only exit (`finish()`) requires it, and the saved record keeps the Files legacy gate closed | Same branch keeps `phase: "blocked"` (a queue still pauses) with `canRelease: true`. The receipted job has ended, so release deletes only this browser's record: no request, no cancellation, no resubmission. Message no longer says a job "was not cancelled" (a canceled row contradicted it) | `single-file-preparation.test.tsx` (3 cases: provider/failed, NULL/failed, document/canceled; no POST, record removed, fresh controller sees no saved work); `single-file-preparation-view.test.tsx` (the screen shows Back to files, releases and navigates, one POST in total). Mutation: restoring `canRelease: false` fails all four |
| Same lock for a skipped legacy document after a Drive sync | P1 (found in this audit, reproduced red: phase `unknown`, not releasable) | `drive_sync_service.py` re-enables a skipped file (`skipped` to `discovered`) on any sync. The stricter `isDefiniteSkip` then fails, the branch falls through to the success path, which throws "Incomplete single-file evidence", giving `unknown` with no exit. At the base commit this case was releasable | A completed stage that skipped (`job.skipped === 1` or the file `skipped`) without exact evidence publishes `blocked` with `canRelease: true` (queue pauses, legacy can release) | `single-file-preparation.test.tsx` "a skipped legacy document stays releasable after a Drive sync re-enables the file" |
| Guards that must not change | – | – | – | New: queued and running legacy jobs are never released; a recovery-flagged failed job stays locked |

Checked and not changed: backend failure classes (a single `return "failed"` in ingestion sets its class; per-file class lives on the live
`progress` object the worker finalizes from; heartbeat, interruption, lease expiry and BUILD-evidence paths set their class; the schema drops
unknown values to NULL); the migration (nullable add, single head, clean downgrade); the backend never writes `canceled` (enum only), so a
canceled row is historical and terminal. The reviewer's P3 "`revalidating` stays true if a refresh never settles" does not occur:
`inspectApplicationSession` always settles within its 15 s timeout. Pre-existing, outside Checkpoint A: a legacy record whose BUILD completed
but whose file was later edited in Drive (indexed back to discovered) also reads `unknown` with no exit; it behaved the same at the base commit.

Additional finding in this cycle (P2, test only): `backend/tests/security/test_alembic_url_credentials.py` still expected head `20261121_1200`
(2 failures in the first full run on the staged tree). Updated to `20261125_1200` with a comment; reran: passed.

**Final verification** (isolated checkout of HEAD plus the exact staged diff; disposable loopback PostgreSQL 18.6 and Qdrant 1.18.0; `OPENAI_API_KEY`
unset; no `.env`): frontend `vitest` 78 files, 979 passed; `tsc`, `lint`, `build` exit 0; backend full suite 4838 passed, 2 failed, 7 skipped,
6 xfailed. The two failures are outside this change: `test_index_gate[first_step_probe]` (reads an API key from `.env` before its patched seam;
fails identically at base `45a3f0c`) and a shutdown timing test (`test_normal_indexing_runtime.py`, passed 5 of 5 reruns of the file alone).
`ruff`, `format`, `mypy` clean; `basedpyright` errors none in `app/` or any changed file. Migration upgrade, downgrade and upgrade verified.
Stub-backend browser runs (Chromium): failure and skip continue, provider failure pauses, reload, lost acknowledgement (one submission),
two tabs (one submission per stage), End with no request, legacy release, tab return without remount.

**Final review:** fresh `drivemind-reviewer`, exact staged diff: **APPROVE**, no P0-P2. P3 recorded, not changed: `discovery.ts` comment about a
finished queue is outdated for v3 (failed or skipped entries can finish a batch); legacy messages say "end preparation here" while the legacy
button reads "Back to files"; `AGENTS.md` "Latest recorded verification" still names head `20261121_1200`; the remaining limitations are not yet
in `docs/KNOWN_ISSUES.md` with tests; a skipped history entry re-enabled by a sync in another browser pauses the queue until it is ended.

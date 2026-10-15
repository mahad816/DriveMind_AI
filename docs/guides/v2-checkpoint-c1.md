# V2 Checkpoint C1: sequential preparation queue foundation

Internal frontend foundation only. No multi-selection or batch UI is exposed yet.
The existing single-document screen remains on the Checkpoint B path. Backend,
API transport, authorization, infrastructure, dependencies and demo UI are unchanged.

## Internal contract

`PreparationQueue` is constructed for an already verified owner and session revision.
It exposes `getSnapshot`, `subscribe`, `reserve`, `check`, `confirm`, `pause`,
`dispose` and `finish`. C2 must wire page hiding/navigation/session transitions to
pause/dispose, as the existing single-file screen does. Construct a new coordinator
after a session revision change; permission is never revived by a later check.

- `reserve(reviewedFiles)` captures 1–5 ordered unique IDs and reviewed metadata
  frames before awaiting anything, then verifies current authorized inventory,
  eligibility, connection and owner job status. It reserves the gate under a short
  lock. Reservation does not create any processing job.
- `check()` observes exact accepted receipts. While the same confirmed child is
  uninterrupted, it can progress that child's stages using the existing executor.
  A fresh/remounted coordinator has no continuation permission. A check never
  authorizes another document.
- `confirm()` is an explicit action for the exact currently reviewed batch, cursor
  and child run. It rechecks state before delegating to single-file confirmation.
  C2 must show the actual authorized document before this action.
- `pause()` invalidates continuation; `dispose()` also fences further UI publication
  and new work. Neither cancels an already issued server job.
- `finish()` closes an all-ready or known failed/skipped queue after rechecking it.
  It never closes uncertain/recovery-required/active work or skips a document to
  reach a later one. Closing a known failed queue abandons its unstarted tail;
  already prepared backend documents remain available.

There is no edit, skip, retry-failed, cancel-server-job, automatic next-file or bulk
API. An unstarted reserved queue can be resumed explicitly; this foundation does
not expose a discard action for it. C2 needs selection/review UI, route handoff,
lifecycle integration and accessible presentation, separately reviewed. Snapshots
are published at coordinator operation boundaries; C2 must also present a local
pending state while awaiting confirmation/reservation.

## One canonical versioned gate

The canonical location remains `drivemind:preparation:v1:<owner>`. The key is retained
for compatibility, but new queue payloads have `schemaVersion: 2`. There is no shadow
record or separate per-child journal.

The queue contains the owner, batch UUID, cursor and 1–5 ordered entries. Each entry
contains a unique file UUID, unique child run UUID, reviewed metadata frame (Drive
ID, MIME type, modified time), ordered stage submission IDs and accepted job UUIDs,
plus advisory `pending`, `ready`, `failed` or `skipped` result. No filename, document
text, credential, token or continuation permission is stored.

Validation checks bounds, identities, stage order, receipt uniqueness, cursor and
completed-prefix/unstarted-tail invariants. Invalid JSON, unknown versions, foreign
owners and malformed records fail closed without removal or migration. Updates
compare the complete expected envelope under discovery's short owner Web Lock.
No network call or backend job runs while the lock is held.

New queues omit Checkpoint B's top-level `fileId`, `runId` and `receipts`. An older
Checkpoint B controller cannot parse them and cannot overwrite or close them.
Existing discovery blocks on the same gate's presence, including between documents
and with unresolved payloads. Legacy records are recognized without conversion.
Valid, uncertain and recovery-required legacy work must continue through the existing
single-file progress/recovery path.

An old tab's already issued POST cannot be canceled. Its receipt can still be saved
if its original legacy record matches. Supported queue APIs cannot replace that
occupied record. Backend admission remains authoritative across noncooperating
clients and separate browsers.

## Execution, permission and handoff

`SingleFilePreparation` remains the only INGEST → CHUNK → BUILD state machine. A
small internal storage adapter projects only the active child into that executor.
Writes are bound to owner, batch, cursor, child run and file; child cleanup cannot
remove the batch gate. The legacy executor defaults remain intact.

The unchanged targeted transport requires the exact file UUID, fresh session/CSRF
proof and the last synchronous permission check immediately before POST. After fetch
is invoked, interruption cannot prove non-submission. Accepted receipts use captured
matching identities and can be saved after navigation/session changes, without
publishing private state or overwriting a newer workflow. Current-session 401
handling and stale-session fencing remain in the unchanged API client.

Within a confirmed child, clean counters, exact jobs and metadata checks allow the
next stage. Failed/skipped/unknown/recovery-required results stop it. BUILD must also
be confirmed indexed by authorized inventory.

A successful child and incremented cursor are written atomically, with the gate
continuously present. The old child is paused/disposed; the next child has no
permission. Fresh explicit confirmation is mandatory even without interruption.
A check that also changed stage receipts requires another observation before handoff.

Historical completed entries are verified against their exact clean BUILD receipts
and current indexed metadata. They need not remain the owner's latest job once later
files start. The active executor retains Checkpoint B's intervening-work checks.

## Failure and recovery

Completed entries survive a later failure, skip or uncertainty; the cursor does not
advance past the stopped file. Unknown acknowledgement has a null job ID and cannot
be replaced by guesses based on latest-owner status. No stage/file is automatically
replayed. Storage/Web Lock failure fails closed; failed handoff cannot start the next
file. Receipt-write failure after POST remains uncertain even if the server accepted.

Browser state is advisory, not proof of backend completion or authorization. There
is no backend batch reservation, submission idempotency/correlation API or atomic
reviewed Drive-version precondition. Hidden historical recovery blockers can still
be rejected during admission. Earlier successes are not rolled back after failure.

Follow Checkpoint B and Checkpoint A recovery guidance: check authenticated
owner-scoped status first, then exact known job IDs. Ask the beta operator to
investigate using approximate time and visible state. A browser intent is distinct
from a backend recovery-required flag. Never expose tokens, owner identifiers or
private content, clear storage, manipulate databases/job flags or blindly resubmit
SYNC/BUILD. Existing APIs cannot prove every lost request outcome.

## Verification scope

Tests use real controllers and API transport with synthetic fetch responses. Cover
bounds, targeting, explicit per-file confirmation, stages, refresh, permissions,
receipts, handoff, partial failures, cross-tab races, compatibility, discovery
exclusion, storage/lock failures, session fencing and demo isolation. Existing
Checkpoint B/discovery/session/transport tests remain required. No production
services or broad visual testing are needed for this internal foundation; C2
requires its own browser acceptance review.

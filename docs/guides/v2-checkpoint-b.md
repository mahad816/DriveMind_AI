# V2 Checkpoint B: single-file preparation

Frontend only. No deployment, backend, schema, migration, dependency, worker,
OAuth configuration or stored-data changes are part of this checkpoint.

## User flow

Previewing a row only shows metadata. **Select for preparation** chooses one
supported, discovered document and opens `/prepare?file=…` for review. No content
request occurs until **Prepare this document**. Cancel returns to Files without
submitting. Indexed documents open chat; failed, skipped, unsupported and orphaned
indexing states cannot start a fresh pipeline in this beta.

The reviewed target is frozen across INGEST → CHUNK → BUILD. All POSTs include its
internal `file_id`. The new targeted transport reuses the existing authenticated
CSRF preflight and receipt observer; legacy helper contracts are unchanged. It
rejects missing/invalid targets and demo mode before any submission. No owner-wide
processing path is used by this flow.

The screen shows actual queued/running/terminal stage states and document counters,
never simulated percentages or estimates. Clean single-file stage counters and
fresh file status are checked before advancing. BUILD is ready only when the
owner-scoped inventory confirms that exact document is indexed. Chat remains
knowledge-wide, not strictly scoped to the selected document.

## Durable observation and coordination

One owner-scoped browser record holds the file ID, metadata version frame, workflow
identity and up to three stage/submission/exact job IDs. It contains no document
text, tokens, cookies or profile information. Every stage reserves its intent
before POST. Matching writes are serialized under discovery's short owner Web Lock;
no lock is held over network calls. Discovery cannot start while a preparation
record exists, and preparation cannot start with an unresolved discovery record.
Backend owner admission remains authoritative, including historical blockers the
latest-job read cannot expose. Browser records are coordination hints, not access
control or backend idempotency guarantees.

A receipt observer persists a valid 202 acknowledgement for the captured owner's
matching submission even after navigation or session changes. It never overwrites
a newer workflow. API session fencing and current-session 401 invalidation retain
precedence over bookkeeping failures. Obsolete controllers cannot publish private
UI or start another stage. Missing storage/Web Locks fails closed.

During uninterrupted preparation the mounted controller advances sequentially.
Navigation, hiding the page and disposal disable automatic continuation. After refresh/navigation, polling resumes
read-only against the saved exact job ID, and **Continue preparation** is required
before another stage. Another file query cannot replace saved work. The user closes
a known terminal workflow with **Back to files** or **Start chatting** before choosing another file.
Leaving the page is never described as server cancellation.

## Failure and recovery limits

- Pre-POST failure or an exact documented admission/session/CSRF rejection removes
  only the matching attempted stage, retaining prior accepted stages. Check status
  before explicitly attempting the stage again. A 401 still unmounts private UI.
- Unknown acceptance (timeout, connection reset, abort, malformed acknowledgement,
  generic 5xx) keeps the pending marker and blocks replay. Failure to persist a 202
  also stays uncertain. No automatic mutation retries exist.
- Failed, canceled, skipped, recovery-required, missing/mismatched job evidence,
  changed metadata, intervening work, or inconsistent final file status stops the
  pipeline. An exact running BUILD with recovery protection is observed without
  restart; a terminal recovery flag blocks completion. Accepted stages are not repeated on refresh. A known failed/skipped
  job without recovery can be closed, but the file's failed/skipped status does
  not enable a fresh retry button.
- An uncertain browser marker is not a backend recovery flag. The operator must
  check authenticated owner-scoped `/index/status` first, then the exact known
  `job_id` if present. Report approximate request time and visible state only;
  never send credentials, owner identifiers or document content. Follow the
  Checkpoint A recovery procedure. Do not clear storage, alter recovery flags,
  manipulate jobs/databases, or blindly resubmit BUILD or SYNC.
- The existing API has no submission idempotency key, request-correlation history,
  workflow reservation or atomic reviewed-document version precondition. Latest
  status cannot prove a lost request's outcome or enumerate all old blockers.
  Unknown work therefore remains blocked pending authorized operator investigation
  or a separately approved backend contract. Legacy clients do not participate in
  browser locking; backend admission still enforces owner concurrency. File metadata
  is rechecked before submission/continuation and the worker validates its own
  snapshots, but this is not a promise to freeze a remote Drive content version.

## Acceptance

Use only local mocks/synthetic data for automated and isolated-browser acceptance.
Check review/cancel, keyboard confirmation, exact targeting, each stage's queued /
running / completed state, refresh with explicit continuation, unknown responses,
recovery exclusion, account change, overlapping tabs, storage/lock failures, final
indexed confirmation, mobile scrolling, light/dark/reduced motion and unchanged
demo/chat/citation behavior. Real OAuth/Drive/provider acceptance is separate and
requires authorized accounts; mocked tests do not establish production acceptance.

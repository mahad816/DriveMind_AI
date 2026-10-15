# V2 Checkpoint A: welcome and metadata discovery

Local frontend changes only. No backend, migration, deployment, OAuth configuration,
worker activation or stored-data changes are part of this checkpoint.

Normal-mode users see a product welcome inside the existing verified-session
boundary. Successful OAuth callbacks still land on Settings at the backend; after
session verification the frontend routes through home readiness to setup or chat.
LOGIN and CONNECT_DRIVE remain separate authenticated operations. Failed provider
callbacks still return the backend's safe JSON error; a friendly redirect needs a
separately approved backend change.

Files is available before indexing. Its discovery action submits only incremental
SYNC, with existing owner verification and CSRF. Reload file list only reads stored
metadata. Browsing is metadata-only: it does not download document previews or
submit extraction, chunking or embedding jobs. Normal preparation entry points are
replaced by a later-update explanation; existing indexed chat remains available.
The demo's existing branches and styling remain separate.

Discovery stores only an owner-scoped job reference or pending-acceptance marker in
browser storage. It writes intent before submitting, polls accepted jobs by exact
ID, observes active work, and blocks on recovery-required work. Status requests and
submission have 15-second timeouts. Polling is read-only at five-second intervals.
No timeout, refresh or retry-status action submits another operation automatically.
Session owner/revision checks fence private UI publication. A response-receipt
observer records only acceptance/rejection against the captured owner's matching
submission identity, even after unmount or session revalidation. The API client
still rejects stale response values. Browser Web Locks serialize short matching-
intent writes across cooperating tabs; they are never held over network I/O.
Missing storage or Web Locks prevents submission rather than falling back to an
unsafe cross-tab write. Existing legacy markers remain readable.

Lost acceptance cannot be resolved reliably with the existing latest-job API.
An uncertain marker stays blocked, including after refresh; the beta owner must
review it rather than users clearing storage or repeating an unknown operation.
Backend owner exclusion remains authoritative across tabs. Browser intent locking
is not an idempotent submission API and cannot coordinate older application tabs. An older unresolved job may also
require operator review if it is not the latest job. Better request correlation and
blocker discovery require separate backend approval.

Metadata sync can update file lifecycle states for changed/removed Drive files;
it is read-only toward Google Drive, not a read-only operation on local metadata.
No document is automatically re-prepared after discovery.

Manual acceptance still required: real successful OAuth redirects; cancellation;
connected/disconnected and empty inventories; discovery and refresh during active
work; interrupted requests; existing indexed chat/citations; two-account isolation;
mobile navigation, keyboard focus, light/dark contrast and reduced motion; unchanged
HarborDesk demo. Use authorized test accounts and data only. Unit tests do not
constitute full browser or production acceptance.

## Submission outcomes and rejection contract

- Before any SYNC POST attempt: session inspection, owner/revision checks, CSRF
  validation, storage or coordination failures are definitely non-submission.
  Only the matching intent is removed. The user checks authoritative discovery
  status before explicitly starting another attempt; nothing auto-retries.
- Definitive server rejection: only exact documented response pairs are accepted:
  401 / `Your application session is invalid or expired.`,
  403 / `Application session request could not be verified.`, and
  409 / `An unresolved indexing job already exists for this account.`
  The session dependencies reject before admission; admission conflict rolls back
  without accepting this request (`api/session_dependencies.py`,
  `security/session_helpers.py`, `api/index.py`, `IndexingJobService.admit`).
  A conflict can mean another job still blocks the account, so a status check
  and backend admission remain necessary even after this intent is cleared.
- Accepted: HTTP 202 with a valid queued job receipt is saved for the matching
  captured owner/submission. Navigation does not discard it. A newer intent is
  never overwritten, and no old-owner response is written under a new owner.
- Unknown: network failure, timeout, abort, truncated/malformed response,
  unrecognized error, generic 5xx, or a success body without the expected 202.
  Preserve the marker. These are not evidence that nothing was committed.

## Safe procedure for genuinely unknown acknowledgement

1. Stay signed in to the intended account and use **Check discovery status** first.
   This performs an authenticated owner-scoped GET, never another submission.
   If an exact receipt was saved, the client observes that job ID automatically.
   Do not switch accounts to try to bypass the block.
2. If still unknown, report the approximate request time, whether navigation or
   connectivity failed, and the visible state to the beta operator. Do not send
   cookies, session/CSRF tokens, account identifiers, document content, or complete
   network exports. The report does not need an internal owner ID.
3. Through authorized read-only tooling and the verified owner's context, the
   operator checks `/api/v1/index/status` first; where a receipt is already known,
   check `/api/v1/index/status?job_id=…`. Compare operation, timestamps, terminal
   state, progress and `recovery_required`. Do not query another owner's resources
   or ask a tester to copy credentials. Available sanitized operational evidence
   may establish a rejection or identify ongoing work; absence of logs is not
   proof that no job was admitted.
4. Distinguish the two blocks. A browser marker with no job ID means request
   correlation was lost; it does not itself mean vectors need recovery. A backend
   `recovery_required` job is an authoritative admission exclusion, including
   failed jobs. It requires the separately approved backend recovery process;
   clearing browser state cannot release it.
5. A latest job with the same operation/time is supporting evidence, not a request
   identity. A completed latest job, no latest job, timeout, lease expiry, or 404
   cannot prove the uncertain request's outcome. Existing status exposes latest
   or exact jobs, not a correlated request history or every historical blocker.
   If evidence is insufficient, leave the marker blocked and escalate for a
   separately approved request-correlation/recovery capability. This checkpoint
   provides no manual force-unlock or legacy-marker clearing shortcut.
6. Do not clear all browser storage, manipulate databases/jobs, change recovery
   flags, or blindly resubmit SYNC or BUILD. A confirmed known job can be observed
   to a terminal state; a genuinely uncertain request must not be replayed merely
   because waiting has ended.

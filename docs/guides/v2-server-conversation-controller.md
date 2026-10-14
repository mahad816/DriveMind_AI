# Server conversation controller (4F2-S3B)

This phase adds no production mounting. S3C must mount **one**
`ServerConversationsProvider` under the existing verified
`ApplicationSessionProvider`, shared by chat and sidebar. Consumers call
`useServerConversations()` for `{state, controller}`. Keep demo on its existing
separate path; do not mount this normal-mode controller there.

The controller owns immutable memory snapshots and temporary request bookkeeping.
PostgreSQL is authoritative. It imports no browser history/storage helpers.
Application-session owner/revision and a controller epoch fence every result and
error. Selection/list request generations fence overlapping reads. The existing
session invalidation event clears private state synchronously and aborts waits.
Provider rendering also hides any snapshot whose verified owner/revision differs.
StrictMode effect restarts abort the first read and establish a fresh epoch.

S3C operations:

- `initialize`, `refreshList`, `loadMoreConversations`: bounded 30-row cursor pages.
  Initialization discards local bookkeeping and reloads verified server state.
- `select(id|null)`, `reloadSelected`, `loadOlderTurns`: bounded 50-turn sequence
  pages. IDs are canonical server UUIDs. `nextTurnCursor` means older history exists.
  Reload keeps confirmed metadata, turns, citations and cursors during the wait and
  transient failures; navigation isolates the old selection. A current 404 removes it.
- `create(title?)`, `retryCreate`: preserve one creation UUID on lost acknowledgments.
  The returned server ID becomes selection only if selection has not since changed.
- `rename(id,title)`, `delete(id)`: use observed metadata version, await server
  confirmation and reconcile 409 with canonical metadata. Confirmed tombstones
  prevent late snapshots from resurrecting a resource. Per-conversation metadata
  generations fence obsolete success and error responses after newer confirmations,
  including stale 404s. A turn-specific 404 does not prove the entire conversation
  was deleted.
- `submitQuestion(question)`: freezes a new UUID, question, conversation and observed
  content version before async work. Temporary `submitting` is not durable RUNNING.
  No caller/browser history is sent. Canonical turn IDs replace no client message IDs.
- `reconcileSubmission`: status lookup for a known turn; exact same-key/payload
  submission replay otherwise. No automatic new UUID or model retry is introduced.
- `refreshTurn(id)`, `pollTurn(id,options)`, `stopPolling`: explicit, bounded polling
  (default 30 attempts/2 seconds; cap 60 attempts and 180-second elapsed budget).
  The elapsed budget includes status HTTP waits and terminal metadata reconciliation,
  with a five-second minimum for short explicit polls. Cancellation-resistant late
  responses are observed and discarded.
  API calls use the supplied abort signal. Selection/account change and
  disposal abort both waits and timers. A polling limit leaves RUNNING truthful.
- `interruptExpiredTurn(id)`: explicit user intent only. Observed expiry is exposed
  in `state.executionExpired[id]`; absence means not observed, not a local deadline
  inference. Expiry never starts a new generation automatically.
- `cancelSubmission`: cancels the browser wait and retains an unknown logical
  outcome. It does not assert SQL rollback or server-side generation cancellation.

Turn results are discriminated server states. FAILED/INTERRUPTED have no successful
answer. Terminal results cannot regress to RUNNING through an older response.
Generation for X cannot overwrite selected Y's turns. Metadata/content counters
merge monotonically; canonical metadata refresh follows completion so the next
request does not use a known stale content version. S3C must await action promises
and respect loading/submission fields, not infer completion from HTTP 200 alone.

Generic 409 does not distinguish busy, payload conflict and stale content versions.
The controller retains unresolved identity and reports the safe category. Present
explicit reconcile/reload actions, never an automatic fresh-key retry. Unmount or
refresh loses temporary bookkeeping; reinitialize and read server history/status
rather than importing browser records or claiming generation resumed. PostgreSQL
may have committed a cancelled/lost HTTP request. No exactly-once model invocation,
streaming, realtime cross-device push or offline sync is promised.

S3C still owns routing, chat rendering, sidebar grouping, citation panels and normal
localStorage retirement. Do not reuse legacy normal stored messages as API history.
The provider and adapter do not change OAuth, indexing activation or demo storage.

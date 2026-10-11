# Managed indexing worker: inactive 4E2 boundary

`IndexingWorker` consumes committed managed jobs using PostgreSQL
`FOR UPDATE SKIP LOCKED`. It is **not constructed or started by production
lifespan**. `indexing_admission_ready` remains false; there is no environment
activation flag or fallback to response-bound background work. Demo mode refuses
worker construction, and known synthetic demo identities are excluded from claims.
Tests explicitly construct and await the executor against disposable storage.

One awaited polling loop runs one stage at a time, with a minimum polling interval
of 100 ms and maximum of 30 seconds. Multiple processes can claim independent
owners' jobs. The existing partial unique index excludes overlapping unresolved
managed jobs for one owner.
The caller owns the awaited loop and its stop event; there are no detached tasks.
The supplied async session factory must use `expire_on_commit=False` and retain
the application's Google refresh lifecycle in session info.

Claims, stage work and terminal finalization use independent sessions. Owner,
operation, optional internal file UUID and full-sync options come from the job.
Unknown historical operations are never claimed. File-target disappearance fails
the job rather than broadening scope. Every SQL stage commit checks the current
RUNNING job/claim/worker/owner; failure finalization uses a fresh transaction.
Stage errors expose fixed classifications, never provider exception bodies.

SYNC validates the same credential row and grant epoch before applying metadata.
INGEST downloads through an independent content session, so content reads cannot
commit the stage's accumulated writes. CHUNK computes from a captured text/hash
snapshot outside its write transaction. BUILD commits prepared chunks before
Qdrant mutations, requires completed write acknowledgements, and rechecks file,
document and chunk snapshots before publishing INDEXED status.

SQL and Qdrant are not atomic. BUILD sets `recovery_required` **before** remote
work; failed, interrupted or uncertain outcomes keep it set and block further
owner admission. Only confirmed successful stage finalization clears it. The
executor never blindly retries ambiguous vector writes. Earlier successful file
commits can remain after a later failure; progress reports committed outcomes.

## Required 4E3 work before activation

- Lease/heartbeat renewal, expiry classification and safe multi-process recovery.
- Recovery of stranded QUEUED/RUNNING work; no current automatic takeover.
- Reconciliation of interrupted BUILD and cross-store partial outcomes.
- Full stale-sync snapshot ordering and protection from competing legacy/operator
  writes. Snapshot rechecks do not provide a distributed Qdrant fencing token.
- Owned startup/drain/shutdown wiring, and opening admission only after consumer
  and recovery readiness. Startup cleanup now affects only historical unmanaged
  jobs; it cannot fail another process's managed RUNNING claim.

Cancellation finalizes a matching claim as failed when the event loop and database
remain available. A process crash or database failure can still leave RUNNING
work. A failed terminal commit propagates to the awaited executor's owner.
Ordinary Python threads are not forcibly stopped; cancelled Google calls may
finish provider I/O, but do not resume the cancelled stage's SQL continuation.
The existing Google refresh lifecycle still owns credential refresh callbacks.

No migration, deployment, real-store indexing or recovery operation is authorized
by this implementation. Existing offline demo loading retains its legacy explicit
owner adapter and does not use the normal managed executor.

# Managed indexing worker: inactive 4E3A boundary

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
owner admission. Confirmed successful stage finalization clears it. The
executor never blindly retries ambiguous vector writes. Earlier successful file
commits can remain after a later failure; progress reports committed outcomes.

BUILD checks the collection's unnamed COSINE vector configuration and dimension
before point deletion, payload repair or upsert, including unchanged-vector builds
and concurrent collection creation. A deterministic configuration rejection before
this job has attempted point mutations fails the file/job without requiring remote
recovery. It never clears uncertainty from an earlier file in the same job, and it
never recreates an incompatible collection. Operator logs identify the required
vector configuration without including provider error bodies or private content.

Normal stale-vector reconciliation requires both the authoritative owner and
internal file UUID. Deletion IDs come from actual Qdrant record IDs. Inconsistent
record/payload IDs, file linkage or provenance stop reconciliation before deletion;
surviving SQL chunks must also belong to that owner/file. Malformed records are
left untouched for investigation, not silently repaired or deleted. Coherent stale
points whose SQL chunks have been replaced can still be removed. Ownerless or
foreign-owner stale points are excluded, not implicitly adopted; this per-file
operation is not exhaustive collection migration. Current unchanged points can
still receive owner-only repair when their SQL identity, file and hash agree.
The isolated demo retains its ownerless payload format and explicit demo owner.

## Required 4E3 work before activation

- Expiry classification and safe multi-process recovery. Leases alone do not
  establish remote-write quiescence or permit takeover.
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

## Database-time ownership (4E3A)

Explicit executors default to a 60-second lease and renew every 10 seconds.
Constructor-only settings are bounded and support short disposable test leases;
there is no production activation flag. Claim, renewal and completion timestamps
come from PostgreSQL, not application clocks. Sessions must use READ COMMITTED.
Job lock waits are bounded (2 seconds by default); statements are bounded at
15 seconds. Renewal also has a wall-time budget of at most 15 seconds (or
one third of the lease), so connection/transport stalls cannot hide heartbeat
failure. A failed heartbeat stops its owned attempt rather than retrying an
expired claim.

Every SQL publication locks the exact RUNNING job/owner/operation/target/options/
claim/worker first, then reads fresh database time in a separate statement. An
expiry predicate in the original locking query is insufficient: PostgreSQL may
evaluate it before waiting on an unchanged row. Publication is authorized only
if the lease is live at the post-lock check. The job lock remains held until
commit or rollback; this does not promise that the physical commit packet arrives
before the lease deadline. Authorization disables ORM autoflush and does not
refresh dirty progress or recovery fields. Failed authorization rolls back stage
changes.

Each attempt owns one stage task and one heartbeat task with independent SQL
sessions. Heartbeat changes only heartbeat/lease fields. Unexpected heartbeat
exit poisons the attempt and cancels stage work; poisoned stage guards refuse
further publication or mutation even if a transport swallows cancellation. Stage
sessions close before heartbeat is stopped and joined, and terminal publication
then uses a fresh session and the same post-lock check. Missing SQL authority or
unavailable storage leaves the durable job unresolved for later classification.

Managed BUILD installs a live-claim/snapshot hook before each independently issued
collection/index creation, point deletion, owner payload repair and upsert batch.
The hook releases SQL locks before network I/O. Embedding completes before the
subsequent mutation hook authorizes its writes. An already-issued Qdrant request
cannot be retracted by claim loss or cancellation. Its prior durable
`recovery_required` marker is retained; no remote rollback or exactly-once result
is claimed. Explicit offline/demo callers retain their existing no-hook adapter.

No expiry classifier, attempt manifest, takeover, operator reconciliation or
FastAPI worker startup is implemented here. Production admission remains closed
until the complete lifecycle and recovery cutover receive independent acceptance.

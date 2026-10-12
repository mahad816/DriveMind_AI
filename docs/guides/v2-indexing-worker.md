# Managed indexing worker: inactive production / supervised disposable 4E3B boundary

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

- Lifecycle wiring for expiry classification and safe multi-process recovery. Leases alone do not
  establish remote-write quiescence or permit takeover.
- Recovery of stranded QUEUED/RUNNING work; no current automatic takeover.
- Reconciliation of interrupted BUILD and cross-store partial outcomes.
- Full stale-sync snapshot ordering and protection from competing legacy/operator
  writes. Snapshot rechecks do not provide a distributed Qdrant fencing token.
- Owned startup/drain/shutdown wiring, and opening admission only after consumer
  and recovery readiness. Startup cleanup now affects only historical unmanaged
  jobs; it cannot fail another process's managed RUNNING claim.

Cancellation finalizes a live matching claim as failed when the event loop and
database remain available. Expired claims remain unresolved until explicit
classification. A process crash or database failure can still leave RUNNING
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

The 4E3A section above does not establish takeover, operator reconciliation or
production FastAPI worker activation. Production admission remains closed
until the complete lifecycle and recovery cutover receive independent acceptance.

## Durable attempt evidence and explicit classification (4E3C)

The additive `20261013_1200` revision adds nullable JSONB `attempt_manifest`.
Historical rows remain NULL. Downgrade refuses to discard any populated manifest.
The existing unresolved-owner partial unique index is unchanged: managed QUEUED,
RUNNING, and recovery-required rows block admission, including FAILED recovery rows.

A version-1 BUILD manifest records the complete owner-scoped selection before any
file processing, job/claim/worker identity, target collection and prior uncertainty.
Each file retains its document/hash/chunk-identity digest and count, phase, SQL
publication status and ordered mutation records. Prepared chunks and snapshot
metadata commit together. Each collection/index, delete, repair or upsert request
has a committed UNKNOWN intent before issue. Verified acknowledgements then commit
separately, with database timestamps and Qdrant operation IDs when available.
A confirmed concurrent-creation rejection is recorded as REJECTED, not a successful
write. Receipts never imply that subsequent SQL publication succeeded. Final BUILD
completion rechecks SQL owner, status, document hash and chunk identity evidence.

Manifests contain no document bodies, credentials or embedding values. Request and
chunk digests are SHA-256 over canonical JSON. Point IDs are retained for batches
of at most 100; larger batches retain their sorted-identity digest and count.
Selections are capped at 2,000 files, attempts at 4,096 mutation records, and JSON
at 2 MiB (also enforced by PostgreSQL). Exceeding a bound fails without truncating
or sending an unrecorded mutation. Each receipt rewrites the bounded JSON document;
this simple design intentionally favors recoverability over high-volume throughput.
Heartbeat updates do not rewrite manifest contents. A larger corpus needs a
separately reviewed evidence-storage design, not relaxed bounds.

`IndexingClassifier(worker).classify(job_uuid)` is an explicitly invoked internal
service, not an API or startup hook. It locks the job and reads fresh database time
AFTER obtaining the lock. QUEUED, historical and terminal rows remain unchanged;
live attempts are untouched. Null lease/claim/worker metadata requires review.
Expired SQL-only attempts become FAILED, retaining prior recovery requirements.
No automatic replay or resubmission occurs. Expired BUILD is non-recovery only
when a valid matching manifest proves complete selection, no mutation intents and
no uncertainty predating that selection. Missing, malformed or unsupported evidence,
any possible remote request (even acknowledged), or prior uncertainty retains
`recovery_required` and owner exclusion. The old claim is retained as audit identity
but cannot renew, publish or finalize once status is FAILED.

Lease expiry does NOT prove Qdrant quiescence. A request can finish after the sender
stops. FAILED recovery rows cannot be cleared by this classifier; 4E3D must establish
operational quiescence and reconcile complete evidence before release. Production
admission remains closed and no executor or classifier starts in FastAPI. 4E3B
still owns lifecycle/health/shutdown integration.

Normal INGEST now carries the downloaded content's nonsecret credential-row UUID
and grant epoch through its independent content adapter. Persistence locks and
checks that same owner's ACTIVE grant before publishing extracted text; reconnect
or disconnect invalidates stale downloads. The public content-response contract
and explicitly offline demo content remain unchanged.


## Supervised lifecycle (4E3B), production still CLOSED

`create_app()` still starts no normal worker or classifier and cannot admit new
indexing requests. No environment setting or HTTP argument can activate them.
4E3D implementation and independent cutover acceptance remain prerequisites.

Synthetic integration tests may explicitly inject
`create_app(indexing_test_runtime=DisposableIndexingRuntime(worker, refresh, ...))`.
This internal Python interface requires a loopback `postgresql+asyncpg` database
named `drivemind_session_test*`, explicit port and no routing query parameters;
a loopback HTTP Qdrant server on a non-default test port; a `drivemind_4e*`
collection; normal mode; and sessions bound to the same owned refresh lifecycle.
It is deliberately unavailable to anonymous demo startup. It is an accidental
real-store safeguard, not a substitute for operator authorization or test isolation.
Use only newly created disposable storage. Production activation is not supported.

The application owns one `IndexingSupervisor`, one polling task and one classifier
task. The accepted worker owns each active stage and heartbeat. Startup verifies
job columns, valid unique owner exclusion and the manifest-size constraint, then
requires successful database polling and classification handshakes. Claims start
only after both handshakes. Duplicate startup on one application is refused.
Intervals, database deadlines and classifier batch size are bounded; defaults are
1-second polling, 5-second classification, 50 candidates and a 10-second database
round-trip deadline. Classification uses the accepted post-lock database clock.
It never retries uncertain BUILD, resets recovery flags or invents legacy leases.

Indexing admission checks task liveness and a fresh database round trip, as well
as the server-owned gate. A stale boolean cannot authorize admission. Idle claim
connection stalls are bounded; active attempts retain their own heartbeat rather
than an overall stage deadline. Unexpected loop failure, cancellation, return or
DB failure makes the local executor unhealthy and stops further claims/rounds.
No automatic loop restart is performed: use a new healthy instance after diagnosis.
A claim already committed during failure is guardedly failed before stage execution.
Ordinary stage/provider failures stay visible on their job and need not kill a
healthy executor; failure to persist a terminal result does kill the local loop.
Another instance's live jobs are never failed by this lifecycle.

`GET /api/v1/health/indexing` reports only executor state and whether local admission
is available. It exposes no worker, job, claim, credential or document identifiers.
Existing liveness and database readiness responses remain unchanged: intentionally
inactive indexing does not make the read-only/chat API unhealthy. A 202 still means
committed durable acceptance, not guaranteed immediate execution after process death.

Shutdown closes admission and stops new rounds, drains active work with heartbeats
still active, then requests cancellation once after the configured drain deadline
(default 20 seconds). Worker rollback, session closure and guarded terminal handling
are joined before credential refresh is sealed/drained and the SQL engine disposed.
The lifespan waits at most drain plus cleanup grace (default another 5 seconds).
Longer SQL cleanup retains strongly owned shutdown/disposal tasks on application
state; engine disposal remains deferred until indexing cleanup joins. Existing
credential-refresh deferred-disposal ownership remains intact. Repeated shutdown
cannot cancel SQL cleanup a second time. Cancelled or failed cleanup never authorizes
engine disposal through a shortcut. Forced process termination/event-loop shutdown
cannot guarantee cleanup or remote-write quiescence; manifests and owner exclusion
remain the recovery authority. 4E3D must reconcile uncertain remote effects before
release, and complete production authorization. No release tool is added here.


## Admission authorization and shutdown ordering (4E3B-R)

A preliminary health check is not an admission grant. The HTTP route registers
an in-flight permit with its local supervisor **before** preliminary storage work
and owner/target-row waits. `IndexingJobService.admit` requires an explicit synchronous
`authorize` callback. All production HTTP admissions pass that request's permit;
trusted synthetic service-only fixtures supply their own explicit adapter.
There is no default no-op authorization in the service signature.

After owner/file locks and unresolved-job checks, the service calls the permit
immediately before adding and committing the job. That synchronous transition is
the authorization point. It checks current task identity, cancellation, registration,
single use, and real supervisor health (including already-dead tasks). Permit grant
and fatal-health/shutdown closure contain no await and are ordered on the same
application event loop. No local mutex spans a database wait; PostgreSQL retains
cross-instance owner serialization and uniqueness.

If closure wins first, final authorization raises a safe 503 and the transaction
rolls back without inserting a job. If the permit is granted first, subsequent local
failure does not revoke the granted publication; a successfully committed job may
truthfully return 202 and remain QUEUED for a future healthy executor. Physical COMMIT
completion need not precede closure. A cancelled or timed-out commit may have an
unknown acknowledgement: no 202 is claimed, and any committed row remains durable.
This mechanism neither deletes accepted jobs nor retries ambiguous commits.

Admission database work has the configured database deadline. The preliminary
HTTP health probe uses the same permit-owned SQL session, so cancellation cannot
leave a separate probe session cleaning up after registration is released. Each registration
owns a shielded rollback/session-close task; cancellation and errors cannot unregister
it before SQL cleanup finishes. The session is closed before later FastAPI dependency
teardown. Repeated caller cancellation cannot cancel cleanup a second time. If cleanup
fails and safe resource release cannot be established, admission fails closed and the
registration is retained; engine disposal is blocked rather than guessed safe.

Shutdown closes new permits synchronously, drains worker tasks **and admissions**,
then requests cancellation once for still-executing requests after the drain deadline.
Requests already performing owned SQL cleanup are not cancelled again. Deferred
shutdown waits for every registration to close before credential cleanup and engine
disposal. The lifespan deadline remains bounded while retained cleanup may continue.
A forced kill cannot guarantee SQL acknowledgement or remote-write quiescence.
Production admission remains CLOSED; this correction adds no 4E3D release or cutover.

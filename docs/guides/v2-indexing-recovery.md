# V2 indexing recovery (4E3D)

Production admission remains closed. This phase adds no activation switch, HTTP
recovery endpoint, alias switch, startup recovery release, or deployment action.
Independent acceptance and separate operational cutover authorization are required.

## Authority and maintenance

`python -m app.ops.indexing_recovery` accepts `audit`, `apply`, or `readiness`.
Supply `--database-env NAME`, `--qdrant-url URL`, `--collection NAME` and
`--embedding-model MODEL`. Audit/apply also require `--owner UUID --job UUID`.
Use the active deployment's embedding model; never choose a substitute to make a
collection compatible. The PostgreSQL URL must have explicit host/port/database
and no query overrides, routing parameters or fragment. Apply additionally requires
the exact `--confirm-target HOST:PORT/DATABASE|QDRANT_URL|COLLECTION` used by the
accepted tenant repair tool. Credentials are neither reported nor copied to evidence.

Before same-collection apply, an operator must independently enforce **all**:

1. Close mutation admission on every application instance, including old versions.
2. Stop/drain normal, offline, legacy and other SQL/Qdrant writers, including previous
   recovery operators. Fence/classify old claims using the accepted classifier.
3. Establish from authoritative operations evidence that every outstanding request
   addressing this concrete collection has finished or can no longer reach it.
4. Freeze SQL lineage and the entire shared collection through reconciliation,
   exhaustive verification and release. Do not allow other-owner BUILDs meanwhile.

Supply `--maintenance-reference REFERENCE --admission-closed --writers-terminated
--outstanding-requests-settled --collection-frozen` only after those conditions are
established. The reference is retained as a digest. These switches are **attestation,
not software proof**. Lease expiry, cancellation, waiting, and inventory scans do not
establish remote quiescence. If settlement cannot be established, refuse same-collection
recovery. Keep the owner blocked; seek separately authorized fresh **concrete** collection
isolation and a reviewed migration plan. This command neither builds nor switches that
fallback. An alias switch is unsafe because old requests may follow the alias.

The operator holds an exclusive PostgreSQL session advisory lock for this database.
Managed admission/claim/publication acquire a shared transaction lock first. Admission
refuses during maintenance, claims pause, and publication uses its existing bounded
SQL wait. This also excludes competing operators. The barrier is database-wide because
the accepted exhaustive verifier inspects all SQL tenants. It cannot stop old binaries,
direct writes or a Qdrant request already sent; external maintenance remains mandatory.
Recovery refuses QUEUED/RUNNING work instead of failing healthy jobs for convenience.

## Recovery state and scope

Only an exact FAILED, recovery-required, normal-owner BUILD with a valid original
manifest is eligible. Validate the original job/claim/worker/owner identity and complete
selection. Scope comes exclusively from that selection, never current FAILED files.
Current files, latest documents, hashes and chunk ID digest/count must match prepared
evidence. Missing/deleted/changed/unprepared snapshots require operator review;
this command does not fabricate chunks or infer missing historical evidence.
New BUILD selections also capture the embedding model/dimension and a nonsecret
file-metadata fingerprint. Recovery compares these with the active configuration
and current file. Old manifests lacking that evidence remain valid historical
records for classification, but automated repair refuses them. Prior uncertainty
outside the complete selected scope is also refused. Neither upgrade nor recovery
backfills invented provenance into those original records.
Prepared evidence also hashes document text and canonical chunk text/index/hash
lineage without storing bodies. This catches source drift even if a declared hash
or chunk UUID was not updated. Metadata-only payload repair retains a verified
unchanged vector; missing or unverifiable vectors require the active embedding service.

An additive nullable `recovery_manifest` preserves the original attempt unchanged.
States are REPAIRING -> VERIFYING -> VERIFIED. Each bounded mutation has its own
actual IDs, request digest, durable UNKNOWN intent and separately committed receipt.
An interruption preserves the FAILED original job and recovery-required exclusion.
To resume, inspect the stored recovery UUID and supply `--resume UUID` with a newly
established maintenance attestation. Another active operator cannot resume concurrently.
Earlier UNKNOWN receipts are never relabeled acknowledged: fresh reconciliation under
renewed external quiescence records RECONCILED only at the verified release boundary.

Scans paginate actual UUID point IDs. Stale deletion requires matching owner/file and
actual/payload chunk identity, plus absence of surviving unrelated SQL chunks. Contradictory
provenance is refused. Missing or mismatched expected points are reconstructed only
from authoritative selected SQL chunks with the configured embedding service. Healthy
points retain their embeddings. No global collection clearing or automatic resizing occurs.
Named vectors, wrong dimensions or distance fail before mutation. Other owners' points
and unrelated FAILED files remain unchanged. All mutation acknowledgements are checked.

Publish justified selected file states while the owner remains blocked, then run a fresh
exhaustive collection inventory. Any unrelated inventory anomaly also blocks release;
do not expand repair scope silently. Finally recheck job, manifest and current lineage,
maintenance lock and complete receipts, then clear only recovery_required. The historical
job remains FAILED. SQL publication and remote writes are never claimed atomic.
The JSONB journal has a 2 MiB database bound, a 4,096-operation bound, batches <=100,
and a conservative complete-plan capacity check before the first mutation. Downgrade
refuses populated recovery evidence.
The target must be an existing concrete collection with compatible tenant payload
indexes. Missing collections or indexes require a separately authorized configuration
repair under maintenance; this command never silently recreates storage or follows aliases.

## Read-only readiness

`readiness` examines schema revision, unresolved/historical jobs, provider identities and
grants, vector configuration, payload indexes, tenant inventory, and default-closed
application admission. It performs no mutation and returns NOT READY (exit 1) because
storage isolation, drained incompatible writers, independent acceptance and explicit
cutover authorization remain external prerequisites. A successful audit or operator
attestation alone must never authorize activation. Executor/classifier runtime health
must additionally pass the accepted controlled lifecycle tests and deployment checks.

CLI failures use nonsecret diagnostics. Exit 2 means blocked/configuration/storage error;
inspect the exact stored evidence before retrying. Never reset recovery_required manually.
Forced kills, network partitions and dishonest operational attestation cannot provide
exactly-once Qdrant guarantees. Keep maintenance and exclusion intact on uncertainty.

# V2 Qdrant tenant I/O and controlled cutover

Step 4D3 changes normal-mode vector I/O, not existing-store migration or public
multi-user activation. No existing collection is declared migrated by this phase.

## Code contract

- Normal points carry `user_id`, the canonical UUID string from PostgreSQL
  DriveFile ownership. Chunk UUID point IDs and existing payload fields remain.
- Normal searches require an explicit owner and filter `user_id` before top-K.
  Exact internal-file UUID conditions join the owner condition with AND.
  Zero hits, missing payloads and errors never cause unfiltered fallback.
- PostgreSQL still checks owner, INDEXED eligibility and exact-file scope before
  loading text. Qdrant payload claims are not sufficient authorization.
- Normal upserts require matching owner metadata. Existing extra payload fields
  survive replacement; authoritative newly supplied fields take precedence.
- An ordinary index build repairs ownership on unchanged points only after
  checking actual point ID, chunk/file linkage and the current PostgreSQL content
  hash. `set_payload` preserves vectors and other fields and does not create
  missing points. Invalid linkage fails the file build rather than guessing.
  This covers processed documents only, not the entire collection.
- Collection setup reconciles compatible keyword/UUID indexes for
  `drive_file_id` and, in normal mode, `user_id`. It does not run at app startup.
  Standard keyword indexing is sufficient. Optional `is_tenant` optimization
  is not an authorization boundary.

## Step 4D4 prerequisites before operational activation

1. Obtain explicit approval identifying the normal PostgreSQL/Qdrant stores and
   the operator's permitted migration actions. Preserve documents and embeddings.
2. Verify the actual server supports query filters, payload indexes and payload
   updates (tested here using client/server 1.18.0). Create the normal `user_id`
   index through the controlled rollout, including strict-mode permissions.
3. Drain old indexing workers and pending writes. Old code can write ownerless
   payloads; do not overlap old writers with the completed tenant cutover.
4. Derive owners from PostgreSQL Chunk -> Document -> DriveFile, then implement
   resumable, idempotent payload-only backfill. Inspect actual point identities,
   hashes and file linkage; explicitly report missing, orphaned or inconsistent
   points rather than assigning a guessed owner.
5. Exhaustively verify coverage, correct owners and preserved vectors/payloads.
   Deploy only the tenant-aware writer/search code after the coordinated data
   gate passes. Ownerless old points are invisible to new normal searches, so a
   premature deployment can return incomplete or empty answers.
6. Complete Step 4D5 feature-path verification and remaining API/job ownership
   gates before allowing multiple independent users. Current general health and
   indexing status are not proof of tenant-payload migration coverage.

The demo keeps its existing ownerless payloads and separate synthetic collection.
Only server demo configuration selects its search policy; the existing API
admission validates the configured identity and complete corpus every request.
The store requires the configured demo owner and rejects the default normal
collection. Normal authentication failure cannot select demo mode.

No unfiltered-search rollback is acceptable for a multi-user collection. Rollback
must retain the release gate, stop incompatible writers and use a reviewed
single-user or unavailable service posture. Payload addition does not require
recomputing embeddings, but never remove ownership metadata as an automatic
rollback. Cross-store indexing/job races remain a later job-ownership concern.

References: [Qdrant multitenancy](https://qdrant.tech/documentation/manage-data/multitenancy/)
and [payload updates](https://qdrant.tech/documentation/manage-data/payload/).

## Step 4D4A: read-only inventory and independent verification

From `backend/`, after explicit approval of the target stores:

```bash
uv run python -m app.ops.qdrant_tenant_inventory audit \
  --database-env AUDIT_DATABASE_URL \
  --qdrant-url https://your-approved-qdrant-host \
  --collection your-approved-normal-collection \
  --batch-size 100 --max-samples 100

uv run python -m app.ops.qdrant_tenant_inventory verify \
  --database-env AUDIT_DATABASE_URL \
  --qdrant-url https://your-approved-qdrant-host \
  --collection your-approved-normal-collection
```

Supply the PostgreSQL URL through the named environment variable, not command-line
arguments or committed files. Existing backend `QDRANT_API_KEY` configuration is
supported for HTTPS targets. Explicit database, Qdrant URL and collection are
required; the CLI never implicitly selects the default development database.
The JSON target identifies database host/port/name and Qdrant host/collection,
omitting passwords, usernames, URL query parameters and API keys.

Both commands perform the same exhaustive read-only scan. Exit codes are `0`
for completed clean coverage, `1` for completed coverage with defects and `2`
for configuration, segregation, pagination, storage or cleanup failure. Always
check `complete` and `clean`; partial counts from a failed scan are not a gate.
An empty existing collection with no indexed SQL chunks is explicitly `empty`.
A missing or unavailable collection is an operational failure, never empty.

Authority is Chunk → Document → internal DriveFile → User. All chunks of
INDEXED files are expected, matching current SQL retrieval eligibility. Other
file states do not require points, but lingering points for them are defects.
External Google file IDs are never ownership or point identity. Different users
may share a provider ID while retaining separate internal file and chunk UUIDs.

Classifications in `issue_counts`:

| Classification | Meaning |
| --- | --- |
| `missing_owner`, `wrong_owner` | Missing or canonical but incorrect owner UUID |
| `invalid_owner` | Noncanonical UUID or unsupported owner value type |
| `orphan_point`, `missing_point` | Point without SQL chunk, or indexed chunk without point |
| `wrong_file_id`, `wrong_chunk_link` | Incorrect internal file or chunk provenance |
| `wrong_hash`, `wrong_chunk_index` | Payload differs from authoritative chunk metadata |
| `missing_provenance` | Missing/null chunk ID, internal file ID, content hash or chunk index |
| `ineligible_point` | Point belongs to a non-INDEXED file |
| `invalid_point_id` | Numeric point ID, unsupported by DriveMind's UUID contract |
| `inconsistent_lineage` | Unresolved SQL relationship or inconsistent chunk/document content hash |
| `invalid_vector` | Missing, wrong-size or nonfinite unnamed dense vector |

`correct_points` counts points passing all checks. Issue counts are occurrences,
not distinct point counts; a record may have multiple defects. Bounded ID-only
samples include `owner_only_repairable=true` only when ownership is the sole
defect. Samples are not an exhaustive repair manifest. Display metadata such as
filenames is not an ownership authority and is not compared or reported.
The scanner does not verify embedding relevance or recompute content hashes.

PostgreSQL uses a read-only REPEATABLE READ transaction and UUID keyset pages.
Indexed chunk IDs are retrieved from Qdrant in bounded batches to find missing
points. A separate Qdrant scroll accounts for every actual point and checks SQL
lineage, provenance, owner and dense-vector shape. Only provenance payload fields
and bounded vector batches are read; neither text nor vectors are exported.
Exact collection counts before/after, monotonic page identities and scanned
cardinality detect incomplete or non-progressing pagination. Matching aggregate
counts alone cannot pass: equal counts with substituted/orphan IDs still fail.
Memory is bounded by batch size (1–1000), vector dimensions and sample limit
(0–1000), rather than collection size.

This is not an atomic cross-store snapshot. Stop incompatible and concurrent
writers for the final cutover gate. Count checks cannot detect every same-count
replacement during an active scan; a clean result under changing stores is not
reliable. Long scans hold a SQL snapshot and may delay vacuum cleanup. Prefer a
read-only database role and appropriately restricted Qdrant credentials.

Demo mode, recognizable demo/HarborDesk collection names, SQL `demo:` identities,
approved synthetic file UUIDs and collections containing their payloads are
rejected. Arbitrarily renamed unidentified stores cannot be inferred magically;
operators must still verify the displayed targets and approved environment.
No deployed demo data needs this normal-mode migration.

The `audit` and `verify` commands call no collection initialization, index creation, payload update,
upsert, deletion or repair API. Payload-index readiness remains a separate
controlled rollout check. Step 4D4B may reuse the pure classifier and bounded
authoritative lineage query, but must re-read and validate current records before
any separately approved owner-only update, then rerun this verifier. The original
Step 4D4A commands remain read-only. No existing store has been scanned or migrated
by implementation tests.

## Step 4D4B: controlled owner-only apply

This capability is tested only on disposable synthetic storage. It is never run
by API startup, indexing jobs or a scheduler. Using it on any existing store
requires separate approval of the exact targets and permitted operational work.

The operational sequence is:

1. Identify the exact normal PostgreSQL database, connection role/schema, Qdrant
   server URL and collection. Verify these are not demo targets.
2. Back up both stores and verify the recovery procedure.
3. Stop or drain incompatible indexing writers; isolate the maintenance window
   from metadata sync, chunk replacement and other PostgreSQL/Qdrant writes.
4. Run standalone `audit`, review all defects and resolve non-owner blockers
   separately. Missing vectors and orphan/provenance defects are not repaired.
5. Prepare compatible `user_id`/file payload indexes if required, including
   indexes needed by strict-mode conditional updates: `chunk_id`,
   `extracted_text_hash` (keyword/UUID as appropriate) and `chunk_index` (integer),
   as well as `drive_file_id` and `user_id`. Apply creates no indexes.
6. Run explicitly confirmed `apply` using the exact target string below.
7. Run a new standalone `verify`, independent of apply's embedded verification.
8. Test tenant-filtered search for authorized users, plus SQL hydration/citations.
9. Keep multi-user activation blocked until 4D5–4G and deployment gates pass.

```bash
uv run python -m app.ops.qdrant_tenant_inventory apply \
  --database-env AUDIT_DATABASE_URL \
  --qdrant-url https://your-approved-qdrant-host \
  --collection your-approved-normal-collection \
  --confirm-target 'your-pg-host:5432/your-database|https://your-approved-qdrant-host|your-approved-normal-collection' \
  --writers-stopped --batch-size 25 --max-samples 100
```

Confirmation is exactly `PG_HOST:PG_PORT/PG_DATABASE|QDRANT_URL|COLLECTION`, with
an explicit PostgreSQL TCP host, port and database, and the Qdrant URL matching the explicit
argument after surrounding whitespace is removed. Apply rejects ALL PostgreSQL
URL query parameters, even non-routing options such as `ssl`, plus fragments,
Unix-socket/multi-host targets and ambiguous or missing target fields. Encoded
and repeated query keys cannot bypass this policy. Supply a query-free
`postgresql+asyncpg` URL with an explicit port; no default port is inferred.
Audit/verify retain their existing read-only URL handling. Any future requirement
for additional apply connection options needs a separately reviewed extension.
The validated apply URL is passed to the engine and supplies the confirmation
and JSON target fields. Do not include passwords or
API keys. Connection role/schema must also be checked by the operator; the
confirmation string does not encode those privileges. The acknowledgement is
an accidental-operation safeguard, not evidence that writers are actually stopped.
Wrong confirmation or missing acknowledgement is rejected before clients open.
Demo protections apply to preflight and to fresh SQL batch lookups.

Apply runs the verified exhaustive inventory first. Any non-owner defect blocks
the entire operation before writes. Only `missing_owner` and `wrong_owner`, with
otherwise valid SQL lineage, string hashes, internal file/chunk linkage, INDEXED
eligibility and a usable dense vector, qualify. Malformed owner representations
are blockers. Bounded samples never serve as a repair manifest.

Points are visited in UUID order in bounded pages. Each batch freshly reads SQL
and current points, then revalidates the discovery snapshot before mutation.
Already-correct points are skipped. PostgreSQL transactions remain read-only and
short; no SQL lock spans Qdrant I/O. Each owner group receives only
`set_payload({"user_id": authoritative_owner})`, with `wait=True` and conditional
point-ID/provenance/previous-owner selectors. No overwrite, vector upsert,
re-embedding, point recreation, deletion or hash modification occurs.

Conditional Qdrant filtering narrows races but is not a full compare-and-swap:
filter matching has array/null semantics and cannot compare vector bytes or an
external SQL revision. Nor can it prevent PostgreSQL changes after a validation
read. A quiescent window is mandatory. Read-back checks revalidate SQL, owner,
all original unrelated payload fields and vector values. Detectable changes,
missing points and rejected/no-op/partial writes prevent success; deleted points
are not recreated. This is not a distributed transaction or locking guarantee.

The JSON contains `preflight`, `verification` and apply counters. `changed` counts
only updates confirmed by read-back; `already_correct` counts points needing no
write; `blocked` counts points refused during batch revalidation; `skipped` counts
points withheld by a preflight refusal or validated pending repairs withheld by
a failed batch. `failed` counts attempted updates that failed verification or
whose outcome is uncertain. Partial-run counters describe observed work, not an
exhaustive accounting of unvisited points. `preflight_blockers` retains the
scanner's overlapping issue counts, rather than pretending they are distinct
point counts. Troubleshooting samples contain IDs and fixed reasons only.

Apply stops at the first invalid batch or operation failure. Exit `0` requires
a NEW complete independent inventory with no defects, not just acknowledgements
or repaired-ID counts. Exit `1` means preflight/revalidation/coverage defects;
exit `2` means configuration, transport, acknowledgement, read-back or incomplete
scan failure. Both failures leave `complete=false` and `clean=false`. Earlier
confirmed updates may remain, and a lost response may hide successful updates.
Do not assume rollback or retry blindly from an old report. Restore the quiet
window, audit the current state, resolve blockers and rerun apply: already-correct
points are left alone and owner-only repair converges without checkpoints.
Use standalone verify afterward, including after interrupted runs.

A clean vector report establishes this corpus gate only. It does not establish
complete multi-user API/job authorization or production deployment readiness.

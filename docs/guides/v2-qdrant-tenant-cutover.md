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

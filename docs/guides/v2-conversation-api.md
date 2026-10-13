# Authenticated conversation metadata APIs (4F2-S2A)

Five `/api/v1/conversations` operations use PostgreSQL and verified normal-mode
application sessions. They do not change legacy `/chat`, browser storage, OAuth,
demo history or indexing activation. Demo requests are rejected before normal
resource access. Drive connectivity is not required for these APIs.

- `POST /conversations`: `{create_request_id: UUID, title?: string}`. Title defaults
  to `New chat`, is trimmed and bounded to 256 characters. First durable creation
  is 201; equivalent replay is 200 with the same identity/current metadata. Changed
  payload reuse is 409; replay of a deleted resource is 404.
- `GET /conversations?limit=30&cursor=...`: active owner-only metadata, ordered by
  activity descending then UUID descending. Maximum limit 100. `next_cursor` is
  versioned owner-bound time/UUID data, not authorization. Editable cursor values
  never select the owner. Malformed/foreign cursors are 422. Concurrent activity
  may reorder listings; this is not a frozen multi-page list snapshot.
- `GET /conversations/{UUID}?limit=50&before_sequence=N`: `{conversation, turns,
  next_before_sequence}`. The newest bounded page is in ascending sequence order;
  continuation fetches older turns. Maximum limit 100. Full pages supply a cursor;
  its next page may be empty. Original questions come from turns, never rewritten
  QueryHistory questions.
- `PATCH /conversations/{UUID}`: `{title, expected_metadata_version}`. Returns
  updated metadata, marks title manual, and rejects stale versions with 409.
- `DELETE /conversations/{UUID}`: JSON `{expected_metadata_version}`. Tombstones
  and fences through the repository; 204 on success. Repeated delete is 404,
  equivalent to missing/foreign/deleted access. Historical results remain retained.

Bodies forbid extra fields. Ownership, counters, timestamps and execution identity
are never writable inputs. Versions are positive strict integers. No endpoint
creates, retries, regenerates or finalizes turns. The current frontend is unchanged.

Reads reuse `require_application_principal`; mutations verify that principal then
reuse `require_session_mutation` for Origin/CSRF. Missing/invalid/revoked/expired
sessions are 401; failed Origin/CSRF is 403. GET follows existing private-read
policy without adding CORS exceptions. Resource absence is one 404 body. Invalid
requests/UUIDs are 422; unavailable/inconsistent storage is safe 503. Matched
success, dependency and validation responses carry
`Cache-Control: private, no-store, max-age=0` and `Vary: Cookie`. Validation errors
omit submitted values. Safe existing diagnostics never log raw SQL/provider bodies.

The service owns the request transaction, which authentication may have begun.
Mutations lock/recheck the initiating session before repository locks and check
fresh database time again before commit. That short shared session lock orders
revocation; expiry during SQL waits rejects publication. Detail briefly holds a
shared conversation lock while reading/serializing metadata and turn state so its
content version matches the page. It releases before HTTP transmission. No provider
or model calls occur. Lock waits are limited to two seconds and statements to ten.
Read DTOs are built before rollback; successful mutation acknowledgement follows
commit. Rename loads its SQL-backed updated timestamp asynchronously before commit.

Completed turns join owner-matched QueryHistory in one bounded query, with answer,
query ID, citation snapshots and retrieval count. Other statuses invent no answer.
FAILED/INTERRUPTED errors become fixed public categories. Execution IDs, deadlines,
session IDs and hashes are excluded. Citation snapshots never authorize live
`/sources/{chunk_id}` access. Response fields are bounded and detail JSON is capped
at 2 MiB; malformed/oversized stored pages fail rather than truncate evidence.

A lost commit acknowledgement may leave durable creation despite an unavailable
HTTP result; retrying the same creation key resolves it. This is not distributed
atomicity. Tombstones retain data; purge/retention approval remains outstanding.
S2B must separately implement durable turn admission/generation, request idempotency,
trusted citation provenance, publication session checks and expired-attempt handling.
No new feature activates indexing or changes anonymous demo storage.

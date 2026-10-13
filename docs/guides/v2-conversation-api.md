# Authenticated conversation APIs (4F2-S2A/S2B)

Five metadata operations under `/api/v1/conversations` use PostgreSQL and verified normal-mode
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
are never writable inputs. Versions are positive strict integers. The metadata operations do not generate turns. The current frontend is unchanged.

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
The S2B turn operations below add generation without activating indexing or changing
anonymous demo storage.


## Durable request-owned turns (4F2-S2B)

- `POST /conversations/{id}/turns` accepts exactly `{client_request_id: UUID,
  question: string, expected_content_version: integer}`. Questions are trimmed,
  nonempty and bounded to 4,000 characters. Version is a strict nonnegative BIGINT.
  Browser-supplied history, owner, execution and result fields are rejected.
  Supply the current conversation content version from metadata/detail. Preserve
  the original version and payload when retrying the same request identity.
- Response: `{turn, replayed}`. A newly completed, committed generation returns
  200. An existing RUNNING request returns 202 with `Location` pointing to its
  status URL. This replay schedules no new work. Existing terminal requests return
  200 with their truthful COMPLETED/FAILED/INTERRUPTED state. Changed payload keys,
  stale content versions or competing RUNNING work return 409. A new generation
  failure/timeout returns 503 with a durable turn receipt where storage permits.
  Storage uncertainty may instead return safe 503 without a receipt; repeat the
  exact original request to discover its durable state. 200 alone is not evidence
  of a successful answer: inspect `turn.status`.
- `GET /conversations/{id}/turns/{turn_id}` returns the same turn shape and a
  derived `execution_expired` boolean. It does not mutate or resume work.
- `POST /conversations/{id}/turns/{turn_id}/interrupt`, with `{}` and valid
  Origin/CSRF, atomically classifies an expired RUNNING execution as INTERRUPTED.
  A still-live execution is 409. Repeating interruption of a terminal turn is
  idempotent. Owner/conversation/turn linkage, execution identity and database
  time are rechecked after locks. An old executor cannot publish afterward.
  This is explicit recovery after a crash, not automatic LLM replay. A retry after
  failure uses a fresh client request UUID and current content version.

All three operations require verified normal application sessions and private
no-store responses. Missing/foreign/deleted conversations and mismatched turn IDs
are indistinguishable 404. Revoked/expired sessions are 401. The detail cursor now
rejects values greater than PostgreSQL BIGINT with 422 before querying storage.

The first submission owns generation in its HTTP/ASGI request; there is no chat
background task or queue. RUNNING, sequence, history boundary, initiating session,
immutable execution UUID and database-time deadline commit before external work.
Generation has a 120-second budget and the execution deadline is 180 seconds.
Generation reads use PostgreSQL READ ONLY sessions, inherited by parallel
retrievers; these never own row locks or independently publish QueryHistory.
Parallel retrieval siblings are cancelled and joined on exceptional exits.
History comes only from owner-matched completed SQL turns below the captured
boundary: at most four question/answer pairs, 8,000 characters per message and
24,000 combined. Omitted or unsuccessful turns make the history window incomplete.
Linear, LangGraph and tool-RAG reuse RagService with `persist_query_history=False`.

Publication takes short fresh SQL transactions in session → conversation → turn
lock order, checks initiating-session identity, live session and exact execution
against fresh database time after lock acquisition, and verifies citation chunk /
file ownership and indexed status. QueryHistory and COMPLETED publish atomically.
The turn retains the original question even when QueryHistory records an internal
rewritten query. Live citation access still independently authorizes the owner.
SQL lock waits are two seconds, statement limits ten seconds; physical commit may
finish after its authorization check. Successful output is returned after commit.

Cancellation, timeout, revoked authority, deleted conversations and storage/model
errors cannot invent completed results. Fresh-session terminal cleanup is bounded;
if it fails, the durable execution remains classifiable after expiry. Repeated
cancellation or forced process death may prevent cleanup. Cancellation-resistant
transports may delay request cleanup; suppressed timeout/cancellation still poisons
publication. ASGI disconnect does not universally cancel application work: a
bounded authorized request may finish after its client disappears. Resolve a lost
response by replaying the request key. On deployment, the long-running backend
must allow request drain and configure proxy timeouts accordingly; forced kills do
not guarantee cleanup or generation resumption. External model work is not atomic
with SQL and may incur cost without producing a stored answer. A fresh request
may invoke the model again; admitted request identities are never automatically
regenerated. No frontend cutover or indexing activation is included.

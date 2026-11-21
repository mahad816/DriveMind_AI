# 06: Apply the paid-question quota to the answering routes, add execution timeouts and input caps

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** `POST /chat`, conversation turn creation and turn streaming, on both the legacy and the tool-agent answering paths, refuse an over-limit question before any provider call with a clear 429, count each executed question exactly once, never bypass the limit through retries, and reject oversized questions and bodies. Owner-mode `/chat` gets an explicit execution timeout. Owner decisions D4-2 and the 2026-11-21 approval.
**Blocked by:** 05.
**Status:** ready-for-agent
**Progress:** open

## Admission flow (decided)

Order of checks, each before the next, for every paid route in normal mode (the body-size limit is middleware, so a 413 can precede a 401, as the demo limit does today):
1. Authentication and CSRF (as today).
2. Body size and schema validation (413 or 422).
3. The route's existing preconditions (404 when streaming is disabled, 409 when streaming needs the tool agent, conversation ownership and existence).
4. **Replay pre-check, conversation turns only:** read the turn table for a turn of this Owner with this client request id. If one exists, skip admission entirely and call the existing submit path, which returns the stored receipt or result without executing (a retry of a completed, failed, interrupted or timed-out turn with the same id never executes; a new attempt needs a new id). The turn table, not the ledger, is the authority on replay.
5. `admit(owner)` (ticket 05): 429 with Retry-After on refusal, 503 on `QuotaUnavailable`. A refusal makes no turn, no query-history row and no provider call.
6. For turns, the reservation step. If it raises (busy, version conflict, not found, payload conflict, any error) or reports that the turn already existed (a simultaneous duplicate), call `release(attempt_id)` and let the original outcome through. A failed pre-execution step never consumes quota; the attempt is counted only once a provider request begins (step 7), so no execution is left uncounted.
7. Run the work with a `PaidExecutionMarker` installed (ticket 05). In a `finally`, call `settle(attempt_id, marker)` in a fresh short session under a 10-second timeout: it finishes the attempt if a provider request began, and releases it if none did. A failure of `settle` is logged by category and swallowed, so it never changes the response (the lease covers it).

**Where release and finish live (required; revised by the Owner decision of 2026-11-21, ticket 04 Comments).** The admission logic is implemented inside the conversation submit path itself, not by a wrapper at route level: the route admits and hands the attempt to `submit`, which owns both the reservation and the paid work. The boundary is no longer the reservation commit but the first provider request. Until the marker is set, everything that fails is released, whether before the reservation commit (every exception in ticket 04 section 4's first table, and a replay return) or after it (`emit("accepted")`, history loading, user resolution, a zero-call route, a cancellation before the first provider request). Once the marker is set, the only permitted end is `finish`, whatever is raised afterwards (the session-expired, not-found and cancellation errors that `submit` re-raises after the paid call must never release, or a paid run would go uncounted). Both ends go through the single `settle(attempt_id, marker)` call in one `finally` that covers the whole submit body. The marker is installed inside the work function itself (inside `run()` for streaming), not in the route function, because the stream's producer task is created after the route returns and would not inherit a route-level context change. A `submit` called without an attempt because the replay pre-check hit, which then finds that its reservation creates a new turn (the turn vanished in between), must abort before any provider call with a retryable 503 and never execute. For `POST /chat` there is no reservation: it admits, runs under its timeout, and finishes in a `finally`.

`release` and `finish` run in a shielded scope (so a cancelled request still frees its row) with a 10-second timeout, in a fresh session; failures are logged by category only and swallowed.

Counting (Owner decision): a question counts exactly when a provider request began. Rejections and failures before that are released and not counted; provider errors, timeouts, cancellations and client disconnects after it still count and free the concurrency slot; a process kill after admission leaves an orphan row that counts until the lease expires. Internal model or embedding calls and SDK retries are never counted separately. A turn that failed after reservation but before any provider request stays FAILED (or INTERRUPTED) in the turn table as today, but consumes no allowance. Each `POST /chat` request is its own attempt (it has no idempotency key). Deliberate behavior change: with one concurrent question allowed, a second question while one is running gets 429, where a second turn in the same conversation used to get 409; a duplicate submission of the same request id gets the stored receipt instead.

A true simultaneous duplicate (two requests with the same new id arriving together, both missing the pre-check) results in exactly one execution and one counted attempt: one reservation wins; the other releases its attempt and returns the receipt, or is refused 429 by the concurrent limit and succeeds on retry via the pre-check. It can never produce an uncounted execution.

## Scope

- Wire the flow above into `POST /chat`, conversation turn creation and turn streaming. Quota logic lives in the service from ticket 05; handlers only call it.
- Streaming: admission happens in the route function before the stream is built, so the refusal is a real 429 (streaming is tool-agent only and answers 409 otherwise). `finish` runs in a `finally` inside the streamed work function, which the stream machinery joins even on disconnect. A client that disconnects before the stream body ever starts leaves the slot held until the lease expires; this is accepted and documented for a single Owner, and tested.
- **Execution timeouts (explicit, validated):** Owner-mode `POST /chat` is wrapped in a new configurable execution timeout (default 180 seconds). On timeout it answers 503 with the existing safe public message (no new status), and the attempt is finished. Conversation turns keep their existing execution bound. Ticket 05's validators relate the lease to both bounds.
- **Input caps in normal mode:** `question` on `POST /chat` is capped at 4000 characters (422, as the conversation endpoints and the demo cap do). Request-body caps by route: 512 KiB for `POST /chat` (the largest legal request is 8 history turns of 8000 characters plus a 4000-character question, under about 170 KiB even with every character escaped), 64 KiB for turn creation and streaming. The existing demo body limit matches only the exact `/chat` path in demo mode; generalize it with a path rule that also matches the turn and stream paths (which contain identifiers) and applies the per-route cap in normal mode, with chunked bodies handled. Demo mode keeps its own cap.
- Replace `test_non_demo_limits_disabled_and_production_errors_safe` with a test that Owner mode is limited, keeping its error-sanitizing assertions. Leave the demo limiter tests (including `test_limiter_expiry_bounded_state_and_non_demo_bypass`) untouched.
- Call `prune()` at a low-frequency, bounded point (for example during admission), not from a new background worker.
- The response for a refusal is a fixed message naming the limit reached (hour, day, concurrent). It never exposes counts of other Owners.

## Out of scope

Dollar accounting; per-user quotas; changing retrieval, grounding, citations or any answering path; the demo limiter and demo mode; the evaluation harness (it calls services directly and is not limited); calibrating values (M1 data, M9 gate); cancelling a turn already running when an account is removed (ticket 03 records it as deferred).

## Inspect

Tickets 04 and 05; `backend/app/api/chat.py`, `conversations.py`; `backend/app/services/conversation_chat_service.py` (submit, `_cleanup`, timeouts); `conversation_repository.py` (`reserve`, replay, `uq_turns_owner_request`); `backend/app/api/chat_stream.py` (`event_stream`); `backend/app/core/public_safety.py`; `backend/app/schemas/chat.py`; `backend/app/core/config.py`; `tests/test_public_safety.py`; `tests/security/test_conversation_chat.py`, `test_conversation_api.py`.

## Deliverables

Wiring, timeout, caps, tests; `## Comments` with documentation items for ticket 09 and the M9 gate input (values to recalibrate).

## Needs

Disposable PostgreSQL and Qdrant as `AGENTS.md` describes for the conversation tests. Fake providers only; `OPENAI_API_KEY` unexported.

- [ ] Tests first fail today: with limits set low, the next question still reaches the counting fake provider.
- [ ] Hour, day and concurrent refusals are 429 with their reason and a correct Retry-After header, and the counting fake provider records zero calls, on the tool-agent path (`/chat`, turn creation, streaming) and the linear path (`/chat`, turn creation).
- [ ] One question is one ledger row whatever its internal model calls (a tool-agent run with intent, rewrite, claim check and a citation-correction retry adds one row).
- [ ] Idempotency: a retry or reconnect with the id of a running, completed, failed or timed-out turn adds no ledger row, runs no provider call and is not refused at any limit (hour limit reached, concurrent slot busy).
- [ ] Pre-execution failures (409 busy, 409 version conflict, 404, payload conflict, a reservation error) leave zero ledger rows and a free slot; retrying the same id afterwards is admitted and counted exactly once.
- [ ] Two simultaneous requests with the same new id: exactly one execution and one counted attempt, never an uncounted execution.
- [ ] Two simultaneous questions for one Owner at concurrent limit 1: exactly one runs, the other gets 429, on `/chat`, turns and streaming.
- [ ] Order of checks: a request that fails a precondition evaluated before admission (the 404 and 409 stream-flag checks, 413, 422, conversation not found if checked in step 3) never consumes quota and is not masked by a 429. Busy and version-conflict 409s are raised at reservation, after admission, so they release the attempt and may be masked by 429 at a limit (deliberate).
- [ ] Release placement (boundary = first provider request): an error raised after a provider request began (session expired, not found, cancellation, provider error, timeout, citation authority lost) never releases the attempt; an error raised before it, including after the reservation commit (history loading failure, `emit("accepted")` failure, user resolution failure, cancellation before the first request), always releases it and leaves zero counted rows. Zero-call routes (conversation-history recall on the linear path, file-target not found) leave zero counted rows with a 200 answer.
- [ ] The marker is installed inside `submit` / `run()` and `/chat`: a streaming question whose provider call happens in a child task is still counted; a tool-agent run with SDK retries counts once. A `submit` with no attempt whose reservation creates a new turn aborts with 503 and makes no provider call.
- [ ] Orphan row (admission committed, then the process or task dies before reservation): the same Owner's retry is refused 429 with a Retry-After until the lease expires, then admitted and counted once; this is documented residual behavior.
- [ ] A cancelled non-stream `/chat` or turn still releases or finishes its attempt (shielded cleanup).
- [ ] A provider error, a timeout, a cancellation and a client disconnect mid-stream each free the concurrency slot and still count; a disconnect before the stream body starts holds the slot only until the lease (injected clock).
- [ ] `/chat` exceeding its execution timeout (a fake that sleeps past it) answers 503 through an explicit `TimeoutError` mapping (not a 500), finishes the attempt and frees the slot; the lease validation rejects a lease shorter than the chat or turn bound plus the margin.
- [ ] A failing `finish` does not change the response status or body; a lock timeout or database error on admission answers 503 (not 429) and makes no provider call.
- [ ] Counts survive building a new application instance on the same database; Owner A's usage does not change Owner B's allowance.
- [ ] A 4001-character question on `/chat` is 422; an over-cap body is rejected before parsing on each of the three routes, including chunked; a maximum legal `/chat` request and a maximum legal turn request are accepted.
- [ ] Demo mode is unchanged: the existing demo limiter, body-limit and budget tests pass unmodified; the evaluation harness tests show no limit applied.
- [ ] No public path or success-response schema changes; no existing test needs more than the defaults or a manual reset. Static checks no worse than the baseline.

## Comments

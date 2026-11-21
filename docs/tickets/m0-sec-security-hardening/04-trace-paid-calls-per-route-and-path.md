# 04: Trace every paid provider call per route and answering path

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A written, evidence-backed table of which requests can cause a paid provider call, how many, on which answering path, and where a per-Owner check can sit before any paid call and before any state is written. It settles the open item of Owner decision D4-2 (the legacy linear path and `POST /chat` without a conversation were never traced) and tells tickets 05 and 06 where admission sits. It also gives M1 the list of counters to measure.
**Blocked by:** None (can start immediately).
**Status:** ready-for-agent
**Progress:** findings written and committed locally (2026-11-21); two read-only reviews (standards; spec/correctness/security) addressed; not pushed

## Scope

- Routes: `POST /chat`; conversation turn creation; conversation turn streaming; any other route that can reach a provider (check `POST /index/build` embeddings and any intent or rewrite call).
- Paths: tool agent (hosted, Owner-reported); legacy linear; legacy LangGraph (one line each; LangGraph only where it differs).
- For each route and path, from reading the code: the provider calls made (chat model, embedding, intent gate, follow-up rewrite, claim check, citation-correction retry), the minimum and the maximum count per question, and the count for (a) a normal question with evidence, (b) an Owner with an empty corpus, (c) a chitchat question, (d) a provider failure partway.
- Where a check can sit for each entry point so that a refused request makes no provider call, leaves no running turn and writes no query history. Note for the analysis: a replayed turn submission is only recognized inside the reservation step, which already stores the turn and its question in one transaction, and the streaming route answers 200 before the submission runs (a 429 is only possible in the route function, before the stream is built; streaming is tool-agent only and answers 409 otherwise). The design is decided in the spec (section C): the turn table, not the quota ledger, is the authority on replay. Ticket 06 reads the turn table for (Owner, client request id) before admission; admission rows carry server-generated attempt ids and are released if the reservation step fails or reports a duplicate. This ticket verifies the facts that design relies on: the scope and uniqueness of a turn's client request identifier (the existing per-Owner unique constraint), what a stream reconnection sends, what a retry of a completed, failed, interrupted or timed-out turn with the same id returns (expected: the stored row, no execution; a new attempt needs a new id), every exception the reservation step can raise after the point where admission would have happened, and the real execution bounds (generation timeout, execution seconds, cleanup and publication time outside them, and the absence of a timeout on `POST /chat`). Report anything that contradicts the design before ticket 05 starts.
- Whether any route outside those can cost money without being covered by an existing bound (indexing is bounded by one unresolved job per account; state what that does and does not limit).
- Where a count is easy to verify with a fake provider, add a deterministic test that counts calls; where it is not, state why and rely on code evidence. No placeholder tests.

## Out of scope

Any quota or limiter code (tickets 05 and 06). Measuring real dollar cost (M1). Changing any path. Any paid or live call.

## Inspect

`docs/tickets/m0-system-audit/04-auth-and-access-control-audit.md` ("Sign-up gate", section 7); `docs/tickets/m0-system-audit/05-rag-paths-and-flags.md`; `backend/app/api/chat.py`, `conversations.py`; `backend/app/services/rag_service.py`, `conversation_chat_service.py`; `backend/app/agents/tool_rag/` (graph, claim check, intent gate); `backend/app/llm/`; `backend/app/embeddings/`.

## Deliverables

`## Findings` in this ticket with the table, the placement analysis and the list of counters for M1.

## Needs

No paid API, no key, no network. `OPENAI_API_KEY` unexported.

- [x] The table covers every route and path listed in Scope, labelled Verified, Unverified or Defect with an evidence type and a pointer (file and symbol, or test name).
- [x] For a new turn, a replay of a running turn, a replay of a completed turn, a retry of a failed or timed-out turn with the same id, a simultaneous duplicate and a stream reconnection, the table states how the turn table classifies it, whether admission happens, whether a provider call can occur, and the response.
- [x] Every exception `reserve` can raise is listed with its status, so ticket 06's release-on-failure covers all of them.
- [x] The execution bounds are tabulated with file and symbol, and the minimum safe lease derived from them is stated.
- [x] Internal model calls (intent, rewrite, claim check, citation correction) are shown to sit inside one admitted attempt, so they are not counted separately.
- [x] Each entry point has one named placement for a per-Owner check, with the reason it runs before any provider call and before state is written, and the reason a replay is or is not charged.
- [x] The empty-corpus case is answered for the tool-agent path and for the linear path.
- [x] The routes that cannot be reached by a signed-in Owner without a paid call, and those that can, are stated separately.
- [x] Any added test is deterministic, uses fakes, and fails if the counted behavior changes.
- [x] No application code changed (`git diff -- backend/app` is empty).
- [x] The list of counters M1 must record (per path: calls and tokens per question) is written down.

## Findings

Method: read the code named in each row; counts for the tool agent and the legacy paths are pinned by `backend/tests/test_paid_call_counts.py` (18 deterministic tests, fakes only, no network, database or key). Labels: **Verified** (code read plus a test that fails if the count changes), **Verified (code)** (code read, no count test), **Existing test** (a PostgreSQL-backed test already in the repo that was read but **not re-run** here, because it needs the disposable containers), **Unverified**, **Defect**. No application file changed (`git diff -- backend/app` is empty).

### 1. Routes that can cost money, and routes that cannot

| Route | Paid provider call? | Bound today | Label |
| --- | --- | --- | --- |
| `POST /api/v1/chat` | yes (chat, embedding) | none except the path's own (section 2) | Verified |
| `POST /conversations/{id}/turns` | yes | `generation_timeout` 120 s, durable deadline 180 s | Verified (code) |
| `POST /conversations/{id}/turns/stream` | yes, tool agent only (409 otherwise, 404 if streaming flag off) | as turns | Verified (code) |
| `POST /index/build` | yes (embeddings only) | one unresolved job per Owner | Verified (code) |
| `POST /index/sync`, `/ingest`, `/chunk` | no OpenAI call (Drive API and local Tesseract only) | same job rule | Verified (code) |
| All other routes: auth, `/files`, `/sources`, conversation create/list/detail/rename/delete, turn status, `/interrupt`, `/index/status`, health | no | n/a | Verified (code; a grep of `app/` for provider clients finds only the modules in sections 2 and 6) |
| Operator CLIs `app/ops/indexing_recovery.py`, `app/demo/load.py` | yes (embeddings) | not HTTP; run by the operator | Verified (code) |

So a signed-in Owner can reach a paid call through exactly four routes (`/chat`, turn creation, turn streaming, `/index/build`); every other route is free of provider cost. Demo mode has its own in-process limiter (`DemoChatLimits`); in Owner mode `DemoChatLimits.execution` yields immediately, so it is no protection and no timeout.

### 2. Paid calls per answering path

"Chat" = one chat-completion request; "Emb" = one embedding request (one query string, so one request). The tool-agent and legacy paths are the same on `/chat` and on turns; only the persistence differs (`/chat` writes `QueryHistory` inside `RagService`; turns write it at publication).

| Path | Calls inside one question | (a) normal, evidence | (b) empty corpus | (c) chitchat | (d) provider failure partway | Label |
| --- | --- | --- | --- | --- | --- | --- |
| **Tool agent** (`ToolAgentAdapter.answer`) | intent gate (1 chat, skipped if question > 300 chars or demo); agent steps (1 chat each, at most `MAX_AGENT_CYCLES` = 6, includes the one citation-correction step); each executed `search_knowledge` or query-focused `file_evidence` = 1 Emb (via `VectorRetriever`); claim check (1 chat per finalization when evidence exists, `claim_check_enabled` default true, `gpt-5.4-mini`); at most 8 tool calls per step, executed one after another, in cycles 1-5 only | intent 1 + steps 2 + claim 1 = **4 chat + 1 Emb** | intent 1 + steps 2 (search, answer) = **3 chat + 1 Emb** if the model chooses to search; **2 chat + 0 Emb** if it answers without searching. Claim check not run (no evidence) | **1 chat, 0 Emb** (gate returns server text) | calls already made stay spent; no in-app retry. Test: intent 1, steps 2 (second fails), 1 Emb, claim 0 → `ChatError` → 503 | Verified (tests; one `retrieve` call is one embedding request by code reading of `HybridRetriever` → `VectorRetriever._retrieve`, and the linear and empty-corpus tests count `embed_texts` directly) |
| min / max | min **1** chat (greeting) · max **1 + 6 + 2 = 9 chat** (intent, 6 steps, 2 claim checks when a citation correction happens) and **40 Emb** (5 cycles × 8 searches per step); the sixth step's tool calls are never run (returns the cycle-limit message as a normal answer, which is persisted) | | | | | Verified (tests) |
| **Legacy linear** (`RagService._ask_normalized`, `AGENT_GRAPH_ENABLED` off) | follow-up rewrite (only with history and a reference word, 1 chat, 2 if the rewrite copies the question); 1 Emb for the query (`VectorRetriever`; hybrid adds free keyword and metadata retrievers); 1 chat to generate, 2 if the first answer lacks valid `[n]` markers, then `ChatCitationValidationError` | **1 Emb + 1 chat** (+1 or +2 chat for a rewrite) | **1 Emb + 0 chat** (embeds before it finds nothing; answers the fixed no-evidence text) | **1 chat, 0 Emb** | after the Emb, a generation failure keeps the Emb: 1 Emb + 1 chat spent, then error | Verified (tests) |
| min / max | min **0** (conversation-history recall, file-target not found or not indexed, empty collection summary: deterministic, no provider) · max **1 Emb + 2 rewrite + 2 generate = 5 requests**; inventory and collection routes: 1 chat (2 with the citation retry) | | | | | Verified (code + tests; the zero-call routes by `test_explicit_history_recall_bypasses_document_pipeline_and_providers`) |
| **Legacy LangGraph** (`AGENT_GRAPH_ENABLED`, grounded route only; differs from linear) | each retrieval round embeds; up to `AGENT_MAX_REWRITE_ATTEMPTS` (2) rewrite rounds, each 1 chat from a **separate** `AsyncOpenAI` client in `nodes._rewrite_with_openai` (only when `OPENAI_API_KEY` is set), then the same generation | 1 Emb + 1-2 chat (more if the first evidence grade fails: up to 3 Emb + 2 rewrite chat + generation) | **3 Emb + 2 rewrite chat + 0 generation** | same as linear | as linear | Verified (test for the empty corpus). Max for M1: the follow-up rewrite in `RagService.ask` runs before routing on this path too, so worst case is 3 Emb + 2 graph rewrites + 2 follow-up rewrites + up to 2 generations = 9 requests; min 0 (zero-call routes) |

Internal calls sit inside one admitted attempt: the intent gate, claim check and citation-correction step run inside `ToolAgentAdapter.answer` / `ToolRagAgentService`, the follow-up rewrite and citation retry inside `RagService.ask` / `OpenAIChatService`, so they need no separate admission; one admitted attempt is one unit regardless of these counts (spec section C holds).

**Not visible in these counts (important for M1):** the OpenAI SDK retries non-streaming requests by default (`DEFAULT_MAX_RETRIES` = 2 in the installed SDK 2.44.0) with a default read timeout of 600 s (`DEFAULT_TIMEOUT`). `OpenAIAgentChatService.step` and the embedding and legacy chat services use those defaults; only `stream_step` sets `max_retries=0`. Whether a retried request that failed is billed is **Unverified** (would need provider documentation; not stated from memory).

**Empty-corpus answer.** Tool agent: no deterministic short-circuit; cost depends on the model, 2 chat (no search) or 3 chat + 1 Emb (search). Linear: always 1 Emb, 0 chat. LangGraph: 3 Emb + 2 chat. In all three, an Owner with nothing indexed can still cause paid calls, so the quota must not assume an empty corpus is free.

**Questions that cost nothing but would be admitted.** Legacy conversation-history recall, file-target "not found / not indexed", empty collection summary make no provider call, yet admission happens before routing, so each would count as one unit. This only over-counts (safe) and is what the spec's "one admitted request" implies; recorded so ticket 06 does not try to classify before admitting.

### 3. Replay and idempotency (turn table), from the code

Identifier scope: `client_request_id` is unique per Owner (`uq_turns_owner_request` on `(owner_id, client_request_id)`), not per conversation. `reserve` first locks the conversation (`FOR UPDATE`, owner-scoped, not deleted), then looks up the Owner's row for that id, then compares `payload_hash` (which includes conversation id, normalized question, operation and `expected_content_version`). Only `operation = ASK` is reachable from a route (the only caller of `reserve` is `ConversationChatService.submit`), so there is no retry or regenerate operation; a new attempt is a new `client_request_id`. Frontend: it sends a fresh `crypto.randomUUID()` per question and, when the outcome is unknown, re-POSTs the exact original body (`reconcileSubmission`) or polls `GET .../turns/{id}`; there is no stream-resume endpoint, so a "stream reconnection" is a re-POST of the same id.

| Situation | Turn-table classification | Admission? | Provider call? | Response | Label |
| --- | --- | --- | --- | --- | --- |
| New turn | no row for (Owner, id) | yes | yes | 200 (completed) or 503 (failed/interrupted/timeout) | Verified (code); Existing test `test_success_atomic_original_question_replay_detail_and_private` |
| Replay of a running turn | row, same hash, status RUNNING | no | no | **202**, `replayed: true`, `Location` | Existing test `test_concurrent_replay_conflict_busy_and_foreign_reads` |
| Replay of a completed turn | row, same hash, COMPLETED | no | no | 200, stored turn and answer; stream: event `complete` | Verified (code); Existing test `test_success_atomic_...` |
| Retry of a failed, interrupted or timed-out turn, same id | row, same hash, FAILED/INTERRUPTED | no | no | **200** with `turn.status` FAILED/INTERRUPTED and `replayed: true` (not a 503); stream: event `receipt` | Existing test `test_failed_replay_and_live_interruption_cannot_regenerate` (also asserts one model call in total) |
| Same id, different payload (question, version, conversation) | row, hash differs | no | no | 409 (`ConversationConflict`) | Existing test (same file, changed question → 409) |
| Simultaneous duplicate | both read no row; the `FOR UPDATE` lock on the conversation row serializes `reserve`: the second waits for the first to commit, then its first lookup finds the row and returns it as a replay (`ON CONFLICT DO NOTHING` is reached only when the same id is used on a different conversation, which ends in 409). A waiter that hits `lock_timeout` (2 s) gets 503 | see mismatch M3 | no (at most one execution) | 202 for the loser | Verified (code) |
| Stream reconnection | not a distinct case: a new POST with the same id → replay row above | no | no | `receipt` or `complete` event, `http_status` 202/200 | Existing test `test_replay_does_not_repeat_generation_or_retrieval` (mocked service) |
| Same id on a deleted or foreign conversation | `_lock` raises first | no | no | 404 | Verified (code) |

Replay precedence inside `reserve`: not found (404) → replay or payload conflict (409) → busy (409) → version conflict (409) → session row missing (404) → insert. So a replay of an old id still returns the stored row even when the conversation has since moved on (the busy and version checks come after the replay check).

### 4. Every exception the reservation step can raise (for ticket 06's release)

The submit path opens `ConversationService.transaction(write=True)`, then `reserve`, then `_status`, then commits. Admission would sit before this, so the release must cover all of:

| Raised where | Exception | Route status | Paid call made? |
| --- | --- | --- | --- |
| `SET LOCAL` / any statement | `SQLAlchemyError` (lock timeout 2 s, statement timeout 10 s, `IntegrityError` on `uq_turns_running_conversation` or `uq_turns_conversation_sequence`, connection loss) | 503 | no |
| `_live_session(lock=True)` and the fresh `_live_session(lock=False)` just before commit | `ConversationSessionExpired` | 401 (stream: `error` event with `code: SESSION_EXPIRED`) | no; the second check runs **after** the turn row was flushed, then rolls back |
| `_lock`, missing application session, missing source turn | `ConversationNotFound` | 404 | no |
| payload mismatch | `ConversationConflict` | 409 | no |
| second running turn in the conversation | `ConversationBusy` | 409 | no |
| stale `expected_content_version` | `ConversationVersionConflict` | 409 | no |
| invalid inputs | `ValueError` | 503 (generic handler) | no; not reachable from the schema (question is stripped and non-blank) |
| `_database_now` / `clock_timestamp` unavailable | `RuntimeError` | 503 | no |
| `db.commit()` failure | `SQLAlchemyError` | 503 | no; the commit outcome can be uncertain (a committed RUNNING row can exist while the caller sees an error) |
| cancellation (client disconnect) | `asyncio.CancelledError` (a `BaseException`, rolled back by `transaction`) | none | no |

All of these happen before any provider call, so releasing the admission row on any exception out of this block is correct. A replay returns normally (not an exception): the code path returns `(response, 202|200)` before the generation block, so ticket 06 must release on `reserved.replayed` too. In the streaming route the same exceptions occur **after** the 200 was sent: they surface only as a generic stream `error` event (or the `SESSION_EXPIRED` event), never as 404/409/401 (verified from `event_stream.produce`). The release must therefore live inside `run()` / `submit`, not in the route's exception handling.

**Rule for ticket 06: release only for exceptions raised before `transaction()` exits normally, and for a replay return. Everything after that is a finish, never a release.** Exits after the reservation commit, all of which are finishes:

| Exit after commit | Result | Notes |
| --- | --- | --- |
| provider error, `ChatError`, other `Exception` in generation or publication, `CitationAuthorityLost` | `_cleanup` then 503 (turn FAILED) | counted |
| `TimeoutError` (generation window) | `_cleanup` (INTERRUPTED) then 503 | counted |
| `ConversationSessionExpired`, `ConversationNotFound` | `_cleanup`, then **re-raised**: 401 / 404 (stream: `SESSION_EXPIRED` or generic `error` event) | can occur after paid work; counted |
| `asyncio.CancelledError` (disconnect) | `_cleanup`, re-raised | counted |
| final observation block (`_live_session`, `_status`) | 401 / 404 / 503 | after paid work; counted |
| `ConversationExecutionLost` | `_cleanup` (EXPIRED) then 503 | counted |

Spec ambiguity to settle in ticket 05/06: failures after the commit but before any provider call (`emit("accepted")` failing, `_context` / `SET LOCAL` failing at stage `history_loading`) fall under "release allowed only until the reservation commits" (so counted) but also under "fails before paid execution starts is not counted". These Findings assume the first reading (counted, finish not release): the turn row exists, so the attempt is no longer a pure refusal. Also: `ValueError` from `reserve` input checks is raised before the replay lookup, and `_status` can raise inside the submit transaction (`ConversationNotFound`, validation errors giving 503).

### 5. Execution bounds and the minimum safe lease

| Bound | Value | Where |
| --- | --- | --- |
| Reservation transaction | `lock_timeout` 2 s and `statement_timeout` 10 s **per statement**; no total bound | `ConversationService.transaction` |
| Generation window (history load + `rag.ask`) | 120 s (`generation_timeout`, constructor-validated to ≤ 120) | `ConversationChatService.__init__`, `submit` |
| Tool-agent window (gate + agent + claim check) | 120 s, then up to 2 × 5 s to close clients, outside the 120 s | `TOOL_AGENT_TIMEOUT_SECONDS`, `ToolAgentAdapter.answer` |
| Inner timeouts | intent gate 10 s, claim check 20 s each | `CLASSIFY_TIMEOUT_SECONDS`, `CLAIM_CHECK_TIMEOUT_SECONDS` |
| Durable turn deadline | 180 s from reservation (`execution_seconds`, ≤ 600): after it, publication is refused (`ConversationExecutionLost`) and the turn can be interrupted | `reserve`, `_execution` |
| Publication transaction | per-statement 2 s / 10 s, no total bound | `submit` (`result_publication`) |
| Cleanup | 10 s | `_cleanup` |
| `POST /chat`, tool agent | the 120 s tool-agent window above, plus the dependency and `QueryHistory` commit | `ToolAgentAdapter` |
| `POST /chat`, legacy linear / LangGraph | **none** (only the SDK's per-request 600 s read timeout, with 2 retries, for up to 5 requests) | `chat.py` calls `limits.execution`, a no-op outside demo mode |

Derivation: paid work ends at most 120 s (+ up to 10 s client close) after the generation starts, and the durable deadline bounds publication at 180 s after reservation; the lease starts at admission, before reservation, and the finish runs after publication and cleanup. The spec's rule (lease > max(bounds) + 60 s) gives **a minimum lease of at least 240 s** for turns (max(120, 180) + 60). For `POST /chat`, ticket 06 must add an execution timeout; if it is at most 120 s the same 240 s lease holds. Recommended default lease: 300 s, so a limit change of 60 s in either bound does not need a lease change (recommendation only; ticket 05 decides).

### 6. Indexing (`POST /index/build`)

The only other provider cost. `uq_indexing_jobs_unresolved_owner` allows one QUEUED/RUNNING or recovery-required job per Owner across all four operations. It **does** stop a second job running at once. It does **not** limit: how many jobs run in a day (a new build can start the moment the last resolves); the size of one job (all pending chunks of all indexed-eligible documents, embedded in batches of 100 with no total cap); or repeated cost on failure (a file whose embedding succeeded but whose vector write failed is re-embedded on the next build). Unchanged chunks are skipped by stored hash, so re-running a build on unchanged content embeds nothing (`IndexingService._index_document`). This is Owner-initiated and outside M0-SEC's quota (spec section C covers questions only); recorded for M1 and the M9 spending-safeguard check.

### 7. Placement, one per entry point

Order everywhere: authentication and CSRF (turns and streaming; `POST /chat` uses `require_resource_user`, which has no Origin or CSRF check until ticket 08) → body and schema validation → replay read → admission (own short session, committed) → existing preconditions and reservation → paid work → finish in a `finally`.

| Entry point | Placement | Why a refusal makes no paid call, leaves no running turn and writes no history | Replay |
| --- | --- | --- | --- |
| `POST /chat` (Owner mode only: `require_resource_user` returns the synthetic user in demo mode, which keeps `DemoChatLimits`; no admission there) | in `ask_grounded_question`, after `require_resource_user` and `ChatRequest` validation, before `service.ask`, with the new execution timeout around `ask`; release/finish in `finally` | nothing is written before `ask`; `get_rag_service` only builds objects (no I/O) | none: each request is a new attempt |
| `POST .../turns` | in `submit_conversation_turn` / `ConversationChatService.submit`, after `require_conversation_mutation`, before `transaction`/`reserve`; read the Owner's row for the `client_request_id` first | admission commits before `reserve`, so a refusal leaves no turn and no query history; release on any exception in section 4 and on replay | a found row skips admission and is not charged |
| `POST .../turns/stream` | in `stream_conversation_turn` (the route function), after the two config checks and before `StreamingResponse` is built; release/finish inside `run()` | only before the response starts can a real 429 be returned | as turns |
| `POST /index/build` | out of M0-SEC scope | n/a | n/a |

### 8. Mismatches and details ticket 05/06 must account for

- **M1 (not a contradiction, a precision): `POST /chat` is bounded on the tool-agent path.** The spec says `/chat` "has no timeout"; that is true of the legacy path only. The tool agent applies its 120 s window on `/chat` too. On turns the outer 120 s generation window starts earlier (it includes history loading), so it fires before the inner tool-agent window; the inner window is the active bound only on `/chat`. Ticket 06's timeout must be applied at the route so it also covers legacy and LangGraph.
- **M2: the bounds the lease must exceed are not settings.** `generation_timeout` (120) and `execution_seconds` (180) are constructor defaults of `ConversationChatService`, built without settings in `get_conversation_chat_service`; `TOOL_AGENT_TIMEOUT_SECONDS` is a module constant. The spec says "configuration validation rejects any violation", which is impossible against values that are not configuration. Ticket 05 must either move them into `Settings` or validate the lease against the module constants (importing them), and say which.
- **M3: simultaneous duplicate outcome.** Spec section C says a simultaneous duplicate is admitted, then released when `reserve` reports it. With 1 concurrent question per Owner, the duplicate arriving in the window between the first request's admission and its reservation commit finds the slot taken and gets **429**, not a 202 receipt (the replay read sees no row yet). It is harmless (no paid call, no count), and the client recovers by re-POSTing the same body. Ticket 06 should either accept this and document it, or retry the replay read once after a busy refusal (decision for ticket 06; do not charge either way).
- **M4: preconditions come after admission in the code.** The spec lists 404/409 preconditions before admission, but busy, version conflict, payload conflict and not found are all discovered inside `reserve`. A request that will fail one of them is therefore admitted, holds the slot briefly, and is released. This matches the spec's "not counted when handled" text; it only means a concurrent legitimate request can see a transient 429 during that window.
- **M5: a replayed or failed turn is returned as 200, not an error.** A FAILED/INTERRUPTED replay is HTTP 200 with a status field; ticket 06 must not treat "200 with replayed" as having consumed admission.
- **M6: streaming error mapping.** After the 200, exceptions become generic stream events. The 429 refusal exists only before the stream starts; a client that disconnects before the body starts never runs `run()`, so the row is released only by lease expiry (already a stated residual risk). A cancelled or crashed process holds the slot until the lease ends.
- **M7: connections (Unverified).** A running turn uses the committed request session, a read session for generation (hybrid retrieval opens scoped sessions per retriever), and later a publication session; admission and release add short extra sessions. The per-turn connection count was not measured; the spec's pool-size check must measure it rather than assume a number.
- **M8: SDK defaults.** The 600 s read timeout and 2 default retries make the per-question maximum above a floor, not a ceiling, for any path without an `asyncio` timeout (legacy `/chat`).
- **No contradiction found** with: Owner-scoped uniqueness of `client_request_id`; replay authority being the turn table; replays and reconnections not executing; internal calls inside one attempt; one attempt id per admission; release before reservation commit being safe.

### 9. Counters M1 must record, per path

Per question: path (tool agent / linear / LangGraph / intent-only / zero-call route); chat calls by purpose (intent, agent step, claim check, follow-up rewrite, graph rewrite, grounded, direct, inventory, file-target, collection, citation-correction regeneration); embedding requests; input and output tokens per call (today only `AgentStepResult.usage` carries tokens, for agent steps; gate, claim check, rewrite and legacy generation record none, and the `rag_execution` log line has steps and tool counts but no embedding or token counts); model name per call (the claim check uses a different model); SDK retries and failed requests; wall time per stage and in total; outcome (completed, no-evidence, cycle-limit, failed, timed out); corpus state (empty or not, chunk count); number of search tool calls per question (0-40).

### 10. Test and check results

- `backend/tests/test_paid_call_counts.py`: 18 passed (`env -u OPENAI_API_KEY uv run pytest tests/test_paid_call_counts.py`), ruff and basedpyright clean for the file. The new tests pin: tool-agent normal 4 chat + 1 Emb, greeting 1 chat, long question skips the gate, empty corpus, failure partway, citation-correction (3 steps, 2 claim checks), the 9-chat maximum (intent, 6 steps, 2 claim checks), worst case (6 steps, 40 searches); linear normal, hybrid-default linear (still 1 embedding), empty corpus, chitchat, follow-up rewrite, failure after the embedding; citation regeneration (2 requests then error, 1 when cited), rewrite (at most 2); LangGraph empty corpus (3 Emb + 2 rewrite requests, no generation).
- Not re-run in this ticket: the PostgreSQL-backed conversation tests cited as "Existing test" (they need the disposable containers); the claims in section 3 that rest on them are labelled accordingly.
- Not measurable without a live provider (stays **Unverified**): dollar cost, token counts, whether failed SDK retries are billed, real latency against the 120 s window.

## Comments

**Owner decision (2026-11-21), quota counting boundary.** Resolves the ambiguity in Findings section 4.
- A question consumes allowance only if paid provider execution began (the first chat or embedding request is about to be issued). Requests rejected in authentication, validation, preconditions, replay handling or turn reservation, and any failure before that first request (including after the reservation commit), are released and not counted.
- Once a provider request began, the attempt counts exactly once even if the provider fails, times out or the user cancels. Internal calls (intent gate, claim check, rewrites, citation correction) and SDK retries are never counted separately.
- Minimal design chosen (no billing system): a request-scoped `PaidExecutionMarker` set by one line at each of five provider-request chokepoints (`OpenAIChatService._complete`, `OpenAIAgentChatService.step` and `stream_step`, `OpenAIEmbeddingService._embed_batch`, graph `_rewrite_with_openai`); one `settle` call at the end finishes the attempt if the marker is set and releases it otherwise. Consequence: zero-call routes (history recall, file-not-found) are never counted, which replaces Findings section 2's note that they would be.
- Carried into tickets 05 (marker, `settle`, chokepoint tests, counting rule) and 06 (release/finish boundary, acceptance tests). Not implemented in this session.


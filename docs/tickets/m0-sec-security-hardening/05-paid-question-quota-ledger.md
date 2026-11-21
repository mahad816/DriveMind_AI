# 05: Persistent paid-question quota: ledger and admission service

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A small PostgreSQL-backed allowance that admits or refuses a paid question per Owner: 20 per rolling hour, 50 per rolling day, 1 concurrent, all configurable and provisional. It is built and tested on its own here; ticket 06 wires it into the routes. The daily limit survives restarts because it lives in the database, with no Redis or other new infrastructure. Owner decisions D4-2 and the 2026-11-21 approval.
**Blocked by:** 04.
**Status:** ready-for-agent
**Progress:** implemented and committed locally (2026-11-21): model, migration `20261121_1200`, settings with validator, `PaidQuestionQuota` service, `PaidExecutionMarker` and the five chokepoint calls, tests; two read-only reviews (standards; spec/correctness/security) found no blocking issues and are addressed; no route wired (ticket 06); not pushed

## Design (decided; the review of 2026-11-21 found the earlier key-based design unsafe)

- **Rows are attempts, not keys.** Each row is one admitted attempt with a server-generated attempt id. There is no client-supplied key and no unique (Owner, key) constraint. Whether a turn submission is a replay is decided from the existing turn table by ticket 06, never from this ledger. A ledger row is not proof that anything executed; it is a reservation that is either confirmed by running (and finished) or released.
- **Operations** (logic in a service module, not in route handlers):
  - `admit(owner)` returns an attempt id or raises `QuotaRefused(reason, retry_after_seconds)` (reason: hour, day or concurrent) or `QuotaUnavailable` (the ledger could not be used).
  - `finish(attempt_id)`: sets the finish time; idempotent; targets only its own row, so a late finish after the lease expired cannot free a later attempt.
  - `release(attempt_id)`: deletes the row. Used whenever the attempt never began paid provider execution (see **Counting rule**), whether it failed before or after the reservation commit.
  - `settle(attempt_id, marker)`: the single end-of-attempt call: `finish` if `marker.started`, otherwise `release`. Ticket 06 calls only this, so a caller cannot release a started attempt or leave an unstarted one counted.
  - `prune()`: deletes finished rows older than `max(retention, 25 hours)` and unfinished rows older than twice the lease. A settings validator rejects a retention below 25 hours so pruning can never shorten the 24-hour window.
- **Admission transaction.** `admit` and `finish`/`release` each use their own short database session (created from the engine, as the conversation service already does for its own sessions), never the request's session, and `admit` commits before it returns, so the reservation is visible to every other request before any reservation of a turn or paid call begins. Inside the transaction: `SET LOCAL lock_timeout` (2 seconds) and `statement_timeout`; take a per-Owner transaction-level advisory lock (keyed on the Owner identifier; do not use `FOR UPDATE` on the users row, which blocks foreign-key checks); count attempts started in the last hour and last day (rolling); look for an unfinished attempt younger than the lease; refuse or insert. The app runs at PostgreSQL's default read-committed isolation, under which "lock, then count, then insert" is correct.
- **Fail closed.** A lock timeout, statement timeout or any database error raises `QuotaUnavailable`, which ticket 06 turns into 503 (never 429, never an admit).
- **Retry-After.** For the hour and day limits: seconds until the limit-th newest attempt in that window ages out. For concurrent: seconds until the blocking attempt's lease would expire (at least 1).
- **Lease and timeouts (validated in configuration).** `lease_seconds` must be at least `max(turn execution bound, chat execution bound) + margin`, margin at least 60 seconds. The lease starts at admission while a turn's deadline starts at reservation, so the margin covers the gap between them (up to 2 seconds waiting for the conversation lock, the reservation commit and session checks), the 10-second cleanup and the result publication and final read that run outside the generation budget. The turn execution bound is the conversation service's execution seconds (180 today, up to 600) and its generation timeout (120, which must stay below the execution bound, the constructor's existing invariant). Today those two are constructor defaults, not settings, so this ticket adds them as settings (`conversation_execution_seconds`, `conversation_generation_timeout`) and passes them where the conversation service is built; the new Owner-mode `/chat` timeout of ticket 06 is a setting too (default 180). One settings validator rejects any configuration that breaks the lease relationship or the existing invariant, so a later change cannot silently let a second paid question start while the first still runs. A crash leaves an unfinished row that stops blocking after the lease.
- **Counting rule (Owner decision of 2026-11-21, ticket 04 Comments).** An attempt counts only if paid provider execution began, meaning the first provider request (chat or embedding) was about to be issued. Rejections in authentication, validation, preconditions, replay handling or turn reservation, and any failure before that first request (history loading, user resolution, a deterministic zero-call route such as conversation-history recall or file-not-found, a cancellation before it), are released and not counted. Once it began, the attempt counts even if the provider fails, times out or the user cancels. Internal model calls, the intent gate, claim check, rewrites, citation-correction retries and SDK retries are one attempt, never several. Between admission and the first provider request the row is held (it blocks the concurrent slot and is counted in the windows until released; this transient over-count is accepted).
- **Paid-execution marker (the minimal reliable design; no per-call accounting).** `PaidExecutionMarker` is a tiny mutable holder (`started: bool`, set once, idempotent) installed in a `ContextVar` for the duration of one attempt; `mark_paid_started()` sets it and is a no-op when no marker is installed (so indexing, the evaluation harness and demo mode are unaffected). A single call is added at each provider-request chokepoint, before the request is sent: `OpenAIChatService._complete`, `OpenAIAgentChatService.step` and `stream_step`, `OpenAIEmbeddingService._embed_batch`, and `agents/drive_graph/nodes._rewrite_with_openai`. The ContextVar holds a reference to the holder, not a flag, because parallel retrievers and graph nodes run in child tasks whose context changes would not reach the parent. Marking before the request means a mid-call timeout or cancellation counts, and SDK retries inside one request cannot add a second count. No call counts, tokens or prices are recorded. A process kill after admission leaves the unfinished row, which counts until the lease expires (already accepted).
- **Schema.** One new table: attempt id, Owner reference (cascade on delete, so it never blocks deleting a user, the KI-033 lesson), start time, finish time (nullable); index on (Owner, start time). One Alembic revision on the single current head, with a downgrade. This is the only schema change in M0-SEC.
- **Settings** (documented beside the code): hour limit (20), day limit (50), concurrent limit (1), lease seconds, retention. State that the values are provisional and unmeasured, that a count is not a dollar amount or a count of provider calls, that windows are rolling, and the multi-replica checklist: admission is correct across processes because it relies on PostgreSQL; before running more than one worker or replica re-check the lease against the execution bounds, the connection pool size (admit, finish and release each take a pooled connection beside the request's own, so the single-worker pool must hold both under concurrent load; a test runs an admission while a request session is open), and that the login-start counter of ticket 07 is process-local.
- The clock is injectable for tests.

## Out of scope

Routes, input caps and any user-visible behavior (ticket 06); dollar accounting, price tables, per-model counts, per-user overrides or quota screens (future requirement); Redis; the login-start limit (ticket 07); the demo limiter.

## Inspect

Ticket 04 `## Findings`; `backend/app/db/session.py` (default isolation); `backend/app/services/conversation_chat_service.py` (own-session pattern, `_cleanup`, timeouts); `backend/app/services/conversation_service.py` (`lock_timeout` and `statement_timeout` usage); `backend/app/db/models/`; `backend/alembic/versions/` (head `20261120_1200`); `backend/app/core/config.py`; `tests/security/conftest.py`; `tests/security/test_conversation_deletion_privacy.py` (cascade guard over per-Owner tables, which must include the new table).

## Deliverables

Model, migration, service, settings with validators, tests; `## Comments` with the retention and Delete-stored-data note for M7 and documentation items for ticket 09.

## Needs

Disposable PostgreSQL. No Qdrant, no provider, no network.

- [ ] Tests first: each case below fails for the stated reason before it is made to pass.
- [ ] With limits 20/50/1 and an injected clock: the 21st admission in an hour, the 51st in a day and a second admission while one is unfinished are refused with the correct reason; the same attempts spread beyond the window are admitted.
- [ ] Retry-After values are correct for each reason (hour, day, concurrent) and at least 1.
- [ ] Real concurrency from separate database sessions: N simultaneous admissions for one Owner at concurrent limit 1 admit exactly one; N simultaneous admissions across the hour limit never exceed it; the admitted reservation is visible to a fresh session immediately after `admit` returns.
- [ ] Lock timeout: with the Owner's advisory lock held by another session, `admit` raises `QuotaUnavailable` within about the lock timeout and inserts nothing.
- [ ] Fault injection: a database error during admit gives `QuotaUnavailable`, never an admit.
- [ ] Restart: counts are identical through a brand-new service and engine instance after admissions made by an old one.
- [ ] Marker: `settle` finishes (keeps counting) when the marker was set and releases when it was not; a marker set from a child task (`asyncio.gather` / `ensure_future`, as `gather_owned` does) is seen by the parent; `mark_paid_started()` without an installed marker is a harmless no-op; it is idempotent.
- [ ] Chokepoints, with fake clients and no network: each of the five provider-request chokepoints sets the marker before the request is sent, including when the request then raises or is cancelled; an SDK-level retry (fake client failing then succeeding) still yields one started marker and one counted attempt; a question whose deterministic route makes no provider call (conversation-history recall, file-target not found) leaves the marker unset. One test per chokepoint fails if its marker call is removed.
- [ ] `release` deletes the row and frees the slot and the hour and day counts; `finish` frees only the concurrent slot and the attempt still counts; both are idempotent and target only their own id.
- [ ] Lease: an unfinished attempt older than the lease no longer blocks, one younger does; a late `finish` of an expired attempt does not free a later attempt's slot.
- [ ] Config validation: lease below `max(execution bounds) + 60 s` is rejected, as is a generation timeout not below the execution bound or above 600, retention below 25 hours is rejected; the defaults are accepted.
- [ ] Prune removes only finished rows older than the retention and unfinished rows older than twice the lease, never a live attempt; the 24-hour count is unaffected by pruning.
- [ ] Owner A at a limit does not change Owner B's admission.
- [ ] Deleting an Owner who has ledger rows succeeds; the cascade-guard test includes the table. Alembic upgrade and downgrade both run; single head.
- [ ] No route, API response schema or existing test changes; the only edits to provider modules are the one-line marker calls, with unchanged behavior and call counts (`tests/test_paid_call_counts.py` still passes). Static checks no worse than the baseline (clean on `app`, 48 baseline errors in `tests/`).

## Comments

**Where things are.** `app/core/paid_execution.py` (marker), `app/services/paid_question_quota.py` (`admit`, `finish`, `release`, `settle`, `prune`), `app/db/models/paid_question_attempt.py`, settings in `app/core/config.py`. Tests: `tests/test_paid_execution_marker.py`, `tests/test_paid_question_settings.py`, `tests/security/test_paid_question_quota.py`.

**Decisions taken while building.**
- `chat_execution_seconds` (default 180) is added now because the lease validator must relate to it; nothing reads it until ticket 06.
- `ConversationChatService` is now built with `conversation_generation_timeout` and `conversation_execution_seconds` from settings (same defaults 120 and 180).
- When several limits refuse at once, the one that clears last is reported (waiting less cannot help).
- Timestamps come from the application clock (injectable), not the database; this is why the multi-replica checklist includes clock agreement.
- `settle` shields the cleanup, bounds it to 10 s, logs failures by exception category and swallows them; on caller cancellation it waits for the cleanup, then re-raises.
- `install_marker` tolerates being closed from another context (a torn-down stream): the reset error is swallowed so it cannot replace the original exit or skip `settle`.
- `tests/security/test_alembic_url_credentials.py` asserts the new head; `conftest.py` applies the new revision; the cascade guard in `test_conversation_deletion_privacy.py` includes the table.

**For ticket 06 (carry-over from the reviews).**
- Call `prune()` at a bounded point (a failed `release` leaves an unstarted row counted in the hour and day windows until prune removes it at twice the lease).
- `admit` is not shielded: a cancellation at the instant of commit can leave a committed row whose id the caller never receives. It blocks the slot until the lease and is pruned later; accepted, like a crash orphan, and worth one test in 06.
- A crashed attempt that had started paid execution stops counting in the windows once pruned (2x lease). This is the specified behaviour.
- No test yet for the "file-target not found" zero-call route; only conversation-history recall is covered. Add it in 06 where the full path is exercised.

**M7 / Delete-stored-data note.** The ledger holds Owner id and timestamps only (no question text). Finished rows are kept at least 25 hours, then pruned; deleting a user cascades to its rows. A future "delete my data" feature must include this table.

**For ticket 09 documentation.** Settings `PAID_QUESTION_HOUR_LIMIT`, `_DAY_LIMIT`, `_CONCURRENT_LIMIT`, `_LEASE_SECONDS`, `_RETENTION_HOURS`, `CONVERSATION_EXECUTION_SECONDS`, `CONVERSATION_GENERATION_TIMEOUT`, `CHAT_EXECUTION_SECONDS` are not yet in `.env.example`. Values are provisional (M9 recalibration). Multi-replica checklist is in the `config.py` comment.

# 05: Persistent paid-question quota: ledger and admission service

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A small PostgreSQL-backed allowance that admits or refuses a paid question per Owner: 20 per rolling hour, 50 per rolling day, 1 concurrent, all configurable and provisional. It is built and tested on its own here; ticket 06 wires it into the routes. The daily limit survives restarts because it lives in the database, with no Redis or other new infrastructure. Owner decisions D4-2 and the 2026-11-21 approval.
**Blocked by:** 04.
**Status:** ready-for-agent
**Progress:** open

## Design (decided; the review of 2026-11-21 found the earlier key-based design unsafe)

- **Rows are attempts, not keys.** Each row is one admitted attempt with a server-generated attempt id. There is no client-supplied key and no unique (Owner, key) constraint. Whether a turn submission is a replay is decided from the existing turn table by ticket 06, never from this ledger. A ledger row is not proof that anything executed; it is a reservation that is either confirmed by running (and finished) or released.
- **Operations** (logic in a service module, not in route handlers):
  - `admit(owner)` returns an attempt id or raises `QuotaRefused(reason, retry_after_seconds)` (reason: hour, day or concurrent) or `QuotaUnavailable` (the ledger could not be used).
  - `finish(attempt_id)`: sets the finish time; idempotent; targets only its own row, so a late finish after the lease expired cannot free a later attempt.
  - `release(attempt_id)`: deletes the row. Used only when the attempt never reached paid execution, that is, before the reservation commit (ticket 06 defines the boundary exactly and where it runs).
  - `prune()`: deletes finished rows older than `max(retention, 25 hours)` and unfinished rows older than twice the lease. A settings validator rejects a retention below 25 hours so pruning can never shorten the 24-hour window.
- **Admission transaction.** `admit` and `finish`/`release` each use their own short database session (created from the engine, as the conversation service already does for its own sessions), never the request's session, and `admit` commits before it returns, so the reservation is visible to every other request before any reservation of a turn or paid call begins. Inside the transaction: `SET LOCAL lock_timeout` (2 seconds) and `statement_timeout`; take a per-Owner transaction-level advisory lock (keyed on the Owner identifier; do not use `FOR UPDATE` on the users row, which blocks foreign-key checks); count attempts started in the last hour and last day (rolling); look for an unfinished attempt younger than the lease; refuse or insert. The app runs at PostgreSQL's default read-committed isolation, under which "lock, then count, then insert" is correct.
- **Fail closed.** A lock timeout, statement timeout or any database error raises `QuotaUnavailable`, which ticket 06 turns into 503 (never 429, never an admit).
- **Retry-After.** For the hour and day limits: seconds until the limit-th newest attempt in that window ages out. For concurrent: seconds until the blocking attempt's lease would expire (at least 1).
- **Lease and timeouts (validated in configuration).** `lease_seconds` must be at least `max(turn execution bound, chat execution bound) + margin`, margin at least 60 seconds. The lease starts at admission while a turn's deadline starts at reservation, so the margin covers the gap between them (up to 2 seconds waiting for the conversation lock, the reservation commit and session checks), the 10-second cleanup and the result publication and final read that run outside the generation budget. The turn execution bound is the conversation service's execution seconds (180 today, up to 600) and its generation timeout (120, which must stay below the execution bound, the constructor's existing invariant). Today those two are constructor defaults, not settings, so this ticket adds them as settings (`conversation_execution_seconds`, `conversation_generation_timeout`) and passes them where the conversation service is built; the new Owner-mode `/chat` timeout of ticket 06 is a setting too (default 180). One settings validator rejects any configuration that breaks the lease relationship or the existing invariant, so a later change cannot silently let a second paid question start while the first still runs. A crash leaves an unfinished row that stops blocking after the lease.
- **Counting rule.** An attempt counts from admission. It keeps counting after provider errors, timeouts, cancellations and disconnects once paid execution may have started. Only `release` removes it.
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
- [ ] `release` deletes the row and frees the slot and the hour and day counts; `finish` frees only the concurrent slot and the attempt still counts; both are idempotent and target only their own id.
- [ ] Lease: an unfinished attempt older than the lease no longer blocks, one younger does; a late `finish` of an expired attempt does not free a later attempt's slot.
- [ ] Config validation: lease below `max(execution bounds) + 60 s` is rejected, as is a generation timeout not below the execution bound or above 600, retention below 25 hours is rejected; the defaults are accepted.
- [ ] Prune removes only finished rows older than the retention and unfinished rows older than twice the lease, never a live attempt; the 24-hour count is unaffected by pruning.
- [ ] Owner A at a limit does not change Owner B's admission.
- [ ] Deleting an Owner who has ledger rows succeeds; the cascade-guard test includes the table. Alembic upgrade and downgrade both run; single head.
- [ ] No route, API response schema or existing test changes. Static checks no worse than the baseline (clean on `app`, 48 baseline errors in `tests/`).

## Comments

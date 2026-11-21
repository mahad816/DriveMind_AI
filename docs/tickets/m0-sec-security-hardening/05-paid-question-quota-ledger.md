# 05: Persistent paid-question quota: ledger and admission service

**Spec:** docs/specs/m0-sec-security-hardening.md
**What to build:** A small PostgreSQL-backed allowance that admits or refuses a paid question per Owner: 20 per rolling hour, 50 per rolling day, 1 concurrent, all configurable and provisional. It is built and tested on its own here; ticket 06 wires it into the routes. The daily limit survives restarts because it lives in the database, with no Redis or other new infrastructure. Owner decisions D4-2 and the 2026-11-21 approval (sections 2 to 4).
**Blocked by:** 04.
**Status:** ready-for-agent
**Progress:** open

## Scope

- One new table recording each admitted attempt: Owner, idempotency key, start time, finish time. Unique on (Owner, key) so the same key is never charged twice. The Owner reference cascades on delete (so the table never blocks deleting a user, the KI-033 lesson) and nothing else references the table. One Alembic revision on the single current head, with a downgrade; no data migration. This is the only schema change in M0-SEC.
- An admission service (logic in a service module, not in route handlers) with three operations: admit (key, Owner), finish (key), and prune old rows. Admit, inside one short transaction and under a per-Owner lock: (1) if the key already exists, return "replay": not counted, not refused, and no concurrency check; (2) otherwise count attempts in the last hour and last day, check for an unfinished attempt younger than the lease, and refuse or insert the row. The refusal says which limit (hour, day, concurrent) and when to retry.
- Settings: hour limit (20), day limit (50), concurrent limit (1), lease seconds (set above the generation timeout), retention for pruning. Document next to the settings that the values are provisional and unmeasured, that a request count is not a dollar amount or a count of provider calls, that windows are rolling, and the multi-replica checklist (lease versus generation timeout, connection pool size; database-backed admission itself is correct across processes).
- Fail closed: if the ledger cannot be read or written, admission raises a refusal, never an admit.
- Unfinished attempts past the lease stop blocking, so a crash cannot lock the Owner out; `finish` is idempotent.
- The clock is injectable for tests.

## Out of scope

Routes, input caps and any behavior change visible to a user (ticket 06); dollar accounting, price tables, per-model counts, per-user overrides or quota screens (future requirement); Redis; the login-start limit (ticket 07); the demo limiter (unchanged).

## Inspect

Ticket 04 `## Findings`; `backend/app/db/models/` (conversation turn and user models for style); `backend/alembic/versions/` (current head `20261120_1200`); `backend/app/db/session.py`; `backend/app/core/config.py`; `tests/security/conftest.py` (disposable PostgreSQL fixtures); `tests/security/test_conversation_deletion_privacy.py` (cascade guard over per-Owner tables, which this table must join).

## Deliverables

Model, migration, service, settings, tests; `## Comments` with the retention and Delete-stored-data note for M7 and documentation items for ticket 09.

## Needs

Disposable PostgreSQL. No Qdrant, no provider, no network.

- [ ] Tests first: the service does not exist, then each case below fails for the stated reason before it is made to pass.
- [ ] With limits 20/50/1: the 21st admission inside an hour, the 51st inside a day and a second admission while one is unfinished are refused with the correct reason; the same attempts spread beyond the window are admitted (injected clock).
- [ ] Real concurrency: N simultaneous admissions from separate database sessions for one Owner at concurrent limit 1 admit exactly one; N simultaneous admissions across the hour limit never exceed it.
- [ ] Restart: counts are identical when read through a brand-new service and engine instance after admissions made by an old one.
- [ ] A repeated key returns "replay", creates no row, is not refused even at every limit, and does not consume a slot; `finish` twice is harmless.
- [ ] An unfinished attempt older than the lease no longer blocks; one younger than the lease does.
- [ ] Owner A at a limit does not change Owner B's admission.
- [ ] If the database raises during admission, the result is a refusal, not an admit (fault-injected).
- [ ] Prune removes only rows older than the retention and never an unfinished attempt younger than the lease.
- [ ] Deleting an Owner who has ledger rows succeeds; the cascade-guard test is extended to include the table.
- [ ] Alembic upgrade from the previous head and downgrade both run; there is a single head.
- [ ] No route, schema of an API response, or existing test changes. Full suite, ruff, format, mypy, basedpyright (clean on `app`, 48 baseline errors in `tests/`) no worse than the baseline.

## Comments

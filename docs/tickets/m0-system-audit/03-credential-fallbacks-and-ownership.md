# 03: Credential fallback and ownership safety (A2, part 1)

**Spec:** docs/specs/m0-system-audit.md
**What to build:** The Owner knows, with evidence, whether any request, background job, startup task or script can act on another Owner's Google credential or data. Each of the six suspected "first stored credential" fallbacks is classified, every caller is traced, and the Owner receives a proposed M0-SEC follow-up ordered by the spec's urgency rules.
**Blocked by:** None (can start immediately). Sequencing note: code inspection and classification need no other ticket. Writing any new database-backed regression test waits until ticket 02 is resolved (or the local container environment has otherwise been verified by ticket 02's baseline), so a new test's failure is not confused with an environment fault. Ticket 01's hosted session-flag value is a soft input: if unread, it stays `Unverified`.
**Status:** ready-for-agent
**Progress:** open

## Scope

- Verify each of the six suspected fallbacks (user resolution, Drive sync, Drive content, chunking, ingestion, indexing services) or show it does not exist. Find the pattern by search (selects of the Google credential model with no owner filter, "first" or limit-one patterns), not only by the six names, and state the search used.
- Find every caller of each: routes, the indexing worker, demo loading, startup, internal services and scripts. Do not assume safety because mounted routes appear to pass an explicit Owner.
- Classify each as exactly one of: **Reachable security vulnerability** / **Latent unsafe behavior** / **Safe or unreachable** (with evidence such as every caller passing a non-null Owner and a test or type constraining it).
- Separate real current vulnerabilities from future multi-Owner scalability concerns.
- Tests: per fallback, a deterministic defect test (strict expected failure) if reachable or latent, or a protective test (passes today) if safe, only where meaningful. A new defect gets a `docs/KNOWN_ISSUES.md` entry with its test.
- **Escalation:** if a reachable vulnerability is confirmed, stop, report it to the Owner at once with evidence and record the time in `## Findings`, before continuing. An emergency fix is a separately approved change, not part of this ticket.
- Write the proposed M0-SEC (scope, ordering, acceptance criteria) for the fallbacks only after all six and all callers are confirmed. Ticket 09 merges in any M0-SEC items from ticket 04.

## Out of scope

Fixing any fallback or removing code. Running exploits against anything hosted. Route inventory, encryption, logging and rate-limit audit (ticket 04). Disconnect/Revoke/Delete-data facts (ticket 07). Corrections to the v1 spec ledger and security README (ticket 09).

## Inspect

`backend/app/services/` (`drive_sync_service.py`, `drive_content_service.py`, `chunking_service.py`, ingestion and indexing services, user resolution), the indexing worker, `backend/app/main.py` (startup), `backend/scripts/` if present, `backend/app/security/principal.py`, `backend/tests/security/` (prior art for ownership tests), `backend/tests/known_issues/`, `docs/KNOWN_ISSUES.md`.

## Deliverables

`## Findings` in this ticket: fallback table (location, callers, classification, evidence, test name), escalation log, proposed M0-SEC for the fallbacks. New tests and registry entries as above.

## Needs

No paid APIs, no live infrastructure (reachability from code and local tests; hosted facts only from ticket 01). Local Docker only for database-backed tests, after ticket 02.

- [ ] All six suspected fallbacks are verified or shown not to exist, with the search method stated; every caller of each is listed.
- [ ] Each fallback has exactly one classification with evidence.
- [ ] Any reachable vulnerability was reported to the Owner when found; the time is recorded in `## Findings`.
- [ ] The proposed M0-SEC has scope, acceptance criteria and an ordering that follows the urgency rules (hotfix / before substantial M1 implementation / recorded cleanup).
- [ ] Every added test is deterministic, free of paid API calls and meaningful; defect tests fail today for the stated reason; protective tests pass; no artificial expected failures.
- [ ] No database-backed test was written before ticket 02 was resolved or its environment was otherwise verified.
- [ ] No application code changed.

## Comments

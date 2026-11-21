# M0-SEC: Minimal Security Hardening Before M1

Draft, 2026-11-21, for Owner approval. Proposed by `docs/audits/m0-system-audit.md` (sections 4 and 8) and required by the M0 spec's urgency rule for "latent but unsafe" findings (`docs/specs/m0-system-audit.md`, "Security escalation rule"). Refines the v1 spec (`docs/specs/drivemind-v1-product-definition.md`), which has no M0-SEC row yet; ticket 09 adds one. Terms follow `GLOSSARY.md`; decisions follow `docs/adr/0001-single-answering-path.md` and `docs/adr/0002-public-demo-isolation.md`. Labels (Verified, Defect, Unverified, Future) and evidence types have the meaning given in the v1 spec, "How to read this spec". This repository is public: no secrets, e-mail addresses, hosted identifiers or private Drive content may appear here, in a ticket or in a test.

## Problem Statement

The M0 audit found no reachable vulnerability, but it left a short list of weaknesses that sit under everything M1 to M10 build on:

- Six services pick an arbitrary stored Google credential when no Owner is given (KI-031). Latent: every production caller passes an Owner today.
- Sign-in has no application-level allow-list. With sessions enabled, any Google account that Google lets through gets a user and a session, and can call paid endpoints. Only Google's consent-screen test-user list guards this, and that list lives outside the repository.
- Owner mode has no request limit, no concurrency limit and no size limit on `POST /chat`. The cost of the legacy linear path was never traced.
- An unauthenticated request can create one stored row per call and nothing removes it (KI-032).
- `POST /chat` is the only mutation that needs no `Origin` or CSRF token. Whether `SameSite=Lax` alone is enough was not assessed.

Nothing is deployed, so none of this is reachable today. The cost of fixing it is lowest now, before M1 to M9 add code on top, and before any redeploy turns sign-in back on.

## Solution

Nine small tickets, each independently testable, that remove or bound exactly these weaknesses and nothing else. No new infrastructure: no Redis, no queue, no external service, no billing system. The one schema change is a small PostgreSQL table that records paid question attempts (ticket 05), because the daily allowance must survive restarts to be called enforceable.

## User Stories (engineering outcomes)

1. As the Owner, no service can act on a Google credential unless the caller names the Owner, so a future code change cannot silently use someone else's credential.
2. As the Owner, only accounts I list can sign in to my DriveMind, whatever the Google consent screen says.
3. As the Owner, a bug, a loop or a stranger cannot run up my model bill through DriveMind: paid requests are limited per Owner, and oversized requests are refused before any provider call.
4. As the Owner, an unauthenticated visitor cannot make the database grow without limit through the login endpoint.
5. As the Owner, I know in writing whether a forged cross-site request can spend my credits through `POST /chat`, and if it can, it cannot.
6. As the Owner, I know which security items are deliberately not in this milestone and which later milestone owns each, so nothing is lost.
7. As a future maintainer or agent, the security tests and docstrings say what the code does.

## Implementation Decisions

No file paths or code snippets in this section. Evidence pointers are in the tickets.

### General boundaries
- M0-SEC fixes only what the audit proved or what the Owner decided (D4-1 to D4-4). It is not a refactoring milestone. Dead code that is made safe is kept, not deleted (deletion is M10).
- No Railway access, no hosted read or write, no deploy, no push, no paid provider call, no real Google call. Tests use fakes and the disposable PostgreSQL and Qdrant fixtures that already exist.
- Exactly one migration, in ticket 05 (the paid-attempt ledger), applying to the single Alembic head. No other ticket changes the schema; one that finds it needs to stops and reports to the Owner.
- The old Railway environment is intentionally offline and is not a constraint. New settings need no backward compatibility with it. A fail-closed default is acceptable even though it changes what an old environment would have done.
- Public API paths, response schemas, status semantics, citation contracts and frontend expectations stay unchanged, except where a ticket names a new refusal status (sign-in refusal, 429 on over-limit, 422 on an oversized question, and the CSRF requirement if ticket 08 finds the risk real).
- Both RAG paths (tool agent and the legacy linear and LangGraph paths) keep their behavior. Limits wrap the entry points; they do not change retrieval, grounding or citations. The evaluation harness is not subject to the limits.
- A fix is not complete until its test was written first and shown to fail for the stated reason, and the full suite passes. This replaces the "held-out question set" rule of `CODING_STANDARDS.md`, which applies to retrieval and answer quality; no M0-SEC ticket makes such a claim.

### Classification of everything the audit found
| Class | Items | Disposition |
|---|---|---|
| Confirmed defect (latent or hygiene) | KI-031 six credential fallbacks; KI-032 login-state growth; the vacuous route-guard test; wrong security docstrings | M0-SEC tickets 01, 02, 07, 09 |
| Potential vulnerability (conditional, dormant while nothing is deployed) | No sign-in allow-list; no Owner-mode limits and unbounded `/chat` input; `/chat` without CSRF | M0-SEC tickets 03, 04, 05, 06, 08 |
| Hardening (no demonstrated impact) | Unhandled-exception text in server logs; provider error text in the offline indexing log; public `/docs` and `/openapi.json`; no early exit for an empty corpus | Deferred (see below) |
| Deployment-only (cannot be fixed or verified in the repository) | Google consent-screen state and test-user list; hosted flag values; encryption keys and backups; `FRONTEND_URL` and cookie settings matching the real hosts; proxy and edge limits; practical provider spending safeguards (budgets, usage alerts: not guaranteed hard caps); claim-check setting; platform logs and retention | M9, per Owner decision D1-F |

### A. Owner is mandatory (tickets 01, 02)
- In normal mode, every service that acts on a Google credential requires an explicit Owner identifier of the right type. A missing or wrongly typed Owner raises the same error `RagService` already raises, before any database read. The six "first stored credential" selects are removed.
- Demo-mode branches of user resolution stay as they are.
- The four entry points with no production caller are kept, with a required Owner. They are not deleted (M10 owns removal).
- Split in two so each ticket stays reviewable: the three services with live production callers first, then the three pipeline services, which also closes KI-031.

### B. Application-level sign-in allow-list (ticket 03)
- Owner decision (this approval): DriveMind remains a private single-Owner beta. No unrestricted public registration. The allow-list, using verified Google identity, is the authorization model; Google's test-user list is a temporary outer control. This milestone does not become multi-user SaaS.
- The allow-list is a configuration value (environment), never committed. It holds verified Google e-mail addresses, compared case-insensitively. It is checked after Google's identity verification and before any user is looked up or created, for both login intents.
- Fail closed: when the list is unset or empty in normal mode, nobody can sign in and no existing session works.
- A refused account gets the same generic refusal as any other failed login (no oracle between "listed" and "unlisted"), creates no user, session or credential row, and its address is not logged. An unauthorized account never holds a usable session.
- **Removal denies protected operations immediately (Owner decision: sign-in-only checking is not revocation).** Every authenticated request already resolves its session to the stored user row. The same check runs there, so an address removed from the list (or an unset list) gets 401 on its next request on every protected route. The check is stateless: the session row is not rewritten, so re-adding an address within an old session's remaining lifetime (at most 7 days) reactivates that session unless it was explicitly revoked. Logout uses its own resolution path that keeps every existing check (valid session, exact `Origin`, session-bound CSRF token) but skips the allow-list and only revokes, so a removed address can still end its session without gaining access to anything else. Demo sessions are untouched.
- **Deferred, not guaranteed:** (a) a turn already running when an address is removed may finish and publish within its bounded execution window; (b) indexing jobs already queued are not cancelled, and the per-job allow-list check is assigned to M6 (first milestone to run Preparation jobs through the worker) and re-verified at the M9 gate; (c) the stored e-mail is refreshed only at sign-in, so a Google-side e-mail change is not seen until the next sign-in. These are residual risks, not security guarantees.

### C. Owner-mode paid-question quota (tickets 04, 05, 06)
- Owner decision D4-2 plus this approval: simple backend protection of paid Owner questions, on `POST /chat`, conversation turns and streaming, across the tool-agent and the legacy linear and LangGraph paths.
- **Limits (configurable, provisional, not measured):** 20 paid questions per Owner per hour, 50 per Owner per day, 1 concurrent paid question per Owner. Windows are rolling (the last 60 minutes and the last 24 hours), so no timezone or calendar-day reset logic exists.
- **What counts.** One paid question attempt is one unit: one admitted request that reaches paid execution, whatever number of model or embedding calls it makes internally. A retry, replay or stream reconnection of an existing turn is not counted and is not refused: it returns the stored turn without executing. Each `POST /chat` request is its own attempt. A refused request, and a request that fails before paid execution starts (busy, version conflict, not found, payload conflict, a reservation error, a simultaneous duplicate), is not counted when the failure is handled; a process kill or hard cancellation between admission and reservation leaves an orphan row that counts and blocks until the lease expires. Provider errors, timeouts, cancellations and disconnects after execution starts are counted.
- **Replay authority.** The existing turn table (unique per Owner and client request id) decides whether a submission is a replay, by a read before admission. The ledger never decides it, because a ledger row proves only that a request was admitted, not that anything executed. Ledger rows carry server-generated attempt ids; if the reservation step fails or reports a duplicate, the row is released (deleted).
- **Persistence and atomicity.** The allowance lives in PostgreSQL, so the daily limit survives restarts. The release and finish logic lives inside the conversation submit path, with release allowed only until the reservation commits, and runs shielded from cancellation. Admission and its release or finish run in their own short database sessions, never the request's session, and admission commits before any reservation or paid call. Admission takes a per-Owner transaction-level advisory lock with a lock timeout, counts the rolling hour and day, checks for an unfinished attempt younger than the lease, and inserts. A lock timeout or database error refuses the paid request with 503 (fail closed), distinct from 429. Old rows are pruned, never inside the 24-hour window. The table references the owner with a cascade, so it never blocks deleting a user (the KI-033 lesson) and is covered by Delete stored data in M7.
- **Timeouts and lease.** `POST /chat` in Owner mode gets an explicit execution timeout (it has none today); turns keep their execution bound. The concurrency lease must exceed both bounds plus a margin of at least 60 seconds (the gap from admission to reservation, cleanup and publication run outside the generation budget); configuration validation rejects any violation. A crash or a missed finish leaves a row that stops blocking after the lease.
- **Where it sits and the order of checks.** At the answering entry points: authentication and CSRF, body and schema validation (the body limit is middleware and can precede authentication), existing preconditions (404, 409), replay read, admission, reservation, paid work, finish in a `finally`. For streaming, admission is in the route function before the stream starts, so a refusal is a real 429. A refusal gets 429, a fixed message naming the limit, a Retry-After header, and leaves no turn and no query history. With one concurrent question allowed, a second question during a running one now gets 429 where a second turn in the same conversation got 409; this is deliberate. Input caps: `question` on `POST /chat` is capped at 4000 characters, and request bodies at 512 KiB for `/chat` and 64 KiB for turn creation and streaming.
- **Trade-off flagged, as requested.** Persistent quotas add one table, one migration and one small service, plus an execution timeout on `/chat` and a replay read before admission. It is the smallest design that makes the daily limit real, so the ticket is kept to that: no price table, no per-model accounting, no admin screen, no per-user overrides. The work is split into two tickets (05 builds and tests the ledger and admission service in isolation; 06 wires it into the routes and adds the input caps) so each fits one context window.
- **One-worker constraint.** Admission is correct across processes because it relies on PostgreSQL, not process memory, so extra replicas do not break the limit. What must be re-checked before running more than one worker or replica: the lease length against the generation timeout, database connection pool size, and that the login-start limiter (section D) is process-local. This is documented where the settings are.
- **Cost controls (this approval).** M0-SEC builds no dollar accounting or billing. A request count is not a dollar amount and not a count of OpenAI calls: one question can make several model calls of very different price. M1 measures real cost, latency and model-call overhead per question on both paths. Before the beta is reopened, practical spending safeguards are verified by the Owner in the provider dashboard (for example a project usage budget and usage alerts). These are described as safeguards, never as guaranteed hard spending caps.

### D. KI-032 (ticket 07)
- Owner decision D4-3: both implications are recorded. Security: an unauthenticated request can create one stored row per call while sessions are enabled, with no data exposure. Storage: unbounded growth.
- Expired login states are deleted when a new login starts. Still-valid states are never deleted.
- The login-start endpoint also gets a small global request limit. It is process-local and independent of the paid-question ledger: an unauthenticated endpoint has no Owner to key on, a lost window after a restart only loosens a limit whose growth is already bounded by the prune, and it keeps ticket 07 free of any dependency on the quota work. A per-IP limit cannot work behind the current proxy setup (proxy headers are disabled), so the limit is global and generous. Trade-off, recorded: an attacker who sustains traffic above the limit can delay the Owner's own login, but cannot read or change anything. Per-IP limiting is an edge or proxy decision for M9.

### E. CSRF on `POST /chat` (ticket 08)
- Owner decision D4-4: assess, do not assume. The assessment states the layout facts it can verify (host-only cookie, same-origin proxy rewrite, no CORS middleware, no normal-mode frontend caller of `/chat`), tests what the installed framework version accepts as a forged "simple" cross-site request, and states what a forged request could do (spend credits, write query history) and could not do (read the answer).
- Layout facts that cannot be verified while nothing is deployed (custom domain, sibling subdomains) are recorded as deployment-only checks for M9, not assumed safe.
- If the risk is real or cannot be excluded, normal-mode `/chat` requires the same `Origin` and CSRF token as every other mutation. Demo mode stays anonymous.

### F. Closeout (ticket 09)
- Fix the vacuous security test, correct the wrong docstrings in the session modules, update the registry, `AGENTS.md`, the security README, the v1 spec ledger and the M9 gate, and record the milestone verification run.

### Deferred, with the milestone that owns each (not pulled into M0-SEC)
| Item | Why it can wait | Owner milestone |
|---|---|---|
| Log unhandled exceptions without their text | Hygiene. No reachable message containing a secret was found (A2.11), the hosted start script already disables the access log, and nothing is deployed. Fits "content-free error logs" | M9 (basic logging) |
| `indexing_service` logs provider error text | Latent, reachable only from the offline demo loader and evaluation harness (A2.12) | M9 (basic logging) |
| Disable `/docs`, `/redoc`, `/openapi.json` outside development | Noise only; the repository is public | M9 |
| Cancel a turn already running, and cancel queued indexing jobs, when an account is removed | Bounded window; the worker is not started by the application and has no session. Recorded as deferrals, not guarantees | Running turns: accepted residual risk (bounded execution window). Queued jobs: M6 (worker check), re-verified at M9 |
| Early exit for an empty corpus on the tool-agent path | Cost and experience optimization for a signed-in, allow-listed Owner; not a security control once tickets 03, 05 and 06 exist | M1 or M2, as an evaluation finding |
| Limit values from measured cost | Needs M1 measurements; the 20/hour, 50/day, 1-concurrent values are provisional | M1 produces the numbers; M9 gate before redeploy |
| Per-user quota management for future beta testers (smaller individual allowances, per-user overrides, quota admin) | Future requirement. Not built until ownership isolation is verified; the ledger is already keyed by owner so it can grow into this | M7 (isolation) then a later milestone |
| Claim check fails open | Owner decision D5-3 | M3 |
| Disconnect, Revoke, Delete stored data, permanent conversation delete, KI-033 | Owner decision D7 | M7 |
| Per-IP limits, edge rate limiting, practical provider spending safeguards, consent-screen and test-user verification, flag and key verification, backups | Deployment-only | M9 (D1-F) |
| Demo spend cap | ADR 0002 | M9 |
| Preparation and embedding-compatibility issues | Not security | M6 |
| CI hosted run; four deselected tests | Not security | M9 |

## Testing Decisions

- A good M0-SEC test asserts externally visible behavior: a refusal status and body, rows that must not exist, a provider fake that must not be called. It does not assert implementation details.
- Test first: each ticket's defect test is written and shown to fail for the stated reason before the fix. Tripwire tests that pin today's behavior are replaced in the same ticket that changes the behavior.
- Quota state lives in the test database and is cleaned per test, the clock is injectable, and one shared test helper sets the allow-list, so neither the new limits nor the fail-closed allow-list default leak between tests or force edits to every fixture.
- Tests that need the database use the existing disposable-container fixtures. No test reaches Google, OpenAI or Railway. `OPENAI_API_KEY` stays unexported (a known test sensitivity, M0 ticket 02).
- Existing security tests (ownership, sessions, route inventory, isolation) are prior art and must keep passing.

### What must be true before M0-SEC is complete
1. KI-031: no unscoped credential select remains outside the demo existence check; all six strict markers removed and passing; the twelve guards pass; KI-031 is in Fixed.
2. Allow-list: unlisted, unset-list and empty-list cases produce no user, session or credential row and the generic refusal; a listed account signs in; both intents covered; no address in logs; an existing session of an address that is removed from the list (or an unset list) gets 401 on its next request on every private route class, logout still revokes that session with its CSRF protections intact, and re-adding the address without revocation restores it (documented).
3. Quota: with limits set low and a counting fake provider, the 21st question in an hour, the 51st in a day and a second concurrent question are refused (429) before any provider call, on the tool-agent path, the linear path, `POST /chat`, conversation turns and streaming; real simultaneous database sessions at the limit admit exactly the allowed number; the daily count survives a simulated restart (new application and service instances); a replay, retry or reconnection of an existing turn (decided from the turn table) is not counted and not refused; pre-execution failures leave no ledger row; a simultaneous duplicate yields one execution and one count; failed, cancelled and disconnected attempts free the slot and still count; the `/chat` timeout and the lease validation are enforced; a lock timeout or database error gives 503 with no provider call; one Owner never consumes another's allowance; internal model calls are not counted; an unfinished attempt past its lease stops blocking; an unreadable ledger refuses (fail closed); refused requests leave no turn and no query history; oversized question and body are refused; demo behavior is unchanged; the test that pinned "Owner mode is unlimited" is replaced.
4. KI-032: strict test passes, guard passes, login-start limit tested, KI-032 is in Fixed with both implications and the lockout trade-off.
5. CSRF: written assessment exists; if the risk is real or cannot be excluded, forged requests are refused and demo `/chat` still works anonymously.
6. Test integrity: the vacuous guard test is fixed; the route inventory (48 tests) passes, updated only where a ticket changed a route's dependency.
7. Full verification once at the end: backend container suite (about 24 minutes, qualified environment of `AGENTS.md`), container-free suite, ruff, format check, mypy, basedpyright (clean on `app`; `tests` no worse than the 48-error baseline), frontend test, lint and build. Any failure is reported, not hidden.
8. Process items: ticket 04's table, placement and idempotency analysis and the counters list for M1 exist and tickets 05 and 06 follow them; ticket 08's deployment-only layout checks are recorded for M9; the M9 gate (four items) is written in the v1 spec and here; the registry and documents match the final behavior; the Owner's decisions recorded under "Owner decisions applied" are reflected in the tickets.
9. Diff scope: only the files the tickets name; exactly one migration (ticket 05); no frontend change unless ticket 08 proves one is needed; a secret and identifier scan of the diff finds nothing.

## Out of Scope

- Anything in the deferred table. Public sign-up, multi-user SaaS behavior, per-user quota management, billing or dollar accounting, roles. Independent multi-user data access is not implemented until ownership isolation is verified (M7).
- Any Railway, Google Cloud console, OpenAI dashboard or hosted action. Verifying the consent screen is an Owner dashboard task owned by M9.
- Switching or removing answering paths. Deleting dead code.
- Rewriting authentication, sessions or the encryption design (audited as sound).

## Further Notes

### Owner decisions applied (2026-11-21 approval)
1. Private single-Owner beta; no public registration; fail-closed allow-list on verified Google identity; unauthorized accounts hold no usable session; removal invalidates existing sessions (section B); no multi-user SaaS.
2. Limits: 20 paid questions per Owner per hour, 50 per day, 1 concurrent; configurable, provisional, not measured; consistent counting without double-counting (section C). This replaces the earlier 60 per hour and 2 concurrent proposal.
3. Daily allowance persisted in PostgreSQL, atomic under concurrency, documented one-worker constraints; scope trade-off flagged (section C).
4. No dollar accounting; request counts are not dollars or provider calls; M1 measures cost; practical spending safeguards verified before the beta reopens and never described as guaranteed hard caps.
5. Per-user quota management is a future requirement, recorded in the deferred table, not built.
6. KI-031, KI-032 and the `/chat` CSRF assessment stay in M0-SEC; M0 findings and deferrals preserved.
7. Logging hygiene (unhandled-exception text, provider error text in the offline indexing log) stays deferred to M9. It was not listed in the Owner's approval and is the one deferred item touching credential-leak risk; the audit found no instance and the hosted start script disables the access log. This is a standing default, not an Owner decision; say so if you want it back in M0-SEC.

### Source of decision IDs
D1 to D7 (for example D1-F, D5-3, D7) are the Owner decisions listed in `docs/audits/m0-system-audit.md`, section 6. D4-1 to D4-4 are the numbered Owner decisions in the Comments of `docs/tickets/m0-system-audit/04-auth-and-access-control-audit.md`.

### Ordering and dependencies
`01 → 02`; `03` and `04` independent; `04 → 05 → 06`; `07` independent; `08` independent (soft: do after 06, both touch the `/chat` route); `09` last, blocked by all. Suggested order: 01, 02, 03, 04, 05, 06, 07, 08, 09. Ticket 06 is the first one that changes route behavior for quota.

M1 may start its non-application work (frozen question set, grader validation) in parallel after 01 and 02, but substantial M1 implementation waits for M0-SEC to complete, as the M0 spec's rule says. The M9 gate (ticket 09 records it): limit values recalibrated from M1 data; deployment-only list verified; practical provider spending safeguards verified (budgets and usage alerts, not guaranteed hard caps); multi-replica checklist from section C reviewed if more than one worker is planned.

### Residual risk after M0-SEC (stated, not hidden)
- The quota values are provisional until recalibrated from M1 data, and a request count is not a cost bound: one question can be expensive.
- Re-adding a removed address within an old session's remaining lifetime reactivates that session unless it was explicitly revoked through logout.
- A running turn and queued indexing jobs of a removed account are not cancelled (bounded window; worker check assigned to M6). The stored e-mail is refreshed only at sign-in. These are deferrals, not guarantees.
- A client that disconnects before a stream body starts, or a process killed between admission and reservation, holds its concurrency slot (and one count) until the lease expires.
- A removed address cannot fetch a fresh CSRF token, so only a client already holding one can log out; otherwise its session ends by expiry.
- A sustained flood on the login endpoint can delay the Owner's login.
- E-mail-based allow-listing matches by Google's verified e-mail claim, not by Google subject.
- Everything on the deployment-only row stays Unverified until M9.

### Related documents
`docs/audits/m0-system-audit.md`; `docs/specs/m0-system-audit.md`; `docs/specs/drivemind-v1-product-definition.md`; `docs/KNOWN_ISSUES.md`; `docs/tickets/m0-system-audit/03` and `04` (full evidence); `docs/adr/0001-single-answering-path.md`; `docs/adr/0002-public-demo-isolation.md`; `CODING_STANDARDS.md`; `AGENTS.md`.
